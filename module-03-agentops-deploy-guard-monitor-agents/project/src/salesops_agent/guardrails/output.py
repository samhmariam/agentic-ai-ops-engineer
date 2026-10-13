"""Output guardrail: inspect the final response before it reaches the user.

Deterministic and model-independent. Rules from a versioned policy
(policies/output_guardrails_vN.yaml) decide one of four outcomes; the most severe
triggered action wins:

  block  -> the response is replaced by a safe refusal (restricted disclosure)
  review -> the response is withheld and queued for human review (unsafe claims in
            a customer-facing email); the user gets a review id
  redact -> sensitive spans (raw values / field names from the internal HR and
            financial files) are replaced by the redaction token
  allow  -> the response is returned unchanged

The decision (action, rule ids, categories, redaction count, review id) is logged
and traced; the withheld text itself is never logged.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from salesops_agent.data import CRMData

Action = Literal["allow", "redact", "review", "block"]
_SEVERITY = {"allow": 0, "redact": 1, "review": 2, "block": 3}
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


# -- policy schema ----------------------------------------------------------

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutputRule(_Strict):
    id: str = Field(pattern=r"^[a-z_]+\.[a-z_]+$")
    category: str
    action: Literal["block", "review"]
    response: str
    scope: Literal["sentence", "response"]
    email_only: bool = False
    match: List[List[str]] = Field(min_length=1)    # alternatives of all-must-match regex groups
    unless: List[str] = []


class ValueSource(_Strict):
    source: Literal["hr", "financial"]
    path: str
    kind: Literal["money", "text"]


class RedactSection(_Strict):
    field_names: List[str] = []
    values_from: List[ValueSource] = []


class OutputPolicy(_Strict):
    version: str = Field(pattern=r"^v\d+$")
    redaction_token: str
    responses: Dict[str, str]
    vocab: Dict[str, str] = {}
    email_detection: List[str] = Field(min_length=1)
    rules: List[OutputRule] = Field(min_length=1)
    redact: RedactSection

    @model_validator(mode="after")
    def references_resolve(self) -> "OutputPolicy":
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule ids")
        missing = {r.response for r in self.rules} - self.responses.keys()
        if missing:
            raise ValueError(f"rules reference undefined responses: {sorted(missing)}")
        return self


# -- decision ---------------------------------------------------------------

@dataclass
class OutputDecision:
    action: Action
    response: str
    rule_ids: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    redactions: int = 0
    review_id: Optional[str] = None

    @property
    def triggered(self) -> bool:
        return self.action != "allow"

    def to_dict(self) -> Dict[str, Any]:
        """Decision metadata for logs/traces (no response text)."""
        data = asdict(self)
        data.pop("response")
        return {"stage": "output", "allowed": self.action in ("allow", "redact"), **data}


# -- helpers ----------------------------------------------------------------

def _values_at(doc: Any, path: List[str]) -> Iterable[Any]:
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
        yield from _values_at(item, rest)


def _money_pattern(amount: int) -> str:
    """Regex matching common renderings of an amount: 2000000, 2,000,000, $2M, $2 million, $850k."""
    forms = [rf"{amount}", rf"{amount:,}".replace(",", r",")]
    for divisor, suffix in ((1_000_000, r"(m|mm|million)"), (1_000, r"(k|thousand)")):
        if amount >= divisor and amount % (divisor // 10) == 0:
            scaled = f"{amount / divisor:g}".replace(".", r"\.")
            forms.append(rf"{scaled}(\.0+)?\s?{suffix}\b")
    return r"(?<![\d.,])(?:\$\s?)?(" + "|".join(forms) + r")(?![\d,]*\d)"


def _crm_amounts(crm: CRMData) -> set[int]:
    amounts: set[int] = set()
    for record in [*crm.accounts, *crm.opportunities, *crm.product_usage]:
        amounts.update(v for v in record.values() if isinstance(v, int) and not isinstance(v, bool))
    return amounts


# -- guardrail --------------------------------------------------------------

class OutputGuardrail:
    def __init__(self, policy: OutputPolicy, sha256: str, crm: CRMData):
        self.policy = policy
        self.sha256 = sha256
        vocab = dict(policy.vocab)
        names = sorted({str(r["name"]) for r in crm.internal_hr_data.get("records", [])}, key=len, reverse=True)
        vocab["employee_names"] = "(" + "|".join(re.escape(n) for n in names) + ")" if names else "(?!x)x"

        def compile_(pattern: str) -> re.Pattern:
            for key, value in vocab.items():
                pattern = pattern.replace("{" + key + "}", value)
            return re.compile(pattern, re.IGNORECASE)

        self._email = [compile_(p) for p in policy.email_detection]
        self._rules = [
            (rule, [[compile_(p) for p in group] for group in rule.match], [compile_(u) for u in rule.unless])
            for rule in policy.rules
        ]
        self._redact = self._build_redactions(policy.redact, crm)

    @classmethod
    def from_file(cls, path: Path, crm: CRMData) -> "OutputGuardrail":
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        policy = OutputPolicy.model_validate(yaml.safe_load(text))
        return cls(policy, hashlib.sha256(text.encode("utf-8")).hexdigest(), crm)

    def _build_redactions(self, section: RedactSection, crm: CRMData) -> List[re.Pattern]:
        patterns = [re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE) for name in section.field_names]
        docs = {"hr": crm.internal_hr_data, "financial": crm.internal_financial_data}
        crm_amounts = _crm_amounts(crm)
        self.skipped_values: List[str] = []
        for src in section.values_from:
            for value in _values_at(docs[src.source], src.path.split(".")):
                if src.kind == "money" and isinstance(value, int):
                    if value in crm_amounts:        # also a legitimate CRM figure: never redact
                        self.skipped_values.append(f"{src.path}={value}")
                        continue
                    patterns.append(re.compile(_money_pattern(value), re.IGNORECASE))
                elif src.kind == "text" and isinstance(value, str) and value.strip():
                    patterns.append(re.compile(rf"\b{re.escape(value.strip())}", re.IGNORECASE))
        return patterns

    def describe(self) -> Dict[str, Any]:
        return {"enabled": True, "policy_version": self.policy.version, "policy_sha256": self.sha256,
                "rules": len(self._rules), "redaction_patterns": len(self._redact)}

    # -- checking -----------------------------------------------------------

    def is_email(self, text: str) -> bool:
        return any(p.search(text) for p in self._email)

    def _rule_hits(self, rule: OutputRule, groups, unless, text: str, is_email: bool) -> bool:
        if rule.email_only and not is_email:
            return False
        units = _SENTENCES.split(text) if rule.scope == "sentence" else [text]
        for unit in units:
            for exempt in unless:
                unit = exempt.sub(" ", unit)
            if any(all(p.search(unit) for p in group) for group in groups):
                return True
        return False

    def check(self, text: str) -> OutputDecision:
        """Decide what to do with a response (does not write the review queue)."""
        is_email = self.is_email(text)
        hits = [rule for rule, groups, unless in self._rules if self._rule_hits(rule, groups, unless, text, is_email)]
        if hits:
            worst = max(hits, key=lambda r: _SEVERITY[r.action])
            decisive = [r for r in hits if r.action == worst.action]
            categories = sorted({r.category for r in decisive})
            return OutputDecision(
                action=worst.action,
                response=self.policy.responses[worst.response].strip(),
                rule_ids=[r.id for r in decisive],
                categories=categories,
            )
        redacted, count = text, 0
        for pattern in self._redact:
            redacted, n = pattern.subn(self.policy.redaction_token, redacted)
            count += n
        if count:
            return OutputDecision("redact", redacted, ["redact.sensitive_values"], ["raw_sensitive_data"], count)
        return OutputDecision("allow", text)

    def apply(self, text: str, review_queue: Path, run_id: Optional[str] = None,
              request: str = "") -> OutputDecision:
        """check(), and for `review` write the withheld response to the review queue."""
        decision = self.check(text)
        if decision.action == "review":
            decision.review_id = uuid.uuid4().hex[:10]
            decision.response = decision.response.format(
                review_id=decision.review_id, categories=", ".join(decision.categories).replace("email_", ""))
            review_queue.parent.mkdir(parents=True, exist_ok=True)
            item = {
                "review_id": decision.review_id,
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "rule_ids": decision.rule_ids,
                "categories": decision.categories,
                "request": request,
                "response": text,
            }
            with review_queue.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item) + "\n")
        return decision


def load_output_guardrail(cfg: dict[str, Any], crm: CRMData) -> Optional[OutputGuardrail]:
    """The configured output guardrail, or None when disabled in config."""
    section = cfg["guardrails"]["output"]
    if not section["enabled"]:
        return None
    return OutputGuardrail.from_file(section["policy"], crm)
