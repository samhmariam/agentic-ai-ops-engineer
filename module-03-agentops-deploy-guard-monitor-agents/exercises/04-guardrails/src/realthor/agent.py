import click
import pandas as pd
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from realthor.config import load_config, load_prompt, make_chat_model, resolve_paths
from realthor.guardrails import UserContext, GUEST_CONTEXT, make_guardrails
from realthor.tools import make_tools

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


def build_agent(config_path: str = "config.yaml"):
    cfg = resolve_paths(load_config(config_path), config_path)
    model = make_chat_model(cfg)
    system_prompt = load_prompt(cfg["paths"]["prompt"])
    demand = pd.read_csv(cfg["paths"]["demand_data"])
    supply = pd.read_csv(cfg["paths"]["supply_data"])
    neighborhoods = pd.read_csv(cfg["paths"]["neighborhood_data"])
    velocity = pd.read_csv(cfg["paths"]["velocity_data"])
    supply_opps = pd.read_csv(cfg["paths"]["supply_opportunities_data"])
    listing_data = pd.read_csv(cfg["paths"]["listings_data"])
    sales_data = pd.read_csv(cfg["paths"]["sales_data"])
    tools = make_tools(demand, supply, neighborhoods, velocity, supply_opps, listing_data, sales_data)
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        context_schema=UserContext,
        middleware=make_guardrails(),
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

    agent = build_agent(config_path)
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
    agent = build_agent(config_path)
    click.echo("Analyzing...")
    result = agent.invoke(
        {"messages": [HumanMessage(message)]},
        context=user_ctx,
    )
    click.echo(result["messages"][-1].content)
