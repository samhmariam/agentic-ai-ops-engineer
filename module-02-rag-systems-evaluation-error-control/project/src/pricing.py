"""Per-model pricing and cost computation.

Shared infrastructure imported by both ``src.rag.generator`` (where token
usage is captured at the source) and ``src.cost.tracker`` (where costs
are aggregated). Lives outside both packages so neither has to import
the other — preserves the forward-dependency rule.

To add a new model, add an entry to ``MODEL_PRICING`` keyed on the
exact model name string and valued ``(input_usd_per_million,
output_usd_per_million)``. Then point ``MODEL_COMPLEX`` or
``MODEL_SIMPLE`` in ``.env`` at the new key. ``compute_cost`` raises
``KeyError`` for an unknown model — that's intentional, so a typo in
.env fails loudly instead of silently logging $0.
"""

from src.models import TokenUsage

# USD per 1M tokens (OpenAI public pricing as of 2026-04)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


def compute_cost(model: str, usage: TokenUsage) -> float:
    """Return the USD cost for a completion given the model and token usage."""
    input_price, output_price = MODEL_PRICING[model]
    return (
        usage.prompt_tokens * input_price + usage.completion_tokens * output_price
    ) / 1_000_000
