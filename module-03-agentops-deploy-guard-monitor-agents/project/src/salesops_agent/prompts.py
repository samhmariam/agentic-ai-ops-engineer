"""Versioned system prompts.

Prompts live as Markdown files under prompts/ (system_prompt_v1.md, ...). config.yaml
selects which version is active, so changing a prompt is a reviewed file change, not
an edit buried in execution logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Prompt:
    version: str
    text: str


def load_system_prompt(cfg: dict[str, Any]) -> Prompt:
    path = cfg["prompt"]["path"]
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"System prompt file is empty: {path}")
    return Prompt(version=cfg["prompt"]["version"], text=text)
