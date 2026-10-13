"""Unit tests for replay.py — reconstructing a past run from persisted state.

Fixture-driven and fully offline: reads the pre-generated tests/fixtures/state.db
(a real SqliteSaver database) and a matching log line. No model, no API key.
Regenerate the checkpoint fixture with: uv run python tests/fixtures/make_replay_fixture.py
"""

from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from realthor.replay import (
    ReplayContext,
    build_checkpointer,
    load_run,
    reconstruct_context,
)

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_DB = FIXTURES / "state.db"
FIXTURE_LOG = FIXTURES / "replay_runs.jsonl"
THREAD_ID = "demo_north_ibuyer"


def _checkpointer() -> SqliteSaver:
    import sqlite3

    return SqliteSaver(sqlite3.connect(str(FIXTURE_DB), check_same_thread=False))


def test_build_checkpointer_returns_sqlite_saver(tmp_path):
    cfg = {"debug": {"state_db": str(tmp_path / "state.db")}}
    checkpointer = build_checkpointer(cfg)
    assert isinstance(checkpointer, SqliteSaver)


def test_load_run_empty_for_unknown_thread():
    assert load_run("no-such-thread", _checkpointer()) == []


def test_load_run_orders_oldest_first():
    snapshots = load_run(THREAD_ID, _checkpointer())
    assert len(snapshots) >= 2
    created = [s.checkpoint["ts"] for s in snapshots]
    assert created == sorted(created)  # oldest -> newest


def test_reconstruct_context_extracts_tool_trajectory():
    ctx = reconstruct_context(THREAD_ID, _checkpointer(), FIXTURE_LOG)
    assert isinstance(ctx, ReplayContext)
    assert ctx.restored is True
    assert ctx.tools_called == ["get_demand_score"]
    assert "Recommend iBuyer" in ctx.final_output


def test_reconstruct_context_extracts_intermediate_values():
    ctx = reconstruct_context(THREAD_ID, _checkpointer(), FIXTURE_LOG)
    assert any("demand_score=0.37" in v for v in ctx.intermediate_values)


def test_reconstruct_context_cross_references_log():
    ctx = reconstruct_context(THREAD_ID, _checkpointer(), FIXTURE_LOG)
    assert ctx.input_text == "Should we acquire through iBuyer in north for 3-bedroom houses?"
    assert ctx.prompt_version == "system_prompt_v8.md"
    assert ctx.dataset_version == "0.8.0"


def test_reconstruct_context_flags_missing_state(tmp_path):
    # Unknown thread + a log that has no matching row -> nothing restored.
    empty_db = build_checkpointer({"debug": {"state_db": str(tmp_path / "empty.db")}})
    ctx = reconstruct_context("ghost-run", empty_db, FIXTURE_LOG)
    assert ctx.restored is False
    assert ctx.tools_called == []
    assert ctx.final_output == ""
