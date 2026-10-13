"""Tool/action guardrail: inspect every proposed tool call before it executes.

Enforced in code, independent of the model: each tool the agent can call is
wrapped (`guard_tools`), and the wrapper checks the call against the versioned
data access policy (policies/tool_guardrails_vN.yaml) before running the tool.

  - default deny: tools not listed in the policy are never executed
  - restricted tools run only for authorized roles; queries that name restricted
    fields are blocked for every role; restricted fields are redacted from results
  - account-scoped CRM tools may only touch accounts named in the request, within
    a per-run lookup budget; a per-run tool-call budget applies to all tools
  - string arguments containing executable code are rejected
  - side-effect tools (send_email) require an approval for that exact action

A blocked call returns an explicit result to the agent instead of running, e.g.
    {"status": "blocked", "reason": "restricted_internal_data",
     "policy": "salesops_data_access_policy", ...}
and is logged (`tool_call_blocked`, without argument values) and traced.

Per-run state (request text, role, approvals, counters) travels in a RunContext
set by the runner via a context variable; LangGraph's tool executor copies
context into its worker threads. Calls made with no active run (e.g. direct
invocation) get a default context, so restricted and approval rules still apply.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import logging
import re
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional, Set

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from salesops_agent.data import CRMData
from salesops_agent.logging_utils import log_event

Reason = Literal[
    "restricted_internal_data", "restricted_field_request", "out_of_scope_account",
    "lookup_budget_exceeded", "tool_budget_exceeded", "unsafe_code", "approval_required",
    "tool_not_allowed",
]


# -- policy schema ----------------------------------------------------------

def _check_regexes(value: List[str]) -> List[str]:
    for pattern in value:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolRule(_Strict):
    scope: Literal["account", "pipeline", "restricted", "action", "analysis"]
    authorized_roles: List[str] = []
    blocked_query_patterns: List[str] = []
    redact_fields: List[str] = []
    requires_approval: bool = False

    @field_validator("blocked_query_patterns")
    @classmethod
    def regexes_compile(cls, value: List[str]) -> List[str]:
        return _check_regexes(value)


class Limits(_Strict):
    max_tool_calls_per_run: int = Field(ge=1)
    max_account_lookups_per_run: int = Field(ge=1)


class ToolPolicy(_Strict):
    name: str
    version: str = Field(pattern=r"^v\d+$")
    roles: List[str] = Field(min_length=1)
    default_role: str
    limits: Limits
    unsafe_code_patterns: List[str]
    messages: Dict[str, str]
    tools: Dict[str, ToolRule]

    @field_validator("unsafe_code_patterns")
    @classmethod
    def regexes_compile(cls, value: List[str]) -> List[str]:
        return _check_regexes(value)

    @model_validator(mode="after")
    def consistent(self) -> "ToolPolicy":
        if self.default_role not in self.roles:
            raise ValueError(f"default_role {self.default_role!r} not in roles")
        for name, rule in self.tools.items():
            unknown = set(rule.authorized_roles) - set(self.roles)
            if unknown:
                raise ValueError(f"{name}: unknown roles {sorted(unknown)}")
            if rule.scope == "restricted" and not rule.authorized_roles:
                raise ValueError(f"{name}: restricted tools must list authorized_roles")
        missing = set(Reason.__args__) - self.messages.keys()
        if missing:
            raise ValueError(f"messages missing for reasons: {sorted(missing)}")
        return self


# -- run context ------------------------------------------------------------

@dataclass
class RunContext:
    """Per-run state the guardrail needs. Mutated under `lock` (tools may run in parallel)."""

    run_id: Optional[str] = None
    request: str = ""
    role: Optional[str] = None
    approvals: Set[str] = field(default_factory=set)       # approved action ids (HITL, 5.5)
    referenced_accounts: Optional[Set[str]] = None          # computed lazily from `request`
    logger: Optional[logging.Logger] = None
    on_block: Optional[Callable[[Dict[str, Any]], None]] = None   # e.g. trace recorder hook
    tool_calls: int = 0
    account_lookups: int = 0
    blocked: List[Dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


_CURRENT: ContextVar[Optional[RunContext]] = ContextVar("salesops_tool_run_context", default=None)


@contextlib.contextmanager
def tool_run_context(ctx: RunContext) -> Iterator[RunContext]:
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


def action_id(tool: str, args: Dict[str, Any]) -> str:
    """Stable id for one concrete action, so an approval covers exactly that call."""
    canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# -- guardrail --------------------------------------------------------------

def _redact(obj: Any, path: List[str]) -> None:
    """Delete `path` (dot-separated, `[]` = every list item) from obj in place."""
    head, rest = path[0], path[1:]
    is_list = head.endswith("[]")
    key = head[:-2] if is_list else head
    if not isinstance(obj, dict) or key not in obj:
        return
    if not rest:
        del obj[key]
        return
    targets = obj[key] if is_list and isinstance(obj[key], list) else [obj[key]]
    for target in targets:
        _redact(target, rest)


class ToolGuardrail:
    def __init__(self, policy: ToolPolicy, sha256: str, crm: CRMData):
        self.policy = policy
        self.sha256 = sha256
        self.crm = crm
        self._unsafe = [re.compile(p, re.IGNORECASE) for p in policy.unsafe_code_patterns]
        self._blocked_query = {
            name: [re.compile(p, re.IGNORECASE) for p in rule.blocked_query_patterns]
            for name, rule in policy.tools.items()
        }

    @classmethod
    def from_file(cls, path: Path, crm: CRMData) -> "ToolGuardrail":
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        policy = ToolPolicy.model_validate(yaml.safe_load(text))
        return cls(policy, hashlib.sha256(text.encode("utf-8")).hexdigest(), crm)

    def describe(self) -> Dict[str, Any]:
        return {"enabled": True, "policy": self.policy.name, "policy_version": self.policy.version,
                "policy_sha256": self.sha256, "tools": sorted(self.policy.tools)}

    # -- decision -----------------------------------------------------------

    def _blocked(self, tool: str, reason: str, rule: str, **extra: Any) -> Dict[str, Any]:
        return {
            "status": "blocked",
            "reason": reason,
            "policy": self.policy.name,
            "policy_version": self.policy.version,
            "tool": tool,
            "rule": rule,
            "message": self.policy.messages[reason].strip(),
            **extra,
        }

    def check(self, tool: str, args: Dict[str, Any], ctx: RunContext) -> Optional[Dict[str, Any]]:
        """Return None to allow the call, or the blocked-result dict."""
        rule = self.policy.tools.get(tool)
        if rule is None:
            return self._blocked(tool, "tool_not_allowed", "default_deny")

        strings = [v for v in args.values() if isinstance(v, str)]
        if any(p.search(s) for p in self._unsafe for s in strings):
            return self._blocked(tool, "unsafe_code", "unsafe_code_patterns")

        role = ctx.role or self.policy.default_role
        if rule.scope == "restricted":
            if role not in rule.authorized_roles:
                return self._blocked(tool, "restricted_internal_data", f"tools.{tool}.authorized_roles", role=role)
            if any(p.search(s) for p in self._blocked_query[tool] for s in strings):
                return self._blocked(tool, "restricted_field_request", f"tools.{tool}.blocked_query_patterns")

        with ctx.lock:
            if ctx.tool_calls >= self.policy.limits.max_tool_calls_per_run:
                return self._blocked(tool, "tool_budget_exceeded", "limits.max_tool_calls_per_run")
            if rule.scope == "account":
                decision = self._check_account_scope(tool, args, ctx)
                if decision:
                    return decision
            if rule.requires_approval:
                aid = action_id(tool, args)
                if aid not in ctx.approvals:
                    return self._blocked(tool, "approval_required", f"tools.{tool}.requires_approval",
                                         approval_id=aid)
            ctx.tool_calls += 1
            if rule.scope == "account":
                ctx.account_lookups += 1
        return None

    def _check_account_scope(self, tool: str, args: Dict[str, Any], ctx: RunContext) -> Optional[Dict[str, Any]]:
        if ctx.account_lookups >= self.policy.limits.max_account_lookups_per_run:
            return self._blocked(tool, "lookup_budget_exceeded", "limits.max_account_lookups_per_run")
        if ctx.referenced_accounts is None:
            ctx.referenced_accounts = self.crm.accounts_mentioned(ctx.request) if ctx.request else set()
        target = self.crm.resolve_account(str(args.get("account_name_or_id", "")))
        # Only constrain when the request names accounts and the target resolves;
        # an unresolvable name simply returns "not found" from the tool.
        if ctx.referenced_accounts and target and target["account_id"] not in ctx.referenced_accounts:
            return self._blocked(tool, "out_of_scope_account", f"tools.{tool}.scope",
                                 account_id=target["account_id"])
        return None

    def redact(self, tool: str, result: Any) -> Any:
        rule = self.policy.tools.get(tool)
        if not rule or not rule.redact_fields or not isinstance(result, dict):
            return result
        result = copy.deepcopy(result)
        container = result.get("data", result)   # restricted tools wrap records in {"query", "data"}
        for path in rule.redact_fields:
            _redact(container, path.split("."))
        result["redacted_fields"] = list(rule.redact_fields)
        return result

    # -- enforcement --------------------------------------------------------

    def wrap(self, tool: str, func: Callable[..., Any]) -> Callable[..., Any]:
        """Return func guarded by this policy: check -> (block | run -> redact)."""

        def guarded(**kwargs: Any) -> Any:
            ctx = _CURRENT.get() or RunContext()
            blocked = self.check(tool, kwargs, ctx)
            if blocked is not None:
                with ctx.lock:
                    ctx.blocked.append(blocked)
                if ctx.logger:
                    log_event(ctx.logger, "tool_call_blocked", level=logging.WARNING, run_id=ctx.run_id,
                              tool=tool, reason=blocked["reason"], rule=blocked["rule"],
                              policy=self.policy.name, arg_names=sorted(kwargs))
                if ctx.on_block:
                    ctx.on_block(blocked)
                return blocked
            return self.redact(tool, func(**kwargs))

        guarded.__name__ = getattr(func, "__name__", tool)
        guarded.__doc__ = getattr(func, "__doc__", None)
        return guarded


def load_tool_guardrail(cfg: dict[str, Any], crm: CRMData) -> Optional[ToolGuardrail]:
    """The configured tool guardrail, or None when disabled in config."""
    section = cfg["guardrails"]["tool"]
    if not section["enabled"]:
        return None
    return ToolGuardrail.from_file(section["policy"], crm)
