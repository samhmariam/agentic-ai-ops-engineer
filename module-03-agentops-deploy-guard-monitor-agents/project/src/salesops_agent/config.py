"""Configuration loading and validation.

config.yaml is the single source of truth for model, prompt version, enabled tools
and file locations. It is validated against `AppConfig` (schema_version 1) on load,
so a typo or missing key fails at startup instead of mid-run. Every entry under
`paths` is resolved relative to the config file, so commands behave the same from
any working directory. The loaded dict also carries the config file's SHA-256 so
runs can be traced back to the exact configuration that produced them.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
CONFIG_SCHEMA_VERSION = 1


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSection(_Section):
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


class ModelSection(_Section):
    name: str = Field(pattern=r"^[a-z_-]+:.+$", description="provider:model for init_chat_model")
    temperature: float = Field(ge=0.0, le=2.0)


class PromptSection(_Section):
    registry: Path
    version: str = Field(pattern=r"^v\d+$")


class ToolsSection(_Section):
    enabled: List[str] = Field(min_length=1)

    @field_validator("enabled")
    @classmethod
    def no_duplicates(cls, value: List[str]) -> List[str]:
        if len(value) != len(set(value)):
            raise ValueError("tools.enabled contains duplicates")
        return value


class PathsSection(_Section):
    data_dir: Path
    email_outbox: Path
    logs_dir: Path
    traces_dir: Path
    reports_dir: Path
    eval_cases: Path


class LoggingSection(_Section):
    file: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class TracingSection(_Section):
    enabled: bool = True
    max_payload_chars: int = Field(default=2000, ge=100)


class Price(_Section):
    input: float = Field(ge=0.0)
    output: float = Field(ge=0.0)


class AppConfig(_Section):
    schema_version: Literal[1]
    agent: AgentSection
    model: ModelSection
    prompt: PromptSection
    tools: ToolsSection
    paths: PathsSection
    logging: LoggingSection
    tracing: TracingSection = TracingSection()
    pricing: Dict[str, Price] = {}


class ConfigError(ValueError):
    pass


def config_hash(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load, validate and resolve config.yaml. Returns a plain dict."""
    path = Path(config_path or DEFAULT_CONFIG_PATH).resolve()
    text = path.read_text(encoding="utf-8")
    try:
        model = AppConfig.model_validate(yaml.safe_load(text))
    except ValidationError as exc:
        raise ConfigError(f"Invalid config {path}:\n{exc}") from exc

    cfg = model.model_dump()
    base = path.parent
    cfg["config_path"] = str(path)
    cfg["config_sha256"] = config_hash(text)
    cfg["paths"] = {key: base / value for key, value in cfg["paths"].items()}
    cfg["prompt"]["registry"] = base / cfg["prompt"]["registry"]

    if not cfg["paths"]["data_dir"].is_dir():
        raise ConfigError(f"paths.data_dir does not exist: {cfg['paths']['data_dir']}")
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
