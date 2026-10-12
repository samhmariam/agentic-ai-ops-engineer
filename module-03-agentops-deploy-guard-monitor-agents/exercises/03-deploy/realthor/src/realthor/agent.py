"""RealThor agent — Module 3 solution (build_agent + CLI + __main__)."""

from dotenv import load_dotenv
import click
import pandas as pd
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from realthor.config import load_config, load_prompt, make_chat_model, resolve_paths
from realthor.tools import make_tools

load_dotenv()


def build_agent(config_path: str = "config.yaml"):
    cfg = resolve_paths(load_config(config_path), config_path)
    model = make_chat_model(cfg)
    system_prompt = load_prompt(cfg["paths"]["prompt"])
    demand = pd.read_csv(cfg["paths"]["demand_data"])
    supply = pd.read_csv(cfg["paths"]["supply_data"])
    tools = make_tools(demand, supply)
    return create_agent(model=model, tools=tools, system_prompt=system_prompt)


@click.group()
def app():
    """RealThor — Listing Supply Intelligence CLI."""


@app.command()
@click.option("--region", required=True, help="Ciudaty region (west, north, south, east, center)")
@click.option("--property-type", "property_type", required=True, help="apartment, house, or studio")
@click.option("--bedrooms", required=True, type=int, help="Number of bedrooms")
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def analyze(region, property_type, bedrooms, config_path):
    """Analyze listing priority for one region/property profile."""
    click.echo("Loading agent...")
    agent = build_agent(config_path)
    question = f"What's the listing priority for {bedrooms}-bedroom {property_type} in the {region} region?"
    click.echo("Analyzing...")
    result = agent.invoke({"messages": [HumanMessage(question)]})
    click.echo(result["messages"][-1].content)


if __name__ == "__main__":
    agent = build_agent()
    result = agent.invoke({
        "messages": [HumanMessage("What's the listing priority for 2-bedroom apartments in the west region?")]
    })
    print(result["messages"][-1].content)
