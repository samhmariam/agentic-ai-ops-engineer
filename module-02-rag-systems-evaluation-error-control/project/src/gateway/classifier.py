"""Classify a customer query as ``simple`` or ``complex`` using gpt-4o-mini.

A small LLM self-classification beats keyword heuristics because it
generalises to unseen phrasings. Cost is ~$0.0001 per call, which is
the price of teaching students that cheap models can be useful
infrastructure for routing decisions, not just answer generation.

To change the routing prompt, edit ``prompts/classifier.j2``. Bad JSON
or unexpected labels fall through to ``"complex"`` — the safer (more
capable, more expensive) route.
"""

import json
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader
from openai import OpenAI

from src.config import settings

QueryType = Literal["simple", "complex"]

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
# Prompts are plaintext, not HTML; explicit autoescape=False signals the
# intent (matches src/rag/generator.py).
_env = Environment(
    loader=FileSystemLoader(_PROMPTS_DIR),
    keep_trailing_newline=True,
    autoescape=False,
)

_client = OpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url or None,
)


def classify(question: str) -> QueryType:
    """Return ``"simple"`` or ``"complex"`` for a customer question.

    Falls back to ``"complex"`` (the safer/more expensive route) if the
    classifier returns malformed JSON or an unexpected label — better to
    pay a bit more than to give a worse answer.
    """
    prompt = _env.get_template("classifier.j2").render(query=question)
    response = _client.chat.completions.create(
        model=settings.model_simple,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
        label = parsed.get("classification")
    except json.JSONDecodeError:
        label = None

    if label not in ("simple", "complex"):
        return "complex"
    return label
