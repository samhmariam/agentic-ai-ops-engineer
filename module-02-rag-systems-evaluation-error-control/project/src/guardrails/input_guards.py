"""Input-side validators: prompt injection detection and PII redaction.

Lightweight regex/heuristic implementations chosen over Guardrails Hub
validators for capstone reliability. The Hub validators (e.g.
``hub://guardrails/detect_pii``) are the production upgrade path covered
in the Guardrails module's content; LLM Guard's ML-backed scanners (in
the sibling ``llm_guard/`` package) are a second upgrade path that runs
locally without external accounts.

To add a new injection pattern, append a ``re.compile(...)`` to
``INJECTION_PATTERNS``. To add a new PII type, add an entry to
``PII_PATTERNS`` and a matching redaction string in ``PII_REDACTIONS``.
"""

import re

INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(all\s+)?(previous|prior|above)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(an?\s+)?", re.IGNORECASE),
    re.compile(r"\bpretend\s+(to\s+be|you\s+are)\b", re.IGNORECASE),
    re.compile(r"^\s*system\s*[:>]", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*assistant\s*[:>]", re.IGNORECASE | re.MULTILINE),
    re.compile(r"<\s*\|?\s*im_start\s*\|?\s*>", re.IGNORECASE),
    re.compile(
        r"\b(reveal|show|print|leak|repeat|tell\s+me)\s+(your|the)\s+"
        r"(system|initial|original|hidden|secret)\s+(prompt|instructions?|rules?|message)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(bypass|override|turn\s+off|disable|ignore)\s+(your|the|all)?\s*"
        r"(safety|guardrails?|filters?|restrictions?|content\s+policy|policies)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(jailbreak\s+mode|DAN\s+mode|developer\s+mode|do\s+anything\s+now)\b",
        re.IGNORECASE,
    ),
    # Instruction reset with verbs the ignore/disregard patterns miss. The
    # object must be the assistant's own instructions ("your", "previous",
    # "system" ...), so "I forget the instructions for the net" passes.
    re.compile(
        r"\b(forget|discard|erase|drop|abandon)\s+(all\s+(of\s+)?)?"
        r"((your|previous|prior|earlier|above|system)\s+){1,2}"
        r"(instructions?|guidelines|directives|rules|prompt)\b"
        r"|\bforget\s+everything\s+(above|before|you\s+(were|have\s+been|'ve\s+been)\s+(told|given))\b",
        re.IGNORECASE,
    ),
    # Delimiter / chat-template spoofing: our own context markers from
    # prompts/rag_system.j2, Llama-style [INST] / <<SYS>> tokens, and
    # pseudo-XML role tags. No product question contains these.
    re.compile(
        r"<{2,}\s*/?\s*(BEGIN|END)_CONTEXT\s*>{2,}"
        r"|\[\s*/?\s*INST\s*\]"
        r"|<<\s*/?\s*SYS\s*>>"
        r"|<\s*/?\s*(system|assistant|instructions?)\s*>",
        re.IGNORECASE,
    ),
    # System-prompt exfiltration phrased as a question or summary, or as an
    # echo of "everything above" — forms the reveal/show pattern misses.
    re.compile(
        r"\b(what\s+(is|are|was|were)|summari[sz]e|describe|translate|paste|output)\s+"
        r"(your|the)\s+(system\s+prompt|(initial|original|hidden|secret|system)\s+"
        r"(instructions?|rules|message|prompt))\b"
        r"|\b(repeat|print|output|paste)\s+(everything|all\s+(of\s+)?the\s+text)\s+"
        r"(above|before\s+this)\b",
        re.IGNORECASE,
    ),
]

PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
}

PII_REDACTIONS: dict[str, str] = {
    "email": "[REDACTED_EMAIL]",
    "phone": "[REDACTED_PHONE]",
    "ssn": "[REDACTED_SSN]",
    "credit_card": "[REDACTED_CARD]",
}


def detect_prompt_injection(text: str) -> str | None:
    """Return a reason string if the input looks like prompt injection, else None."""
    for pattern in INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"prompt_injection: matched pattern {pattern.pattern!r}"
    return None


def detect_pii(text: str) -> tuple[str, list[str]]:
    """Redact known PII kinds from ``text``. Returns ``(redacted, kinds_found)``."""
    found: list[str] = []
    redacted = text
    for kind, pattern in PII_PATTERNS.items():
        if pattern.search(redacted):
            found.append(kind)
            redacted = pattern.sub(PII_REDACTIONS[kind], redacted)
    return redacted, found
