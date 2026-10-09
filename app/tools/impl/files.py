"""Workspace-scoped file operations.

Every path that reaches these functions is validated against a single root (the session
workspace from `AppContext`). The model can only ever name a *bare filename*: separators,
absolute paths, `.`/`..` and drive letters are rejected before the filesystem is touched,
and the resolved target is checked to still sit inside the root (which also blocks
symlinks pointing elsewhere).

Error messages name the file but never the host directory, because they are replayed into
the model's context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.tools.errors import ToolInputError, WorkspaceBoundaryError

MAX_FILENAME_CHARS = 200

_SEPARATORS = tuple({sep for sep in ("/", "\\", os.sep, os.altsep or "\0") if sep != "\0"})


@dataclass(frozen=True)
class FileEntry:
    name: str
    size: int

    def summary(self) -> str:
        return f"{self.name} ({self.size} 字节)"


def _validated_name(filename: object) -> str:
    if not isinstance(filename, str) or not filename.strip():
        raise ToolInputError("文件名不能为空")

    name = filename.strip()
    if len(name) > MAX_FILENAME_CHARS:
        raise ToolInputError(f"文件名过长（上限 {MAX_FILENAME_CHARS} 字符）")
    if name in {".", ".."}:
        raise ToolInputError("文件名不能是 . 或 ..（那是目录，不是文件）")
    if any(sep in name for sep in _SEPARATORS):
        raise ToolInputError("文件名不能包含目录分隔符，只接受工作区内的纯文件名")
    if os.path.isabs(name) or ":" in name:
        raise ToolInputError("文件名不能是绝对路径，只接受工作区内的纯文件名")
    return name


def safe_path(root: Path, filename: object) -> Path:
    """Resolve `filename` inside `root`, refusing anything that escapes it."""
    name = _validated_name(filename)
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / name).resolve()

    if not candidate.is_relative_to(root_resolved):
        raise WorkspaceBoundaryError("越界访问被拒绝：目标文件必须位于会话工作区内")
    return candidate


def read_text(root: Path, filename: object, *, max_read_bytes: int) -> str:
    path = safe_path(root, filename)
    if path.is_dir():
        raise ToolInputError(f"{path.name} 是目录，不是文件")
    if not path.is_file():
        raise ToolInputError(f"文件不存在：{path.name}")

    size = path.stat().st_size
    if size > max_read_bytes:
        raise ToolInputError(f"文件过大：{size} 字节，上限 {max_read_bytes} 字节")

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolInputError(f"{path.name} 不是 UTF-8 文本文件") from exc


def write_text(root: Path, filename: object, content: str, *, max_write_bytes: int) -> str:
    path = safe_path(root, filename)
    if path.is_dir():
        raise ToolInputError(f"{path.name} 是目录，不能当作文件写入")
    if not isinstance(content, str):
        raise ToolInputError("content 必须是文本字符串")

    payload = content.encode("utf-8")
    if len(payload) > max_write_bytes:
        raise ToolInputError(f"内容过大：{len(payload)} 字节，上限 {max_write_bytes} 字节")

    path.write_bytes(payload)
    return f"已写入 {path.name}（{len(payload)} 字节）"


def list_files(root: Path) -> list[FileEntry]:
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    entries = [
        FileEntry(name=item.name, size=item.stat().st_size)
        for item in sorted(directory.iterdir())
        if item.is_file() and not item.name.startswith(".")
    ]
    return entries


def delete_file(root: Path, filename: object) -> str:
    path = safe_path(root, filename)
    if path.is_dir():
        raise ToolInputError(f"{path.name} 是目录，不支持删除目录")
    if not path.is_file():
        raise ToolInputError(f"文件不存在：{path.name}")
    path.unlink()
    return f"已删除 {path.name}"
