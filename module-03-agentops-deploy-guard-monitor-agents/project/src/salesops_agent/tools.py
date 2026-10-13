"""Agent tools.

`make_tools` builds the tool functions as closures over a CRMData instance and
returns only those enabled in config.yaml. Docstrings are the tool descriptions the
model sees, so they are kept identical to the notebook prototype.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from salesops_agent.data import CRMData, load_json

Tool = Callable[..., Any]

CLOSED_STAGES = {"Closed Won", "Closed Lost"}


def make_tools(crm: CRMData, email_outbox: Path, enabled: List[str]) -> List[Tool]:
    def lookup_account(account_name_or_id: str) -> Dict[str, Any]:
        """Look up a B2B account by account ID or account name."""
        account = crm.resolve_account(account_name_or_id)
        if not account:
            return {"error": f"No account found for {account_name_or_id}"}
        return account

    def lookup_account_context(account_name_or_id: str) -> Dict[str, Any]:
        """Return account context including contacts, opportunities, activities, tickets, and product usage."""
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
        """List open opportunities, optionally filtered by stage."""
        results = [o for o in crm.opportunities if o["stage"] not in CLOSED_STAGES]
        if stage:
            results = [o for o in results if o["stage"].lower() == stage.lower()]
        return results

    def summarize_pipeline() -> Dict[str, Any]:
        """Summarize opportunity count and value by stage."""
        summary: Dict[str, Dict[str, Any]] = {}
        for opp in crm.opportunities:
            bucket = summary.setdefault(opp["stage"], {"count": 0, "amount_usd": 0})
            bucket["count"] += 1
            bucket["amount_usd"] += opp["amount_usd"]
        return summary

    def lookup_internal_hr_data(query: str) -> Dict[str, Any]:
        """Look up internal HR data. Prototype-only tool. Not production safe."""
        return {"query": query, "data": crm.internal_hr_data}

    def lookup_internal_financial_data(query: str) -> Dict[str, Any]:
        """Look up internal financial data. Prototype-only tool. Not production safe."""
        return {"query": query, "data": crm.internal_financial_data}

    def draft_email(account_name_or_id: str, purpose: str) -> Dict[str, Any]:
        """Draft a follow-up email for an account's primary contact."""
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
        """Fake-send an email by appending it to a local JSON outbox."""
        outbox = load_json(email_outbox) if email_outbox.exists() else []
        message = {"to": to, "subject": subject, "body": body, "status": "sent"}
        outbox.append(message)
        email_outbox.parent.mkdir(parents=True, exist_ok=True)
        with email_outbox.open("w", encoding="utf-8") as f:
            json.dump(outbox, f, indent=2)
        return {"status": "sent", "message": message}

    registry: Dict[str, Tool] = {
        fn.__name__: fn
        for fn in (
            lookup_account,
            lookup_account_context,
            list_open_opportunities,
            summarize_pipeline,
            lookup_internal_hr_data,
            lookup_internal_financial_data,
            draft_email,
            send_email,
        )
    }

    unknown = sorted(set(enabled) - registry.keys())
    if unknown:
        raise ValueError(f"Unknown tools in config tools.enabled: {unknown}")
    return [registry[name] for name in enabled]
