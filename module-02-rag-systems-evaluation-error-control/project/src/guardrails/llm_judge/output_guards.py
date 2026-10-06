"""Output-side validators using an LLM judge.

Replaces ``FactualConsistency`` (NLI) for hallucination detection. The
NLI scanner had structurally high false-positive rates on paragraph-
level RAG output (40% FPR on grounded answers — see
``docs/verifications/2026-04-29-factuality-threshold-tuning.md``). This
module asks gpt-4o-mini directly: "does this answer follow from the
source?" The model's answer-paraphrase-source semantics handles the
cases NLI failed on (numeric paraphrases, comparisons, refusals).

Trade-offs:

- +1 LLM call per ``/query`` (~1–2s latency, ~$0.0002 per request).
- Cost-log gets a second entry per request with
  ``query_type="hallucination_check"`` so the additional spend is
  visible in ``data/cost_log.jsonl``.
- **Fail-open**: any error (network, rate limit, JSON parse, missing
  field) returns ``None`` — the answer flows through unblocked. The
  alternative (false-positive on a network blip) is worse for a course
  demo. A WARN-level log entry surfaces the failure for operators.

``is_off_topic`` is re-exported from ``src.guardrails.llm_guard`` —
that scanner (BanTopics zero-shot) works fine and didn't need
replacing. Keeping the import here so ``src.gateway.routes`` imports
both names from a single module.
"""

import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from openai import OpenAI

from src.config import settings
from src.cost.tracker import log_request
from src.guardrails.llm_guard.output_guards import is_off_topic
from src.models import Source, TokenUsage
from src.pricing import compute_cost

LOGGER = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_env = Environment(
    loader=FileSystemLoader(_PROMPTS_DIR),
    keep_trailing_newline=True,
    autoescape=False,
)

_client = OpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url or None,
)

__all__ = ["check_hallucination", "is_off_topic"]


def check_hallucination(answer: str, sources: list[Source]) -> str | None:
    """Return a block-reason string if the LLM judge says the answer
    isn't supported by the sources. Return ``None`` to pass.

    Empty ``sources`` is not the scanner's concern — the upstream
    confidence check handles unretrieved queries — so we mirror the
    behaviour of the NLI variant and return ``None``. Any error inside
    the judge call is logged at WARN and treated as a pass (fail-open).
    """
    if not sources:
        return None

    source_text = " ".join(s.chunk_text for s in sources)
    prompt = _env.get_template("judge.j2").render(
        source=source_text, answer=answer
    )

    try:
        response = _client.chat.completions.create(
            model=settings.model_simple,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        LOGGER.warning("LLM judge call failed; failing open: %s", exc)
        return None

    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
        verdict = parsed["verdict"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        LOGGER.warning(
            "LLM judge returned unparseable response %r; failing open: %s",
            raw[:200],
            exc,
        )
        return None

    # Log the cost regardless of verdict — we paid for the call.
    usage = TokenUsage(
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )
    cost = compute_cost(settings.model_simple, usage)
    log_request(settings.model_simple, usage, cost, "hallucination_check")

    if verdict == "NOT_SUPPORTED":
        reason = parsed.get("reason", "judge marked answer as not supported")
        return f"hallucination: {reason}"
    return None
