"""Tests for identity resolution and the state-isolation key (context.py).

Offline: no model, no API key. resolve_user reads a temporary application
database seeded from a tiny users.csv.
"""

import pandas as pd
import pytest

from realthor.auth import hash_password
from realthor.context import (
    GUEST_CONTEXT,
    UserContext,
    resolve_user,
    thread_id_for,
    trace_metadata,
)
from realthor.sessions import seed_users_from_csv


@pytest.fixture
def app_db(tmp_path):
    users_csv = tmp_path / "users.csv"
    pd.DataFrame(
        [
            ("analyst_001", "Maria", "analyst", "all", True),
            ("broker_west_001", "Emma", "broker", "west", True),
        ],
        columns=["user_id", "name", "role", "region_access", "active"],
    ).to_csv(users_csv, index=False)
    db = tmp_path / "realthor.db"
    seed_users_from_csv(str(db), str(users_csv), hash_password("pw"))
    return str(db)


# --- thread_id_for: the isolation key -------------------------------------

def test_thread_id_stable_for_same_identity():
    assert thread_id_for("analyst_001", "s1") == thread_id_for("analyst_001", "s1")


def test_thread_id_differs_across_users():
    assert thread_id_for("analyst_001", "s1") != thread_id_for("analyst_002", "s1")


def test_thread_id_differs_across_sessions():
    assert thread_id_for("analyst_001", "s1") != thread_id_for("analyst_001", "s2")


def test_thread_id_namespaced_by_user():
    # A shared/guessed session id still cannot collide across users.
    assert thread_id_for("analyst_001", "shared").startswith("analyst_001:")
    assert thread_id_for("analyst_002", "shared").startswith("analyst_002:")


def test_thread_id_guest_handling():
    assert thread_id_for("", "s1") == "guest:s1"


# --- resolve_user: identity from the database, not the caller -------------

def test_resolve_user_reads_role_and_region(app_db):
    ctx = resolve_user("broker_west_001", app_db)
    assert ctx.user_id == "broker_west_001"
    assert ctx.role == "broker"
    assert ctx.region_access == "west"


def test_resolve_unknown_user_is_guest(app_db):
    assert resolve_user("nobody", app_db) is GUEST_CONTEXT


def test_resolve_empty_user_is_guest(app_db):
    assert resolve_user("", app_db) is GUEST_CONTEXT


# --- trace_metadata: identity attribution on traces ------------------------

def test_trace_metadata_carries_identity_and_tag():
    ctx = UserContext(user_id="analyst_001", role="analyst", region_access="all")
    md = trace_metadata(ctx, "sess-1", "chat")
    assert md["langfuse_user_id"] == "analyst_001"
    assert md["langfuse_session_id"] == "sess-1"
    assert md["langfuse_tags"] == ["chat"]


def test_trace_metadata_tag_is_the_command():
    ctx = UserContext(user_id="analyst_002", role="analyst", region_access="all")
    assert trace_metadata(ctx, "s", "analyze")["langfuse_tags"] == ["analyze"]


def test_trace_metadata_guest_fallback():
    md = trace_metadata(GUEST_CONTEXT, "s", "chat")
    assert md["langfuse_user_id"] == "guest"
