"""Tests for scripts/start_watcher.py."""

import importlib.util
import signal
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def cli_module():
    spec = importlib.util.spec_from_file_location(
        "_start_watcher_cli",
        Path(__file__).resolve().parents[2] / "scripts" / "start_watcher.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_invokes_start_watcher_with_defaults(cli_module, tmp_path):
    inbox = tmp_path / "inbox"

    with patch.object(cli_module, "start_watcher") as start, \
         patch("signal.signal") as sig:
        exit_code = cli_module.main(["--inbox", str(inbox)])

    assert exit_code == 0
    start.assert_called_once()
    kwargs = start.call_args.kwargs
    assert kwargs["inbox_dir"] == inbox
    assert kwargs["debounce_s"] == 0.5
    assert kwargs["failed_dir"] is None
    # SIGINT and SIGTERM both registered
    signals_registered = {call.args[0] for call in sig.call_args_list}
    assert signals_registered == {signal.SIGINT, signal.SIGTERM}


def test_cli_forwards_custom_args(cli_module, tmp_path):
    inbox = tmp_path / "inbox"
    failed = tmp_path / "elsewhere"

    with patch.object(cli_module, "start_watcher") as start, \
         patch("signal.signal"):
        cli_module.main([
            "--inbox", str(inbox),
            "--failed", str(failed),
            "--debounce", "1.5",
        ])

    kwargs = start.call_args.kwargs
    assert kwargs["failed_dir"] == failed
    assert kwargs["debounce_s"] == 1.5
