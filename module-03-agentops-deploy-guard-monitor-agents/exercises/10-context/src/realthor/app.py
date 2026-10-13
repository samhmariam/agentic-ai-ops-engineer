import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
from dotenv import load_dotenv
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from realthor import auth, sessions
from realthor.agents import build_main_agent
from realthor.config import load_config, resolve_paths
from realthor.context import GUEST_CONTEXT, resolve_user, thread_id_for, trace_metadata
from realthor.monitor import RunRecord, compute_metrics, generate_report, load_run_records
from realthor.replay import build_checkpointer, format_report, reconstruct_context
from realthor.tracing import build_tracer, flush_tracer

load_dotenv()


def ensure_db(cfg: dict) -> None:
    """Make sure the application database exists and is seeded.

    Idempotent: creates the users/sessions tables and, on a fresh database,
    seeds users from users.csv with the shared dev password. Lets the app run
    end-to-end even before ``data_forge`` has been invoked.
    """
    app_db = cfg["paths"]["app_db"]
    sessions.init_db(app_db)
    if sessions.is_empty(app_db):
        sessions.seed_users_from_csv(
            app_db, cfg["paths"]["users_data"], auth.hash_password(auth.DEV_PASSWORD)
        )


def authenticate_or_exit(cfg: dict, user_id: str, password: str):
    """Resolve identity for a headless subcommand.

    No ``user_id`` → guest mode (maximum restriction). A ``user_id`` must be
    backed by a matching ``--password``: identity is a proven credential now, not
    a bare flag, so the same rule holds locally and in CI.
    """
    if not user_id:
        return GUEST_CONTEXT
    if not password:
        raise click.ClickException(
            f"Authentication required: pass --password for --user {user_id}."
        )
    ctx = auth.authenticate(cfg["paths"]["app_db"], user_id, password)
    if ctx is None:
        raise click.ClickException(f"Authentication failed for user {user_id}.")
    return ctx


def _extract_token_usage(callback: UsageMetadataCallbackHandler, model_name: str) -> tuple:
    usage = callback.usage_metadata.get(model_name, {})
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def _build_run_record(
    run_id: str,
    timestamp: str,
    user_id: str,
    command: str,
    input_text: str,
    result,
    success: bool,
    failure_reason: str,
    latency_s: float,
    input_tokens: int,
    output_tokens: int,
    cfg: dict,
    hitl_decision: str = "none",
) -> RunRecord:
    cost_per_1k_in = cfg["logging"]["cost_per_1k_tokens_input"]
    cost_per_1k_out = cfg["logging"]["cost_per_1k_tokens_output"]
    cost_usd = (input_tokens / 1000) * cost_per_1k_in + (output_tokens / 1000) * cost_per_1k_out

    tools_called = []
    guardrail_blocked = False
    guardrail_reason = ""

    if result and isinstance(result, dict):
        messages = result.get("messages", [])
        for msg in messages:
            if isinstance(msg, ToolMessage) and msg.name:
                tools_called.append(msg.name)
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                try:
                    parsed = json.loads(msg.content)
                    if parsed.get("status") == "blocked":
                        guardrail_blocked = True
                        guardrail_reason = parsed.get("reason", "")
                except (json.JSONDecodeError, AttributeError):
                    pass

    return RunRecord(
        run_id=run_id,
        timestamp=timestamp,
        user_id=user_id,
        command=command,
        input_text=input_text,
        success=success,
        failure_reason=failure_reason,
        latency_s=latency_s,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        tools_called=tools_called,
        guardrail_blocked=guardrail_blocked,
        guardrail_reason=guardrail_reason,
        hitl_decision=hitl_decision,
        prompt_version=Path(cfg["paths"]["prompt"]).name,
        dataset_version=cfg["agent"]["version"],
    )


def _log_run(cfg: dict, record: RunRecord) -> None:
    log_dir = Path(cfg["logging"]["log_dir"])
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "runs.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(record.__dict__) + "\n")


def run_agent_turn(
    cfg: dict,
    agent,
    user_ctx,
    session_id: str,
    message: str,
    command: str,
    tracer,
    approval: str | None = None,
    approval_resolver=None,
):
    """Invoke the agent for one turn, keyed to (identity, session).

    The checkpointer thread is ``thread_id_for(user, session)`` — state resumes
    for the same identity+session and is isolated from every other. When tracing
    is on, the trace is attributed with the user and session ids (and tagged by
    command) so runs group by identity in Langfuse.

    HITL: if a tool call needs approval the agent interrupts. A decision comes
    from ``approval`` (headless ``--approval``) or, when that is None, from
    ``approval_resolver(action)`` (the interactive app prompts the operator).
    With a decision the run resumes in the same invocation, so no interrupt is
    left dangling. Logs the run and returns ``(result, output_text, hitl_decision)``.
    """
    thread_id = thread_id_for(user_ctx.user_id or "", session_id)
    config = {"configurable": {"thread_id": thread_id}}

    callback = UsageMetadataCallbackHandler()
    callbacks = [callback] + ([tracer] if tracer else [])
    # Attribute the trace to the identity + session so runs group by who ran
    # them, and tag by command for easy filtering.
    trace_meta = {"metadata": trace_metadata(user_ctx, session_id, command)} if tracer else {}

    timestamp = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    result = None
    output_text = ""
    success = True
    failure_reason = ""
    hitl_decision = "none"

    try:
        result = agent.invoke(
            {"messages": [HumanMessage(message)]},
            config={**config, "callbacks": callbacks, **trace_meta},
            context=user_ctx,
        )
        if result.get("__interrupt__"):
            pending = result["__interrupt__"][0].value
            action = pending["action_requests"][0]
            click.echo(f"\n[HITL] Pending approval: {action['name']}")
            click.echo(f"[HITL] {action['description']}")
            # Decision from the headless flag, or from the interactive resolver
            # (which prompts the operator). None → left pending.
            decision = approval if approval is not None else (
                approval_resolver(action) if approval_resolver else None
            )
            if decision is None:
                hitl_decision = "pending"
                output_text = "This action requires operator approval."
                click.echo("\n" + output_text)
            else:
                result = agent.invoke(
                    Command(resume={"decisions": [{"type": decision}]}),
                    config={**config, "callbacks": callbacks, **trace_meta},
                    context=user_ctx,
                )
                hitl_decision = "approved" if decision == "approve" else "rejected"
                output_text = result["messages"][-1].content
                click.echo(f"[HITL] Decision: {decision}")
        else:
            output_text = result["messages"][-1].content
    except Exception as e:
        success = False
        failure_reason = str(e)
        click.echo(f"Error: {failure_reason}", err=True)
    finally:
        latency_s = time.perf_counter() - t0
        flush_tracer(tracer)
        input_tokens, output_tokens = _extract_token_usage(callback, cfg["model"]["name"])
        record = _build_run_record(
            run_id=thread_id,
            timestamp=timestamp,
            user_id=user_ctx.user_id or "",
            command=command,
            input_text=message,
            result=result,
            success=success,
            failure_reason=failure_reason,
            latency_s=latency_s,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cfg=cfg,
            hitl_decision=hitl_decision,
        )
        _log_run(cfg, record)

    return result, output_text, hitl_decision


@click.group(invoke_without_command=True)
@click.option("--config", "config_path", default="config.yaml", show_default=True)
@click.pass_context
def app(ctx, config_path):
    """RealThor — Listing Supply Intelligence.

    Run with no subcommand to start the interactive application (login + session
    menu). The subcommands below are the headless surface for scripting and CI.
    """
    if ctx.invoked_subcommand is None:
        # Lazy import avoids a circular dependency (interactive imports helpers here).
        from realthor.interactive import run_interactive

        run_interactive(config_path)


@app.command()
@click.option("--region", required=True, help="Ciudaty region (west, north, south, east, center)")
@click.option("--property-type", "property_type", required=True, help="apartment, house, or studio")
@click.option("--bedrooms", required=True, type=int, help="Number of bedrooms")
@click.option("--user", "user_id", default="", help="Authenticated user id")
@click.option("--password", default="", help="Password for --user (headless auth)")
@click.option(
    "--trace/--no-trace",
    default=None,
    help="Emit a Langfuse trace for this run (overrides config.tracing.enabled).",
)
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def analyze(region, property_type, bedrooms, user_id, password, trace, config_path):
    """Analyze listing priority for one region/property profile (headless)."""
    click.echo("Loading agent...")
    cfg = resolve_paths(load_config(config_path), config_path)
    ensure_db(cfg)
    if trace is not None:
        cfg = {**cfg, "tracing": {**cfg.get("tracing", {}), "enabled": trace}}
    user_ctx = authenticate_or_exit(cfg, user_id, password)
    click.echo(f"Identity: {user_ctx.user_id or 'guest'} ({user_ctx.role})")

    checkpointer = build_checkpointer(cfg)
    agent = build_main_agent(cfg, checkpointer=checkpointer)
    tracer = build_tracer(cfg)
    # A headless one-shot is an ephemeral session: unique id, keyed per run.
    session_id = str(uuid.uuid4())
    question = (
        f"What's the listing priority for {bedrooms}-bedroom "
        f"{property_type} in the {region} region?"
    )
    click.echo("Analyzing...")
    _, output_text, _ = run_agent_turn(
        cfg, agent, user_ctx, session_id, question, "analyze", tracer
    )
    click.echo(output_text)
    if tracer:
        click.echo("Trace sent to Langfuse — open your project to inspect the run.")


@app.command()
@click.option("--user", "-u", "user_id", default="", help="Authenticated user id")
@click.option("--password", default="", help="Password for --user (headless auth)")
@click.option("--message", "-m", required=True, help="Free-text message to send to the agent")
@click.option(
    "--approval",
    type=click.Choice(["approve", "reject"]),
    default=None,
    help="Pre-authorize (approve) or deny (reject) any pending HITL action.",
)
@click.option(
    "--trace/--no-trace",
    default=None,
    help="Emit a Langfuse trace for this run (overrides config.tracing.enabled).",
)
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def chat(user_id, password, message, approval, trace, config_path):
    """Send a free-text message to the agent (headless; all guardrails + HITL active)."""
    click.echo("Loading agent...")
    cfg = resolve_paths(load_config(config_path), config_path)
    ensure_db(cfg)
    if trace is not None:
        cfg = {**cfg, "tracing": {**cfg.get("tracing", {}), "enabled": trace}}
    user_ctx = authenticate_or_exit(cfg, user_id, password)
    click.echo(f"Identity: {user_ctx.user_id or 'guest'} ({user_ctx.role})")

    checkpointer = build_checkpointer(cfg)
    agent = build_main_agent(cfg, checkpointer=checkpointer)
    tracer = build_tracer(cfg)
    session_id = str(uuid.uuid4())
    click.echo("Analyzing...")
    result, output_text, hitl_decision = run_agent_turn(
        cfg, agent, user_ctx, session_id, message, "chat", tracer, approval=approval
    )
    if hitl_decision == "pending":
        click.echo("Re-run with --approval approve or --approval reject.")
    else:
        click.echo(output_text)
    if tracer:
        click.echo("Trace sent to Langfuse — open your project to inspect the run.")


@app.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def report(config_path):
    """Generate a monitoring report from logs/runs.jsonl."""
    cfg = resolve_paths(load_config(config_path), config_path)
    log_path = Path(cfg["logging"]["log_dir"]) / "runs.jsonl"
    output_dir = Path(cfg["logging"]["reports_dir"])
    records = load_run_records(log_path)
    if not records:
        click.echo(f"No run records found at {log_path}")
        return
    metrics = compute_metrics(records)
    generate_report(metrics, output_dir)
    click.echo(f"Report written to {output_dir / 'monitoring_report.md'}")


@app.command()
@click.option("--run-id", "run_id", required=True, help="run_id of a past run to reconstruct")
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def replay(run_id, config_path):
    """Reconstruct a past run's execution context from persisted checkpoints + logs."""
    cfg = resolve_paths(load_config(config_path), config_path)
    log_path = Path(cfg["logging"]["log_dir"]) / "runs.jsonl"
    checkpointer = build_checkpointer(cfg)
    ctx = reconstruct_context(run_id, checkpointer, log_path)
    click.echo(format_report(ctx))
