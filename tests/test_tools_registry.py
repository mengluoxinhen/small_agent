"""T1 — tool registry: discovery, risk metadata, and schema invariants.

The invariants here are what let P4 be testable at all: if a tool exists without a risk
level, or a risk entry points at a tool that was deleted, the approval policy would
silently guess. These tests make that impossible.
"""

from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path

import pytest
from agents import FunctionTool
from app.tools.registry import (
    RISK_LEVELS,
    DuplicateToolError,
    RegistryIntegrityError,
    UnknownToolError,
    build_registry,
    default_registry,
    discover_tools,
)

EXPECTED_TOOLS = {
    "calculator",
    "read_text_file",
    "write_text_file",
    "list_session_files",
    "delete_session_file",
}


@pytest.fixture
def make_package(tmp_path: Path):
    """Build a throwaway tool package on disk and import it."""

    def _make(name: str, files: dict[str, str]):
        pkg = tmp_path / name
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        for filename, body in files.items():
            (pkg / filename).write_text(textwrap.dedent(body), encoding="utf-8")
        sys.path.insert(0, str(tmp_path))
        try:
            return importlib.import_module(name)
        finally:
            sys.path.remove(str(tmp_path))

    return _make


# ---------------------------------------------------------------- defaults


def test_default_registry_exposes_exactly_the_five_builtin_tools():
    registry = default_registry()
    assert set(registry.names) == EXPECTED_TOOLS


def test_discovered_tools_are_function_tool_instances():
    for tool in default_registry().tools:
        assert isinstance(tool, FunctionTool)


def test_tool_names_are_valid_identifiers_and_unique():
    names = default_registry().names
    assert len(names) == len(set(names))
    for name in names:
        assert name.isidentifier(), name
        assert len(name) <= 64, "some OpenAI-compatible endpoints reject long tool names"


def test_every_tool_has_a_declared_risk():
    registry = default_registry()
    for name in registry.names:
        assert registry.risk_for(name) in RISK_LEVELS


def test_risk_levels_cover_all_three_tiers():
    """P4's approval matrix is meaningless without at least one of each kind."""
    tiers = {default_registry().risk_for(name) for name in default_registry().names}
    assert tiers == set(RISK_LEVELS)


def test_risk_for_unknown_tool_raises():
    with pytest.raises(UnknownToolError, match="nope"):
        default_registry().risk_for("nope")


def test_default_registry_is_cached():
    assert default_registry() is default_registry()


# ---------------------------------------------------------------- discovery rules


def test_underscore_prefixed_modules_are_ignored(make_package):
    pkg = make_package(
        "pkg_underscore",
        {
            "_draft.py": '''
                from agents import function_tool
                @function_tool
                async def hidden_tool(x: str) -> str:
                    """不该被发现。

                    Args:
                        x: 参数
                    """
                    return x
                TOOL_RISK = {"hidden_tool": "read"}
            ''',
            "used.py": '''
                from agents import function_tool
                @function_tool
                async def real_tool(x: str) -> str:
                    """应当被发现。

                    Args:
                        x: 参数
                    """
                    return x
                TOOL_RISK = {"real_tool": "read"}
            ''',
        },
    )
    names = {t.name for t in discover_tools(pkg)}
    assert names == {"real_tool"}


def test_duplicate_tool_names_are_rejected(make_package):
    pkg = make_package(
        "pkg_duplicate",
        {
            "a.py": '''
                from agents import function_tool
                @function_tool
                async def same_name(x: str) -> str:
                    """甲。

                    Args:
                        x: 参数
                    """
                    return x
                TOOL_RISK = {"same_name": "read"}
            ''',
            "b.py": '''
                from agents import function_tool
                @function_tool(name_override="same_name")
                async def other(x: str) -> str:
                    """乙。

                    Args:
                        x: 参数
                    """
                    return x
                TOOL_RISK = {"same_name": "write"}
            ''',
        },
    )
    with pytest.raises(DuplicateToolError, match="same_name"):
        discover_tools(pkg)


def test_risk_entry_for_a_nonexistent_tool_is_rejected(make_package):
    pkg = make_package(
        "pkg_orphan",
        {
            "a.py": '''
                from agents import function_tool
                @function_tool
                async def present(x: str) -> str:
                    """存在。

                    Args:
                        x: 参数
                    """
                    return x
                TOOL_RISK = {"present": "read", "deleted_long_ago": "write"}
            ''',
        },
    )
    with pytest.raises(RegistryIntegrityError, match="deleted_long_ago"):
        build_registry(pkg)


def test_tool_without_risk_declaration_is_rejected(make_package):
    pkg = make_package(
        "pkg_unclassified",
        {
            "a.py": '''
                from agents import function_tool
                @function_tool
                async def mystery(x: str) -> str:
                    """没有风险等级。

                    Args:
                        x: 参数
                    """
                    return x
                TOOL_RISK = {}
            ''',
        },
    )
    with pytest.raises(RegistryIntegrityError, match="mystery"):
        build_registry(pkg)


def test_invalid_risk_value_is_rejected(make_package):
    pkg = make_package(
        "pkg_bad_risk",
        {
            "a.py": '''
                from agents import function_tool
                @function_tool
                async def risky(x: str) -> str:
                    """风险等级写错了。

                    Args:
                        x: 参数
                    """
                    return x
                TOOL_RISK = {"risky": "very-bad"}
            ''',
        },
    )
    with pytest.raises(RegistryIntegrityError, match="very-bad"):
        build_registry(pkg)


# ---------------------------------------------------------------- schema invariants


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_schema_has_no_context_parameter(name: str):
    tool = default_registry().by_name(name)
    assert "ctx" not in tool.params_json_schema.get("properties", {})
    assert "context" not in tool.params_json_schema.get("properties", {})


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_schema_is_closed_and_fully_required(name: str):
    """strict_mode forces every declared parameter into `required`; a tool with an
    optional parameter would therefore demand it from the model. We keep the surface
    honest: no optional parameters at all."""
    schema = default_registry().by_name(name).params_json_schema
    assert schema["additionalProperties"] is False
    properties = set(schema.get("properties", {}))
    required = set(schema.get("required", []))
    assert properties == required, f"{name}: {properties ^ required} are inconsistent"


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_description_and_every_parameter_are_documented(name: str):
    tool = default_registry().by_name(name)
    assert tool.description and tool.description.strip()
    for param, spec in tool.params_json_schema.get("properties", {}).items():
        assert spec.get("description"), f"{name}.{param} has no description for the model"


def test_list_session_files_takes_no_parameters():
    schema = default_registry().by_name("list_session_files").params_json_schema
    assert schema.get("properties", {}) == {}
    assert schema.get("required", []) in ([], None)


def test_calculator_takes_exactly_one_string_parameter():
    schema = default_registry().by_name("calculator").params_json_schema
    assert list(schema["properties"]) == ["expression"]
    assert schema["properties"]["expression"]["type"] == "string"
