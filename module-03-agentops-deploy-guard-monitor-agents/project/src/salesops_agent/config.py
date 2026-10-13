"""Configuration loading.

config.yaml is the single source of truth for model, prompt version, enabled tools
and file locations. Every entry under `paths` is resolved relative to the config
file, so commands behave the same from any working directory.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load config.yaml and resolve `paths` (and the prompt path) to absolute paths."""
    path = Path(config_path or DEFAULT_CONFIG_PATH).resolve()
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    base = path.parent
    cfg["config_path"] = str(path)
    cfg["paths"] = {key: base / value for key, value in cfg["paths"].items()}
    cfg["prompt"]["registry"] = base / cfg["prompt"]["registry"]
    return cfg


def with_overrides(cfg: dict[str, Any], **paths: Path) -> dict[str, Any]:
    """Return a copy of cfg with some `paths` entries replaced (e.g. eval outbox)."""
    new = copy.deepcopy(cfg)
    new["paths"].update(paths)
    return new


def ensure_output_dirs(cfg: dict[str, Any]) -> None:
    for key in ("logs_dir", "traces_dir", "reports_dir"):
        cfg["paths"][key].mkdir(parents=True, exist_ok=True)


def model_pricing(cfg: dict[str, Any]) -> dict[str, float]:
    """USD per 1M tokens for the configured model, or zeros if unpriced."""
    model_name = cfg["model"]["name"].split(":")[-1]
    return cfg.get("pricing", {}).get(model_name, {"input": 0.0, "output": 0.0})
