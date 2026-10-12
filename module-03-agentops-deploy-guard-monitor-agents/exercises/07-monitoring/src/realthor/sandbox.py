import ast
import threading
import io
import math

import pandas as pd

BLOCKED_IMPORTS = {
    "os", "sys", "subprocess", "socket", "requests", "urllib",
    "shutil", "pathlib", "glob", "tempfile", "pickle",
}

BLOCKED_BUILTINS = {
    "open", "eval", "exec", "__import__", "compile",
    "breakpoint", "input",
}


def validate_code(code: str) -> tuple[bool, str]:
    """AST pass: block dangerous imports and builtins. Returns (is_safe, reason)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BLOCKED_IMPORTS:
                    return False, f"blocked import: {alias.name}"

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root in BLOCKED_IMPORTS:
                return False, f"blocked import: {module}"

        elif isinstance(node, ast.Call):
            func_name: str | None = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name in BLOCKED_BUILTINS:
                return False, f"blocked call: {func_name}"

    return True, ""


def run_sandboxed(
    code: str,
    dataframes: dict[str, pd.DataFrame],
    timeout: int = 30,
) -> tuple[str, str]:
    """Execute code in restricted globals with timeout.

    Returns (stdout, error). DataFrames are injected directly — no imports needed.
    __builtins__ is empty so open/eval/exec are unavailable at runtime.
    """
    buf = io.StringIO()

    safe_globals: dict = {
        "__builtins__": {},
        "pd": pd,
        "math": math,
        "print": lambda *args, **kwargs: buf.write(
            " ".join(str(a) for a in args) + "\n"
        ),
        **dataframes,
    }

    errors: list[str] = []

    def _exec() -> None:
        try:
            exec(code, safe_globals)  # noqa: S102
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    # Daemon thread so a runaway loop (e.g. `while True: pass`) can't block
    # interpreter exit. On timeout we abandon it instead of joining forever.
    thread = threading.Thread(target=_exec, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return "", "execution timed out"
    if errors:
        return "", errors[0]
    return buf.getvalue().strip(), ""
