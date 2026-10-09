"""Repository for the trace store: sessions, runs, events, approvals.

All timestamps are UTC ISO strings; all JSON is written with `ensure_ascii=False` so
Chinese payloads stay readable inside the database file (the user opens it with sqlite
tools sometimes — that counts).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

RUN_STATUSES = ("running", "awaiting_approval", "succeeded", "failed", "cancelled")
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
VALID_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "running": frozenset({"awaiting_approval", "succeeded", "failed", "cancelled"}),
    "awaiting_approval": frozenset({"running", "cancelled", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}
APPROVAL_DECISIONS = ("approved", "rejected", "always_approved")


class InvalidTransitionError(ValueError):
    """A state-machine edge that must never happen, in either table."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @contextmanager
    def _immediate(self):
        """Serialize writers: one BEGIN IMMEDIATE per logical mutation."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # ------------------------------------------------------------- sessions

    def create_session(self, *, id: str, title: str, mode: str, model: str) -> None:
        now = _now()
        with self._immediate():
            self.conn.execute(
                "INSERT INTO sessions (id, title, mode, model, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (id, title, mode, model, now, now),
            )

    def get_session(self, session_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(f"会话不存在：{session_id}")
        return dict(row)

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM sessions ORDER BY created_at DESC, id").fetchall()
        return [dict(row) for row in rows]

    def update_session(self, session_id: str, **fields: Any) -> dict[str, Any]:
        """Patch title/mode; unknown keys are a programming error, not silent SQL."""
        allowed = {"title", "mode"}
        unexpected = set(fields) - allowed
        if unexpected:
            raise ValueError(f"会话只能更新 {sorted(allowed)}，收到 {sorted(unexpected)}")
        if not fields:
            return self.get_session(session_id)
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._immediate():
            self.get_session(session_id)  # existence check inside the transaction
            self.conn.execute(
                f"UPDATE sessions SET {assignments}, updated_at = ? WHERE id = ?",
                (*fields.values(), _now(), session_id),
            )
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> None:
        """Remove the session and its whole trace in one transaction.

        The schema has no ON DELETE CASCADE (SQLite would need it per connection), so
        children go explicitly, in FK order. The SDK's own `sdk_*` tables are
        deliberately left alone (PLAN §7: 不碰).
        """
        with self._immediate():
            self.get_session(session_id)
            self.conn.execute(
                "DELETE FROM approvals WHERE run_id IN (SELECT id FROM runs WHERE session_id = ?)",
                (session_id,),
            )
            self.conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
            self.conn.execute("DELETE FROM runs WHERE session_id = ?", (session_id,))
            self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # ------------------------------------------------------------- runs

    def start_run(self, *, id: str, session_id: str, input_text: str, mode: str) -> None:
        with self._immediate():
            self.conn.execute(
                "INSERT INTO runs (id, session_id, input_text, mode, status, started_at)"
                " VALUES (?, ?, ?, ?, 'running', ?)",
                (id, session_id, input_text, mode, _now()),
            )

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"run 不存在：{run_id}")
        return dict(row)

    def active_run_ids(self, session_id: str) -> list[str]:
        """Runs of one session that have not reached a terminal status."""
        placeholders = ", ".join("?" for _ in TERMINAL_STATUSES)
        rows = self.conn.execute(
            f"SELECT id FROM runs WHERE session_id = ? AND status NOT IN ({placeholders}) ORDER BY started_at",
            (session_id, *sorted(TERMINAL_STATUSES)),
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def _require_status(self, run_id: str) -> str:
        row = self.conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"run 不存在：{run_id}")
        return str(row["status"])

    def _check_edge(self, frm: str, to: str) -> None:
        if to not in RUN_STATUSES:
            raise InvalidTransitionError(f"未知的 run 状态：{to}")
        if to not in VALID_TRANSITIONS[frm]:
            raise InvalidTransitionError(f"run 状态跃迁非法：{frm} -> {to}")

    def transition_run(self, run_id: str, to: str) -> None:
        with self._immediate():
            frm = self._require_status(run_id)
            self._check_edge(frm, to)
            if to in TERMINAL_STATUSES:
                self.conn.execute(
                    "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?", (to, _now(), run_id)
                )
            else:
                self.conn.execute("UPDATE runs SET status = ? WHERE id = ?", (to, run_id))

    def finish_run(
        self, run_id: str, status: str, *, usage: dict[str, Any] | None, turns: int | None, error: str | None = None
    ) -> None:
        """Terminal transition with the result fields filled in one step."""
        if status not in TERMINAL_STATUSES:
            raise InvalidTransitionError(f"finish_run 只接受终态，收到：{status}")
        with self._immediate():
            frm = self._require_status(run_id)
            self._check_edge(frm, status)
            self.conn.execute(
                "UPDATE runs SET status = ?, finished_at = ?, usage_json = ?, turns = ?, error = ?"
                " WHERE id = ?",
                (status, _now(), _dumps(usage) if usage is not None else None, turns, error, run_id),
            )

    def save_run_state(self, run_id: str, state: dict[str, Any]) -> None:
        with self._immediate():
            self.conn.execute("UPDATE runs SET state_json = ? WHERE id = ?", (_dumps(state), run_id))

    def load_run_state(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT state_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"run 不存在：{run_id}")
        return json.loads(row["state_json"]) if row["state_json"] is not None else None

    # ------------------------------------------------------------- events

    def append_event(self, *, session_id: str, run_id: str, type: str, payload: dict[str, Any]) -> int:
        """Assign the per-session seq atomically; returns the new seq.

        The MAX(seq)+1 read and the INSERT share one BEGIN IMMEDIATE transaction, and
        UNIQUE(session_id, seq) is the belt: under concurrent writers a seq can only
        ever be dense and collision-free.
        """
        with self._immediate():
            row = self.conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = int(row["next"])
            self.conn.execute(
                "INSERT INTO events (session_id, run_id, seq, type, payload_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, run_id, seq, type, _dumps(payload), _now()),
            )
        return seq

    def list_events(self, session_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE session_id = ? AND seq > ? ORDER BY seq",
            (session_id, after_seq),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------- approvals

    def create_approval(
        self, *, run_id: str, approval_id: str, tool_name: str, arguments: dict[str, Any], risk: str
    ) -> None:
        with self._immediate():
            self.conn.execute(
                "INSERT INTO approvals (run_id, approval_id, tool_name, arguments_json, risk, decision, created_at)"
                " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (run_id, approval_id, tool_name, _dumps(arguments), risk, _now()),
            )

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError(f"审批不存在：{approval_id}")
        return dict(row)

    def list_approvals(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM approvals WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def decide_approval(self, approval_id: str, decision: str) -> None:
        if decision not in APPROVAL_DECISIONS:
            raise InvalidTransitionError(f"未知审批决定：{decision}")
        with self._immediate():
            row = self.conn.execute(
                "SELECT decision FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"审批不存在：{approval_id}")
            if row["decision"] != "pending":
                raise InvalidTransitionError(f"审批已处理过（{row['decision']}），不能重复决定")
            self.conn.execute(
                "UPDATE approvals SET decision = ?, decided_at = ? WHERE approval_id = ?",
                (decision, _now(), approval_id),
            )
