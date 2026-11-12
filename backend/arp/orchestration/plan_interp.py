"""Tree-walking interpreter for checked plan scripts. Never calls `exec` or `eval`.

`run_script` drives any set of step functions (real adapters, or test stubs). `dry_run` drives
placeholders: their per-company values are `Unknown`, a branch on an unknown takes its true path once,
and every step call inside it records `depends_on` = the step whose result it read.
"""
from __future__ import annotations

import ast
import builtins
from collections.abc import Callable
from typing import Any

from arp.errors import ClientInputError, NotConfigured
from arp.orchestration.plan_api import BUILTINS, STEPS
from arp.orchestration.plan_check import check_script, placeholder

MAX_STEPS = 500
MAX_OPS = 100_000  # statements and loop iterations: bounds scripts that never call a step
MAX_RANGE = 10_000


class StepLimitExceeded(NotConfigured):
    pass


class PlanScriptError(ClientInputError):
    pass


class Unknown:
    """A value only the real run will know; `seq` is the step it comes from."""

    def __init__(self, seq: int):
        self.seq = seq

    def __repr__(self) -> str:
        return f"<from step {self.seq}>"


_CMP = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
        ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
        ast.Is: lambda a, b: a is b, ast.IsNot: lambda a, b: a is not b}


class _Interp:
    def __init__(self, steps: dict[str, Callable[..., Any]], previous: list[dict] | None, first_seq: int):
        self.steps = steps
        self.env: dict[str, Any] = {} if previous is None else {"previous": previous}
        self.first_seq = first_seq
        self.calls: list[dict] = []
        self.ops = 0
        self.deps: list[int] = []  # seqs of unknowns the current branch/loop depends on

    # statements
    def run(self, body: list[ast.stmt]) -> None:
        for stmt in body:
            self.tick()
            self.stmt(stmt)

    def tick(self) -> None:
        self.ops += 1
        if self.ops > MAX_OPS:
            raise PlanScriptError(f"operation limit {MAX_OPS} exceeded")

    def stmt(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Assign):
            value = self.expr(node.value)
            for target in node.targets:
                self.assign(target, value)
        elif isinstance(node, ast.Expr):
            self.expr(node.value)
        elif isinstance(node, ast.If):
            cond = self.expr(node.test)
            if isinstance(cond, Unknown):
                self.with_dep(cond.seq, node.body)
            else:
                self.run(node.body if cond else node.orelse)
        elif isinstance(node, ast.For):
            for item, dep in self.iterate(self.expr(node.iter)):
                self.assign(node.target, item)
                self.with_dep(dep, node.body) if dep else self.run(node.body)
        elif not isinstance(node, ast.Pass):
            raise PlanScriptError(f"line {node.lineno}: {type(node).__name__} not allowed")

    def with_dep(self, seq: int, body: list[ast.stmt]) -> None:
        self.deps.append(seq)
        try:
            self.run(body)
        finally:
            self.deps.pop()

    def assign(self, target: ast.expr, value: Any) -> None:
        if not isinstance(target, ast.Name):
            raise PlanScriptError(f"line {target.lineno}: only plain names can be assigned")
        self.env[target.id] = value

    def iterate(self, value: Any):
        if isinstance(value, Unknown):
            yield Unknown(value.seq), value.seq  # one representative pass
        else:
            for item in value:
                yield item, None

    # expressions
    def expr(self, node: ast.expr) -> Any:
        match node:
            case ast.Constant(value=v):
                return v
            case ast.Name(id=name):
                if name not in self.env:
                    raise PlanScriptError(f"line {node.lineno}: name {name} is not defined")
                return self.env[name]
            case ast.List(elts=elts) | ast.Tuple(elts=elts):
                return [self.expr(e) for e in elts]
            case ast.Dict(keys=keys, values=values):
                if None in keys:
                    raise PlanScriptError(f"line {node.lineno}: ** unpacking not allowed")
                return {self.expr(k): self.expr(v) for k, v in zip(keys, values, strict=True)}
            case ast.Attribute(value=obj, attr=attr):
                return self.field(self.expr(obj), attr, node.lineno)
            case ast.Subscript(value=obj, slice=key):
                obj, key = self.expr(obj), self.expr(key)
                return obj if isinstance(obj, Unknown) else obj[key]
            case ast.UnaryOp(op=ast.Not(), operand=x):
                v = self.expr(x)
                return v if isinstance(v, Unknown) else not v
            case ast.UnaryOp(op=ast.USub(), operand=x):
                v = self.expr(x)
                return v if isinstance(v, Unknown) else -v
            case ast.BoolOp(op=op, values=values):
                return self.boolop(op, values)
            case ast.Compare(left=left, ops=ops, comparators=rights):
                return self.compare(left, ops, rights)
            case ast.ListComp(elt=elt, generators=[gen]):
                return self.listcomp(elt, gen)
            case ast.Call():
                return self.call(node)
        raise PlanScriptError(f"line {node.lineno}: {type(node).__name__} not allowed")

    def field(self, obj: Any, attr: str, line: int) -> Any:
        if isinstance(obj, Unknown):
            return Unknown(obj.seq)
        if isinstance(obj, dict) and attr in obj:
            return obj[attr]
        raise PlanScriptError(f"line {line}: no field {attr}")

    def boolop(self, op: ast.boolop, values: list[ast.expr]) -> Any:
        result: Any = None
        for v in values:
            result = self.expr(v)
            if isinstance(result, Unknown):
                return result
            if isinstance(op, ast.And) and not result or isinstance(op, ast.Or) and result:
                return result
        return result

    def compare(self, left: ast.expr, ops: list[ast.cmpop], rights: list[ast.expr]) -> Any:
        a = self.expr(left)
        for op, right in zip(ops, rights, strict=True):
            b = self.expr(right)
            if isinstance(a, Unknown) or isinstance(b, Unknown):
                return a if isinstance(a, Unknown) else b
            if not _CMP[type(op)](a, b):
                return False
            a = b
        return True

    def listcomp(self, elt: ast.expr, gen: ast.comprehension) -> Any:
        out = []
        for item, dep in self.iterate(self.expr(gen.iter)):
            self.tick()
            self.assign(gen.target, item)
            conds = [self.expr(c) for c in gen.ifs]
            unknown = dep or next((c.seq for c in conds if isinstance(c, Unknown)), None)
            if unknown:
                return Unknown(unknown)
            if all(conds):
                out.append(self.expr(elt))
        return out

    def call(self, node: ast.Call) -> Any:
        name = node.func.id  # the checker allows only plain-name calls
        args = [self.expr(a) for a in node.args]
        kwargs = {k.arg: self.expr(k.value) for k in node.keywords}
        if name in BUILTINS:
            if any(isinstance(a, Unknown) for a in args):
                return next(a for a in args if isinstance(a, Unknown))
            if name == "range" and len(range(*args)) > MAX_RANGE:
                raise PlanScriptError(f"line {node.lineno}: range longer than {MAX_RANGE}")
            return getattr(builtins, name)(*args, **kwargs)
        if len(self.calls) >= MAX_STEPS:
            raise StepLimitExceeded(f"step limit {MAX_STEPS} exceeded")
        seq = self.first_seq + len(self.calls)
        found = [v.seq for v in _flatten(kwargs.values()) if isinstance(v, Unknown)]
        depends_on = (self.deps[-1] if self.deps else None) or (found[0] if found else None)
        model = STEPS[name]
        # A value only the real run knows is checked by type here and for real when the step runs.
        model.model_validate({k: placeholder(model, k) if isinstance(v, Unknown) else _jsonable(v)
                              for k, v in kwargs.items()})
        params = {k: ([repr(v)] if isinstance(placeholder(model, k), list) else repr(v)) if isinstance(v, Unknown)
                  else _jsonable(v) for k, v in kwargs.items()}
        self.calls.append({"seq": seq, "kind": name, "params": params, "depends_on": depends_on})
        return self.steps[name](seq=seq, **params)


def _flatten(values):
    for v in values:
        if isinstance(v, list):
            yield from _flatten(v)
        else:
            yield v


def _jsonable(value: Any) -> Any:
    if isinstance(value, Unknown):
        return repr(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def run_script(source: str, steps: dict[str, Callable[..., Any]], previous: list[dict] | None = None,
               first_seq: int = 1) -> list[dict]:
    """Check, then run `source` against `steps`; returns the recorded calls in order. A re-planned script also
    sees `previous` (the finished steps' results) and numbers its calls from `first_seq`."""
    errors = check_script(source)
    if errors:
        raise PlanScriptError("\n".join(errors))
    interp = _Interp(steps, previous, first_seq)
    interp.run(ast.parse(source).body)
    return interp.calls


def _placeholder(kind: str) -> Callable[..., Any]:
    def step(*, seq: int, **_: Any) -> dict:
        return {"id": f"{kind}_{seq}", "run_id": f"{kind}_{seq}", "companies": Unknown(seq)}
    return step


def dry_run(source: str, previous: list[dict] | None = None, first_seq: int = 1) -> list[dict]:
    """The calls a script will make, without reading the database or starting any run."""
    return run_script(source, {kind: _placeholder(kind) for kind in STEPS}, previous, first_seq)
