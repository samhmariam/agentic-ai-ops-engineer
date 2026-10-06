"""Regression tests for the OPENAI_BASE_URL empty-string footgun.

A learner who follows the original starter instructions ("leave
OPENAI_BASE_URL blank") used to end up with `base_url=""` passed to
the OpenAI SDK, which silently broke API calls. The config-layer
validator now coerces empty / whitespace-only values to None so the
SDK falls back to its built-in default. These tests pin that
behavior.
"""

from src.config import Settings


def test_empty_base_url_is_coerced_to_none():
    assert Settings(openai_base_url="").openai_base_url is None


def test_whitespace_base_url_is_coerced_to_none():
    assert Settings(openai_base_url="   ").openai_base_url is None


def test_vocareum_base_url_is_preserved():
    url = "https://openai.vocareum.com/v1"
    assert Settings(openai_base_url=url).openai_base_url == url
