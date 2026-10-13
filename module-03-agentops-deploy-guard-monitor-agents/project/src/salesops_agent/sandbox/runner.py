"""Sandbox runner: executed as a separate process (`python -I -S -B runner.py`).

Reads one JSON request on stdin, writes one JSON response line on stdout. Standard
library only, and it never imports the salesops_agent package: the child process
sees nothing but the request it is given.

Request:  {"code", "data", "reference_date", "policy": {...}}
Response: {"ok": true, "result": ..., "stdout": "..."}
       or {"ok": false, "error_type": "rejected|runtime|output", "message": "..."}
"""

import builtins
import importlib
import importlib.util
import io
import json
import socket
import sys
import types
from pathlib import Path


def _blocked(*_args, **_kwargs):
    raise PermissionError("network access is disabled in the sandbox")


def _disable_network() -> None:
    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "socketpair", "fromfd"):
        if hasattr(socket, name):
            setattr(socket, name, _blocked)


def _load_validator():
    spec = importlib.util.spec_from_file_location("sandbox_validator", Path(__file__).with_name("validator.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_proxy(module: types.ModuleType) -> types.SimpleNamespace:
    """Public, non-module attributes only: `statistics.sys`, `json.decoder` etc. vanish."""
    public = {
        name: value for name, value in vars(module).items()
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    }
    return types.SimpleNamespace(**public)


def _safe_import(allowed):
    proxies = {}

    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if level or root not in allowed:
            raise ImportError(f"import of '{name}' is not allowed in the sandbox")
        if root not in proxies:
            proxies[root] = _module_proxy(importlib.import_module(root))
        return proxies[root]

    return importer


def _jsonable(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    return str(value)


def main() -> None:
    real_stdout = sys.stdout
    request = json.loads(sys.stdin.read())
    policy = request["policy"]

    def respond(payload) -> None:
        real_stdout.write(json.dumps(payload, default=_jsonable) + "\n")
        real_stdout.flush()

    validator = _load_validator()
    try:   # validated again here, independently of the parent process
        validator.validate(
            request["code"],
            allowed_modules=policy["allowed_modules"],
            forbidden_names=policy["forbidden_names"],
            forbidden_attribute_prefixes=policy["forbidden_attribute_prefixes"],
            forbidden_attributes=policy["forbidden_attributes"],
            max_code_chars=policy["limits"]["max_code_chars"],
        )
    except validator.SandboxRejected as exc:
        respond({"ok": False, "error_type": "rejected", "message": str(exc)})
        return

    _disable_network()
    captured = io.StringIO()
    safe_builtins = {name: getattr(builtins, name) for name in policy["allowed_builtins"] if hasattr(builtins, name)}
    safe_builtins["print"] = lambda *args, **kwargs: print(*args, file=captured, **{k: v for k, v in kwargs.items() if k in ("sep", "end")})
    safe_builtins["__import__"] = _safe_import(set(policy["allowed_modules"]))
    env = {
        "__builtins__": safe_builtins,
        "__name__": "sandbox",
        "data": request["data"],
        "REFERENCE_DATE": request["reference_date"],
        "result": None,
    }
    try:
        exec(compile(request["code"], "<analysis>", "exec"), env)   # validated code, restricted globals
    except Exception as exc:   # report the analysis error to the agent; never crash the parent
        respond({"ok": False, "error_type": "runtime", "message": f"{type(exc).__name__}: {exc}"})
        return

    stdout = captured.getvalue()
    limit = policy["limits"]["max_stdout_chars"]
    if len(stdout) > limit:
        stdout = stdout[:limit] + f"... [truncated {len(stdout) - limit} chars]"
    respond({"ok": True, "result": env.get("result"), "stdout": stdout})


if __name__ == "__main__":
    main()
