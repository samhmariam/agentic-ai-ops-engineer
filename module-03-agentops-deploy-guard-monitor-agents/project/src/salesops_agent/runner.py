"""Single entry point for running one question through the agent.

`run_question` is used by both the CLI and the evaluation harness, so every run
gets the same treatment: a run_id, a local trace file, a `run_started` log line
carrying the full version manifest, and a `run_completed` log line with latency,
tokens, cost and tools called.

Runtime controls run here, outside the model: the input guardrail checks the
request first, and a blocked request is answered from the policy without invoking
the agent graph at all (no model call, no tool call).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from salesops_agent.agent import SalesOpsAgent, build_agent
from salesops_agent.config import ensure_output_dirs, model_pricing
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
    tools_called: List[str] = field(default_factory=list)
    trace_path: Optional[str] = None
    guardrail: Optional[Dict[str, Any]] = None   # blocking decision, if a guardrail fired

    @property
    def blocked(self) -> bool:
        return bool(self.guardrail and not self.guardrail["allowed"])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_question(
    cfg: dict[str, Any], question: str, source: str = "cli", agent: Optional[SalesOpsAgent] = None
) -> RunResult:
    """Run one question, recording a trace and a structured log entry.

    Building the agent happens before the run starts: an invalid config, prompt or
    dataset raises immediately rather than being logged as a failed run.
    """
    ensure_output_dirs(cfg)
    logger = setup_logging(cfg)
    agent = agent or build_agent(cfg)
    run_id = uuid.uuid4().hex[:12]
    recorder = LocalTraceRecorder(run_id, cfg["tracing"].get("max_payload_chars", 2000))

    log_event(logger, "run_started", run_id=run_id, source=source, versions=agent.manifest)

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
    if guardrail is None:
        try:
            result = agent.graph.invoke(
                {"messages": [{"role": "user", "content": question}]},
                config={"callbacks": [recorder], "run_name": "salesops_agent", "metadata": {"run_id": run_id}},
            )
            answer = result["messages"][-1].content
        except Exception as exc:  # surface failures as data, not crashes
            error = f"{type(exc).__name__}: {exc}"
    latency = round(time.perf_counter() - t0, 3)

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
        tools_called=recorder.tools_called,
        trace_path=trace_path,
        guardrail=guardrail,
    )
    manifest = agent.manifest
    log_event(logger, "run_completed", source=source, experiment=manifest["experiment"],
              agent_version=manifest["agent_version"], prompt_version=manifest["prompt_version"],
              model=manifest["model"], git_commit=manifest["git"]["commit"],
              **{k: v for k, v in result.to_dict().items() if k not in ("question", "answer")})
    return result
