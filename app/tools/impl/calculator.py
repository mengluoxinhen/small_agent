"""Safe arithmetic evaluator.

No `eval`. The expression is parsed to an AST and only a deliberately small whitelist is
executed, so `__import__('os')` or `(1).real` can never reach Python. The guards that look
paranoid (`9**9**9`, 500-char input, full-width symbols) are what keep a runaway model
from hanging the run or burning the token budget.
"""

from __future__ import annotations

import ast
import math
import re

from app.tools.errors import ToolInputError

MAX_EXPRESSION_CHARS = 500
MAX_POSITIVE_EXPONENT = 128

_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

_BINARY_OPS: frozenset[type[ast.operator]] = frozenset(
    {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow}
)

_FULLWIDTH_HINT = (
    "请勿使用全角符号（× ÷ － ＋ （） 以及全角数字），"
    "改用 ASCII 的 * / - + ( )"
)

_ALLOWED_SUMMARY = "只允许 + - * / // % ** 括号、常数 pi/e/tau、函数 sqrt/abs/round/min/max"


def _reject(node: ast.AST) -> ToolInputError:
    return ToolInputError(f"不支持的写法：{type(node).__name__}。{_ALLOWED_SUMMARY}")


def _syntax_error(expression: str, error: SyntaxError) -> ToolInputError:
    has_fullwidth = any(char in expression for char in "×÷－＋（）０１２３４５６７８９．，")
    hint = f"。{_FULLWIDTH_HINT}" if has_fullwidth else ""
    return ToolInputError(f"表达式语法错误：{error.msg}{hint}")


def _as_number(value: object, node: ast.AST) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _reject(node)
    return value


def _evaluate_number(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant):
        return _as_number(node.value, node)

    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ToolInputError(f"未知标识符：{node.id}。{_ALLOWED_SUMMARY}")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _evaluate_number(node.operand)
        return +operand if isinstance(node.op, ast.UAdd) else -operand

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        left = _evaluate_number(node.left)
        right = _evaluate_number(node.right)
        return _apply_binary(node, node.op, left, right)

    if isinstance(node, ast.Call):
        return _evaluate_call(node)

    raise _reject(node)


def _apply_binary(node: ast.BinOp, op: ast.operator, left: float, right: float):
    if isinstance(op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
        raise ToolInputError("除数为零")

    if isinstance(op, ast.Pow) and isinstance(right, int) and right > MAX_POSITIVE_EXPONENT:
        raise ToolInputError(f"幂次过大：指数 {right} 超过上限 {MAX_POSITIVE_EXPONENT}")

    try:
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.FloorDiv):
            return left // right
        if isinstance(op, ast.Mod):
            return left % right
        return left**right
    except OverflowError as exc:
        raise ToolInputError("计算结果溢出，请缩小数值") from exc


def _evaluate_call(node: ast.Call) -> float | int:
    if node.keywords:
        raise ToolInputError("函数调用不支持关键字参数")
    if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
        called = getattr(node.func, "id", None) or getattr(node.func, "attr", None) or "<表达式>"
        raise ToolInputError(f"不允许的函数：{called}。{_ALLOWED_SUMMARY}")
    arguments = [_evaluate_number(arg) for arg in node.args]
    try:
        return _FUNCTIONS[node.func.id](*arguments)  # type: ignore[operator]
    except (ValueError, TypeError) as exc:
        raise ToolInputError(f"函数 {node.func.id} 调用失败：{exc}") from exc


def evaluate(expression: str) -> float | int:
    """Evaluate an arithmetic expression and return its numeric value."""
    if not isinstance(expression, str) or not expression.strip():
        raise ToolInputError("表达式为空")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise ToolInputError(f"表达式过长（上限 {MAX_EXPRESSION_CHARS} 字符）")

    # `ast.parse(..., mode="eval")` rejects leading indentation and raw newlines around
    # operators, but models emit pretty-printed expressions all the time. Collapsing
    # whitespace is safe here: the whitelist contains no string literals, so spaces
    # are never meaningful inside a token.
    try:
        tree = ast.parse(re.sub(r"\s+", " ", expression.strip()), mode="eval")
    except SyntaxError as exc:
        raise _syntax_error(expression, exc) from exc

    return _evaluate_number(tree.body)
