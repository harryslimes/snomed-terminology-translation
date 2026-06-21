"""A tiny, safe arithmetic evaluator for flow *score* formulas.

A formula node lets a user combine the metric vectors that upstream evaluate
nodes emit into a single comparable scalar — e.g.::

    0.7 * eval_think.composite_score + 0.3 * eval_nothink.mean_chrf / 100

without writing or editing any Python. We parse the expression with :mod:`ast`
and walk the tree ourselves, allowing only a whitelist of operators, a few
numeric helper functions, numeric literals, and *variable lookups* (bare names
like ``composite_score`` or dotted names like ``eval_think.composite_score``).
Anything else — attribute access on objects, function calls to non-whitelisted
names, comprehensions, lambdas, indexing — raises :class:`FormulaError`.

Variables are supplied as a flat dict keyed by the dotted string
(``"eval_think.composite_score"``) and, for convenience, the bare metric name
(``"composite_score"``). Names are case-sensitive.
"""
from __future__ import annotations

import ast
import operator
from typing import Mapping


class FormulaError(Exception):
    """Raised for a malformed or disallowed formula, or an unknown variable."""


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
# Pure, total numeric helpers only — no I/O, no attribute tricks.
_FUNCS = {"min": min, "max": max, "abs": abs, "round": round}


def _dotted_name(node: ast.AST) -> str | None:
    """The dotted variable string for a ``Name``/``Attribute`` chain
    (``a.b.c``), or ``None`` if the node isn't a plain name chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _eval(node: ast.AST, variables: Mapping[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError(f"only numeric literals are allowed, got {node.value!r}")
        return float(node.value)
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = _dotted_name(node)
        if name is None:
            raise FormulaError("unsupported attribute access")
        if name not in variables:
            raise FormulaError(f"unknown variable {name!r}")
        return float(variables[name])
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left, variables),
                                      _eval(node.right, variables))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval(node.operand, variables))
    if isinstance(node, ast.Call):
        fname = node.func.id if isinstance(node.func, ast.Name) else None
        if fname not in _FUNCS:
            raise FormulaError(f"unsupported function call {fname!r}; "
                               f"allowed: {sorted(_FUNCS)}")
        if node.keywords:
            raise FormulaError("keyword arguments are not allowed")
        return float(_FUNCS[fname](*[_eval(a, variables) for a in node.args]))
    raise FormulaError(f"unsupported expression element: {type(node).__name__}")


def compile_formula(expression: str) -> ast.Expression:
    """Parse + validate the *shape* of a formula (operators, calls, literals)
    without evaluating it — variable names are NOT checked here, so this works
    at preview time before any metrics exist. Raises :class:`FormulaError`."""
    if not expression or not expression.strip():
        raise FormulaError("empty formula")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"syntax error: {exc.msg}") from exc

    # Walk once to reject disallowed node kinds early (clear error messages,
    # and defence-in-depth on top of _eval's per-node checks).
    for sub in ast.walk(tree):
        if isinstance(sub, (ast.Expression, ast.BinOp, ast.UnaryOp,
                            ast.Constant, ast.Name, ast.Attribute, ast.Load,
                            ast.Call)):
            continue
        if isinstance(sub, tuple(_BINOPS)) or isinstance(sub, tuple(_UNARYOPS)):
            continue
        raise FormulaError(f"disallowed syntax: {type(sub).__name__}")
    return tree


def formula_names(expression: str) -> set[str]:
    """The variable names a formula references (dotted form)."""
    tree = compile_formula(expression)
    names: set[str] = set()
    for sub in ast.walk(tree):
        # Only collect the *outermost* name of each chain (an Attribute whose
        # parent is also an Attribute is covered by its parent).
        if isinstance(sub, ast.Attribute) and _dotted_name(sub):
            names.add(_dotted_name(sub))
        elif isinstance(sub, ast.Name):
            names.add(sub.id)
    # Drop the function names (min/max/...) and partial chains shadowed by a
    # longer dotted name they're a prefix of.
    names -= set(_FUNCS)
    return {n for n in names if not any(o != n and o.startswith(n + ".")
                                        for o in names)}


def eval_formula(expression: str, variables: Mapping[str, float]) -> float:
    """Evaluate ``expression`` against ``variables`` -> float.

    Raises :class:`FormulaError` on bad syntax, a disallowed construct, an
    unknown variable, or a math error (e.g. division by zero)."""
    tree = compile_formula(expression)
    try:
        return float(_eval(tree, variables))
    except FormulaError:
        raise
    except ZeroDivisionError as exc:
        raise FormulaError("division by zero") from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise FormulaError(f"math error: {exc}") from exc
