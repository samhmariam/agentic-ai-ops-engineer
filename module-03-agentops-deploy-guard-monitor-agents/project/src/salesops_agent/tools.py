"""Agent tools.

Each tool is declared as a `ToolSpec`: a version, a pydantic input schema from
schemas.py, and metadata describing its risk (data classification and whether it
has side effects). Several versions of a tool can coexist in the registry; config
pins one per tool (`tools.enabled: {name: version}`), so an experiment can swap a
single tool version and be evaluated against the baseline. `make_tools` turns the
pinned specs into LangChain StructuredTools, so arguments are validated before a
tool runs and the version/risk metadata travels with the tool. 1.0.0 descriptions
are the notebook prototype's text, unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Type

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from salesops_agent.data import CRMData, load_json
from salesops_agent.schemas import (
    AccountQuery,
    DraftEmailInput,
    InternalDataQuery,
    NoArgs,
    OpportunityFilter,
    OpportunityFilterV1_1,
    SendEmailInput,
)

CLOSED_STAGES = {"Closed Won", "Closed Lost"}

Classification = Literal["crm", "restricted"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    args_schema: Type[BaseModel]
    classification: Classification
    side_effect: bool
    func: Callable[..., Any]

    def metadata(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "classification": self.classification,
            "side_effect": self.side_effect,
        }


ToolRegistry = Dict[str, Dict[str, ToolSpec]]   # name -> version -> spec


def build_tool_specs(crm: CRMData, email_outbox: Path) -> ToolRegistry:
    """Every version of every tool. Released versions are never edited: a behaviour
    or schema change is added as a new ToolSpec with a bumped version, and configs
    choose which version to run."""
    def lookup_account(account_name_or_id: str) -> Dict[str, Any]:
        account = crm.resolve_account(account_name_or_id)
        if not account:
            return {"error": f"No account found for {account_name_or_id}"}
        return account

    def lookup_account_context(account_name_or_id: str) -> Dict[str, Any]:
        account = crm.resolve_account(account_name_or_id)
        if not account:
            return {"error": f"No account found for {account_name_or_id}"}
        account_id = account["account_id"]
        return {
            "account": account,
            "contacts": crm.contacts_for(account_id),
            "opportunities": crm.opportunities_for(account_id),
            "activities": crm.activities_for(account_id),
            "support_tickets": crm.tickets_for(account_id),
            "product_usage": crm.usage_for(account_id),
        }

    def list_open_opportunities(stage: Optional[str] = None) -> List[Dict[str, Any]]:
        results = [o for o in crm.opportunities if o["stage"] not in CLOSED_STAGES]
        if stage:
            results = [o for o in results if o["stage"].lower() == stage.lower()]
        return results

    def list_open_opportunities_v1_1(stage: Optional[str] = None, limit: int = 25) -> Dict[str, Any]:
        # 1.0.0 returned every open opportunity (~12k tokens unfiltered). 1.1.0 caps the
        # list, returns the largest deals first, and reports totals so the model can
        # answer count/value questions without paging through records.
        matching = sorted(list_open_opportunities(stage), key=lambda o: o["amount_usd"], reverse=True)
        return {
            "stage_filter": stage,
            "total_matching": len(matching),
            "total_amount_usd": sum(o["amount_usd"] for o in matching),
            "returned": min(limit, len(matching)),
            "opportunities": matching[:limit],
        }

    def summarize_pipeline() -> Dict[str, Any]:
        summary: Dict[str, Dict[str, Any]] = {}
        for opp in crm.opportunities:
            bucket = summary.setdefault(opp["stage"], {"count": 0, "amount_usd": 0})
            bucket["count"] += 1
            bucket["amount_usd"] += opp["amount_usd"]
        return summary

    def lookup_internal_hr_data(query: str) -> Dict[str, Any]:
        return {"query": query, "data": crm.internal_hr_data}

    def lookup_internal_financial_data(query: str) -> Dict[str, Any]:
        return {"query": query, "data": crm.internal_financial_data}

    def draft_email(account_name_or_id: str, purpose: str) -> Dict[str, Any]:
        context = lookup_account_context(account_name_or_id)
        if "error" in context:
            return context

        account = context["account"]
        account_contacts = context["contacts"]
        primary_contact = next(
            (c for c in account_contacts if c.get("is_primary")),
            account_contacts[0] if account_contacts else None,
        )
        if not primary_contact:
            return {"error": f"No contact found for account {account['name']}"}

        return {
            "to": primary_contact["email"],
            "subject": f"Following up on {account['name']}",
            "body": (
                f"Hi {primary_contact['first_name']},\n\n"
                f"I wanted to follow up regarding {purpose}.\n\n"
                "Best,\nUdaCenture SalesOps Agent\n"
            ),
            "status": "drafted",
        }

    def send_email(to: str, subject: str, body: str) -> Dict[str, Any]:
        outbox = load_json(email_outbox) if email_outbox.exists() else []
        message = {"to": to, "subject": subject, "body": body, "status": "sent"}
        outbox.append(message)
        email_outbox.parent.mkdir(parents=True, exist_ok=True)
        with email_outbox.open("w", encoding="utf-8") as f:
            json.dump(outbox, f, indent=2)
        return {"status": "sent", "message": message}

    specs = [
        ToolSpec("lookup_account", "1.0.0",
                 "Look up a B2B account by account ID or account name.",
                 AccountQuery, "crm", False, lookup_account),
        ToolSpec("lookup_account_context", "1.0.0",
                 "Return account context including contacts, opportunities, activities, tickets, and product usage.",
                 AccountQuery, "crm", False, lookup_account_context),
        ToolSpec("list_open_opportunities", "1.0.0",
                 "List open opportunities, optionally filtered by stage.",
                 OpportunityFilter, "crm", False, list_open_opportunities),
        ToolSpec("list_open_opportunities", "1.1.0",
                 "List open opportunities, optionally filtered by stage. Returns the total count "
                 "and value of all matching opportunities plus the largest ones (up to `limit`).",
                 OpportunityFilterV1_1, "crm", False, list_open_opportunities_v1_1),
        ToolSpec("summarize_pipeline", "1.0.0",
                 "Summarize opportunity count and value by stage.",
                 NoArgs, "crm", False, summarize_pipeline),
        ToolSpec("lookup_internal_hr_data", "1.0.0",
                 "Look up internal HR data. Prototype-only tool. Not production safe.",
                 InternalDataQuery, "restricted", False, lookup_internal_hr_data),
        ToolSpec("lookup_internal_financial_data", "1.0.0",
                 "Look up internal financial data. Prototype-only tool. Not production safe.",
                 InternalDataQuery, "restricted", False, lookup_internal_financial_data),
        ToolSpec("draft_email", "1.0.0",
                 "Draft a follow-up email for an account's primary contact.",
                 DraftEmailInput, "crm", False, draft_email),
        ToolSpec("send_email", "1.0.0",
                 "Fake-send an email by appending it to a local JSON outbox.",
                 SendEmailInput, "crm", True, send_email),
    ]
    registry: ToolRegistry = {}
    for spec in specs:
        registry.setdefault(spec.name, {})[spec.version] = spec
    return registry


def to_langchain_tool(spec: ToolSpec) -> BaseTool:
    return StructuredTool.from_function(
        func=spec.func,
        name=spec.name,
        description=spec.description,
        args_schema=spec.args_schema,
        metadata=spec.metadata(),
    )


def make_tools(crm: CRMData, email_outbox: Path, enabled: Dict[str, str]) -> List[BaseTool]:
    """Build the enabled tools at their pinned versions, in config order.

    Unknown tool names or versions are config errors; the message lists what exists.
    """
    registry = build_tool_specs(crm, email_outbox)
    problems = []
    for name, version in enabled.items():
        if name not in registry:
            problems.append(f"unknown tool {name!r} (known: {sorted(registry)})")
        elif version not in registry[name]:
            problems.append(f"{name} has no version {version} (available: {sorted(registry[name])})")
    if problems:
        raise ValueError("Invalid tools.enabled in config: " + "; ".join(problems))
    return [to_langchain_tool(registry[name][version]) for name, version in enabled.items()]


def available_tool_versions(crm: CRMData, email_outbox: Path) -> Dict[str, List[str]]:
    return {name: sorted(versions) for name, versions in build_tool_specs(crm, email_outbox).items()}


def tool_versions(tools: List[BaseTool]) -> Dict[str, str]:
    return {t.name: (t.metadata or {}).get("version", "unknown") for t in tools}
