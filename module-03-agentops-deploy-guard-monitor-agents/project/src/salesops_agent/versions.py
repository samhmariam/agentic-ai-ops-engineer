"""Version manifest.

One dict that pins everything that determines agent behaviour: agent version,
config schema + content hash, prompt version + hash, data schema version, model,
per-tool versions and the git commit. It is attached to every log line's
`run_started` event, every trace file and every evaluation result, so any output
can be traced back to the exact code, prompt and configuration that produced it.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Optional

from salesops_agent.config import CONFIG_SCHEMA_VERSION, PROJECT_ROOT
from salesops_agent.prompts import Prompt
from salesops_agent.schemas import DATA_SCHEMA_VERSION

# Paths whose uncommitted changes would make a run irreproducible from its commit.
_VERSIONED_PATHS = ["src", "prompts", "policies", "config.yaml", "configs", "evaluation", "pyproject.toml", "uv.lock"]


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def git_revision() -> Dict[str, Any]:
    commit = _git("rev-parse", "--short", "HEAD")
    if commit is None:
        return {"commit": None, "dirty": None}
    status = _git("status", "--porcelain", "--untracked-files=no", "--", *_VERSIONED_PATHS)
    return {"commit": commit, "dirty": bool(status)}


def build_manifest(
    cfg: dict[str, Any], prompt: Prompt, tool_versions: Dict[str, str], guardrails: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "experiment": cfg["experiment"]["name"],
        "agent_version": cfg["agent"]["version"],
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "config_sha256": cfg["config_sha256"],
        "prompt_version": prompt.version,
        "prompt_sha256": prompt.sha256,
        "data_schema_version": DATA_SCHEMA_VERSION,
        "model": cfg["model"]["name"],
        "temperature": cfg["model"]["temperature"],
        "tools": tool_versions,
        "guardrails": guardrails,
        "git": git_revision(),
    }


def short_manifest(manifest: Dict[str, Any]) -> List[str]:
    """Compact human-readable lines for CLI output and reports."""
    git = manifest["git"]
    git_text = f"{git['commit']}{' (uncommitted changes)' if git['dirty'] else ''}" if git["commit"] else "n/a"
    return [
        f"experiment {manifest.get('experiment', 'n/a')}",
        f"agent {manifest['agent_version']}",
        f"prompt {manifest['prompt_version']} ({manifest['prompt_sha256'][:12]})",
        f"config schema v{manifest['config_schema_version']} ({manifest['config_sha256'][:12]})",
        f"data schema {manifest['data_schema_version']}",
        f"model {manifest['model']} (temperature {manifest['temperature']})",
        "tools " + ", ".join(f"{name}@{ver}" for name, ver in manifest["tools"].items()),
        "input guardrail " + _guard_text(manifest.get("guardrails", {}).get("input")),
        "tool guardrail " + _guard_text(manifest.get("guardrails", {}).get("tool")),
        "output guardrail " + _guard_text(manifest.get("guardrails", {}).get("output")),
        f"git {git_text}",
    ]


def _guard_text(guard: Optional[Dict[str, Any]]) -> str:
    if not guard:
        return "n/a"
    if not guard.get("enabled"):
        return "disabled"
    detail = f"{guard['rules']} rules" if "rules" in guard else guard.get("policy", "")
    return f"policy {guard['policy_version']} ({guard['policy_sha256'][:12]}, {detail})"
