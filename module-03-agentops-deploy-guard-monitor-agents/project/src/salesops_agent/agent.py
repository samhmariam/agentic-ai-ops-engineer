"""Agent creation: wires model, versioned prompt and enabled tools from config."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from salesops_agent.data import CRMData
from salesops_agent.prompts import load_system_prompt
from salesops_agent.tools import make_tools


def build_agent(cfg: dict[str, Any]):
    """Build the SalesOps agent. Credentials come from the environment (.env)."""
    model = init_chat_model(cfg["model"]["name"], temperature=cfg["model"]["temperature"])
    crm = CRMData(cfg["paths"]["data_dir"])
    tools = make_tools(crm, cfg["paths"]["email_outbox"], cfg["tools"]["enabled"])
    prompt = load_system_prompt(cfg)
    return create_agent(model=model, tools=tools, system_prompt=prompt.text)
