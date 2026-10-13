"""Agent creation: wires model, versioned prompt, enabled tools and runtime controls from config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, NamedTuple, Optional

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import BaseTool

from salesops_agent.data import CRMData
from salesops_agent.guardrails import InputGuardrail, load_input_guardrail
from salesops_agent.prompts import Prompt, load_system_prompt
from salesops_agent.tools import make_tools, tool_versions
from salesops_agent.versions import build_manifest


@dataclass
class SalesOpsAgent:
    graph: Any                                   # compiled LangGraph agent
    manifest: Dict[str, Any]                     # versions of everything that shaped this agent
    input_guard: Optional[InputGuardrail] = None # runs before the graph; None when disabled


class _Components(NamedTuple):
    prompt: Prompt
    tools: List[BaseTool]
    input_guard: Optional[InputGuardrail]
    manifest: Dict[str, Any]


def _load_components(cfg: dict[str, Any]) -> _Components:
    """Load prompt, tools (validating data) and guardrails, and compute the version manifest."""
    crm = CRMData(cfg["paths"]["data_dir"])
    tools = make_tools(crm, cfg["paths"]["email_outbox"], cfg["tools"]["enabled"])
    prompt = load_system_prompt(cfg)
    input_guard = load_input_guardrail(cfg)
    guardrails = {"input": input_guard.describe() if input_guard else {"enabled": False}}
    manifest = build_manifest(cfg, prompt, tool_versions(tools), guardrails)
    return _Components(prompt, tools, input_guard, manifest)


def describe_versions(cfg: dict[str, Any]) -> Dict[str, Any]:
    """Version manifest for the current config, without creating a model client."""
    return _load_components(cfg).manifest


def build_agent(cfg: dict[str, Any]) -> SalesOpsAgent:
    """Build the SalesOps agent. Credentials come from the environment (.env)."""
    c = _load_components(cfg)
    model = init_chat_model(cfg["model"]["name"], temperature=cfg["model"]["temperature"])
    graph = create_agent(model=model, tools=c.tools, system_prompt=c.prompt.text)
    return SalesOpsAgent(graph=graph, manifest=c.manifest, input_guard=c.input_guard)
