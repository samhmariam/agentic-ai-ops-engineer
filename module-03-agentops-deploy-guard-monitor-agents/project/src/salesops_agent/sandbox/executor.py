"""Sandbox executor (parent side) for the run_analysis tool.

Validates code against the sandbox policy, then runs it in an isolated child
process (sandbox/runner.py) with only the approved CRM datasets. See
policies/sandbox_v1.yaml for the full list of constraints.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from salesops_agent.data import CRMData
from salesops_agent.logging_utils import LOGGER_NAME, log_event
from salesops_agent.sandbox.validator import SandboxRejected, validate

RUNNER = Path(__file__).with_name("runner.py")
APPROVED_DATASETS = {"accounts", "opportunities", "activities", "support_tickets", "product_usage", "contacts"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Limits(_Strict):
    timeout_s: float = Field(gt=0, le=60)
    cpu_s: int = Field(gt=0, le=60)
    memory_mb: int = Field(ge=64, le=4096)
    max_code_chars: int = Field(ge=100)
    max_result_chars: int = Field(ge=100)
    max_stdout_chars: int = Field(ge=0)


class SandboxPolicy(_Strict):
    version: str = Field(pattern=r"^v\d+$")
    limits: Limits
    allowed_modules: List[str]
    allowed_builtins: List[str]
    forbidden_names: List[str]
    forbidden_attribute_prefixes: List[str]
    forbidden_attributes: List[str]
    reference_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    datasets: Dict[str, List[str]]

    @model_validator(mode="after")
    def safe_by_construction(self) -> "SandboxPolicy":
        unknown = set(self.datasets) - APPROVED_DATASETS
        if unknown:   # internal HR/financial data can never be configured as input
            raise ValueError(f"datasets not approved for the sandbox: {sorted(unknown)}")
        dangerous = {"eval", "exec", "compile", "open", "__import__", "getattr", "globals", "vars", "input"}
        if dangerous & set(self.allowed_builtins):
            raise ValueError(f"builtins that may never be allowed: {sorted(dangerous & set(self.allowed_builtins))}")
        unsafe_modules = {"os", "sys", "subprocess", "socket", "shutil", "pathlib", "io", "importlib",
                          "ctypes", "builtins", "pickle", "marshal", "urllib", "http", "ssl", "multiprocessing",
                          "threading", "inspect", "gc"}
        if unsafe_modules & set(self.allowed_modules):
            raise ValueError(f"modules that may never be allowed: {sorted(unsafe_modules & set(self.allowed_modules))}")
        return self


def _posix_limits(cpu_s: int, memory_mb: int):   # pragma: no cover - not available on Windows
    import resource

    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

    return apply


class Sandbox:
    def __init__(self, policy: SandboxPolicy, sha256: str, crm: CRMData):
        self.policy = policy
        self.sha256 = sha256
        self.data = self._approved_data(crm)
        self._data_json = json.dumps(self.data)

    @classmethod
    def from_file(cls, path: Path, crm: CRMData) -> "Sandbox":
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        policy = SandboxPolicy.model_validate(yaml.safe_load(text))
        return cls(policy, hashlib.sha256(text.encode("utf-8")).hexdigest(), crm)

    def _approved_data(self, crm: CRMData) -> Dict[str, List[Dict[str, Any]]]:
        """Copy only approved datasets/fields. HR and financial data are never read."""
        out = {}
        for name, fields in self.policy.datasets.items():
            records = getattr(crm, name)
            out[name] = [dict(r) if fields == ["*"] else {f: r.get(f) for f in fields} for r in records]
        return out

    def describe(self) -> Dict[str, Any]:
        return {"enabled": True, "policy_version": self.policy.version, "policy_sha256": self.sha256,
                "datasets": sorted(self.data), "timeout_s": self.policy.limits.timeout_s}

    def schema_hint(self) -> str:
        """Dataset field names, for the tool description the model sees."""
        parts = []
        for name, records in self.data.items():
            fields = list(records[0]) if records else []
            parts.append(f"{name}({', '.join(fields)})")
        return "; ".join(parts)

    # -- execution ----------------------------------------------------------

    def _env(self) -> Dict[str, str]:
        """Minimal environment: no API keys, proxies or Python path settings leak in."""
        env = {"PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        for key in ("SYSTEMROOT", "WINDIR"):   # required for Python to start on Windows
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def run(self, code: str) -> Dict[str, Any]:
        """Execute code; always returns a dict with status ok/error, never raises."""
        started = time.perf_counter()
        outcome = self._run(code)
        outcome["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        outcome["sandbox_policy"] = self.policy.version
        log_event(logging.getLogger(LOGGER_NAME), "sandbox_execution",
                  level=logging.INFO if outcome["status"] == "ok" else logging.WARNING,
                  status=outcome["status"], error_type=outcome.get("error_type"),
                  duration_ms=outcome["duration_ms"], code_chars=len(code))
        return outcome

    def _run(self, code: str) -> Dict[str, Any]:
        p = self.policy
        try:
            validate(code, allowed_modules=p.allowed_modules, forbidden_names=p.forbidden_names,
                     forbidden_attribute_prefixes=p.forbidden_attribute_prefixes,
                     forbidden_attributes=p.forbidden_attributes, max_code_chars=p.limits.max_code_chars)
        except SandboxRejected as exc:
            return {"status": "error", "error_type": "rejected", "message": str(exc)}

        request = json.dumps({"code": code, "reference_date": p.reference_date,
                              "policy": p.model_dump()})[:-1] + f', "data": {self._data_json}}}'
        kwargs: Dict[str, Any] = {}
        if os.name == "posix":   # pragma: no cover
            kwargs["preexec_fn"] = _posix_limits(p.limits.cpu_s, p.limits.memory_mb)
        with tempfile.TemporaryDirectory(prefix="salesops_sandbox_") as workdir:
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-S", "-B", str(RUNNER)],
                    input=request, capture_output=True, text=True, encoding="utf-8",
                    cwd=workdir, env=self._env(), timeout=p.limits.timeout_s, **kwargs,
                )
            except subprocess.TimeoutExpired:
                return {"status": "error", "error_type": "timeout",
                        "message": f"analysis exceeded the {p.limits.timeout_s}s time limit and was stopped"}

        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        if proc.returncode != 0 or not lines:
            reason = (proc.stderr.strip().splitlines() or ["no output"])[-1][:300]
            return {"status": "error", "error_type": "crashed", "message": f"sandbox process failed: {reason}"}
        response = json.loads(lines[-1])
        if not response["ok"]:
            return {"status": "error", "error_type": response["error_type"], "message": response["message"]}

        result_json = json.dumps(response["result"])
        if len(result_json) > p.limits.max_result_chars:
            return {"status": "error", "error_type": "output_too_large",
                    "message": f"result is {len(result_json)} characters; the limit is "
                               f"{p.limits.max_result_chars}. Aggregate further (counts, top-N)."}
        return {"status": "ok", "result": response["result"], "stdout": response["stdout"]}


def load_sandbox(cfg: dict[str, Any], crm: CRMData) -> Optional[Sandbox]:
    section = cfg.get("sandbox")
    if not section or not section.get("enabled", True):
        return None
    return Sandbox.from_file(section["policy"], crm)
