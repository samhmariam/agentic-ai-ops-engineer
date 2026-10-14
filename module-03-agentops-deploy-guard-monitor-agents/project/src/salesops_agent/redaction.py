"""Redaction for logs and trace artifacts.

Applied to everything the observability layer persists (user input, tool arguments,
tool outputs, model tool-call arguments, final output, error messages), whatever
the guardrail configuration. Even a prototype config that lets the model read HR
data leaves no raw sensitive values on disk.

  - restricted tool outputs (classification "restricted": HR / financial lookups)
    are replaced entirely: "[REDACTED: restricted tool output, N chars]"
  - sensitive values from the internal HR and financial files (salaries, bonuses,
    revenue, employee ids, performance status, HR notes, confidential strategy text)
    are replaced by [REDACTED] in any rendering ($2,000,000 / 2000000 / $2M / $850k);
    values that also occur in CRM data are skipped so CRM figures stay readable
  - email addresses keep only their domain: o***@acmecorp.example.com

The output guardrail reuses the same value matching (values_at, money_pattern).
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Tuple

from salesops_agent.data import CRMData

TOKEN = "[REDACTED]"
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

# (source, dot path with [] for lists, kind) of internal values that must never be persisted.
SENSITIVE_VALUES = [
    ("hr", "records[].salary_usd", "money"),
    ("hr", "records[].equity_bonus_usd", "money"),
    ("hr", "records[].employee_id", "text"),
    ("hr", "records[].performance_status", "text"),
    ("hr", "records[].notes", "text"),
    ("financial", "quarterly_summary.revenue_usd", "money"),
    ("financial", "confidential_strategy.CONFIDENTIAL_M_AND_A.status", "text"),
    ("financial", "confidential_strategy.CONFIDENTIAL_M_AND_A.notes", "text"),
    ("financial", "confidential_strategy.CONFIDENTIAL_LAYOFF_PLAN.planned_reduction", "text"),
    ("financial", "confidential_strategy.CONFIDENTIAL_DISCOUNT_POLICY.max_unapproved_discount", "text"),
    ("financial", "confidential_strategy.CONFIDENTIAL_DISCOUNT_POLICY.executive_override_threshold", "text"),
    ("financial", "confidential_strategy.CONFIDENTIAL_DISCOUNT_POLICY.notes", "text"),
]


def values_at(doc: Any, path: List[str]) -> Iterable[Any]:
    """Values at a dot path where `name[]` iterates a list."""
    if not path:
        yield doc
        return
    head, rest = path[0], path[1:]
    key = head[:-2] if head.endswith("[]") else head
    if not isinstance(doc, dict) or key not in doc:
        return
    items = doc[key] if head.endswith("[]") and isinstance(doc[key], list) else [doc[key]]
    for item in items:
        yield from values_at(item, rest)


def money_pattern(amount: int) -> str:
    """Regex matching common renderings of an amount: 2000000, 2,000,000, $2M, $2 million, $850k."""
    forms = [rf"{amount}", rf"{amount:,}".replace(",", r",")]
    for divisor, suffix in ((1_000_000, r"(m|mm|million)"), (1_000, r"(k|thousand)")):
        if amount >= divisor and amount % (divisor // 10) == 0:
            scaled = f"{amount / divisor:g}".replace(".", r"\.")
            forms.append(rf"{scaled}(\.0+)?\s?{suffix}\b")
    return r"(?<![\d.,])(?:\$\s?)?(" + "|".join(forms) + r")(?![\d,]*\d)"


def crm_amounts(crm: CRMData) -> set[int]:
    amounts: set[int] = set()
    for record in [*crm.accounts, *crm.opportunities, *crm.product_usage]:
        amounts.update(v for v in record.values() if isinstance(v, int) and not isinstance(v, bool))
    return amounts


def value_pattern(value: Any, kind: str, skip_amounts: set[int]) -> re.Pattern | None:
    if kind == "money" and isinstance(value, int) and value not in skip_amounts:
        return re.compile(money_pattern(value), re.IGNORECASE)
    if kind == "text" and isinstance(value, str) and value.strip():
        text = re.escape(value.strip())
        # word boundaries only where the value starts/ends with a word character
        return re.compile((r"\b" if value.strip()[0].isalnum() else "") + text
                          + (r"\b" if value.strip()[-1].isalnum() else ""), re.IGNORECASE)
    return None


class Redactor:
    def __init__(self, crm: CRMData):
        docs = {"hr": crm.internal_hr_data, "financial": crm.internal_financial_data}
        skip = crm_amounts(crm)
        self.patterns: List[re.Pattern] = []
        for source, path, kind in SENSITIVE_VALUES:
            for value in values_at(docs[source], path.split(".")):
                pattern = value_pattern(value, kind, skip)
                if pattern is not None:
                    self.patterns.append(pattern)

    def text(self, value: Any) -> Tuple[str, int]:
        """Redacted string form of value, and how many spans were redacted."""
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        count = 0
        for pattern in self.patterns:
            text, n = pattern.subn(TOKEN, text)
            count += n
        text, n = _EMAIL.subn(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
        return text, count + n

    def __call__(self, value: Any) -> str:
        return self.text(value)[0]
