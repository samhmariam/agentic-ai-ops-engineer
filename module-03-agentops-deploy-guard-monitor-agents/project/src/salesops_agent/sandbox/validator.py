"""Static validation of sandbox code. Standard library only: this module is also
loaded by the isolated runner process (python -I -S), which has no site-packages.
"""

from __future__ import annotations

import ast
from typing import Iterable, List

_ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Name, ast.Constant,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp,
    ast.GeneratorExp, ast.comprehension, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.IfExp, ast.Call, ast.keyword, ast.Attribute, ast.Subscript, ast.Slice, ast.Starred,
    ast.For, ast.While, ast.If, ast.Break, ast.Continue, ast.Pass, ast.FunctionDef,
    ast.Lambda, ast.Return, ast.arguments, ast.arg, ast.Import, ast.ImportFrom, ast.alias,
    ast.JoinedStr, ast.FormattedValue,
    ast.expr_context, ast.operator, ast.boolop, ast.cmpop, ast.unaryop,
)


class SandboxRejected(ValueError):
    """The code violates the sandbox policy; it was not executed."""


def validate(
    code: str,
    *,
    allowed_modules: Iterable[str],
    forbidden_names: Iterable[str],
    forbidden_attribute_prefixes: Iterable[str],
    forbidden_attributes: Iterable[str],
    max_code_chars: int,
) -> None:
    """Raise SandboxRejected listing every violation, or return if the code is allowed."""
    if len(code) > max_code_chars:
        raise SandboxRejected(f"code is {len(code)} characters; the limit is {max_code_chars}")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SandboxRejected(f"syntax error: {exc.msg} (line {exc.lineno})") from exc

    allowed = set(allowed_modules)
    names = set(forbidden_names)
    prefixes = tuple(forbidden_attribute_prefixes)
    attrs = set(forbidden_attributes)
    problems: List[str] = []

    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if not isinstance(node, _ALLOWED_NODES):
            problems.append(f"line {line}: {type(node).__name__} is not allowed")
            continue
        if isinstance(node, ast.Name) and (node.id in names or node.id.startswith("_")):
            problems.append(f"line {line}: name '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and (node.attr in attrs or node.attr.startswith(prefixes)):
            problems.append(f"line {line}: attribute '.{node.attr}' is not allowed")
        elif isinstance(node, (ast.FunctionDef, ast.Lambda, ast.arg)):
            name = getattr(node, "name", None) or getattr(node, "arg", None)
            if name and name.startswith("_"):
                problems.append(f"line {line}: name '{name}' is not allowed")
            if isinstance(node, ast.FunctionDef) and node.decorator_list:
                problems.append(f"line {line}: decorators are not allowed")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in allowed:
                    problems.append(f"line {line}: import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in allowed:
                problems.append(f"line {line}: import from '{node.module}' is not allowed")
            for alias in node.names:
                if alias.name == "*" or alias.name.startswith("_"):
                    problems.append(f"line {line}: 'from {node.module} import {alias.name}' is not allowed")
        if isinstance(node, ast.alias) and node.asname and node.asname.startswith("_"):
            problems.append(f"line {line}: alias '{node.asname}' is not allowed")

    if problems:
        raise SandboxRejected("; ".join(dict.fromkeys(problems)))
