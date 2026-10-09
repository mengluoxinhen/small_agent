"""T1 — calculator implementation.

Pure logic, no SDK, no I/O. This is the layer where the real bugs live, so it gets the
most cases. Note the deliberate non-ASCII tests: domestic models love replying with
full-width symbols like × ÷ －, and a helpful message there saves a wasted agent turn.
"""

from __future__ import annotations

import pytest
from app.tools.errors import ToolInputError
from app.tools.impl.calculator import evaluate


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1+1", 2),
        ("2 - 3", -1),
        ("6*7", 42),
        ("7/2", 3.5),
        ("7//2", 3),
        ("7%3", 1),
        ("2**10", 1024),
        ("(1+2)*(3+4)", 21),
        ("-5+3", -2),
        ("+5", 5),
        ("1.5*2", 3.0),
        ("3.14", 3.14),
        ("min(3, 1, 2)", 1),
        ("max(3, 1, 2)", 3),
        ("abs(-4)", 4),
        ("round(2.567, 2)", 2.57),
        ("sqrt(16)", 4.0),
        ("2*pi", pytest.approx(6.283185307)),
        ("e", pytest.approx(2.718281828)),
        ("sqrt(2)**2", pytest.approx(2.0)),
    ],
)
def test_valid_arithmetic(expression: str, expected):
    assert evaluate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "1+",
        "((1+2)",
        "2**",
        "1,2",
        "'a'",
        "None",
        "True",
        "a+1",
        "os.system('ls')",
        "__import__('os')",
        "(1).real",
        "[1,2][0]",
        "{'a':1}",
        "1 if 2 else 3",
        "1==1",
        "1<2",
        "lambda: 1",
        "sum([1,2])",
        "open('x')",
        "print(1)",
        "1 and 1",
        "3 × 4",
        "3 － 1",
        "（1+2）*3",
        "３＋１",
    ],
)
def test_rejected_expressions_raise_actionable_error(expression: str):
    with pytest.raises(ToolInputError) as exc:
        evaluate(expression)
    message = str(exc.value)
    assert message.strip(), "an error the model cannot read is not an error, it is a dead end"
    assert "Traceback" not in message


def test_division_by_zero_is_reported_not_crashed():
    with pytest.raises(ToolInputError, match="零"):
        evaluate("1/0")
    with pytest.raises(ToolInputError, match="零"):
        evaluate("1//0")
    with pytest.raises(ToolInputError, match="零"):
        evaluate("1%0")


def test_huge_exponent_is_capped():
    """`9**9**9` would hang the run and blow up the token budget."""
    with pytest.raises(ToolInputError, match="幂"):
        evaluate("9**9**9")
    with pytest.raises(ToolInputError, match="幂"):
        evaluate("2**1000")


def test_exponent_within_cap_is_allowed():
    assert evaluate("2**128") == 2**128


def test_negative_exponent_is_allowed_even_when_large_magnitude():
    # |x| governs the guard, not the sign: 2**-1000 terminates immediately.
    assert evaluate("2**-1000") == 2**-1000


def test_full_width_operators_get_a_specific_hint():
    with pytest.raises(ToolInputError, match=r"\*"):
        evaluate("3 × 4")


def test_unknown_identifier_names_what_is_allowed():
    with pytest.raises(ToolInputError, match="sqrt"):
        evaluate("foo(2)")


def test_whitespace_and_newlines_are_tolerated():
    assert evaluate("  1 +\n 2 ") == 3


def test_result_is_a_number_not_a_string():
    assert isinstance(evaluate("1+1"), (int, float))
    assert isinstance(evaluate("1/3"), float)


def test_expression_length_is_capped():
    with pytest.raises(ToolInputError, match="过长"):
        evaluate("1+" * 600)
