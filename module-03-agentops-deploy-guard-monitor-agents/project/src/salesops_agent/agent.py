"""Agent creation: wires model, versioned prompt and enabled tools from config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import BaseTool

from salesops_agent.data import CRMData
from salesops_agent.prompts import Prompt, load_system_prompt
from salesops_agent.tools import make_tools, tool_versions
from salesops_agent.versions import build_manifest


@dataclass
class SalesOpsAgent:
    graph: Any                 # compiled LangGraph agent
    manifest: Dict[str, Any]   # versions of everything that shaped this agent


def _load_components(cfg: dict[str, Any]) -> Tuple[Prompt, List[BaseTool], Dict[str, Any]]:
    """Load prompt and tools (validating data) and compute the version manifest."""
    crm = CRMData(cfg["paths"]["data_dir"])
    tools = make_tools(crm, cfg["paths"]["email_outbox"], cfg["tools"]["enabled"])
    prompt = load_system_prompt(cfg)
    return prompt, tools, build_manifest(cfg, prompt, tool_versions(tools))


def describe_versions(cfg: dict[str, Any]) -> Dict[str, Any]:
    """Version manifest for the current config, without creating a model client."""
    return _load_components(cfg)[2]


def build_agent(cfg: dict[str, Any]) -> SalesOpsAgent:
    """Build the SalesOps agent. Credentials come from the environment (.env)."""
    prompt, tools, manifest = _load_components(cfg)
    model = init_chat_model(cfg["model"]["name"], temperature=cfg["model"]["temperature"])
    graph = create_agent(model=model, tools=tools, system_prompt=prompt.text)
    return SalesOpsAgent(graph=graph, manifest=manifest)
