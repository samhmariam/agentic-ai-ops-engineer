"""Input guardrail: inspect a user request before the agent acts on it.

The check is deterministic (regex rules from a versioned policy file under
policies/), so it does not depend on the model choosing to refuse. A blocked
request never reaches the model: no tool can be called and no restricted data can
be retrieved. The caller returns the rule's fixed response instead and records the
decision (category and rule id, never the raw request) in logs and traces.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ZERO_WIDTH = re.compile("[​‌‍⁠﻿­]")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "′": "'"})
_JOINERS = re.compile(r"(?<=\w)[.\-_*](?=\w)")


def normalize(text: str) -> str:
    """Canonical form for matching: NFKC, no zero-width chars, straight quotes,
    lowercase, collapsed whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text).translate(_QUOTES).lower()
    return re.sub(r"\s+", " ", text).strip()


def compact(normalized: str) -> str:
    """Join word characters split by . - _ * ("c.e.o" -> "ceo", "lay-offs" -> "layoffs")."""
    return _JOINERS.sub("", normalized)


# -- policy schema ----------------------------------------------------------

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Rule(_Strict):
    id: str = Field(pattern=r"^[a-z_]+\.[a-z_]+$")
    category: str
    response: str
    patterns: List[str] = Field(min_length=1)
    unless: List[str] = []

    @field_validator("patterns", "unless")
    @classmethod
    def regexes_compile(cls, value: List[str]) -> List[str]:
        for pattern in value:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc
        return value


class InputPolicy(_Strict):
    version: str = Field(pattern=r"^v\d+$")
    max_input_chars: int = Field(ge=100)
    responses: Dict[str, str]
    rules: List[Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def references_resolve(self) -> "InputPolicy":
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule ids")
        missing = {r.response for r in self.rules} - self.responses.keys()
        if missing or "too_long" not in self.responses:
            raise ValueError(f"rules reference undefined responses: {sorted(missing | ({'too_long'} - self.responses.keys()))}")
        return self


# -- runtime ----------------------------------------------------------------

@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    stage: Literal["input"] = "input"
    rule_id: Optional[str] = None
    category: Optional[str] = None
    response: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Decision with an explicit status and reason (same shape as tool/output blocks)."""
        return {"status": "allowed" if self.allowed else "blocked", "reason": self.category, **asdict(self)}


ALLOW = GuardDecision(allowed=True)


@dataclass(frozen=True)
class _CompiledRule:
    rule: Rule
    patterns: List[re.Pattern]
    unless: List[re.Pattern]

    def matches(self, variants: List[str]) -> bool:
        # `unless` phrases are blanked out, not used to exempt the whole request:
        # "ignoring customer acquisition, are we acquiring Acme?" must still match.
        for variant in variants:
            for exempt in self.unless:
                variant = exempt.sub(" ", variant)
            if any(p.search(variant) for p in self.patterns):
                return True
        return False


class InputGuardrail:
    def __init__(self, policy: InputPolicy, sha256: str):
        self.policy = policy
        self.sha256 = sha256
        self._rules = [
            _CompiledRule(
                rule,
                [re.compile(p, re.IGNORECASE) for p in rule.patterns],
                [re.compile(u, re.IGNORECASE) for u in rule.unless],
            )
            for rule in policy.rules
        ]

    @classmethod
    def from_file(cls, path: Path) -> "InputGuardrail":
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        policy = InputPolicy.model_validate(yaml.safe_load(text))
        return cls(policy, hashlib.sha256(text.encode("utf-8")).hexdigest())

    def check(self, text: str) -> GuardDecision:
        """Return ALLOW, or a block decision naming the first matching rule."""
        if len(text) > self.policy.max_input_chars:
            return GuardDecision(False, rule_id="limits.max_input_chars", category="input_too_long",
                                 response=self.policy.responses["too_long"])
        normalized = normalize(text)
        variants = [normalized, compact(normalized)]
        for compiled in self._rules:
            if compiled.matches(variants):
                rule = compiled.rule
                return GuardDecision(False, rule_id=rule.id, category=rule.category,
                                     response=self.policy.responses[rule.response])
        return ALLOW

    def describe(self) -> Dict[str, Any]:
        return {"enabled": True, "policy_version": self.policy.version, "policy_sha256": self.sha256,
                "rules": len(self._rules)}


def load_input_guardrail(cfg: dict[str, Any]) -> Optional[InputGuardrail]:
    """The configured input guardrail, or None when disabled in config."""
    section = cfg["guardrails"]["input"]
    if not section["enabled"]:
        return None
    return InputGuardrail.from_file(section["policy"])
