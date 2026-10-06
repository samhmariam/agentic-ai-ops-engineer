"""Shared pytest fixtures.

The tests run without real API credentials. We replace the network-creating
constructors in ``chromadb`` and ``openai`` *after* the real packages load,
so type references like ``chromadb.Collection`` still resolve. Individual
tests mock the exported functions directly when they need to control
behaviour.

Phoenix is mocked via ``sys.modules`` injection — *before* any test code
imports it — for two reasons: (a) the in-process Phoenix UI launched by
``phoenix.launch_app()`` and the global OpenAI SDK patch installed by
``OpenAIInstrumentor`` are side effects we never want in tests; (b) the
real ``phoenix`` package has an undeclared ``pytz`` import in
``phoenix.datetime_utils`` (a packaging bug in arize-phoenix as of
v10.15) that crashes ``import phoenix`` if pytz is absent. The fakes
below stand in for whatever ``init_tracing`` reaches for.
"""

import sys
from unittest.mock import MagicMock

# Pre-populate sys.modules with fake Phoenix + OpenInference modules so
# any ``import phoenix`` / ``from phoenix.otel import register`` inside
# the codebase resolves to a mock without ever loading the real package.
_fake_phoenix = MagicMock()
_fake_phoenix.launch_app = MagicMock(return_value=MagicMock())
sys.modules["phoenix"] = _fake_phoenix

_fake_phoenix_otel = MagicMock()
_fake_phoenix_otel.register = MagicMock(return_value=MagicMock())
sys.modules["phoenix.otel"] = _fake_phoenix_otel

_fake_oi_openai = MagicMock()
_fake_oi_openai.OpenAIInstrumentor = MagicMock(return_value=MagicMock())
sys.modules["openinference.instrumentation.openai"] = _fake_oi_openai

import chromadb  # noqa: E402
import openai  # noqa: E402
import llm_guard.input_scanners  # noqa: E402
import llm_guard.output_scanners  # noqa: E402

chromadb.PersistentClient = MagicMock(return_value=MagicMock())
openai.OpenAI = MagicMock(return_value=MagicMock())

# Stub LLM Guard scanner classes — their real constructors download ~400 MB
# of HuggingFace models (DeBERTa for injection, zero-shot for topic, NLI for
# factuality, spaCy + Presidio for PII) on first use. Tests patch per-module
# scanner instances to assert orchestration.
#
# The mocks default to "clean" output: ``scan(text, ...) -> (text, True, 0.0)``
# — i.e., the scanner finds nothing to flag. Tests that need to simulate a
# block patch ``src.gateway.routes.detect_prompt_injection`` (etc.) directly
# rather than overriding the scanner internals.
def _clean_scan_input(text: str):
    return text, True, 0.0


def _clean_scan_output(prompt: str, output: str):
    return output, True, 0.0


_injection_mock = MagicMock()
_injection_mock.scan = MagicMock(side_effect=_clean_scan_input)
llm_guard.input_scanners.PromptInjection = MagicMock(return_value=_injection_mock)

_anonymize_mock = MagicMock()
_anonymize_mock.scan = MagicMock(side_effect=_clean_scan_input)
llm_guard.input_scanners.Anonymize = MagicMock(return_value=_anonymize_mock)

_bantopics_mock = MagicMock()
_bantopics_mock.scan = MagicMock(side_effect=_clean_scan_output)
llm_guard.output_scanners.BanTopics = MagicMock(return_value=_bantopics_mock)

_factuality_mock = MagicMock()
_factuality_mock.scan = MagicMock(side_effect=_clean_scan_output)
llm_guard.output_scanners.FactualConsistency = MagicMock(return_value=_factuality_mock)
