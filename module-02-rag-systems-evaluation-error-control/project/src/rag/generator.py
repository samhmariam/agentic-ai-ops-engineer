"""Generate an answer using OpenAI chat completions with retrieved context.

The system prompt template lives at ``prompts/rag_system.j2`` — including
the ``<<<BEGIN_CONTEXT>>>`` / ``<<<END_CONTEXT>>>`` markers that mitigate
indirect prompt injection from poisoned retrieval. Edit that file to
change tone, response constraints, or the citation style; this module
just renders it.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from openai import OpenAI

from src.config import settings
from src.models import Source, TokenUsage
from src.pricing import compute_cost

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
# Prompts are plaintext sent to the LLM, not HTML; HTML-escaping would
# corrupt characters like '{' and '&'. State the choice explicitly so a
# future reuse of this Environment for HTML rendering doesn't silently
# inherit unsafe behavior.
_env = Environment(
    loader=FileSystemLoader(_PROMPTS_DIR),
    keep_trailing_newline=True,
    autoescape=False,
)

_client = OpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url or None,
)


def render_system_prompt(sources: list[Source]) -> str:
    """Render the rag_system.j2 template with retrieved chunks as context."""
    contexts = "\n\n".join(
        f"[{s.doc_id}] {s.chunk_text}" for s in sources
    )
    template = _env.get_template("rag_system.j2")
    return template.render(contexts=contexts)


def generate(
    question: str, sources: list[Source], model: str
) -> tuple[str, TokenUsage, float]:
    """Call OpenAI chat completions and return (answer, token_usage, cost_usd)."""
    system_prompt = render_system_prompt(sources)
    response = _client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
    )
    answer = response.choices[0].message.content or ""
    usage = TokenUsage(
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )
    cost = compute_cost(model, usage)
    return answer, usage, cost
