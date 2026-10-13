"""Local trace artifacts.

`LocalTraceRecorder` is a LangChain callback handler that records each model call
and tool call of one agent run as a span (name, timings, token usage, truncated
inputs/outputs, errors). `save()` writes the trace to traces/<run_id>.json, so every
run can be inspected after the fact without an external tracing backend.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalTraceRecorder(BaseCallbackHandler):
    def __init__(self, run_id: str, max_payload_chars: int = 2000):
        self.run_id = run_id
        self.max_payload_chars = max_payload_chars
        self.spans: List[Dict[str, Any]] = []
        self._open: Dict[UUID, Dict[str, Any]] = {}

    # -- helpers ------------------------------------------------------------

    def _truncate(self, value: Any) -> str:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
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
        tool_calls: List[str] = []
        for gen_list in response.generations:
            for gen in gen_list:
                message = getattr(gen, "message", None)
                if message is None:
                    continue
                for key, val in (getattr(message, "usage_metadata", None) or {}).items():
                    if isinstance(val, int):
                        usage[key] = usage.get(key, 0) + val
                tool_calls += [tc["name"] for tc in getattr(message, "tool_calls", [])]
        self._end(run_id, status="ok", usage=usage, requested_tool_calls=tool_calls)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", error=repr(error))

    # -- tool calls ---------------------------------------------------------

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name", "tool")
        self._start(run_id, parent_run_id, "tool", name, input=self._truncate(inputs or input_str))

    def on_tool_end(self, output, *, run_id, **kwargs):
        content = getattr(output, "content", output)
        self._end(run_id, status="ok", output=self._truncate(content))

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", error=repr(error))

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
        traces_dir.mkdir(parents=True, exist_ok=True)
        path = traces_dir / f"{self.run_id}.json"
        trace = {
            "run_id": self.run_id,
            **run_attrs,
            "spans": sorted(self.spans, key=lambda s: s["start_time"]),
        }
        path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
        return path
