"""Unit tests for the Langfuse tracing wiring.

No network and no API key: the Langfuse CallbackHandler is monkeypatched with a stub
and the LANGFUSE_* environment is controlled per test, so build_tracer/trace_callbacks
are exercised purely on their config + env branching.
"""

import realthor.tracing as tracing


class _StubHandler:
    """Stand-in for langfuse.langchain.CallbackHandler (constructs without network)."""


def _set_langfuse_env(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")


def test_build_tracer_returns_none_when_disabled(monkeypatch):
    _set_langfuse_env(monkeypatch)
    monkeypatch.setattr(tracing, "CallbackHandler", _StubHandler)
    assert tracing.build_tracer({"tracing": {"enabled": False}}) is None


def test_build_tracer_returns_none_when_env_missing(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(tracing, "CallbackHandler", _StubHandler)
    assert tracing.build_tracer({"tracing": {"enabled": True}}) is None


def test_build_tracer_returns_handler_when_enabled(monkeypatch):
    _set_langfuse_env(monkeypatch)
    monkeypatch.setattr(tracing, "CallbackHandler", _StubHandler)
    handler = tracing.build_tracer({"tracing": {"enabled": True}})
    assert isinstance(handler, _StubHandler)


def test_trace_callbacks_empty_when_disabled(monkeypatch):
    _set_langfuse_env(monkeypatch)
    monkeypatch.setattr(tracing, "CallbackHandler", _StubHandler)
    assert tracing.trace_callbacks({"tracing": {"enabled": False}}) == []


def test_trace_callbacks_contains_handler_when_enabled(monkeypatch):
    _set_langfuse_env(monkeypatch)
    monkeypatch.setattr(tracing, "CallbackHandler", _StubHandler)
    callbacks = tracing.trace_callbacks({"tracing": {"enabled": True}})
    assert len(callbacks) == 1
    assert isinstance(callbacks[0], _StubHandler)
