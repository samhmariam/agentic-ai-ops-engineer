"""Agent creation: wires model, versioned prompt, enabled tools and runtime controls from config."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import BaseTool

from salesops_agent.data import CRMData
from salesops_agent.guardrails import (
    InputGuardrail, OutputGuardrail, ToolGuardrail,
    load_input_guardrail, load_output_guardrail, load_tool_guardrail,
)
from salesops_agent.prompts import Prompt, load_system_prompt
from salesops_agent.sandbox import load_sandbox
from salesops_agent.redaction import Redactor
from salesops_agent.tools import build_tool_specs, make_tools, tool_versions
from salesops_agent.versions import build_manifest


@dataclass
class SalesOpsAgent:
    graph: Any                                   # compiled LangGraph agent
    manifest: Dict[str, Any]                     # versions of everything that shaped this agent
    input_guard: Optional[InputGuardrail] = None # runs before the graph; None when disabled
    tool_guard: Optional[ToolGuardrail] = None   # wraps every tool call; None when disabled
    output_guard: Optional[OutputGuardrail] = None  # checks the final response; None when disabled
    # Builds any registered tool, wrapped by this agent's tool guardrail and sandbox, so
    # control probes can propose calls exactly as a misbehaving model would.
    tool_factory: Optional[Callable[[str, str], BaseTool]] = None
    redactor: Optional[Redactor] = None                       # applied to everything logs/traces persist
    restricted_tools: Set[str] = field(default_factory=set)   # outputs withheld from traces


class _Components(NamedTuple):
    prompt: Prompt
    tools: List[BaseTool]
    input_guard: Optional[InputGuardrail]
    tool_guard: Optional[ToolGuardrail]
    output_guard: Optional[OutputGuardrail]
    manifest: Dict[str, Any]
    tool_factory: Callable[[str, str], BaseTool]
    redactor: Redactor
    restricted_tools: Set[str]


def _load_components(cfg: dict[str, Any]) -> _Components:
    """Load prompt, tools (validating data) and guardrails, and compute the version manifest."""
    crm = CRMData(cfg["paths"]["data_dir"])
    tool_guard = load_tool_guardrail(cfg, crm)
    sandbox = load_sandbox(cfg, crm) if "run_analysis" in cfg["tools"]["enabled"] else None
    tools = make_tools(crm, cfg["paths"]["email_outbox"], cfg["tools"]["enabled"], tool_guard, sandbox)
    if tool_guard is not None:
        _require_approval_for_side_effects(tools, tool_guard)
    prompt = load_system_prompt(cfg)
    input_guard = load_input_guardrail(cfg)
    output_guard = load_output_guardrail(cfg, crm)
    guardrails = {
        "input": input_guard.describe() if input_guard else {"enabled": False},
        "tool": tool_guard.describe() if tool_guard else {"enabled": False},
        "output": output_guard.describe() if output_guard else {"enabled": False},
        "sandbox": sandbox.describe() if sandbox else {"enabled": False},
    }
    manifest = build_manifest(cfg, prompt, tool_versions(tools), guardrails)

    def tool_factory(name: str, version: str) -> BaseTool:
        return make_tools(crm, cfg["paths"]["email_outbox"], {name: version}, tool_guard,
                          sandbox or load_sandbox(cfg, crm))[0]

    restricted = {name for name, versions in build_tool_specs(crm, cfg["paths"]["email_outbox"]).items()
                  if any(spec.classification == "restricted" for spec in versions.values())}
    return _Components(prompt, tools, input_guard, tool_guard, output_guard, manifest, tool_factory,
                       Redactor(crm), restricted)


def model_kwargs(cfg: dict[str, Any]) -> Dict[str, Any]:
    """Arguments for init_chat_model. The timeout bounds a single API request (a
    stalled call fails after timeout_s and is retried up to max_retries times)
    instead of waiting for the client default."""
    m = cfg["model"]
    return {"model": m["name"], "temperature": m["temperature"],
            "timeout": m["timeout_s"], "max_retries": m["max_retries"]}


def _require_approval_for_side_effects(tools: List[BaseTool], guard: ToolGuardrail) -> None:
    """Startup invariant: with the tool guardrail on, every tool that changes the outside
    world must go through the human approval gate. A config or policy that exposes a
    side-effect tool without `requires_approval` fails to build, so there is no
    unguarded path to a customer-facing action."""
    for tool in tools:
        if (tool.metadata or {}).get("side_effect"):
            rule = guard.policy.tools.get(tool.name)
            if rule is None or not rule.requires_approval:
                raise ValueError(f"side-effect tool {tool.name!r} is exposed without requires_approval "
                                 f"in {guard.policy.name} {guard.policy.version}")


def describe_versions(cfg: dict[str, Any]) -> Dict[str, Any]:
    """Version manifest for the current config, without creating a model client."""
    return _load_components(cfg).manifest


def build_agent(cfg: dict[str, Any]) -> SalesOpsAgent:
    """Build the SalesOps agent. Credentials come from the environment (.env)."""
    c = _load_components(cfg)
    model = init_chat_model(**model_kwargs(cfg))
    graph = create_agent(model=model, tools=c.tools, system_prompt=c.prompt.text)
    return SalesOpsAgent(graph=graph, manifest=c.manifest, input_guard=c.input_guard,
                         tool_guard=c.tool_guard, output_guard=c.output_guard, tool_factory=c.tool_factory,
                         redactor=c.redactor, restricted_tools=c.restricted_tools)
