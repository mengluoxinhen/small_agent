"""T1 — workspace-scoped file implementation.

These tools are the only place the agent can touch the filesystem, so the boundary tests
matter more than the happy path. Everything is confined to a per-session workspace dir;
`root` is always supplied by the caller (the run context), never by the model.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.tools.errors import ToolInputError
from app.tools.impl.files import delete_file, list_files, read_text, safe_path, write_text


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


# ---------------------------------------------------------------- happy paths


def test_write_then_read_roundtrip(workspace: Path):
    summary = write_text(workspace, "notes.txt", "第一行\n第二行", max_write_bytes=1_000_000)
    assert "notes.txt" in summary
    assert read_text(workspace, "notes.txt", max_read_bytes=200_000) == "第一行\n第二行"


def test_write_overwrites_and_reports_size(workspace: Path):
    write_text(workspace, "a.txt", "x" * 10, max_write_bytes=1_000_000)
    summary = write_text(workspace, "a.txt", "yyy", max_write_bytes=1_000_000)
    assert read_text(workspace, "a.txt", max_read_bytes=200_000) == "yyy"
    assert "3" in summary


def test_list_files_is_sorted_and_shows_sizes(workspace: Path):
    assert list_files(workspace) == []
    write_text(workspace, "b.txt", "22", max_write_bytes=1_000_000)
    write_text(workspace, "a.txt", "1", max_write_bytes=1_000_000)
    entries = list_files(workspace)
    assert [e.name for e in entries] == ["a.txt", "b.txt"]
    assert "1" in entries[0].summary() and "2" in entries[1].summary()


def test_delete_removes_existing_file(workspace: Path):
    write_text(workspace, "gone.txt", "bye", max_write_bytes=1_000_000)
    assert delete_file(workspace, "gone.txt").startswith("已删除")
    assert list_files(workspace) == []


def test_filenames_may_contain_dots_and_spaces(workspace: Path):
    write_text(workspace, "my report.v2.txt", "ok", max_write_bytes=1_000_000)
    assert read_text(workspace, "my report.v2.txt", max_read_bytes=200_000) == "ok"


def test_empty_file_is_readable_not_an_error(workspace: Path):
    write_text(workspace, "empty.txt", "", max_write_bytes=1_000_000)
    assert read_text(workspace, "empty.txt", max_read_bytes=200_000) == ""


# ---------------------------------------------------------------- boundary attacks


@pytest.mark.parametrize(
    "filename",
    [
        "../secret.txt",
        "..\\secret.txt",
        "sub/dir.txt",
        "sub\\dir.txt",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "./../escape.txt",
        "..",
        ".",
        "a/../../b.txt",
    ],
)
def test_paths_that_escape_the_workspace_are_rejected(workspace: Path, filename: str):
    with pytest.raises(ToolInputError) as exc:
        safe_path(workspace, filename)
    message = str(exc.value)
    assert "目录" in message or "越界" in message or "绝对路径" in message
    assert str(workspace) not in message, "never echo the host path back to the model"


def test_symlink_pointing_outside_workspace_is_rejected(workspace: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("top secret", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this volume")
    with pytest.raises(ToolInputError):
        read_text(workspace, "link.txt", max_read_bytes=200_000)


def test_directory_cannot_be_read_as_a_file(workspace: Path):
    (workspace / "adir").mkdir()
    with pytest.raises(ToolInputError):
        read_text(workspace, "adir", max_read_bytes=200_000)


def test_directory_cannot_be_overwritten_by_a_file(workspace: Path):
    (workspace / "adir").mkdir()
    with pytest.raises(ToolInputError):
        write_text(workspace, "adir", "boom", max_write_bytes=1_000_000)


def test_directory_cannot_be_deleted_as_a_file(workspace: Path):
    (workspace / "adir").mkdir()
    with pytest.raises(ToolInputError):
        delete_file(workspace, "adir")


@pytest.mark.parametrize("filename", ["", "   ", None])
def test_blank_filename_is_rejected(workspace: Path, filename):
    with pytest.raises(ToolInputError, match="文件名"):
        safe_path(workspace, filename)


def test_very_long_filename_is_rejected(workspace: Path):
    with pytest.raises(ToolInputError, match="文件名"):
        safe_path(workspace, "n" * 300 + ".txt")


def test_missing_file_message_names_the_file(workspace: Path):
    with pytest.raises(ToolInputError, match="missing.txt"):
        read_text(workspace, "missing.txt", max_read_bytes=200_000)


def test_missing_file_on_delete_is_reported(workspace: Path):
    with pytest.raises(ToolInputError, match="nope.txt"):
        delete_file(workspace, "nope.txt")


# ---------------------------------------------------------------- size limits


def test_read_is_capped_by_max_bytes(workspace: Path):
    write_text(workspace, "big.txt", "x" * 5_000, max_write_bytes=1_000_000)
    with pytest.raises(ToolInputError, match="过大"):
        read_text(workspace, "big.txt", max_read_bytes=100)


def test_write_is_capped_by_max_bytes(workspace: Path):
    with pytest.raises(ToolInputError, match="过大"):
        write_text(workspace, "big.txt", "x" * 5_000, max_write_bytes=100)


def test_read_within_cap_succeeds(workspace: Path):
    write_text(workspace, "ok.txt", "x" * 500, max_write_bytes=1_000_000)
    assert len(read_text(workspace, "ok.txt", max_read_bytes=1_000)) == 500


def test_list_ignores_subdirectories_and_hidden_files(workspace: Path):
    write_text(workspace, "visible.txt", "1", max_write_bytes=1_000_000)
    (workspace / ".hidden").write_text("1", encoding="utf-8")
    (workspace / "sub").mkdir()
    assert [e.name for e in list_files(workspace)] == ["visible.txt"]


# ---------------------------------------------------------------- encoding


def test_utf8_content_survives_roundtrip(workspace: Path):
    write_text(workspace, "cn.txt", "气动力学 CFD 仿真 ✓", max_write_bytes=1_000_000)
    assert read_text(workspace, "cn.txt", max_read_bytes=200_000) == "气动力学 CFD 仿真 ✓"
