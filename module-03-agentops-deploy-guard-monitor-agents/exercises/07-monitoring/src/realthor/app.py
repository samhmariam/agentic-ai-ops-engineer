import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd
from dotenv import load_dotenv
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from realthor.agents import build_main_agent
from realthor.config import load_config, resolve_paths
from realthor.guardrails import GUEST_CONTEXT, UserContext
from realthor.monitor import RunRecord, compute_metrics, generate_report, load_run_records

load_dotenv()


def _resolve_user(user_id: str, users_path: str) -> UserContext:
    """Look up user in users.csv. Returns GUEST_CONTEXT if not found or no user_id."""
    if not user_id:
        return GUEST_CONTEXT
    users = pd.read_csv(users_path)
    row = users[users["user_id"] == user_id]
    if row.empty:
        return GUEST_CONTEXT
    r = row.iloc[0]
    return UserContext(
        user_id=str(r["user_id"]),
        role=str(r["role"]),
        region_access=str(r["region_access"]),
    )


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
    )


def _log_run(cfg: dict, record: RunRecord) -> None:
    log_dir = Path(cfg["logging"]["log_dir"])
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "runs.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(record.__dict__) + "\n")


@click.group()
def app():
    """RealThor — Listing Supply Intelligence CLI."""


@app.command()
@click.option("--region", required=True, help="Ciudaty region (west, north, south, east, center)")
@click.option("--property-type", "property_type", required=True, help="apartment, house, or studio")
@click.option("--bedrooms", required=True, type=int, help="Number of bedrooms")
@click.option("--user", "user_id", default="", help="User ID resolved from users.csv")
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def analyze(region, property_type, bedrooms, user_id, config_path):
    """Analyze listing priority for one region/property profile."""
    click.echo("Loading agent...")
    cfg = resolve_paths(load_config(config_path), config_path)
    user_ctx = _resolve_user(user_id, cfg["paths"]["users_data"])
    click.echo(f"Identity: {user_ctx.user_id or 'guest'} ({user_ctx.role})")
    agent = build_main_agent(cfg)
    question = (
        f"What's the listing priority for {bedrooms}-bedroom "
        f"{property_type} in the {region} region?"
    )
    click.echo("Analyzing...")

    run_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    callback = UsageMetadataCallbackHandler()
    t0 = time.perf_counter()
    result = None
    success = True
    failure_reason = ""
    try:
        result = agent.invoke(
            {"messages": [HumanMessage(question)]},
            config={"callbacks": [callback]},
            context=user_ctx,
        )
        click.echo(result["messages"][-1].content)
    except Exception as e:
        success = False
        failure_reason = str(e)
        click.echo(f"Error: {failure_reason}", err=True)
    finally:
        latency_s = time.perf_counter() - t0
        input_tokens, output_tokens = _extract_token_usage(callback, cfg["model"]["name"])
        record = _build_run_record(
            run_id=run_id,
            timestamp=timestamp,
            user_id=user_ctx.user_id or "",
            command="analyze",
            input_text=question,
            result=result,
            success=success,
            failure_reason=failure_reason,
            latency_s=latency_s,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cfg=cfg,
        )
        _log_run(cfg, record)


@app.command()
@click.option("--user", "-u", "user_id", default="", help="User ID resolved from users.csv")
@click.option("--message", "-m", required=True, help="Free-text message to send to the agent")
@click.option(
    "--approval",
    type=click.Choice(["approve", "reject"]),
    default=None,
    help="Pre-authorize (approve) or deny (reject) any pending HITL action.",
)
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def chat(user_id, message, approval, config_path):
    """Send a free-text message to the agent (all guardrail layers + HITL policy active)."""
    click.echo("Loading agent...")
    cfg = resolve_paths(load_config(config_path), config_path)
    user_ctx = _resolve_user(user_id, cfg["paths"]["users_data"])
    click.echo(f"Identity: {user_ctx.user_id or 'guest'} ({user_ctx.role})")

    # InMemorySaver holds graph state across the pause/resume cycle.
    # This is a required setup detail — covered in depth in a later module.
    checkpointer = InMemorySaver()
    agent = build_main_agent(cfg, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    run_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    callback = UsageMetadataCallbackHandler()
    t0 = time.perf_counter()
    result = None
    success = True
    failure_reason = ""
    hitl_decision = "none"

    click.echo("Analyzing...")
    try:
        result = agent.invoke(
            {"messages": [HumanMessage(message)]},
            config={**config, "callbacks": [callback]},
            context=user_ctx,
        )

        if result.get("__interrupt__"):
            pending = result["__interrupt__"][0].value
            action = pending["action_requests"][0]
            click.echo(f"\n[HITL] Pending approval: {action['name']}")
            click.echo(f"[HITL] {action['description']}")
            if approval is None:
                hitl_decision = "pending"
                click.echo("\nThis action requires operator approval.")
                click.echo("Re-run with --approval approve or --approval reject.")
            else:
                result = agent.invoke(
                    Command(resume={"decisions": [{"type": approval}]}),
                    config={**config, "callbacks": [callback]},
                    context=user_ctx,
                )
                hitl_decision = "approved" if approval == "approve" else "rejected"
                click.echo(f"[HITL] Decision: {approval}")
                click.echo(result["messages"][-1].content)
        else:
            click.echo(result["messages"][-1].content)
    except Exception as e:
        success = False
        failure_reason = str(e)
        click.echo(f"Error: {failure_reason}", err=True)
    finally:
        latency_s = time.perf_counter() - t0
        input_tokens, output_tokens = _extract_token_usage(callback, cfg["model"]["name"])
        record = _build_run_record(
            run_id=run_id,
            timestamp=timestamp,
            user_id=user_ctx.user_id or "",
            command="chat",
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


@app.command()
@click.option(
    "--seed",
    is_flag=True,
    help="Load a representative week of prior runs from seed_runs.jsonl into an empty log, "
    "so the report shows the Key Signals firing. Only seeds when the log is empty.",
)
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def report(config_path, seed):
    """Generate a monitoring report from logs/runs.jsonl."""
    cfg = resolve_paths(load_config(config_path), config_path)
    log_path = Path(cfg["logging"]["log_dir"]) / "runs.jsonl"
    output_dir = Path(cfg["logging"]["reports_dir"])
    if seed:
        seed_path = Path(__file__).resolve().parents[2] / "seed_runs.jsonl"
        if log_path.exists():
            click.echo(f"{log_path} already present — not re-seeding.")
        else:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(seed_path.read_text())
            n = sum(1 for _ in open(seed_path))
            click.echo(f"Loaded {n} prior runs from seed_runs.jsonl.")
    records = load_run_records(log_path)
    if not records:
        click.echo(f"No run records found at {log_path}")
        return
    metrics = compute_metrics(records)
    generate_report(metrics, output_dir)
    click.echo(f"Report written to {output_dir / 'monitoring_report.md'}")
