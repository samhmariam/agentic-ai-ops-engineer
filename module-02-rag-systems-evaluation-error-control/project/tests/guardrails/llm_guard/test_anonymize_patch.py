"""Regression test for the ALL_SUPPORTED_LANGUAGES monkey-patch.

The patch lives at the top of `src.guardrails.llm_guard.input_guards`
and works around an llm-guard upstream bug
(https://github.com/protectai/llm-guard/issues/337):
``Anonymize.__init__`` ignores its ``language`` parameter and passes
the hardcoded ``["en", "zh"]`` into ``get_analyzer()``, which makes
Presidio auto-download ``zh_core_web_sm`` + ``spacy-pkuseg`` on first
init.

These tests fire if a future llm-guard release breaks the assumptions
the patch relies on, so the workaround can't silently stop working
when the dependency is bumped.
"""

import importlib

import spacy
import spacy.util


def test_patch_takes_effect_on_import() -> None:
    """After importing our module, the constant must be English-only."""
    import src.guardrails.llm_guard.input_guards  # noqa: F401  — import-only

    anonymize_mod = importlib.import_module("llm_guard.input_scanners.anonymize")
    assert anonymize_mod.ALL_SUPPORTED_LANGUAGES == ["en"], (
        "Monkey-patch in src.guardrails.llm_guard.input_guards no longer "
        "narrows ALL_SUPPORTED_LANGUAGES to English. Either the patch was "
        "removed or llm-guard restructured."
    )


def test_constant_path_still_resolves() -> None:
    """The dotted path the patch targets must still exist in llm-guard.

    If llm-guard renames the constant, moves it to another module, or
    converts it to a frozen tuple, the patch will silently stop
    working. Catch that explicitly.
    """
    anonymize_mod = importlib.import_module("llm_guard.input_scanners.anonymize")
    assert hasattr(anonymize_mod, "ALL_SUPPORTED_LANGUAGES"), (
        "llm-guard removed or renamed ALL_SUPPORTED_LANGUAGES. The patch "
        "in src.guardrails.llm_guard.input_guards needs to be re-targeted."
    )
    assert isinstance(anonymize_mod.ALL_SUPPORTED_LANGUAGES, list), (
        "ALL_SUPPORTED_LANGUAGES is no longer a mutable list; the patch "
        "via attribute assignment will silently fail to apply."
    )


def test_anonymize_init_does_not_install_zh_core_web_sm() -> None:
    """Constructing the live anonymize scanner must not trigger zh download.

    This is the behavioral guarantee we actually care about: the patch
    is supposed to stop Presidio's `_get_nlp_engine` from calling
    `spacy.cli.download("zh_core_web_sm")`. We verify by importing the
    module (which constructs `_anonymize_scanner` at module scope) and
    confirming the Chinese model is still not installed.
    """
    import src.guardrails.llm_guard.input_guards  # noqa: F401  — triggers init

    assert not spacy.util.is_package("zh_core_web_sm"), (
        "zh_core_web_sm was auto-installed during Anonymize init. The "
        "ALL_SUPPORTED_LANGUAGES patch is not preventing the download "
        "path in llm_guard.input_scanners.anonymize_helpers.analyzer."
        "_get_nlp_engine. Image build will pull the pkuseg C-compile dep."
    )
