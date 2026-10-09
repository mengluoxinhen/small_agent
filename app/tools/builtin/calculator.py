"""Calculator tool."""

from __future__ import annotations

from agents import RunContextWrapper, function_tool

from app.tools.context import AppContext
from app.tools.errors import describe_failure
from app.tools.impl import calculator as calc


def _format(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@function_tool(failure_error_function=describe_failure)
async def calculator(ctx: RunContextWrapper[AppContext], expression: str) -> str:
    """计算一个算术表达式并返回数值结果。

    Args:
        expression: 要计算的表达式，只使用 ASCII 的数字与运算符，例如 "6*7"、"sqrt(2)**2"、"round(3.14159, 2)"。
    """
    value = calc.evaluate(expression)
    return f"{expression} = {_format(value)}"


TOOL_RISK = {"calculator": "read"}
