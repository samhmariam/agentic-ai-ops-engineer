"""Identity and state-isolation keys.

At scale, RealThor serves many callers at once. Two things must hold:

1. A caller's conversation must *persist* — a follow-up question continues the
   same thread instead of starting from nothing.
2. One caller's state must never *leak* into another's.

Both come down to a single rule: agent state is keyed to identity. This module
owns that key. ``resolve_user`` turns an authenticated ``user_id`` into a
``UserContext`` (role + region access, read from the application database, never
trusted from the caller). ``thread_id_for`` derives the checkpointer thread key
so the same user+session resumes its own conversation and no other identity can
reach it.

``UserContext`` itself is defined in ``guardrails`` (it was born there in the
guardrail module); it is re-exported here so identity has one import surface.
"""

from realthor.guardrails import GUEST_CONTEXT, UserContext
from realthor.sessions import get_user

__all__ = [
    "GUEST_CONTEXT",
    "UserContext",
    "resolve_user",
    "thread_id_for",
    "trace_metadata",
]


def thread_id_for(user_id: str, session_id: str) -> str:
    """Derive the checkpointer thread key for a (user, session) pair.

    This is the third layer of RealThor's isolation contract, beneath
    authentication (you are who you logged in as) and session ownership (you can
    only resume your own sessions). Namespacing the thread by ``user_id`` means
    that even a leaked or guessed ``session_id`` cannot cross into another user's
    checkpoint space.

    Contract:
      * Same ``user_id`` + same ``session_id`` → same key → state resumes.
      * Different ``user_id`` *or* ``session_id`` → different key → state isolated.

    Empty ``user_id`` is treated as ``guest``.
    """
    return f"{user_id or 'guest'}:{session_id}"


def trace_metadata(user_ctx: UserContext, session_id: str, command: str) -> dict:
    """Build the Langfuse trace attribution for one run.

    This is the module's payoff wired into observability: every traced run is
    attributed to *who* ran it and *which session*, so in Langfuse you can filter
    by user or session and see each identity's runs as a separate group — the
    same isolation the checkpointer enforces on state, made visible in the traces.

    Returns the keys Langfuse reads from ``config["metadata"]``:
      * ``langfuse_user_id``   — the caller (``"guest"`` when unauthenticated),
      * ``langfuse_session_id``— groups a user's turns into one conversation,
      * ``langfuse_tags``      — ``[command]`` (e.g. ``"chat"``/``"analyze"``) for filtering.
    """
    return {
        "langfuse_user_id": user_ctx.user_id or "guest",
        "langfuse_session_id": session_id,
        "langfuse_tags": [command],
    }


def resolve_user(user_id: str, app_db_path: str) -> UserContext:
    """Resolve an identity to a ``UserContext`` from the application database.

    The role and region access come from the ``users`` table — never from a
    caller-supplied claim. Returns ``GUEST_CONTEXT`` when ``user_id`` is empty or
    unknown. This is the trusted, password-free path used once identity is
    already established (the CLI login and the eval harness); interactive login
    goes through ``auth.authenticate``, which additionally checks the password.
    """
    if not user_id:
        return GUEST_CONTEXT
    row = get_user(app_db_path, user_id)
    if row is None:
        return GUEST_CONTEXT
    return UserContext(
        user_id=str(row["user_id"]),
        role=str(row["role"]),
        region_access=str(row["region_access"]),
    )
