"""Single entry point for running one question through the agent.

`run_question` is used by both the CLI and the evaluation harness, so every run
gets the same treatment: a run_id, a local trace file, and one structured
`run_completed` log line with latency, tokens, cost and tools called.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional

from salesops_agent.agent import build_agent
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_question(cfg: dict[str, Any], question: str, source: str = "cli", agent=None) -> RunResult:
    """Run one question, recording a trace and a structured log entry."""
    ensure_output_dirs(cfg)
    logger = setup_logging(cfg)
    run_id = uuid.uuid4().hex[:12]
    recorder = LocalTraceRecorder(run_id, cfg["tracing"].get("max_payload_chars", 2000))

    log_event(logger, "run_started", run_id=run_id, source=source,
              prompt_version=cfg["prompt"]["version"], model=cfg["model"]["name"])

    answer, error = "", None
    t0 = time.perf_counter()
    try:
        agent = agent or build_agent(cfg)
        result = agent.invoke(
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
            agent_version=cfg["agent"]["version"],
            prompt_version=cfg["prompt"]["version"],
            model=cfg["model"]["name"],
            question=question,
            answer=answer,
            error=error,
            latency_s=latency,
            token_usage=usage,
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
    )
    log_event(logger, "run_completed", source=source,
              prompt_version=cfg["prompt"]["version"], model=cfg["model"]["name"],
              **{k: v for k, v in result.to_dict().items() if k not in ("question", "answer")})
    return result
