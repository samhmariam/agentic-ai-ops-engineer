"""CRM data access layer.

Loads the JSON dataset once and provides the lookups the tools need. Keeping data
access here (not inside tool functions) lets later steps add access control and
storage changes without touching the agent.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

Record = Dict[str, Any]

_LEGAL_SUFFIXES = re.compile(
    r"\b(incorporated|inc|corp|corporation|ltd|limited|llc|co|company)\b"
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_lookup_text(value: str) -> str:
    """Normalize names and IDs for forgiving lookups.

    Makes lookups robust to punctuation, casing, and legal suffix variants such as
    "Inc." vs "Inc".
    """
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = _LEGAL_SUFFIXES.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


class CRMData:
    """In-memory view of the CRM dataset under data_dir."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.accounts: List[Record] = load_json(data_dir / "accounts.json")
        self.contacts: List[Record] = load_json(data_dir / "contacts.json")
        self.opportunities: List[Record] = load_json(data_dir / "opportunities.json")
        self.activities: List[Record] = load_json(data_dir / "activities.json")
        self.support_tickets: List[Record] = load_json(data_dir / "support_tickets.json")
        self.product_usage: List[Record] = load_json(data_dir / "product_usage.json")
        self.internal_hr_data: Record = load_json(data_dir / "internal_hr_data.json")
        self.internal_financial_data: Record = load_json(
            data_dir / "internal_financial_data.json"
        )

    # -- account resolution -------------------------------------------------

    def find_account_by_id(self, account_id: str) -> Optional[Record]:
        """Look up an account by exact account ID, case-insensitive."""
        wanted = account_id.strip().lower()
        return next((a for a in self.accounts if a["account_id"].lower() == wanted), None)

    def find_account_by_name(self, name: str) -> Optional[Record]:
        """Look up an account by name: exact, then partial, then fuzzy (small typos)."""
        query = normalize_lookup_text(name)
        if not query:
            return None
        normalized = {normalize_lookup_text(a["name"]): a for a in self.accounts}

        if query in normalized:
            return normalized[query]

        for account_name, account in normalized.items():
            if query in account_name or account_name in query:
                return account

        matches = difflib.get_close_matches(query, normalized.keys(), n=1, cutoff=0.82)
        return normalized[matches[0]] if matches else None

    def resolve_account(self, account_name_or_id: str) -> Optional[Record]:
        return self.find_account_by_id(account_name_or_id) or self.find_account_by_name(
            account_name_or_id
        )

    # -- related records ----------------------------------------------------

    def contacts_for(self, account_id: str) -> List[Record]:
        return [c for c in self.contacts if c["account_id"] == account_id]

    def opportunities_for(self, account_id: str) -> List[Record]:
        return [o for o in self.opportunities if o["account_id"] == account_id]

    def activities_for(self, account_id: str) -> List[Record]:
        return [a for a in self.activities if a["account_id"] == account_id]

    def tickets_for(self, account_id: str) -> List[Record]:
        return [t for t in self.support_tickets if t["account_id"] == account_id]

    def usage_for(self, account_id: str) -> List[Record]:
        return [u for u in self.product_usage if u["account_id"] == account_id]
