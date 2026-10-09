"""Test/dev helpers for constructing SDK contexts.

`make_tool_context` exists because a bare `RunContextWrapper` is *not* enough to invoke a
tool: `on_invoke_tool` needs `tool_name` and `run_config`, and raises `AttributeError`
without them. Centralising that here means P2/P4/P6 all drive tools the same way the
runner does.
"""

from __future__ import annotations

import uuid
from typing import Any

from agents.run_config import RunConfig
from agents.tool_context import ToolContext


def make_tool_context(
    context: Any,
    *,
    tool_name: str,
    tool_call_id: str | None = None,
) -> ToolContext:
    return ToolContext(
        context,
        tool_name=tool_name,
        tool_call_id=tool_call_id or f"call_test_{uuid.uuid4().hex[:8]}",
        tool_arguments="{}",
        run_config=RunConfig(),
    )
