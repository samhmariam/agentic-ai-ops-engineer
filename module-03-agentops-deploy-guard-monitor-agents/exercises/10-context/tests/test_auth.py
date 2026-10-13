"""Tests for authentication (auth.py). Offline: no model, no API key."""

import pandas as pd
import pytest

from realthor.auth import authenticate, hash_password, verify_password
from realthor.sessions import seed_users_from_csv


@pytest.fixture
def app_db(tmp_path):
    users_csv = tmp_path / "users.csv"
    pd.DataFrame(
        [
            ("analyst_001", "Maria", "analyst", "all", True),
            ("broker_off", "Ghost", "broker", "east", False),
        ],
        columns=["user_id", "name", "role", "region_access", "active"],
    ).to_csv(users_csv, index=False)
    db = tmp_path / "realthor.db"
    seed_users_from_csv(str(db), str(users_csv), hash_password("realthor-dev"))
    return str(db)


def test_hash_verify_round_trip():
    stored = hash_password("s3cret")
    assert verify_password("s3cret", stored)


def test_verify_rejects_wrong_password():
    stored = hash_password("s3cret")
    assert not verify_password("guessed", stored)


def test_verify_rejects_malformed_hash():
    assert not verify_password("anything", "not-a-valid-hash")


def test_hash_is_salted():
    # Two hashes of the same password differ (random salt).
    assert hash_password("same") != hash_password("same")


def test_authenticate_valid_credentials(app_db):
    ctx = authenticate(app_db, "analyst_001", "realthor-dev")
    assert ctx is not None
    assert ctx.user_id == "analyst_001"
    assert ctx.role == "analyst"


def test_authenticate_wrong_password(app_db):
    assert authenticate(app_db, "analyst_001", "wrong") is None


def test_authenticate_unknown_user(app_db):
    assert authenticate(app_db, "nobody", "realthor-dev") is None


def test_authenticate_inactive_user(app_db):
    # Inactive users are filtered out at lookup, so they cannot authenticate.
    assert authenticate(app_db, "broker_off", "realthor-dev") is None
