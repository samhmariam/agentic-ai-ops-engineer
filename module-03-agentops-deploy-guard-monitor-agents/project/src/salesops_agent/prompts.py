"""Versioned system prompts.

Prompts live as Markdown files under prompts/ and are listed in prompts/registry.yaml
with a version id, description and SHA-256 of their content. config.yaml selects the
active version. Loading verifies the hash, so editing a released prompt in place
fails loudly: a prompt change must ship as a new version (system_prompt_v2.md + a
new registry entry), which keeps evaluation results attributable to exact prompt text.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Prompt:
    version: str
    text: str
    sha256: str
    path: Path


def prompt_hash(text: str) -> str:
    """SHA-256 of prompt text with normalized line endings (stable across checkouts)."""
    normalized = text.replace("\r\n", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_registry(registry_path: Path) -> dict[str, Any]:
    with registry_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)["prompts"]


def load_system_prompt(cfg: dict[str, Any]) -> Prompt:
    registry_path = cfg["prompt"]["registry"]
    version = cfg["prompt"]["version"]
    registry = load_registry(registry_path)
    if version not in registry:
        raise ValueError(f"Prompt version {version!r} not in {registry_path}; known: {sorted(registry)}")

    entry = registry[version]
    path = registry_path.parent / entry["file"]
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    if not text:
        raise ValueError(f"System prompt file is empty: {path}")

    digest = prompt_hash(text)
    if digest != entry["sha256"]:
        raise ValueError(
            f"Prompt {version} ({path.name}) does not match its registered sha256. "
            "Released prompts are immutable: add a new version instead of editing this one."
        )
    return Prompt(version=version, text=text, sha256=digest, path=path)
