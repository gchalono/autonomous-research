"""Safe computation: an AST-validated expression evaluator.

Only arithmetic, comparisons and a small whitelist of math/statistics
functions are allowed. No attribute access, no imports, no function
definitions, no names other than whitelisted ones -- so an expression can
never touch the filesystem, network or interpreter state.

Arbitrary generated-code execution is intentionally NOT provided here. A
subprocess is not a sandbox; see config.Settings.allow_code_execution and
the README limitation note. If that flag is ever enabled, code execution
must be added as a separate, explicitly authorized tool.
"""
from __future__ import annotations

import ast
import math
import operator
import statistics

from ..security.permissions import Permission
from .base import Tool, ToolResult

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CMPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}
_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "sqrt": math.sqrt, "log": math.log, "exp": math.exp,
    "mean": statistics.mean, "median": statistics.median,
    "stdev": statistics.stdev, "pstdev": statistics.pstdev,
}
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("only numeric literals are allowed")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNOPS:
        return _UNOPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1 \
            and type(node.ops[0]) in _CMPS:
        return _CMPS[type(node.ops[0])](_eval(node.left), _eval(node.comparators[0]))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e) for e in node.elts]
    raise ValueError(f"disallowed expression: {ast.dump(node)[:80]}")


def safe_evaluate(expression: str) -> float:
    tree = ast.parse(expression, mode="eval")
    return _eval(tree)


def calculate_tool() -> Tool:
    def run(args: dict) -> ToolResult:
        expr = str(args.get("expression", "")).strip()
        if not expr:
            return ToolResult(ok=False, error="expression is required")
        try:
            value = safe_evaluate(expr)
        except Exception as exc:
            return ToolResult(ok=False, error=f"calculation rejected: {exc}")
        return ToolResult(ok=True, output=f"{expr} = {value}",
                          provenance={"expression": expr})

    return Tool(
        name="calculate",
        description="Evaluate a safe arithmetic/statistics expression. "
                    "No file, network or interpreter access is possible.",
        permission=Permission.READ_ONLY,
        input_schema={"expression": "string (required), e.g. 'mean([1, 2, 3]) * 12'"},
        timeout_s=10,
        run=run,
    )
