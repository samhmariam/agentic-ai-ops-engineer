"""The application database: users and sessions.

RealThor now keeps two SQLite databases with different responsibilities:

* ``state.db``   — the LangGraph checkpointer. *Agent* state: the messages and
  tool results of a conversation, keyed by ``thread_id``. Owned by the framework.
* ``realthor.db`` — *application* state: who the users are (credentials, role,
  region access) and their sessions (the resumable conversations a user owns).
  Owned by us. This module is its only gateway.

Sessions are first-class here, the way a conversation is first-class in a chat
product: each has an opaque ``session_id``, a human-readable ``title`` derived
from the first message, and an owner. A user lists and resumes only their own.
"""

import sqlite3
import uuid
from datetime import datetime, timezone

import pandas as pd

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,
    region_access TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1
)
"""

SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    title          TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    message_count  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(app_db_path: str) -> sqlite3.Connection:
    """Open the application database with row access by column name."""
    conn = sqlite3.connect(app_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(app_db_path: str) -> None:
    """Create the users and sessions tables if they do not exist."""
    conn = connect(app_db_path)
    try:
        conn.execute(USERS_SCHEMA)
        conn.execute(SESSIONS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def seed_users_from_csv(app_db_path: str, users_csv: str, password_hash: str) -> int:
    """Populate the users table from users.csv, giving every user the same
    (already hashed) development password. Idempotent — existing rows are
    replaced. Returns the number of users written.

    users.csv stays the seed of truth for role and region access; the database
    adds the credential column the CSV never had.
    """
    init_db(app_db_path)
    df = pd.read_csv(users_csv)
    conn = connect(app_db_path)
    try:
        for _, r in df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO users "
                "(user_id, name, role, region_access, password_hash, active) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(r["user_id"]),
                    str(r["name"]),
                    str(r["role"]),
                    str(r["region_access"]),
                    password_hash,
                    1 if bool(r["active"]) else 0,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return len(df)


def is_empty(app_db_path: str) -> bool:
    """True if the users table has no rows (fresh database needing a seed)."""
    init_db(app_db_path)
    conn = connect(app_db_path)
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    finally:
        conn.close()
    return n == 0


def get_user(app_db_path: str, user_id: str) -> sqlite3.Row | None:
    """Return the users row for ``user_id`` (active only), or None."""
    conn = connect(app_db_path)
    try:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ? AND active = 1", (user_id,)
        ).fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sessions — owned, resumable conversations
# ---------------------------------------------------------------------------

def create_session(app_db_path: str, user_id: str, title: str) -> str:
    """Create a session owned by ``user_id`` and return its ``session_id``."""
    session_id = str(uuid.uuid4())
    now = _now()
    conn = connect(app_db_path)
    try:
        conn.execute(
            "INSERT INTO sessions "
            "(session_id, user_id, title, created_at, last_active_at, message_count) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (session_id, user_id, title, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def list_sessions(app_db_path: str, user_id: str) -> list[dict]:
    """List a user's own sessions, most recently active first.

    Ownership is the query's WHERE clause: a user can only ever see sessions
    where ``user_id`` matches. There is no path to another user's list.
    """
    conn = connect(app_db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY last_active_at DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_session(app_db_path: str, session_id: str, user_id: str) -> dict | None:
    """Fetch a session **only if it belongs to ``user_id``**.

    The ``user_id`` predicate is the ownership check: passing someone else's
    ``session_id`` returns None, so a caller can never resume a session they do
    not own — even if they learn its id.
    """
    conn = connect(app_db_path)
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def touch_session(app_db_path: str, session_id: str) -> None:
    """Record activity on a session: bump last_active_at and message_count."""
    conn = connect(app_db_path)
    try:
        conn.execute(
            "UPDATE sessions "
            "SET last_active_at = ?, message_count = message_count + 1 "
            "WHERE session_id = ?",
            (_now(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session titles — a human-readable name from the first message
# ---------------------------------------------------------------------------

_TITLE_PROMPT = (
    "Summarize the following user request as a short session title of at most 6 "
    "words. Return only the title, no punctuation at the end.\n\nRequest: {msg}"
)


def _prefix_title(first_message: str, max_len: int = 48) -> str:
    """Fallback title: a trimmed prefix of the first message."""
    text = " ".join(first_message.split())
    if len(text) <= max_len:
        return text or "New session"
    return text[:max_len].rstrip() + "…"


def generate_title(first_message: str, model=None) -> str:
    """Generate a human-readable session title from the first message.

    Mirrors how chat products name conversations: a short LLM one-liner. Falls
    back to a prefix of the message when no model is supplied or the call fails
    (offline, no API key), so title generation never blocks starting a session.
    """
    if model is None:
        return _prefix_title(first_message)
    try:
        resp = model.invoke(_TITLE_PROMPT.format(msg=first_message))
        title = (getattr(resp, "content", "") or "").strip().strip('"')
        return title or _prefix_title(first_message)
    except Exception:
        return _prefix_title(first_message)
