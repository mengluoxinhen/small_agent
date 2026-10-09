"""File tools, all confined to the session workspace in `AppContext`."""

from __future__ import annotations

from agents import RunContextWrapper, function_tool

from app.tools.context import AppContext
from app.tools.errors import describe_failure
from app.tools.impl import files as impl


@function_tool(failure_error_function=describe_failure)
async def read_text_file(ctx: RunContextWrapper[AppContext], filename: str) -> str:
    """读取当前会话工作区里的 UTF-8 文本文件，返回它的完整内容。

    Args:
        filename: 工作区内的纯文件名，例如 "notes.txt"；不能包含目录分隔符或路径。
    """
    return impl.read_text(
        ctx.context.workspace,
        filename,
        max_read_bytes=ctx.context.max_read_bytes,
    )


@function_tool(failure_error_function=describe_failure)
async def write_text_file(ctx: RunContextWrapper[AppContext], filename: str, content: str) -> str:
    """在当前会话工作区创建一个 UTF-8 文本文件，同名文件会被覆盖。

    Args:
        filename: 工作区内的纯文件名，例如 "result.txt"；不能包含目录分隔符或路径。
        content: 要写入的文本内容（UTF-8）。
    """
    return impl.write_text(
        ctx.context.workspace,
        filename,
        content,
        max_write_bytes=ctx.context.max_write_bytes,
    )


@function_tool(failure_error_function=describe_failure)
async def delete_session_file(ctx: RunContextWrapper[AppContext], filename: str) -> str:
    """删除当前会话工作区里的一个文件。不能删除目录，删除后无法恢复。

    Args:
        filename: 工作区内的纯文件名，例如 "old.txt"。
    """
    return impl.delete_file(ctx.context.workspace, filename)


@function_tool(failure_error_function=describe_failure)
async def list_session_files(ctx: RunContextWrapper[AppContext]) -> str:
    """列出当前会话工作区里的所有文件及其字节数，不需要任何参数。"""
    entries = impl.list_files(ctx.context.workspace)
    if not entries:
        return "工作区为空，还没有任何文件。"
    return "工作区文件：\n" + "\n".join(entry.summary() for entry in entries)


TOOL_RISK = {
    "read_text_file": "read",
    "write_text_file": "write",
    "delete_session_file": "dangerous",
    "list_session_files": "read",
}
