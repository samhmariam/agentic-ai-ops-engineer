"""The interactive RealThor application: login, then a session menu.

This is where RealThor stops being a one-shot command and becomes a multi-user
app. A caller logs in with a password (no ``--user`` impersonation), then works
inside owned, resumable sessions — the way a chat product lists your past
conversations and lets you pick one up. Each session has a human-readable title
from its first message and a durable thread, so context persists across turns
and never crosses to another identity.

In M11 the agent's market-data tools are no longer built in-process — they are
served by the MCP data service and fetched over the protocol at startup. All of
this is pre-wired: the only piece the student implements is ``load_mcp_tools``
(the connection to the MCP server) in ``mcp_client.py``.
"""

import asyncio

import aiosqlite
import click
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from realthor import auth, sessions
from realthor.agents import build_main_agent
from realthor.app import arun_agent_turn, ensure_db
from realthor.config import load_config, make_chat_model, resolve_paths
from realthor.mcp_client import load_mcp_tools
from realthor.tracing import build_tracer

_MAX_LOGIN_ATTEMPTS = 3

# The agent turn is async (MCP tools are async), and its SQLite checkpointer is
# async too (AsyncSqliteSaver). aiosqlite binds a connection to the event loop
# that created it, so we run every turn on ONE persistent loop for the session —
# not a fresh asyncio.run() per turn, which would strand the connection.
_LOOP: asyncio.AbstractEventLoop | None = None


def run_interactive(config_path: str) -> None:
    global _LOOP
    cfg = resolve_paths(load_config(config_path), config_path)
    ensure_db(cfg)

    click.echo("=" * 48)
    click.echo("  RealThor — Listing Supply Intelligence")
    click.echo("=" * 48)

    try:
        user_ctx = _login(cfg)
        if user_ctx is None:
            click.echo("Too many failed attempts. Goodbye.")
            return
        click.echo(
            f"\nWelcome, {user_ctx.user_id} ({user_ctx.role}). Access: {user_ctx.region_access}"
        )

        # One persistent event loop for the whole session (see the _LOOP note).
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)

        async def _open_session():
            # AsyncSqliteSaver captures the *running* loop at construction, and
            # loads the tools over MCP — both must happen on _LOOP.
            conn = await aiosqlite.connect(cfg["debug"]["state_db"])
            checkpointer = AsyncSqliteSaver(conn)
            mcp_tools = await load_mcp_tools(cfg)
            return conn, checkpointer, mcp_tools

        conn, checkpointer, mcp_tools = _LOOP.run_until_complete(_open_session())
        try:
            # Build the agent + tracer once; every session reuses them. The agent's
            # market-data tools are the MCP-served ones fetched above (start the
            # server first with `uv run proptech-mcp serve`).
            agent = build_main_agent(cfg, checkpointer=checkpointer, mcp_tools=mcp_tools)
            tracer = build_tracer(cfg)
            title_model = make_chat_model(cfg)
            _menu_loop(cfg, agent, user_ctx, tracer, title_model)
        finally:
            _LOOP.run_until_complete(conn.close())
            _LOOP.close()
            _LOOP = None
    except (click.Abort, EOFError, KeyboardInterrupt):
        # Clean exit on Ctrl-C / Ctrl-D at any prompt — no traceback.
        click.echo("\nGoodbye.")


def _login(cfg: dict):
    app_db = cfg["paths"]["app_db"]
    for _ in range(_MAX_LOGIN_ATTEMPTS):
        user_id = click.prompt("\nUser id").strip()
        password = click.prompt("Password", hide_input=True)
        ctx = auth.authenticate(app_db, user_id, password)
        if ctx is not None:
            return ctx
        click.echo("Invalid credentials.")
    return None


def _menu_loop(cfg, agent, user_ctx, tracer, title_model) -> None:
    while True:
        click.echo("\n--- Menu ---")
        click.echo("  1) New session")
        click.echo("  2) Resume a session")
        click.echo("  3) Analyze a segment")
        click.echo("  4) Logout and exit")
        choice = click.prompt("Choose", type=click.Choice(["1", "2", "3", "4"]))

        if choice == "1":
            _new_session(cfg, agent, user_ctx, tracer, title_model)
        elif choice == "2":
            _resume_session(cfg, agent, user_ctx, tracer)
        elif choice == "3":
            _analyze(cfg, agent, user_ctx, tracer, title_model)
        else:
            click.echo("Logged out. Goodbye.")
            return


def _prompt_nonempty(text: str) -> str:
    """Prompt until the user enters something non-blank."""
    while True:
        value = click.prompt(text).strip()
        if value:
            return value
        click.echo("Please enter a value.")


def _approval_resolver(action) -> str:
    """Ask the operator to approve or reject a paused (HITL) action.

    ``run_agent_turn`` has already printed the action's name and description; here
    we just collect the decision and hand it back so the run resumes in place.
    """
    return click.prompt("[HITL] Approve or reject this action", type=click.Choice(["approve", "reject"]))


def _new_session(cfg, agent, user_ctx, tracer, title_model) -> None:
    app_db = cfg["paths"]["app_db"]
    first_message = _prompt_nonempty("\nWhat do you want to ask")
    title = sessions.generate_title(first_message, model=title_model)
    session_id = sessions.create_session(app_db, user_ctx.user_id, title)
    click.echo(f'Started session "{title}"')

    _run_and_show(cfg, agent, user_ctx, tracer, session_id, first_message, "chat")
    _chat_loop(cfg, agent, user_ctx, tracer, session_id)


def _resume_session(cfg, agent, user_ctx, tracer) -> None:
    app_db = cfg["paths"]["app_db"]
    my_sessions = sessions.list_sessions(app_db, user_ctx.user_id)
    if not my_sessions:
        click.echo("\nYou have no previous sessions.")
        return

    click.echo("\n--- Your sessions ---")
    for i, s in enumerate(my_sessions, 1):
        when = s["last_active_at"][:19].replace("T", " ")
        click.echo(f"  {i}) {s['title']}  ·  {s['message_count']} msgs  ·  {when}")
    idx = click.prompt("Resume which", type=click.IntRange(1, len(my_sessions)))
    chosen = my_sessions[idx - 1]

    # Ownership re-check through the same guarded accessor the isolation contract
    # relies on: a session is only ever loaded for the user who owns it.
    session = sessions.get_session(app_db, chosen["session_id"], user_ctx.user_id)
    if session is None:
        click.echo("Session not found for this user.")
        return
    click.echo(f'Resumed "{session["title"]}"')
    _chat_loop(cfg, agent, user_ctx, tracer, session["session_id"])


def _analyze(cfg, agent, user_ctx, tracer, title_model) -> None:
    app_db = cfg["paths"]["app_db"]
    region = _prompt_nonempty("Region")
    property_type = _prompt_nonempty("Property type")
    bedrooms = click.prompt("Bedrooms", type=int)
    question = (
        f"What's the listing priority for {bedrooms}-bedroom "
        f"{property_type} in the {region} region?"
    )
    title = f"Analyze {bedrooms}br {property_type} in {region}"
    session_id = sessions.create_session(app_db, user_ctx.user_id, title)
    _run_and_show(cfg, agent, user_ctx, tracer, session_id, question, "analyze")
    # An analysis is a real session — let the caller keep asking follow-ups.
    _chat_loop(cfg, agent, user_ctx, tracer, session_id)


def _chat_loop(cfg, agent, user_ctx, tracer, session_id) -> None:
    click.echo("(type /back to return to the menu)")
    while True:
        message = click.prompt("\nyou").strip()
        if message == "/back":
            return
        if not message:
            continue
        _run_and_show(cfg, agent, user_ctx, tracer, session_id, message, "chat")


def _run_and_show(cfg, agent, user_ctx, tracer, session_id, message, command) -> None:
    # The turn is async (MCP tools + async checkpointer); run it on the session's
    # persistent loop so the aiosqlite connection stays valid across turns.
    _, output_text, _ = _LOOP.run_until_complete(
        arun_agent_turn(
            cfg, agent, user_ctx, session_id, message, command, tracer,
            approval_resolver=_approval_resolver,
        )
    )
    sessions.touch_session(cfg["paths"]["app_db"], session_id)
    click.echo(f"\nrealthor> {output_text}")
    if tracer:
        click.echo("(traced — grouped by your user id and session in Langfuse)")
