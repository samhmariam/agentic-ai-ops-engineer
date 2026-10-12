import click
import pandas as pd
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from realthor.agents import build_main_agent
from realthor.config import load_config, resolve_paths
from realthor.guardrails import GUEST_CONTEXT, UserContext

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
    result = agent.invoke(
        {"messages": [HumanMessage(question)]},
        context=user_ctx,
    )
    click.echo(result["messages"][-1].content)


@app.command()
@click.option("--user", "-u", "user_id", default="", help="User ID resolved from users.csv")
@click.option("--message", "-m", required=True, help="Free-text message to send to the agent")
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def chat(user_id, message, config_path):
    """Send a free-text message to the agent (all three guardrail layers active)."""
    click.echo("Loading agent...")
    cfg = resolve_paths(load_config(config_path), config_path)
    user_ctx = _resolve_user(user_id, cfg["paths"]["users_data"])
    click.echo(f"Identity: {user_ctx.user_id or 'guest'} ({user_ctx.role})")
    agent = build_main_agent(cfg)
    click.echo("Analyzing...")
    result = agent.invoke(
        {"messages": [HumanMessage(message)]},
        context=user_ctx,
    )
    click.echo(result["messages"][-1].content)
