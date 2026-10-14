"""Single entry point for running one question through the agent.

`run_question` is used by both the CLI and the evaluation harness, so every run
gets the same treatment: a run_id, one structured record in logs/runs.jsonl (input,
status, tools, latency, cost, guardrail interventions, HITL decision, failure
reason), a redacted trace in traces/<run_id>.json, and run_started / run_completed
events (plus guardrail, approval and sandbox events) in logs/agent.jsonl.

Runtime controls run here, outside the model: the input guardrail checks the
request first, and a blocked request is answered from the policy without invoking
the agent graph at all (no model call, no tool call). While the agent runs, the
tool guardrail (wrapped around every tool) checks each proposed call against the
data access policy using the RunContext set up here (request, role, approvals).
Finally the output guardrail inspects the agent's answer before it is returned:
it may block it (safe refusal), withhold it for human review, or redact it.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from salesops_agent.agent import SalesOpsAgent, build_agent
from salesops_agent.config import ensure_output_dirs, model_pricing
from salesops_agent.guardrails import RunContext, tool_run_context
from salesops_agent.guardrails.approval import Approver, make_approver
from salesops_agent.logging_utils import log_event, setup_logging, write_run_record
from salesops_agent.tracing import LocalTraceRecorder


@dataclass
class RunResult:
    run_id: str
    question: str
    answer: str
    success: bool
    error: Optional[str]
    latency_s: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    tools_called: List[str] = field(default_factory=list)       # tools that actually executed
    trace_path: Optional[str] = None
    guardrail: Optional[Dict[str, Any]] = None   # input-guardrail block decision, if it fired
    tools_blocked: List[Dict[str, Any]] = field(default_factory=list)  # tool calls the policy refused
    role: Optional[str] = None
    approval_mode: Optional[str] = None
    approvals: List[Dict[str, Any]] = field(default_factory=list)      # HITL requests and decisions
    sandbox_runs: List[Dict[str, Any]] = field(default_factory=list)   # run_analysis outcomes
    output_guardrail: Optional[Dict[str, Any]] = None  # output decision when it changed the answer
    task_id: Optional[str] = None                      # evaluation task id, when run by the eval harness
    task_passed: Optional[bool] = None
    task_failures: List[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.guardrail and not self.guardrail["allowed"])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_question(
    cfg: dict[str, Any],
    question: str,
    source: str = "cli",
    agent: Optional[SalesOpsAgent] = None,
    role: Optional[str] = None,
    approvals: Optional[set[str]] = None,
    approval: str = "pending",
    approver: Optional[Approver] = None,
    task_id: Optional[str] = None,
    scorer: Optional[Callable[["RunResult"], List[str]]] = None,
) -> RunResult:
    """Run one question, recording a trace and a structured log entry.

    Building the agent happens before the run starts: an invalid config, prompt or
    dataset raises immediately rather than being logged as a failed run.
    """
    ensure_output_dirs(cfg)
    logger = setup_logging(cfg)
    agent = agent or build_agent(cfg)
    if agent.tool_guard is not None:
        roles = agent.tool_guard.policy.roles
        if role is not None and role not in roles:
            raise ValueError(f"Unknown role {role!r}; policy roles: {roles}")
        role = role or agent.tool_guard.policy.default_role
    run_id = uuid.uuid4().hex[:12]
    recorder = LocalTraceRecorder(run_id, cfg["tracing"].get("max_payload_chars", 2000),
                                  redactor=agent.redactor, restricted_tools=agent.restricted_tools)

    log_event(logger, "run_started", run_id=run_id, source=source, task_id=task_id, role=role,
              versions=agent.manifest)

    answer, error, guardrail = "", None, None
    t0 = time.perf_counter()
    if agent.input_guard is not None:
        decision = agent.input_guard.check(question)
        recorder.record_guardrail(decision.to_dict(), (time.perf_counter() - t0) * 1000)
        if not decision.allowed:
            guardrail = decision.to_dict()
            answer = decision.response
            log_event(logger, "guardrail_blocked", level=logging.WARNING, run_id=run_id, source=source,
                      stage=decision.stage, rule_id=decision.rule_id, category=decision.category)
    ctx = RunContext(
        run_id=run_id, request=question, role=role, approvals=set(approvals or ()), logger=logger,
        on_block=lambda b: recorder.record_guardrail({"stage": "tool", "allowed": False, **b}, 0.0),
        approver=approver or make_approver(approval),
        approvals_log=cfg["paths"]["approvals_log"],
        on_approval=recorder.record_approval,
    )
    if guardrail is None:
        try:
            with tool_run_context(ctx):
                result = agent.graph.invoke(
                    {"messages": [{"role": "user", "content": question}]},
                    config={"callbacks": [recorder], "run_name": "salesops_agent", "metadata": {"run_id": run_id}},
                )
            answer = result["messages"][-1].content
        except Exception as exc:  # surface failures as data, not crashes
            error = f"{type(exc).__name__}: {exc}"
    latency = round(time.perf_counter() - t0, 3)
    output_decision = None
    if agent.output_guard is not None and guardrail is None and error is None:
        t_out = time.perf_counter()
        decision = agent.output_guard.apply(answer, cfg["paths"]["review_queue"], run_id=run_id, request=question)
        recorder.record_guardrail(decision.to_dict(), (time.perf_counter() - t_out) * 1000)
        if decision.triggered:
            output_decision = decision.to_dict()
            answer = decision.response
            log_event(logger, "output_guardrail_triggered", level=logging.WARNING, run_id=run_id, source=source,
                      action=decision.action, rule_ids=decision.rule_ids, categories=decision.categories,
                      redactions=decision.redactions, review_id=decision.review_id)
        latency = round(time.perf_counter() - t0, 3)
    tools_blocked = [{k: b.get(k) for k in ("tool", "reason", "rule")} for b in ctx.blocked]
    approval_records = [asdict(r) for r in ctx.approval_records]
    tools_executed = list(recorder.tools_called)
    for blocked in tools_blocked:           # attempted-but-refused calls did not execute
        if blocked["tool"] in tools_executed:
            tools_executed.remove(blocked["tool"])

    usage = recorder.token_usage
    pricing = model_pricing(cfg)
    cost = round((usage["input_tokens"] * pricing["input"] + usage["output_tokens"] * pricing["output"]) / 1_000_000, 6)

    result = RunResult(
        run_id=run_id,
        question=question,
        answer=answer,
        success=error is None,
        error=error,
        latency_s=latency,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cost_usd=cost,
        tools_called=tools_executed,
        guardrail=guardrail,
        tools_blocked=tools_blocked,
        role=role,
        output_guardrail=output_decision,
        approval_mode=approval,
        approvals=approval_records,
        sandbox_runs=list(ctx.sandbox_runs),
        task_id=task_id,
    )
    if scorer is not None:                 # evaluation: record the task outcome with the run
        result.task_failures = list(scorer(result))
        result.task_passed = not result.task_failures

    redact = agent.redactor or str
    summary = run_summary(result, redact)
    manifest = agent.manifest
    if cfg["tracing"].get("enabled", True):
        result.trace_path = str(recorder.save(
            cfg["paths"]["traces_dir"],
            source=source,
            started_at=recorder.started_at,
            finished_at=_now(),
            versions=manifest,
            **summary,
            token_usage=usage,
        ))

    write_run_record(cfg, {
        "run_id": run_id,
        "timestamp": recorder.started_at,
        "finished_at": _now(),
        "source": source,
        "experiment": manifest["experiment"],
        "agent_version": manifest["agent_version"],
        "prompt_version": manifest["prompt_version"],
        "model": manifest["model"],
        "git_commit": manifest["git"]["commit"],
        **summary,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "tools_selected": [c["name"] for c in recorder.tools_selected],
        "trace_path": result.trace_path,
    })
    log_event(logger, "run_completed", source=source, experiment=manifest["experiment"],
              agent_version=manifest["agent_version"], prompt_version=manifest["prompt_version"],
              model=manifest["model"], git_commit=manifest["git"]["commit"],
              **{k: v for k, v in result.to_dict().items() if k not in ("question", "answer")})
    return result


def run_status(result: RunResult) -> str:
    if result.error:
        return "error"
    if result.blocked:
        return "blocked_by_input_guardrail"
    action = (result.output_guardrail or {}).get("action")
    return {"block": "output_blocked", "review": "output_withheld_for_review",
            "redact": "completed_with_redactions"}.get(action, "completed")


def run_summary(result: RunResult, redact: Callable[[Any], str]) -> Dict[str, Any]:
    """Fields shared by the run log line and the trace. Free text is redacted."""
    interventions: List[Dict[str, Any]] = []
    if result.guardrail:
        interventions.append({"stage": "input", "action": "block", "status": "blocked",
                              "reason": result.guardrail["category"], "rule": result.guardrail["rule_id"],
                              "category": result.guardrail["category"]})
    for b in result.tools_blocked:
        action = "rejected" if b["reason"] == "approval_rejected" else "block"
        interventions.append({"stage": "tool", "action": action, "status": "rejected" if action == "rejected" else "blocked",
                              "tool": b["tool"], "reason": b["reason"], "rule": b["rule"]})
    for s in result.sandbox_runs:
        if s["status"] != "ok":
            interventions.append({"stage": "sandbox", "action": "refuse", "status": "refused",
                                  "reason": s["error_type"]})
    if result.output_guardrail:
        o = result.output_guardrail
        interventions.append({"stage": "output", "action": o["action"], "status": o["status"],
                              "reason": o["reason"], "rules": o["rule_ids"], "categories": o["categories"],
                              "redactions": o["redactions"], "review_id": o["review_id"]})
    decisions = [a["decision"] for a in result.approvals]
    if "rejected" in decisions:
        hitl_decision = "rejected"
    elif "pending" in decisions:
        hitl_decision = "pending"
    elif decisions:
        hitl_decision = "approved"
    else:
        hitl_decision = None
    failure_reason = result.error
    if failure_reason is None and result.task_failures:
        failure_reason = "; ".join(result.task_failures)
    return {
        "task_id": result.task_id,
        "role": result.role,
        "user_input": redact(result.question),
        "status": run_status(result),
        "final_output": redact(result.answer),
        "error": redact(result.error) if result.error else None,
        "failure_reason": redact(failure_reason) if failure_reason else None,
        "task_passed": result.task_passed,
        "tools_called": result.tools_called,
        "tools_blocked": result.tools_blocked,
        "latency_s": result.latency_s,
        "cost_usd": result.cost_usd,
        "guardrail_interventions": interventions,
        "hitl": {
            "mode": result.approval_mode,
            "decisions": [{k: a[k] for k in ("approval_id", "tool", "decision", "decided_by", "preapproved")}
                          for a in result.approvals],
        },
        "hitl_decision": hitl_decision,
        "sandbox_runs": result.sandbox_runs,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
