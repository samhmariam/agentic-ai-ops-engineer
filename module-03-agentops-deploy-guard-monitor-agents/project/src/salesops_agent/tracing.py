"""Local trace artifacts.

`LocalTraceRecorder` is a LangChain callback handler that records the execution
trajectory of one agent run as spans: each model call (token usage and the tool
calls it selected, with arguments), each tool call (arguments and output), each
guardrail decision, each sandbox outcome and each human approval. `save()` writes
the trace to traces/<run_id>.json together with the run summary (status, input,
final output, errors, interventions, HITL decision), so a failed run can be
debugged after the fact without an external tracing backend.

Nothing sensitive is written raw: every persisted payload passes through the
Redactor (internal HR/financial values, email addresses), outputs of restricted
tools are withheld entirely, and payloads are truncated to max_payload_chars.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalTraceRecorder(BaseCallbackHandler):
    def __init__(
        self,
        run_id: str,
        max_payload_chars: int = 2000,
        redactor: Optional[Callable[[Any], str]] = None,
        restricted_tools: Optional[Set[str]] = None,
    ):
        self.run_id = run_id
        self.started_at = _now()
        self.max_payload_chars = max_payload_chars
        self.redactor = redactor
        self.restricted_tools = set(restricted_tools or ())
        self.spans: List[Dict[str, Any]] = []
        self.tools_selected: List[Dict[str, Any]] = []
        self.restricted_outputs_withheld = 0
        self._open: Dict[UUID, Dict[str, Any]] = {}

    # -- helpers ------------------------------------------------------------

    def safe(self, value: Any) -> str:
        """Redacted, size-limited string form of a payload: the only way data enters a trace."""
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        if self.redactor is not None:
            text = self.redactor(text)
        limit = self.max_payload_chars
        return text if len(text) <= limit else text[:limit] + f"... [truncated {len(text) - limit} chars]"

    def _start(self, run_id: UUID, parent_run_id: Optional[UUID], kind: str, name: str, **attrs: Any) -> None:
        self._open[run_id] = {
            "span_id": str(run_id),
            "parent_span_id": str(parent_run_id) if parent_run_id else None,
            "kind": kind,
            "name": name,
            "start_time": _now(),
            "_t0": time.perf_counter(),
            **attrs,
        }

    def _end(self, run_id: UUID, **attrs: Any) -> None:
        span = self._open.pop(run_id, None)
        if span is None:
            return
        span["duration_ms"] = round((time.perf_counter() - span.pop("_t0")) * 1000, 1)
        span["end_time"] = _now()
        span.update(attrs)
        self.spans.append(span)

    # -- model calls --------------------------------------------------------

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        name = (kwargs.get("metadata") or {}).get("ls_model_name") or (serialized or {}).get("name", "chat_model")
        self._start(run_id, parent_run_id, "llm", name, input_messages=sum(len(m) for m in messages))

    def on_llm_end(self, response, *, run_id, **kwargs):
        usage: Dict[str, int] = {}
        selected: List[Dict[str, Any]] = []
        for gen_list in response.generations:
            for gen in gen_list:
                message = getattr(gen, "message", None)
                if message is None:
                    continue
                for key, val in (getattr(message, "usage_metadata", None) or {}).items():
                    if isinstance(val, int):
                        usage[key] = usage.get(key, 0) + val
                for tc in getattr(message, "tool_calls", []):
                    selected.append({"name": tc["name"], "args": self.safe(tc.get("args", {}))})
        self.tools_selected += selected
        self._end(run_id, status="ok", usage=usage, requested_tool_calls=selected)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", error=self.safe(repr(error)))

    # -- tool calls ---------------------------------------------------------

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name", "tool")
        self._start(run_id, parent_run_id, "tool", name, input=self.safe(inputs or input_str))

    def on_tool_end(self, output, *, run_id, **kwargs):
        content = getattr(output, "content", output)
        span = self._open.get(run_id, {})
        text = content if isinstance(content, str) else json.dumps(content, default=str)
        status = "ok"
        if '"status": "blocked"' in text or "'status': 'blocked'" in text:
            status = "blocked"
        elif '"status": "rejected"' in text or "'status': 'rejected'" in text:
            status = "rejected"
        if span.get("name") in self.restricted_tools and status == "ok":
            self.restricted_outputs_withheld += 1
            self._end(run_id, status=status, output=f"[REDACTED: restricted tool output, {len(text)} chars]")
        else:
            self._end(run_id, status=status, output=self.safe(text))

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", error=self.safe(repr(error)))

    # -- runtime controls ---------------------------------------------------

    def record_guardrail(self, decision: Dict[str, Any], duration_ms: float) -> None:
        """Record a guardrail check as its own span (rule and category, never the text)."""
        self.spans.append({
            "span_id": f"guardrail-{decision['stage']}-{len(self.spans)}",
            "parent_span_id": None,
            "kind": "guardrail",
            "name": f"{decision['stage']}_guardrail",
            "start_time": _now(),
            "end_time": _now(),
            "duration_ms": round(duration_ms, 3),
            "status": decision.get("action") or ("allowed" if decision["allowed"] else "blocked"),
            **{k: decision[k] for k in ("rule_id", "category", "tool", "reason", "rule_ids", "categories",
                                        "redactions", "review_id", "approval_id") if decision.get(k)},
        })

    def record_approval(self, record: Dict[str, Any]) -> None:
        """Record a human-in-the-loop approval request and its decision."""
        self.spans.append({
            "span_id": f"approval-{record['approval_id']}-{len(self.spans)}",
            "parent_span_id": None,
            "kind": "approval",
            "name": "human_approval",
            "start_time": record["requested_at"],
            "end_time": record["decided_at"],
            "duration_ms": 0.0,
            "status": record["decision"],
            "approval_requested": True,
            **{k: record[k] for k in ("approval_id", "tool", "decision", "decided_by", "preapproved")},
        })

    # -- results ------------------------------------------------------------

    @property
    def tools_called(self) -> List[str]:
        return [s["name"] for s in self.spans if s["kind"] == "tool"]

    @property
    def token_usage(self) -> Dict[str, int]:
        totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for span in self.spans:
            for key in totals:
                totals[key] += span.get("usage", {}).get(key, 0)
        return totals

    def save(self, traces_dir: Path, **run_attrs: Any) -> Path:
        """Write traces/<run_id>.json: run summary + tool selections + ordered spans."""
        traces_dir.mkdir(parents=True, exist_ok=True)
        path = traces_dir / f"{self.run_id}.json"
        trace = {
            "trace_schema_version": 2,
            "run_id": self.run_id,
            **run_attrs,
            "tools_selected": self.tools_selected,
            "redaction": {
                "applied": self.redactor is not None,
                "restricted_tool_outputs_withheld": self.restricted_outputs_withheld,
                "payload_limit_chars": self.max_payload_chars,
            },
            "spans": sorted(self.spans, key=lambda s: s["start_time"]),
        }
        path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
        return path
