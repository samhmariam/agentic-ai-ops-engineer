"""Input-side validators — layered regex pre-filter + LLM Guard scanners.

**Defense in depth.** This module wraps two production-grade ML scanners
behind a fast, explainable, learner-extensible regex layer:

- **Prompt injection**: regex pre-filter (``src.guardrails.input_guards``)
  catches known patterns in microseconds. On miss, falls through to
  ``PromptInjection`` (``protectai/deberta-v3-small-prompt-injection-v2``,
  ~250 MB DeBERTa fine-tuned on 30K injection/benign pairs) for novel
  attacks.
- **PII**: regex pre-filter redacts high-precision patterns
  (email/phone/SSN/credit card). Then ``Anonymize`` (Microsoft Presidio
  NER) runs on the cleaned text to catch names, addresses, and other
  fuzzier entities. The final ``kinds_found`` list is the union.

Why layer rather than pick one:

- The regex layer is **explainable** — a learner can read
  ``INJECTION_PATTERNS`` / ``PII_PATTERNS`` and predict what fires.
- It's **extensible** — adding a new pattern is one line and takes
  effect immediately at the live ``/query`` route. (Course rubric §6
  asks the learner to do exactly this.)
- The ML layer **catches what the regex misses** — novel injections,
  obfuscated attacks, names/places the regex doesn't enumerate.
- Short-circuiting on a regex hit also **avoids the DeBERTa cold start**
  for known attacks, keeping latency low when the system is busy
  rejecting bot traffic.

Both scanners follow LLM Guard's common signature:
    scan(prompt: str) -> (sanitized_text, is_valid: bool, risk_score: float)

``is_valid=False`` means the scanner found something worth flagging. For
injection we block. For PII we let the request continue with the redacted
text — PII in a product FAQ is almost always accidental.
"""

import re as _re

# Workaround for llm-guard upstream bug
# (https://github.com/protectai/llm-guard/issues/337):
# Anonymize.__init__ accepts a `language` parameter but ignores it,
# passing the hardcoded module-level ALL_SUPPORTED_LANGUAGES (= ["en",
# "zh"]) into get_analyzer() instead. That triggers Presidio's
# _get_nlp_engine to call spacy.cli.download for any missing language
# model, pulling zh_core_web_sm and its Chinese-segmenter compile-step
# dep spacy-pkuseg even though our /query path is English-only.
#
# Narrow the constant before importing Anonymize. Remove this patch
# (and the regression test in tests/guardrails/llm_guard/
# test_anonymize_patch.py) when llm-guard ships the upstream fix and
# the dependency pin is bumped past that release.
import llm_guard.input_scanners.anonymize as _llm_guard_anonymize_mod

_llm_guard_anonymize_mod.ALL_SUPPORTED_LANGUAGES = ["en"]
assert _llm_guard_anonymize_mod.ALL_SUPPORTED_LANGUAGES == ["en"], (
    "llm-guard structural change: ALL_SUPPORTED_LANGUAGES is no longer a "
    "mutable module-level list. The English-only patch above no longer "
    "takes effect; revisit the workaround "
    "(see https://github.com/protectai/llm-guard/issues/337)."
)

from llm_guard.input_scanners import Anonymize, PromptInjection
from llm_guard.input_scanners.anonymize_helpers import BERT_BASE_NER_CONF
from llm_guard.vault import Vault

from src.guardrails.input_guards import (
    detect_pii as _regex_detect_pii,
    detect_prompt_injection as _regex_detect_prompt_injection,
)

_injection_scanner = PromptInjection()
_pii_vault = Vault()
# llm-guard's Anonymize defaults to Isotonic/deberta-v3-base_finetuned_ai4privacy_v2,
# which is CC-BY-NC-4.0 (non-commercial). We override to dslim/bert-base-NER (MIT)
# so the workspace image — and any downstream commercial deployment — stays on
# permissive licenses. Detects PER/LOC/ORG/MISC; Presidio still runs the regex
# recognizers (email/phone/SSN/credit card) on top via our regex layer.
_anonymize_scanner = Anonymize(vault=_pii_vault, recognizer_conf=BERT_BASE_NER_CONF)


def detect_prompt_injection(text: str) -> str | None:
    """Return a block reason if regex OR DeBERTa flags the text, else None.

    Regex pre-filter runs first (microseconds, explainable). On a hit we
    short-circuit and skip DeBERTa — the answer is the same either way
    (block) and we save the model call. On a miss, fall through to
    DeBERTa for novel attacks the regex can't anticipate.
    """
    if reason := _regex_detect_prompt_injection(text):
        return reason
    _sanitized, is_valid, risk_score = _injection_scanner.scan(text)
    if not is_valid:
        return f"prompt_injection: risk_score={risk_score:.3f}"
    return None


def detect_pii(text: str) -> tuple[str, list[str]]:
    """Redact PII via regex + Presidio; return ``(sanitized_text, kinds_found)``.

    Unlike injection (where regex hit short-circuits), PII layering runs
    BOTH layers because they catch different things:

    - Regex catches high-confidence structural patterns (email, phone,
      SSN, credit card) with near-zero false-positive rate.
    - Presidio catches entities regex can't enumerate (names,
      addresses, organizations) using a NER model.

    Regex runs first to redact the structural patterns, then Presidio
    runs on the cleaned text to find the rest. ``kinds_found`` is the
    union of both layers' detections. If neither finds anything, returns
    the original text and ``[]``.
    """
    # Regex layer: catches email / phone / SSN / credit card.
    sanitized, regex_kinds = _regex_detect_pii(text)

    # Presidio layer: NER on the cleaned text. Anything regex already
    # replaced with `[REDACTED_*]` looks like a token to Presidio and
    # won't double-tag.
    after_presidio, is_valid, _risk_score = _anonymize_scanner.scan(sanitized)
    presidio_kinds: list[str] = []
    if not is_valid:
        # Presidio placeholders look like `[REDACTED_EMAIL_ADDRESS_1]`.
        # Extract entity labels so callers can surface them in `blocked_by`.
        placeholders = _re.findall(r"\[REDACTED_([A-Z_]+?)_\d+\]", after_presidio)
        presidio_kinds = sorted({p.lower() for p in placeholders}) if placeholders else ["pii"]

    kinds = sorted(set(regex_kinds) | set(presidio_kinds))
    return after_presidio, kinds
