"""CLI tests for the interactive app (interactive.py) via click's CliRunner.

Offline and deterministic: the model, checkpointer, tracer, and title model are
monkeypatched, so no API key or network is needed. A tmp config points the
application database at the isolated filesystem, so tests never touch the real
realthor.db. These cover the surfaces unit tests miss — login, session lifecycle,
ownership isolation, and the HITL approve/reject flow.
"""

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from langgraph.types import Command

from realthor import interactive, sessions
from realthor.app import app

REAL_USERS_CSV = str(Path(__file__).parent.parent / "data" / "users.csv")


# --- fakes -----------------------------------------------------------------

class _Msg:
    def __init__(self, content):
        self.content = content
        self.name = None


class _Interrupt:
    def __init__(self, value):
        self.value = value


class _FakeAgent:
    """Returns canned turns. A message containing 'submit' triggers a HITL
    interrupt; the Command(resume=...) call returns the completed action.

    ``ainvoke`` (async) mirrors the real agent — the turn is driven with
    ``ainvoke`` now that RealThor's tools are served over MCP (async)."""

    async def ainvoke(self, payload, config=None, context=None):
        if isinstance(payload, Command):
            return {"messages": [_Msg("Channel recommendation submitted.")]}
        text = payload["messages"][-1].content.lower()
        if "submit" in text:
            return {
                "__interrupt__": [
                    _Interrupt(
                        {"action_requests": [
                            {"name": "submit_channel_recommendation",
                             "description": "Submit a channel recommendation for OPP-00001"}
                        ]}
                    )
                ]
            }
        return {"messages": [_Msg("Demand is strong (0.82).")]}


class _FakeTitleModel:
    def __init__(self, *a, **k):
        pass

    def invoke(self, _prompt):
        return _Msg("Test session title")


async def _fake_load_mcp_tools(cfg):
    """No MCP server in tests — the faked agent ignores tools anyway."""
    return []


@pytest.fixture
def cli(monkeypatch):
    """A CliRunner with the interactive module's heavy deps stubbed out."""
    monkeypatch.setattr(
        interactive, "build_main_agent",
        lambda cfg, checkpointer=None, mcp_tools=None: _FakeAgent(),
    )
    # The fake agent ignores the checkpointer, so the real AsyncSqliteSaver runs
    # harmlessly against a tmp state.db in the isolated filesystem (offline).
    monkeypatch.setattr(interactive, "build_tracer", lambda cfg: None)
    monkeypatch.setattr(interactive, "load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr(interactive, "make_chat_model", lambda cfg: _FakeTitleModel())
    return CliRunner()


def _write_config() -> str:
    """Write a tmp config (CWD = isolated fs); app_db lives here, users from the real CSV."""
    cfg = {
        "agent": {"name": "RealThor", "version": "0.11.0-test"},
        "model": {"name": "gpt-4o-mini", "temperature": 0.0},
        "tracing": {"enabled": False},
        "debug": {"state_db": "state.db"},
        "paths": {
            "prompt": "prompts/system_prompt_v11.md",  # basename only used (agent is faked)
            "app_db": "realthor.db",
            "users_data": REAL_USERS_CSV,  # absolute → survives resolve_paths
        },
        "logging": {
            "log_dir": "logs", "reports_dir": "reports",
            "cost_per_1k_tokens_input": 0.00015, "cost_per_1k_tokens_output": 0.00060,
        },
    }
    with open("config.yaml", "w") as f:
        yaml.safe_dump(cfg, f)
    return "config.yaml"


def _run(cli, stdin: str):
    with cli.isolated_filesystem():
        config = _write_config()
        return cli.invoke(app, ["--config", config], input=stdin)


# --- login -----------------------------------------------------------------

def test_wrong_then_right_password(cli):
    # attempt 1: wrong password; attempt 2: correct; then logout
    r = _run(cli, "analyst_001\nWRONG\nanalyst_001\nrealthor-dev\n4\n")
    assert r.exit_code == 0
    assert "Invalid credentials" in r.output
    assert "Welcome, analyst_001" in r.output
    assert "Logged out" in r.output


# --- session lifecycle -----------------------------------------------------

def test_new_session_answers_and_persists(cli):
    with cli.isolated_filesystem():
        config = _write_config()
        r = cli.invoke(
            app, ["--config", config],
            input="analyst_001\nrealthor-dev\n1\nWhat is demand for west?\n/back\n4\n",
        )
        assert r.exit_code == 0
        assert "Started session" in r.output
        assert "Demand is strong" in r.output  # the faked answer was shown
        # a session row was created for this user
        rows = sessions.list_sessions("realthor.db", "analyst_001")
        assert len(rows) == 1 and rows[0]["title"] == "Test session title"


# --- ownership isolation ---------------------------------------------------

def test_sessions_are_isolated_per_user(cli):
    with cli.isolated_filesystem():
        config = _write_config()
        # analyst_001 creates a session
        cli.invoke(app, ["--config", config],
                   input="analyst_001\nrealthor-dev\n1\nMy private note\n/back\n4\n")
        # analyst_002 tries to resume — should see none of analyst_001's
        r2 = cli.invoke(app, ["--config", config],
                        input="analyst_002\nrealthor-dev\n2\n4\n")
        assert "You have no previous sessions" in r2.output
        # analyst_001 resumes — their own session is listed
        r3 = cli.invoke(app, ["--config", config],
                        input="analyst_001\nrealthor-dev\n2\n1\n/back\n4\n")
        assert "Test session title" in r3.output


# --- HITL approve / reject -------------------------------------------------

def test_hitl_approve_completes_action(cli):
    r = _run(cli, "analyst_001\nrealthor-dev\n1\nplease submit a recommendation\napprove\n/back\n4\n")
    assert r.exit_code == 0
    assert "Pending approval: submit_channel_recommendation" in r.output
    assert "Decision: approve" in r.output
    assert "Channel recommendation submitted." in r.output


def test_hitl_reject_blocks_action(cli):
    r = _run(cli, "analyst_001\nrealthor-dev\n1\nplease submit a recommendation\nreject\n/back\n4\n")
    assert r.exit_code == 0
    assert "Decision: reject" in r.output


# --- graceful exit ---------------------------------------------------------

def test_eof_exits_cleanly(cli):
    # input ends at the menu prompt → EOF → clean goodbye, no traceback
    r = _run(cli, "analyst_001\nrealthor-dev\n")
    assert r.exit_code == 0
    assert "Goodbye." in r.output
