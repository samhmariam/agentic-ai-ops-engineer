"""Run RAGAS evaluation against the golden test set.

Only the four stable metrics are run by default —
``faithfulness``, ``answer_relevancy``, ``context_recall``,
``context_precision``. Other RAGAS metrics churn between point releases
and have produced inconsistent scores during course development; this
list is the ones we trust to compare runs against.

To add a metric, append it to ``DEFAULT_METRICS`` (or pass a custom
list to ``evaluate_pipeline``). Pin ``ragas`` to an exact version in
``pyproject.toml`` — 0.x patches break occasionally.
"""

import csv
import json
from pathlib import Path
from typing import Sequence

from datasets import Dataset
from langchain_openai import ChatOpenAI as LangchainChatOpenAI
from langchain_openai import OpenAIEmbeddings as LangchainOpenAIEmbeddings
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.run_config import RunConfig
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from src.config import settings
from src.rag import run_pipeline

DEFAULT_METRICS = [
    faithfulness,
    answer_relevancy,
    context_recall,
    context_precision,
]


def load_golden_set(path: str | Path) -> list[dict]:
    """Load the golden CSV. Returns a list of {question, ground_truth, contexts}.

    The ``contexts`` field in the CSV is a JSON-encoded ``list[str]`` of the
    expected/relevant passages. RAGAS does not consume this column directly
    (retrieval quality is measured against the contexts the pipeline returns
    at eval time), but we parse it so callers can use it for diff reports.
    """
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "question": row["question"],
                    "ground_truth": row["ground_truth"],
                    "contexts": json.loads(row["contexts"]),
                }
            )
    return rows


def build_eval_dataset(golden_set: list[dict], *, top_k: int = 5) -> Dataset:
    """Run the RAG pipeline for each row and collect the outputs RAGAS needs.

    ``top_k`` is forwarded to ``run_pipeline`` so callers can sweep
    retrieval depth without editing the pipeline source. The default
    matches ``run_pipeline``'s default so existing call sites keep their
    current behavior.
    """
    questions: list[str] = []
    answers: list[str] = []
    retrieved_contexts: list[list[str]] = []
    ground_truths: list[str] = []

    for row in golden_set:
        response = run_pipeline(row["question"], top_k=top_k)
        questions.append(row["question"])
        answers.append(response.answer)
        retrieved_contexts.append([s.chunk_text for s in response.sources])
        ground_truths.append(row["ground_truth"])

    return Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": retrieved_contexts,
            "ground_truth": ground_truths,
        }
    )


def _build_llm() -> LangchainLLMWrapper:
    """Build a RAGAS LLM wrapper with explicit ``max_tokens`` and ``bypass_n=True``.

    Two corrections to RAGAS defaults:

    1. ``max_tokens=8192``. RAGAS auto-instantiates a default
       ``ChatOpenAI`` with ``max_tokens`` unset → OpenAI applies its own
       cap (~3072 for gpt-4o-mini), which truncates RAGAS's
       statement-extraction prompts on multi-product comparison
       questions. Truncation produced floods of
       ``The output is incomplete due to a max_tokens length limit``
       errors. gpt-4o-mini supports 16,384 output tokens; 8k is
       generous-but-not-wasteful.

    2. ``bypass_n=True``. RAGAS's default ``LangchainLLMWrapper.agenerate_text``
       (ragas 0.4.x) mutates the shared ``langchain_llm.n`` attribute
       per call — see ``ragas/llms/base.py::agenerate_text`` ~line 296.
       With ``max_workers=16`` (RAGAS's default ``RunConfig``), 16
       concurrent coroutines race to set ``.n`` on the same instance,
       and the loser sometimes sees ``n=1``. The metric then gets a
       single generation instead of the 3-sample self-consistency vote,
       and RAGAS warns ``LLM returned 1 generations instead of requested 3``.
       Setting ``bypass_n=True`` routes RAGAS through the fallback path
       at base.py:303–312, which issues N separate ``n=1`` calls
       sequentially per row — no shared mutation, no race. Costs ~3×
       the API calls per row, but on Vocareum the per-call latency is
       smaller (each ``n=1`` call is faster than an ``n=3`` call), so
       wall-clock is comparable. Eliminates the race entirely.

       Upstream issue draft: ``docs/issues/ragas-langchain-wrapper-n-race.md``.
    """
    return LangchainLLMWrapper(
        LangchainChatOpenAI(
            model=settings.model_simple,
            openai_api_key=settings.openai_api_key,
            openai_api_base=settings.openai_base_url or None,
            max_tokens=8192,
        ),
        bypass_n=True,
    )


def _build_embeddings() -> LangchainEmbeddingsWrapper:
    """Build a RAGAS embeddings provider from the project's OpenAI settings.

    RAGAS auto-instantiates a default embeddings provider when none is
    supplied to ``evaluate(...)``. In 0.4.x that default is
    ``ragas.embeddings.OpenAIEmbeddings`` — RAGAS's *modern* provider,
    which exposes ``embed_text``/``embed_texts`` but not ``embed_query``.
    The metrics (``answer_relevancy``, in particular) still call the
    legacy ``embed_query`` interface, so the modern provider raises
    ``AttributeError`` per row and the metric ends up NaN.

    The deprecated-but-still-functional ``LangchainEmbeddingsWrapper``
    around ``langchain_openai.OpenAIEmbeddings`` exposes ``embed_query``
    and works with every metric in 0.4.3. ``OPENAI_BASE_URL`` is honored
    so Vocareum deployments work without extra config.
    """
    return LangchainEmbeddingsWrapper(
        LangchainOpenAIEmbeddings(
            openai_api_key=settings.openai_api_key,
            openai_api_base=settings.openai_base_url or None,
            model=settings.embedding_model,
        )
    )


def evaluate_pipeline(
    golden_set: list[dict],
    metrics: Sequence | None = None,
    *,
    top_k: int = 5,
    max_workers: int | None = None,
):
    """Run the pipeline against the golden set and score with RAGAS.

    ``top_k`` is forwarded into ``build_eval_dataset`` and from there
    into ``run_pipeline``. ``scripts/eval_topk_sweep.py`` calls this
    function once per sweep value so a learner can produce a §2
    comparison table without editing pipeline source.

    ``max_workers`` caps the RAGAS executor concurrency. ``None`` lets
    RAGAS use its built-in default (16). Set to 1 when running through
    a contended OpenAI proxy (e.g. Vocareum from Jeff's local host)
    where parallel judge calls throttle into ``TimeoutError`` floods
    that turn metric averages into ``nan``.
    """
    dataset = build_eval_dataset(golden_set, top_k=top_k)
    kwargs = {
        "metrics": list(metrics or DEFAULT_METRICS),
        "embeddings": _build_embeddings(),
        "llm": _build_llm(),
    }
    if max_workers is not None:
        kwargs["run_config"] = RunConfig(max_workers=max_workers)
    return evaluate(dataset, **kwargs)


def summarize(result) -> dict[str, float]:
    """Aggregate per-row metric scores into a flat ``{metric: mean}`` dict.

    RAGAS adds string-typed columns alongside metric scores (``user_input``,
    ``retrieved_contexts``, ``response``, ``reference`` since 0.2.x). We
    reduce only numeric columns to avoid ``mean()`` raising on strings.
    """
    import pandas as pd  # Local import: keeps top of file dependency-light.

    df = result.to_pandas()
    scored: dict[str, float] = {}
    for col in df.columns:
        if col in {"question", "answer", "contexts", "ground_truth"}:
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        scored[col] = float(df[col].mean())
    return scored
