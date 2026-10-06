"""Tests for src.evaluation.run_eval."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.evaluation import (
    DEFAULT_METRICS,
    build_eval_dataset,
    evaluate_pipeline,
    load_golden_set,
    summarize,
)
from src.models import QueryResponse, Source, TokenUsage


@pytest.fixture
def golden_csv(tmp_path):
    path = tmp_path / "golden.csv"
    path.write_text(
        "question,ground_truth,contexts\n"
        'How heavy is the Selkirk?,7.8 oz.,"[""Selkirk weighs 7.8 oz.""]"\n'
        "What core does Joola use?,Polypropylene,\"[\"\"Joola has a polypropylene core.\"\"]\"\n"
    )
    return path


def make_response(answer: str, sources: list[tuple[str, str]]) -> QueryResponse:
    return QueryResponse(
        answer=answer,
        sources=[
            Source(doc_id=d, chunk_text=c, similarity_score=0.8) for d, c in sources
        ],
        confidence=0.8,
        model="gpt-4o-mini",
        tokens=TokenUsage(prompt_tokens=10, completion_tokens=5),
        cost_usd=0.0,
    )


def test_load_golden_set_parses_json_contexts(golden_csv):
    rows = load_golden_set(golden_csv)

    assert len(rows) == 2
    assert rows[0] == {
        "question": "How heavy is the Selkirk?",
        "ground_truth": "7.8 oz.",
        "contexts": ["Selkirk weighs 7.8 oz."],
    }
    assert rows[1]["contexts"] == ["Joola has a polypropylene core."]


def test_build_eval_dataset_runs_pipeline_per_row():
    golden = [
        {"question": "Q1", "ground_truth": "GT1", "contexts": ["expected1"]},
        {"question": "Q2", "ground_truth": "GT2", "contexts": ["expected2"]},
    ]
    responses = [
        make_response("A1", [("p1", "ctx1a"), ("p2", "ctx1b")]),
        make_response("A2", [("p3", "ctx2a")]),
    ]

    with patch(
        "src.evaluation.run_eval.run_pipeline", side_effect=responses
    ) as run:
        dataset = build_eval_dataset(golden)

    assert run.call_count == 2
    run.assert_any_call("Q1", top_k=5)
    run.assert_any_call("Q2", top_k=5)

    assert dataset["question"] == ["Q1", "Q2"]
    assert dataset["answer"] == ["A1", "A2"]
    assert dataset["contexts"] == [["ctx1a", "ctx1b"], ["ctx2a"]]
    assert dataset["ground_truth"] == ["GT1", "GT2"]


def test_evaluate_pipeline_calls_ragas_with_default_metrics():
    golden = [{"question": "Q", "ground_truth": "GT", "contexts": []}]
    fake_dataset = MagicMock()
    fake_result = MagicMock()
    fake_embedder = MagicMock()

    with patch(
        "src.evaluation.run_eval.build_eval_dataset", return_value=fake_dataset
    ) as build, patch(
        "src.evaluation.run_eval._build_embeddings", return_value=fake_embedder
    ), patch(
        "src.evaluation.run_eval.evaluate", return_value=fake_result
    ) as ragas_evaluate:
        result = evaluate_pipeline(golden)

    build.assert_called_once_with(golden, top_k=5)
    ragas_evaluate.assert_called_once()
    assert ragas_evaluate.call_args.args == (fake_dataset,)
    assert ragas_evaluate.call_args.kwargs["metrics"] == DEFAULT_METRICS
    assert ragas_evaluate.call_args.kwargs["embeddings"] is fake_embedder
    assert result is fake_result


def test_build_eval_dataset_threads_top_k_to_run_pipeline():
    """`top_k` must reach `run_pipeline` so eval_topk_sweep produces
    different retrieval depths per sweep value."""
    golden = [{"question": "Q", "ground_truth": "GT", "contexts": []}]
    response = make_response("A", [("p", "ctx")])
    with patch(
        "src.evaluation.run_eval.run_pipeline", return_value=response
    ) as run:
        build_eval_dataset(golden, top_k=10)

    run.assert_called_once_with("Q", top_k=10)


def test_evaluate_pipeline_threads_top_k_to_build_eval_dataset():
    golden = [{"question": "Q", "ground_truth": "GT", "contexts": []}]
    with patch(
        "src.evaluation.run_eval.build_eval_dataset"
    ) as build, patch(
        "src.evaluation.run_eval._build_embeddings"
    ), patch("src.evaluation.run_eval.evaluate"):
        evaluate_pipeline(golden, top_k=3)

    build.assert_called_once_with(golden, top_k=3)


def test_evaluate_pipeline_accepts_custom_metrics():
    golden = [{"question": "Q", "ground_truth": "GT", "contexts": []}]
    custom = [MagicMock(name="metric")]

    with patch("src.evaluation.run_eval.build_eval_dataset"), \
         patch("src.evaluation.run_eval._build_embeddings"), \
         patch("src.evaluation.run_eval.evaluate") as ragas_evaluate:
        evaluate_pipeline(golden, metrics=custom)

    ragas_evaluate.assert_called_once()
    assert ragas_evaluate.call_args.kwargs["metrics"] == custom


def test_evaluate_pipeline_omits_run_config_when_max_workers_is_none():
    """Default behavior: let RAGAS pick its own worker count."""
    golden = [{"question": "Q", "ground_truth": "GT", "contexts": []}]
    with patch("src.evaluation.run_eval.build_eval_dataset"), \
         patch("src.evaluation.run_eval._build_embeddings"), \
         patch("src.evaluation.run_eval.evaluate") as ragas_evaluate:
        evaluate_pipeline(golden)

    assert "run_config" not in ragas_evaluate.call_args.kwargs


def test_evaluate_pipeline_passes_max_workers_via_run_config():
    """``max_workers=1`` plumbs into ``RunConfig(max_workers=1)`` and
    reaches RAGAS's ``evaluate(..., run_config=...)``."""
    golden = [{"question": "Q", "ground_truth": "GT", "contexts": []}]
    with patch("src.evaluation.run_eval.build_eval_dataset"), \
         patch("src.evaluation.run_eval._build_embeddings"), \
         patch("src.evaluation.run_eval.evaluate") as ragas_evaluate:
        evaluate_pipeline(golden, max_workers=1)

    run_config = ragas_evaluate.call_args.kwargs.get("run_config")
    assert run_config is not None
    assert run_config.max_workers == 1


def test_summarize_averages_only_metric_columns():
    fake_result = MagicMock()
    fake_result.to_pandas.return_value = pd.DataFrame(
        {
            "question": ["Q1", "Q2"],
            "answer": ["A1", "A2"],
            "contexts": [["c1"], ["c2"]],
            "ground_truth": ["G1", "G2"],
            "faithfulness": [0.8, 0.6],
            "answer_relevancy": [0.9, 0.7],
        }
    )

    aggregate = summarize(fake_result)

    assert aggregate == {"faithfulness": pytest.approx(0.7), "answer_relevancy": pytest.approx(0.8)}


def test_default_metrics_are_the_four_stable_ones():
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    assert DEFAULT_METRICS == [
        faithfulness,
        answer_relevancy,
        context_recall,
        context_precision,
    ]
