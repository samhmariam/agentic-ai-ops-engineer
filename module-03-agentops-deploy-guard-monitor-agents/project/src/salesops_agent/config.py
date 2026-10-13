"""Configuration loading and validation.

config.yaml is the baseline configuration. Experiment configs under configs/ name a
parent with `extends:` and override only what they change, so each experiment's
difference from the baseline is visible at a glance:

    extends: ../config.yaml
    experiment: {name: prompt-v2}
    prompt: {version: v2}
    tools:
      enabled:
        lookup_internal_hr_data: null   # null removes an inherited entry

Mappings merge recursively; lists and scalars replace. Relative paths are resolved
against the file that declares them. The merged result is validated against
`AppConfig` (schema_version 1), so a typo or missing key fails at startup instead
of mid-run, and its canonical SHA-256 is recorded with every run.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
CONFIG_SCHEMA_VERSION = 1
SEMVER = r"^\d+\.\d+\.\d+$"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSection(_Section):
    name: str
    version: str = Field(pattern=SEMVER)


class ExperimentSection(_Section):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str = ""


class ModelSection(_Section):
    name: str = Field(pattern=r"^[a-z_-]+:.+$", description="provider:model for init_chat_model")
    temperature: float = Field(ge=0.0, le=2.0)
    timeout_s: float = Field(default=30.0, gt=0, description="per-request timeout; a stalled call fails fast")
    max_retries: int = Field(default=2, ge=0, le=10, description="client retries after timeouts/429/5xx")


class PromptSection(_Section):
    registry: Path
    version: str = Field(pattern=r"^v\d+$")


class ToolsSection(_Section):
    enabled: Dict[str, str] = Field(min_length=1, description="tool name -> pinned tool version")

    @field_validator("enabled")
    @classmethod
    def versions_are_semver(cls, value: Dict[str, str]) -> Dict[str, str]:
        bad = {name: ver for name, ver in value.items() if not re.match(SEMVER, str(ver))}
        if bad:
            raise ValueError(f"tool versions must be MAJOR.MINOR.PATCH: {bad}")
        return value


class PathsSection(_Section):
    data_dir: Path
    email_outbox: Path
    logs_dir: Path
    traces_dir: Path
    reports_dir: Path
    eval_cases: Path
    review_queue: Path          # responses withheld by the output guardrail for human review


class LoggingSection(_Section):
    file: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class TracingSection(_Section):
    enabled: bool = True
    max_payload_chars: int = Field(default=2000, ge=100)


class InputGuardrailSection(_Section):
    enabled: bool
    policy: Path


class ToolGuardrailSection(_Section):
    enabled: bool
    policy: Path


class OutputGuardrailSection(_Section):
    enabled: bool
    policy: Path


class GuardrailsSection(_Section):
    input: InputGuardrailSection
    tool: ToolGuardrailSection
    output: OutputGuardrailSection


class SandboxSection(_Section):
    enabled: bool = True
    policy: Path


class Price(_Section):
    input: float = Field(ge=0.0)
    output: float = Field(ge=0.0)


class AppConfig(_Section):
    schema_version: Literal[1]
    experiment: ExperimentSection
    agent: AgentSection
    model: ModelSection
    prompt: PromptSection
    tools: ToolsSection
    paths: PathsSection
    guardrails: GuardrailsSection
    sandbox: SandboxSection
    logging: LoggingSection
    tracing: TracingSection = TracingSection()
    pricing: Dict[str, Price] = {}


class ConfigError(ValueError):
    pass


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overlay into a copy of base. Dicts merge, None deletes, others replace."""
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


# File references outside `paths` that are resolved relative to the declaring file.
_PATH_FIELDS = [
    ("prompt", "registry"),
    ("guardrails", "input", "policy"),
    ("guardrails", "tool", "policy"),
    ("guardrails", "output", "policy"),
    ("sandbox", "policy"),
]


def _resolve_relative_paths(raw: Dict[str, Any], base_dir: Path) -> None:
    for key, value in (raw.get("paths") or {}).items():
        if value is not None:
            raw["paths"][key] = str(base_dir / value)
    for *parents, leaf in _PATH_FIELDS:
        section = raw
        for key in parents:
            section = section.get(key) if isinstance(section, dict) else None
        if isinstance(section, dict) and section.get(leaf) is not None:
            section[leaf] = str(base_dir / section[leaf])


def _load_raw(path: Path, chain: List[Path]) -> Dict[str, Any]:
    if path in chain:
        raise ConfigError(f"Circular extends: {' -> '.join(map(str, chain + [path]))}")
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    chain.append(path)
    _resolve_relative_paths(raw, path.parent)
    parent = raw.pop("extends", None)
    if parent is None:
        return raw
    return deep_merge(_load_raw((path.parent / parent).resolve(), chain), raw)


def _portable(value: Any) -> Any:
    """Paths inside the project become project-relative, so hashes match across machines."""
    if isinstance(value, dict):
        return {k: _portable(v) for k, v in value.items()}
    if isinstance(value, Path):
        try:
            return value.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return value.as_posix()
    return value


def config_hash(validated: Dict[str, Any]) -> str:
    canonical = json.dumps(_portable(validated), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_config(config_path: Optional[str | Path] = None) -> dict[str, Any]:
    """Load, merge (`extends`), validate and resolve a config. Returns a plain dict."""
    path = Path(config_path or DEFAULT_CONFIG_PATH).resolve()
    chain: List[Path] = []
    raw = _load_raw(path, chain)
    try:
        cfg = AppConfig.model_validate(raw).model_dump()
    except ValidationError as exc:
        raise ConfigError(f"Invalid config {path}:\n{exc}") from exc

    cfg["config_sha256"] = config_hash(cfg)
    cfg["config_path"] = str(path)
    cfg["config_files"] = [str(p) for p in chain]
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
