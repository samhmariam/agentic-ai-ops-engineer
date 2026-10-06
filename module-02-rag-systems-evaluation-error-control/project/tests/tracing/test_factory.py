"""Tests for the tracing backend factory in src/tracing/__init__.py."""

import importlib

import pytest

import src.tracing
from src.config import settings


def test_each_backend_module_exports_required_symbols():
    """Every backend implements the same four-symbol contract."""
    from src.tracing import noop_backend, phoenix_backend

    for module in (noop_backend, phoenix_backend):
        assert callable(module.init_tracing)
        assert callable(module.flush)
        assert callable(module.trace_rag_query)
        assert callable(module.traced_pipeline)


def test_default_backend_is_phoenix():
    assert settings.tracing_backend == "phoenix"
    assert (
        src.tracing.traced_pipeline.__module__
        == "src.tracing.phoenix_backend"
    )


@pytest.mark.parametrize(
    "backend,expected_module",
    [
        ("phoenix", "src.tracing.phoenix_backend"),
        ("none", "src.tracing.noop_backend"),
    ],
)
def test_factory_selects_module_for_each_backend(
    monkeypatch, backend, expected_module
):
    monkeypatch.setattr(settings, "tracing_backend", backend)
    importlib.reload(src.tracing)
    assert src.tracing.traced_pipeline.__module__ == expected_module
