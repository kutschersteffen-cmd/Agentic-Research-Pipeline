"""Syntax-tree checker for plan scripts: only a small, side-effect-free subset of Python passes."""
from __future__ import annotations

import ast

from pydantic import ValidationError

from arp.orchestration.plan_api import BUILTINS, STEPS

MAX_LINES = 200

_ALLOWED = (
    ast.Module, ast.Assign, ast.Expr, ast.For, ast.If, ast.Pass, ast.Compare, ast.BoolOp, ast.UnaryOp,
    ast.Name, ast.Constant, ast.List, ast.Dict, ast.Tuple, ast.ListComp, ast.comprehension, ast.Attribute,
    ast.Subscript, ast.Call, ast.keyword, ast.Load, ast.Store, ast.And, ast.Or, ast.Not, ast.USub,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
)
_ARITH = (ast.BinOp, ast.AugAssign, ast.operator)
_NAMED = {ast.Import: "import", ast.ImportFrom: "import", ast.FunctionDef: "def", ast.AsyncFunctionDef: "def",
          ast.ClassDef: "class", ast.Lambda: "lambda", ast.While: "while", ast.Try: "try", ast.With: "with",
          ast.Global: "global", ast.Nonlocal: "nonlocal"}


def check_script(source: str) -> list[str]:
    """Return error lines (`line N: ...`); an empty list means the script may run."""
    if len(source.splitlines()) > MAX_LINES:
        return [f"script exceeds {MAX_LINES} lines"]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"line {exc.lineno}: syntax error: {exc.msg}"]
    errors: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        where = f"line {line}: " if line else ""
        if isinstance(node, _ARITH):
            if not isinstance(node, ast.operator):
                errors.append(f"{where}arithmetic not allowed")
            continue
        if type(node) in _NAMED:
            errors.append(f"{where}{_NAMED[type(node)]} not allowed")
            continue
        if not isinstance(node, _ALLOWED):
            errors.append(f"{where}{type(node).__name__} not allowed")
            continue
        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
        if name and name.startswith("_"):
            errors.append(f"{where}name {name} not allowed")
        if isinstance(node, ast.Name) and node.id == "previous" and isinstance(node.ctx, ast.Store):
            errors.append(f"{where}name previous cannot be assigned")  # a re-planned plan's finished steps
        if isinstance(node, ast.Call):
            errors.extend(_check_call(node, where))
    return errors


def _check_call(node: ast.Call, where: str) -> list[str]:
    func = node.func.id if isinstance(node.func, ast.Name) else None
    if func in BUILTINS:
        return []
    if func not in STEPS:
        label = func or ast.unparse(node.func)
        return [f"{where}call to {label} not allowed"]
    if node.args:
        return [f"{where}{func}: use keyword arguments only"]
    model = STEPS[func]
    errors = [f"{where}{func}: unexpected argument {k.arg}" for k in node.keywords if k.arg not in model.model_fields]
    if errors:
        return errors
    # Validate literal arguments now; arguments read from other steps are checked when the step runs.
    literals = {k.arg: ast.literal_eval(k.value) for k in node.keywords if _is_literal(k.value)}
    dynamic = {k.arg for k in node.keywords} - literals.keys()
    try:
        model.model_validate({**{f: placeholder(model, f) for f in dynamic}, **literals})
    except ValidationError as exc:
        return [f"{where}{func}: {e['loc'][0] if e['loc'] else ''} {e['msg']}".rstrip() for e in exc.errors()]
    return []


def _is_literal(node: ast.expr) -> bool:
    try:
        ast.literal_eval(node)
    except Exception:  # noqa: BLE001 - literal_eval raises ValueError, TypeError, SyntaxError, RecursionError
        return False
    return True


def placeholder(model, field: str):
    """A value of the field's type, standing in for an argument only known at run time."""
    ann = str(model.model_fields[field].annotation)
    return ["x"] if "list" in ann else "x"
