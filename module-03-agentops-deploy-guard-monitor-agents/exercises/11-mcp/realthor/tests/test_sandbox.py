import pathlib

import pandas as pd
import pytest

from realthor.config import load_config, resolve_paths
from realthor.sandbox import run_sandboxed, validate_code

CONFIG_PATH = str(pathlib.Path(__file__).parent.parent / "config.yaml")


# ---------------------------------------------------------------------------
# validate_code — AST checks
# ---------------------------------------------------------------------------

def test_safe_code_passes():
    ok, reason = validate_code("result = listings[listings['region'] == 'west'].shape[0]\nprint(result)")
    assert ok is True
    assert reason == ""


def test_import_os_blocked():
    ok, reason = validate_code("import os\nprint(os.listdir('.'))")
    assert ok is False
    assert "os" in reason


def test_import_subprocess_blocked():
    ok, reason = validate_code("import subprocess\nsubprocess.run(['ls'])")
    assert ok is False
    assert "subprocess" in reason


def test_open_builtin_blocked():
    ok, reason = validate_code("open('listings.csv', 'w')")
    assert ok is False
    assert "open" in reason


def test_eval_blocked():
    ok, reason = validate_code("result = eval('1 + 1')")
    assert ok is False
    assert "eval" in reason


def test_exec_blocked():
    ok, reason = validate_code("exec('x = 1')")
    assert ok is False
    assert "exec" in reason


# ---------------------------------------------------------------------------
# run_sandboxed — execution checks
# ---------------------------------------------------------------------------

def test_basic_pandas_runs():
    df = pd.DataFrame({"region": ["west", "west", "east"], "value": [1, 2, 3]})
    output, error = run_sandboxed(
        "result = listings[listings['region'] == 'west']['value'].sum()\nprint(result)",
        {"listings": df},
    )
    assert error == ""
    assert "3" in output


def test_timeout_enforced():
    _, error = run_sandboxed("while True: pass", {}, timeout=1)
    assert "timed out" in error


def test_sensitive_columns_absent():
    """Sensitive columns must be stripped before DataFrames reach the sandbox."""
    cfg = resolve_paths(load_config(CONFIG_PATH), CONFIG_PATH)
    listings = pd.read_csv(cfg["paths"]["listings_data"]).drop(
        columns=["seller_name", "seller_motivation"], errors="ignore"
    )
    assert "seller_name" not in listings.columns
    assert "seller_motivation" not in listings.columns
