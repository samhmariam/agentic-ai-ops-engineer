"""Single entry point for running one question through the agent.

`run_question` is used by both the CLI and the evaluation harness, so every run
gets the same treatment: a run_id, a local trace file, a `run_started` log line
carrying the full version manifest, and a `run_completed` log line with latency,
tokens, cost and tools called.

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
from typing import Any, Dict, List, Optional

from salesops_agent.agent import SalesOpsAgent, build_agent
from salesops_agent.config import ensure_output_dirs, model_pricing
from salesops_agent.guardrails import RunContext, tool_run_context
from salesops_agent.guardrails.approval import Approver, make_approver
from salesops_agent.logging_utils import log_event, setup_logging
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
    output_guardrail: Optional[Dict[str, Any]] = None  # output decision when it changed the answer

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
    recorder = LocalTraceRecorder(run_id, cfg["tracing"].get("max_payload_chars", 2000))

    log_event(logger, "run_started", run_id=run_id, source=source, role=role, versions=agent.manifest)

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
    cost = (usage["input_tokens"] * pricing["input"] + usage["output_tokens"] * pricing["output"]) / 1_000_000

    trace_path = None
    if cfg["tracing"].get("enabled", True):
        trace_path = str(recorder.save(
            cfg["paths"]["traces_dir"],
            source=source,
            versions=agent.manifest,
            question=question,
            answer=answer,
            error=error,
            latency_s=latency,
            token_usage=usage,
            guardrail=guardrail,
            tools_blocked=tools_blocked,
            role=role,
            output_guardrail=output_decision,
            approval_mode=approval,
            approvals=approval_records,
        ))

    result = RunResult(
        run_id=run_id,
        question=question,
        answer=answer,
        success=error is None,
        error=error,
        latency_s=latency,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cost_usd=round(cost, 6),
        tools_called=tools_executed,
        trace_path=trace_path,
        guardrail=guardrail,
        tools_blocked=tools_blocked,
        role=role,
        output_guardrail=output_decision,
        approval_mode=approval,
        approvals=approval_records,
    )
    manifest = agent.manifest
    log_event(logger, "run_completed", source=source, experiment=manifest["experiment"],
              agent_version=manifest["agent_version"], prompt_version=manifest["prompt_version"],
              model=manifest["model"], git_commit=manifest["git"]["commit"],
              **{k: v for k, v in result.to_dict().items() if k not in ("question", "answer")})
    return result
