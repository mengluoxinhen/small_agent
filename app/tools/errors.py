"""Tool error vocabulary.

Two ideas live here:

* `ToolInputError` marks a problem the *model* can fix (bad expression, escaping path,
  missing file). Messages are written as instructions in Chinese because they are fed
  straight back into the model's context — a Python traceback there is a wasted turn.
* `describe_failure` is installed as every builtin tool's `failure_error_function`.
  The SDK default returns "An error occurred while running the tool. Please try again.",
  which teaches the model nothing; this replaces it with the actual reason.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

logger = logging.getLogger("small_dify.tools")


class ToolInputError(ValueError):
    """Invalid tool input the model is expected to correct."""


class WorkspaceBoundaryError(ToolInputError):
    """A path that would leave the session workspace."""


def _describe_argument_error(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        location = ".".join(str(x) for x in item.get("loc") or ()) or "arguments"
        parts.append(f"{location}: {item.get('msg', '参数不合法')}")
    return "参数不符合工具定义（" + "; ".join(parts) + "）"


def _required_params(tool_name: str) -> list[str]:
    """Required parameter names of a builtin tool, or [] when it cannot be resolved.

    The lazy registry import keeps `app.tools.errors` importable without walking the
    builtin packages at module load, and avoids the errors -> registry -> builtin
    import cycle that describe_failure would otherwise create.
    """
    try:
        from app.tools.registry import (
            DuplicateToolError,
            RegistryIntegrityError,
            UnknownToolError,
            default_registry,
        )

        tool = default_registry().by_name(tool_name)
    except (UnknownToolError, DuplicateToolError, RegistryIntegrityError):
        return []
    schema = getattr(tool, "params_json_schema", None) or {}
    required = schema.get("required") or []
    return [str(name) for name in required]


def describe_failure(context: Any, error: Exception) -> str:
    """Turn an exception into a message the agent can act on."""
    tool_name = getattr(context, "tool_name", None) or "工具"

    # Imported here on purpose: `impl/` modules import this file and must stay SDK-free.
    from agents.exceptions import ModelBehaviorError

    if isinstance(error, ValidationError):
        detail = _describe_argument_error(error)
    elif isinstance(error, ModelBehaviorError):
        # The SDK raises this when the emitted arguments are not valid JSON or miss
        # required keys, and its own text carries no parameter names. Listing the
        # schema's required params is what makes the next model turn fixable.
        required = _required_params(tool_name)
        if required:
            detail = "参数 JSON 缺失或不合法，该工具的必填参数为：" + "、".join(required)
        else:
            detail = "参数 JSON 缺失或不合法，请严格按照工具定义重新提供参数"
    elif isinstance(error, ToolInputError):
        detail = str(error)
    else:
        # Unexpected failures are logged in full, but the model only gets the class name:
        # host paths and library internals must not leak into the conversation.
        logger.exception("tool %s raised %s", tool_name, type(error).__name__)
        detail = f"工具内部错误（{type(error).__name__}），请换一种输入重试"

    return f"工具 {tool_name} 调用失败：{detail}。请修正后重新调用。"
