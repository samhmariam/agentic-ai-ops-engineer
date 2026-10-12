import pandas as pd
from langchain.agents import create_agent
from langchain_core.tools import tool

from realthor.config import load_prompt, make_chat_model
from realthor.guardrails import UserContext, make_guardrails
from realthor.tools import make_execute_python_tool, make_tools


def build_analyst_agent(cfg: dict):
    """Build the analyst sub-agent: execute_python only, no guardrails."""
    model = make_chat_model(cfg)
    analyst_prompt = load_prompt(cfg["paths"]["analyst_prompt"])
    tools = [make_execute_python_tool(cfg)]
    return create_agent(model=model, tools=tools, system_prompt=analyst_prompt)


def build_main_agent(cfg: dict):
    """Build the main RealThor agent with bespoke tools + analyst delegation + guardrails."""
    model = make_chat_model(cfg)
    system_prompt = load_prompt(cfg["paths"]["prompt"])
    analyst = build_analyst_agent(cfg)

    @tool
    def analyze_data(question: str) -> str:
        """Delegate analytical queries requiring filtering or aggregation of raw listing data —
        percentages, averages, rankings, counts that span many rows."""
        result = analyst.invoke({"messages": [{"role": "user", "content": question}]})
        return result["messages"][-1].content

    demand = pd.read_csv(cfg["paths"]["demand_data"])
    supply = pd.read_csv(cfg["paths"]["supply_data"])
    neighborhoods = pd.read_csv(cfg["paths"]["neighborhood_data"])
    velocity = pd.read_csv(cfg["paths"]["velocity_data"])
    supply_opps = pd.read_csv(cfg["paths"]["supply_opportunities_data"])
    listing_data = pd.read_csv(cfg["paths"]["listings_data"])
    sales_data = pd.read_csv(cfg["paths"]["sales_data"])
    bespoke_tools = make_tools(demand, supply, neighborhoods, velocity, supply_opps, listing_data, sales_data)

    return create_agent(
        model=model,
        tools=bespoke_tools + [analyze_data],
        system_prompt=system_prompt,
        context_schema=UserContext,
        middleware=make_guardrails(),
    )
