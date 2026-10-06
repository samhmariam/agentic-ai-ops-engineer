"""Tests for scripts/run_eval.py CLI."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


@pytest.fixture
def cli_module():
    spec = importlib.util.spec_from_file_location(
        "_run_eval_cli",
        Path(__file__).resolve().parents[2] / "scripts" / "run_eval.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def golden_csv(tmp_path):
    path = tmp_path / "golden.csv"
    path.write_text(
        "question,ground_truth,contexts\n"
        'Q1,GT1,"[""ctx1""]"\n'
        'Q2,GT2,"[""ctx2""]"\n'
        'Q3,GT3,"[""ctx3""]"\n'
    )
    return path


def _fake_result(rows: int):
    result = MagicMock()
    result.to_pandas.return_value = pd.DataFrame(
        {
            "question": [f"Q{i}" for i in range(rows)],
            "answer": [f"A{i}" for i in range(rows)],
            "contexts": [["c"] for _ in range(rows)],
            "ground_truth": [f"GT{i}" for i in range(rows)],
            "faithfulness": [0.8] * rows,
            "answer_relevancy": [0.9] * rows,
        }
    )
    return result


def test_cli_runs_full_set_and_prints_aggregate(cli_module, golden_csv, capsys):
    with patch.object(
        cli_module, "evaluate_pipeline", return_value=_fake_result(3)
    ) as eval_fn:
        exit_code = cli_module.main(["--golden", str(golden_csv)])

    assert exit_code == 0
    eval_fn.assert_called_once()
    # 3 rows passed in
    assert len(eval_fn.call_args.args[0]) == 3

    out = capsys.readouterr().out
    assert "Evaluating 3 questions" in out
    assert "faithfulness: 0.800" in out
    assert "answer_relevancy: 0.900" in out


def test_cli_limit_truncates_golden_set(cli_module, golden_csv, capsys):
    with patch.object(
        cli_module, "evaluate_pipeline", return_value=_fake_result(2)
    ) as eval_fn:
        exit_code = cli_module.main(["--golden", str(golden_csv), "--limit", "2"])

    assert exit_code == 0
    assert len(eval_fn.call_args.args[0]) == 2
    assert "Evaluating 2 questions" in capsys.readouterr().out


def test_cli_writes_output_json(cli_module, golden_csv, tmp_path):
    output = tmp_path / "results.json"

    with patch.object(
        cli_module, "evaluate_pipeline", return_value=_fake_result(3)
    ):
        cli_module.main(
            ["--golden", str(golden_csv), "--output", str(output)]
        )

    payload = json.loads(output.read_text())
    assert payload["aggregate"]["faithfulness"] == pytest.approx(0.8)
    assert len(payload["rows"]) == 3
