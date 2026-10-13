"""Reconstruct a past agent run from persisted checkpoints + the run log.

Debugging in a non-deterministic system starts with reproducibility: you cannot
fix a failure you cannot restore. This module reads the durable SqliteSaver
checkpoints written during a run (keyed by thread_id == run_id) and cross-references
the monitoring log to rebuild the run's execution context — the input, the active
prompt/dataset versions, the tool trajectory, the intermediate tool outputs, and
the final answer.

It reads state through the checkpointer's own API, so it needs no model, no API
key, and no dataset load — a run can be inspected long after the process that
produced it has exited.
"""

import dataclasses
import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from realthor.monitor import load_run_records


@dataclasses.dataclass
class ReplayContext:
    """The reconstructed execution context of a single run."""

    run_id: str
    input_text: str = ""
    prompt_version: str = ""
    dataset_version: str = ""
    tools_called: list = dataclasses.field(default_factory=list)
    intermediate_values: list = dataclasses.field(default_factory=list)
    final_output: str = ""
    restored: bool = False


def build_checkpointer(cfg: dict) -> SqliteSaver:
    """Open the durable checkpoint database as a SqliteSaver.

    Uses the plain constructor with a raw sqlite3 connection so the saver stays
    alive for the whole command (unlike ``from_conn_string``, whose connection
    closes on ``with``-block exit). ``check_same_thread=False`` lets the agent
    loop touch the connection from worker threads.
    """
    conn = sqlite3.connect(cfg["debug"]["state_db"], check_same_thread=False)
    return SqliteSaver(conn)


def load_run(thread_id: str, checkpointer: SqliteSaver) -> list:
    """Return the run's checkpoint tuples, oldest to newest.

    ``checkpointer.list`` yields tuples most-recent-first; reverse so the caller
    reads the run in execution order. Returns an empty list if the thread was
    never persisted.
    """
    config = {"configurable": {"thread_id": thread_id}}
    return list(reversed(list(checkpointer.list(config))))


def _messages_from_snapshots(snapshots: list) -> list:
    """Pull the accumulated message list from the newest snapshot."""
    if not snapshots:
        return []
    channel_values = snapshots[-1].checkpoint.get("channel_values", {})
    return channel_values.get("messages", [])


def reconstruct_context(run_id: str, checkpointer: SqliteSaver, log_path: Path) -> ReplayContext:
    """Rebuild the execution context for ``run_id``.

    Walks the persisted messages to recover the tool trajectory, intermediate
    tool outputs, and final answer, then cross-references the ``runs.jsonl`` row
    for the same run_id to recover the input and the prompt/dataset versions that
    were active. When no checkpoint exists for the run, falls back to the log
    alone and marks ``restored=False``.
    """
    ctx = ReplayContext(run_id=run_id)

    snapshots = load_run(run_id, checkpointer)
    ctx.restored = bool(snapshots)

    for msg in _messages_from_snapshots(snapshots):
        if isinstance(msg, ToolMessage):
            if msg.name:
                ctx.tools_called.append(msg.name)
            ctx.intermediate_values.append(_as_text(msg.content))
        elif isinstance(msg, AIMessage):
            text = _as_text(msg.content)
            if text:
                ctx.final_output = text

    record = next((r for r in load_run_records(log_path) if r.run_id == run_id), None)
    if record is not None:
        ctx.input_text = record.input_text
        ctx.prompt_version = record.prompt_version
        ctx.dataset_version = record.dataset_version
        if not ctx.tools_called:
            ctx.tools_called = list(record.tools_called)

    return ctx


def _as_text(content) -> str:
    """Normalize message content (str or content-block list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [c.get("text", "") if isinstance(c, dict) else str(c) for c in content]
        return "".join(parts)
    return str(content)


def format_report(ctx: ReplayContext) -> str:
    """Render a reconstructed run as a human-readable report."""
    trajectory = " → ".join(ctx.tools_called) if ctx.tools_called else "(none)"
    lines = [
        f"Replay of run {ctx.run_id}",
        f"  state restored : {ctx.restored}",
        f"  input          : {ctx.input_text}",
        f"  prompt version : {ctx.prompt_version or '(unknown)'}",
        f"  dataset version: {ctx.dataset_version or '(unknown)'}",
        f"  tool trajectory: {trajectory}",
    ]
    if ctx.intermediate_values:
        lines.append("  intermediate values:")
        for name, value in zip(ctx.tools_called, ctx.intermediate_values):
            lines.append(f"    - {name}: {value}")
    lines.append(f"  final output   : {ctx.final_output}")
    return "\n".join(lines)
