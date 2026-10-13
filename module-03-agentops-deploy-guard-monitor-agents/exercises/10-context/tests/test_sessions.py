"""Tests for the application database: users + sessions (sessions.py).

Offline: no model, no API key. generate_title uses the prefix fallback (model
is None), so no LLM call is made.
"""

import pandas as pd
import pytest

from realthor.auth import hash_password
from realthor.sessions import (
    create_session,
    generate_title,
    get_session,
    get_user,
    list_sessions,
    seed_users_from_csv,
    touch_session,
)


@pytest.fixture
def app_db(tmp_path):
    users_csv = tmp_path / "users.csv"
    pd.DataFrame(
        [
            ("analyst_001", "Maria", "analyst", "all", True),
            ("broker_west_001", "Emma", "broker", "west", True),
            ("broker_off", "Ghost", "broker", "east", False),
        ],
        columns=["user_id", "name", "role", "region_access", "active"],
    ).to_csv(users_csv, index=False)
    db = tmp_path / "realthor.db"
    seed_users_from_csv(str(db), str(users_csv), hash_password("pw"))
    return str(db)


# --- users -----------------------------------------------------------------

def test_get_user_active(app_db):
    row = get_user(app_db, "analyst_001")
    assert row is not None and row["role"] == "analyst"


def test_get_user_inactive_is_none(app_db):
    assert get_user(app_db, "broker_off") is None


def test_seed_is_idempotent(app_db, tmp_path):
    users_csv = tmp_path / "users.csv"  # same fixture csv
    n = seed_users_from_csv(app_db, str(users_csv), hash_password("pw"))
    assert n == 3
    assert get_user(app_db, "analyst_001") is not None


# --- sessions: ownership & persistence ------------------------------------

def test_create_and_get_own_session(app_db):
    sid = create_session(app_db, "analyst_001", "Priority for west")
    s = get_session(app_db, sid, "analyst_001")
    assert s is not None and s["title"] == "Priority for west"


def test_get_session_denies_other_user(app_db):
    sid = create_session(app_db, "analyst_001", "Private")
    # A different user cannot fetch it even with the exact id.
    assert get_session(app_db, sid, "broker_west_001") is None


def test_list_sessions_scoped_to_owner(app_db):
    create_session(app_db, "analyst_001", "A")
    create_session(app_db, "analyst_001", "B")
    create_session(app_db, "broker_west_001", "C")
    mine = list_sessions(app_db, "analyst_001")
    assert {s["title"] for s in mine} == {"A", "B"}
    assert list_sessions(app_db, "broker_west_001")[0]["title"] == "C"


def test_touch_increments_message_count(app_db):
    sid = create_session(app_db, "analyst_001", "Counting")
    touch_session(app_db, sid)
    touch_session(app_db, sid)
    assert get_session(app_db, sid, "analyst_001")["message_count"] == 2


# --- titles ---------------------------------------------------------------

def test_generate_title_prefix_fallback():
    assert generate_title("What is the demand for west apartments?", model=None)


def test_generate_title_truncates_long_message():
    long = "word " * 50
    title = generate_title(long, model=None)
    assert title.endswith("…") and len(title) <= 50
