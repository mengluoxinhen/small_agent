"""T1 — tools invoked the way the SDK invokes them.

`on_invoke_tool(ToolContext, arguments_json)` is the real entry point the agent loop uses,
including its argument validation and its failure-message path. Testing the tools through
anything else would prove too little.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agents.tool_context import ToolContext
from app.testing.context import make_tool_context
from app.tools.context import AppContext
from app.tools.registry import default_registry

SDK_GENERIC_MESSAGE = "An error occurred while running the tool"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def registry():
    return default_registry()


async def invoke(registry, name: str, arguments: dict, workspace: Path) -> str:
    tool = registry.by_name(name)
    ctx = make_tool_context(AppContext(workspace=workspace), tool_name=name)
    return await tool.on_invoke_tool(ctx, json.dumps(arguments, ensure_ascii=False))


# ---------------------------------------------------------------- plumbing


def test_make_tool_context_builds_a_real_sdk_tool_context(workspace: Path):
    ctx = make_tool_context(AppContext(workspace=workspace), tool_name="calculator")
    assert isinstance(ctx, ToolContext)
    assert ctx.tool_name == "calculator"
    assert ctx.tool_call_id
    # Without run_config the SDK raises AttributeError deep inside on_invoke_tool;
    # this is the exact trap that made a hand-rolled RunContextWrapper useless.
    assert ctx.run_config is not None
    assert ctx.context.workspace == workspace


# ---------------------------------------------------------------- calculator


async def test_calculator_returns_the_computed_value(registry, workspace: Path):
    out = await invoke(registry, "calculator", {"expression": "6*7"}, workspace)
    assert "42" in out


async def test_calculator_failure_message_is_actionable_and_model_facing(registry, workspace: Path):
    out = await invoke(registry, "calculator", {"expression": "3 × 4"}, workspace)
    assert "calculator" in out
    assert "Traceback" not in out
    assert SDK_GENERIC_MESSAGE not in out, "the default SDK message teaches the model nothing"


async def test_calculator_missing_required_argument_is_reported(registry, workspace: Path):
    out = await invoke(registry, "calculator", {}, workspace)
    assert "expression" in out
    assert SDK_GENERIC_MESSAGE not in out


async def test_calculator_rejects_or_ignores_an_unknown_argument(registry, workspace: Path):
    """Whatever the SDK's stance on extra keys, it must not answer with the generic message."""
    out = await invoke(registry, "calculator", {"expression": "6*7", "precision": 3}, workspace)
    assert SDK_GENERIC_MESSAGE not in out
    assert ("42" in out) or ("precision" in out)


async def test_calculator_division_by_zero_does_not_break_the_tool(registry, workspace: Path):
    out = await invoke(registry, "calculator", {"expression": "1/0"}, workspace)
    assert "零" in out


# ---------------------------------------------------------------- file tools


async def test_write_then_read_roundtrip_through_the_tools(registry, workspace: Path):
    written = await invoke(registry, "write_text_file", {"filename": "note.txt", "content": "气动力学"}, workspace)
    assert "note.txt" in written
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "气动力学"
    read = await invoke(registry, "read_text_file", {"filename": "note.txt"}, workspace)
    assert "气动力学" in read


async def test_tools_use_the_context_workspace_not_the_current_directory(registry, workspace: Path, monkeypatch):
    monkeypatch.chdir(workspace.parent)
    await invoke(registry, "write_text_file", {"filename": "here.txt", "content": "x"}, workspace)
    assert (workspace / "here.txt").is_file()
    assert not (workspace.parent / "here.txt").exists()


async def test_read_of_a_missing_file_names_the_file_and_hides_host_paths(registry, workspace: Path):
    out = await invoke(registry, "read_text_file", {"filename": "ghost.txt"}, workspace)
    assert "ghost.txt" in out
    assert str(workspace) not in out, "absolute host paths must not leak into model context"


async def test_traversal_attempt_is_blocked_and_gives_no_host_path(registry, workspace: Path):
    (workspace.parent / "secret.txt").write_text("top secret", encoding="utf-8")
    out = await invoke(registry, "read_text_file", {"filename": "../secret.txt"}, workspace)
    assert "top secret" not in out, "the escape must not succeed"
    assert str(workspace) not in out, "absolute host paths must not leak into model context"
    assert not (workspace / "secret.txt").exists(), "no copy of the escaped file may land inside"


async def test_list_reports_names_and_sizes(registry, workspace: Path):
    assert "空" in await invoke(registry, "list_session_files", {}, workspace)
    await invoke(registry, "write_text_file", {"filename": "a.txt", "content": "12345"}, workspace)
    out = await invoke(registry, "list_session_files", {}, workspace)
    assert "a.txt" in out


async def test_delete_removes_and_reports(registry, workspace: Path):
    await invoke(registry, "write_text_file", {"filename": "tmp.txt", "content": "bye"}, workspace)
    out = await invoke(registry, "delete_session_file", {"filename": "tmp.txt"}, workspace)
    assert "tmp.txt" in out
    assert not (workspace / "tmp.txt").exists()


async def test_delete_of_a_missing_file_is_reported(registry, workspace: Path):
    out = await invoke(registry, "delete_session_file", {"filename": "none.txt"}, workspace)
    assert "none.txt" in out


async def test_write_rejects_a_subdirectory_path(registry, workspace: Path):
    out = await invoke(registry, "write_text_file", {"filename": "sub/x.txt", "content": "y"}, workspace)
    assert "目录" in out
    assert not (workspace / "sub").exists()


# ---------------------------------------------------------------- risk wiring


@pytest.mark.parametrize(
    ("name", "risk"),
    [
        ("calculator", "read"),
        ("read_text_file", "read"),
        ("list_session_files", "read"),
        ("write_text_file", "write"),
        ("delete_session_file", "dangerous"),
    ],
)
def test_each_tool_declares_the_intended_risk(registry, name: str, risk: str):
    assert registry.risk_for(name) == risk
