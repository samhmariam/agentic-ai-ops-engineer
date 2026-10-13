"""Agent creation: wires model, versioned prompt, enabled tools and runtime controls from config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, NamedTuple, Optional

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import BaseTool

from salesops_agent.data import CRMData
from salesops_agent.guardrails import (
    InputGuardrail, OutputGuardrail, ToolGuardrail,
    load_input_guardrail, load_output_guardrail, load_tool_guardrail,
)
from salesops_agent.prompts import Prompt, load_system_prompt
from salesops_agent.tools import make_tools, tool_versions
from salesops_agent.versions import build_manifest


@dataclass
class SalesOpsAgent:
    graph: Any                                   # compiled LangGraph agent
    manifest: Dict[str, Any]                     # versions of everything that shaped this agent
    input_guard: Optional[InputGuardrail] = None # runs before the graph; None when disabled
    tool_guard: Optional[ToolGuardrail] = None   # wraps every tool call; None when disabled
    output_guard: Optional[OutputGuardrail] = None  # checks the final response; None when disabled


class _Components(NamedTuple):
    prompt: Prompt
    tools: List[BaseTool]
    input_guard: Optional[InputGuardrail]
    tool_guard: Optional[ToolGuardrail]
    output_guard: Optional[OutputGuardrail]
    manifest: Dict[str, Any]


def _load_components(cfg: dict[str, Any]) -> _Components:
    """Load prompt, tools (validating data) and guardrails, and compute the version manifest."""
    crm = CRMData(cfg["paths"]["data_dir"])
    tool_guard = load_tool_guardrail(cfg, crm)
    tools = make_tools(crm, cfg["paths"]["email_outbox"], cfg["tools"]["enabled"], tool_guard)
    prompt = load_system_prompt(cfg)
    input_guard = load_input_guardrail(cfg)
    output_guard = load_output_guardrail(cfg, crm)
    guardrails = {
        "input": input_guard.describe() if input_guard else {"enabled": False},
        "tool": tool_guard.describe() if tool_guard else {"enabled": False},
        "output": output_guard.describe() if output_guard else {"enabled": False},
    }
    manifest = build_manifest(cfg, prompt, tool_versions(tools), guardrails)
    return _Components(prompt, tools, input_guard, tool_guard, output_guard, manifest)


def model_kwargs(cfg: dict[str, Any]) -> Dict[str, Any]:
    """Arguments for init_chat_model. The timeout bounds a single API request (a
    stalled call fails after timeout_s and is retried up to max_retries times)
    instead of waiting for the client default."""
    m = cfg["model"]
    return {"model": m["name"], "temperature": m["temperature"],
            "timeout": m["timeout_s"], "max_retries": m["max_retries"]}


def describe_versions(cfg: dict[str, Any]) -> Dict[str, Any]:
    """Version manifest for the current config, without creating a model client."""
    return _load_components(cfg).manifest


def build_agent(cfg: dict[str, Any]) -> SalesOpsAgent:
    """Build the SalesOps agent. Credentials come from the environment (.env)."""
    c = _load_components(cfg)
    model = init_chat_model(**model_kwargs(cfg))
    graph = create_agent(model=model, tools=c.tools, system_prompt=c.prompt.text)
    return SalesOpsAgent(graph=graph, manifest=c.manifest, input_guard=c.input_guard,
                         tool_guard=c.tool_guard, output_guard=c.output_guard)
