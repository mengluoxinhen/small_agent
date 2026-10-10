"""SQLite plumbing for the human-facing trace store (PLAN §7).

`SQLiteSession` (the SDK's) owns the *model's* memory in its own `sdk_*` tables; this
module owns what the *UI* replays: sessions, runs, events, approvals. Connections are
opened in autocommit mode (`isolation_level=None`) so transactions are explicit —
concurrent writers serialize on `BEGIN IMMEDIATE` instead of deadlocking.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    input_text TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    state_json TEXT,
    error TEXT,
    usage_json TEXT,
    turns INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    run_id TEXT NOT NULL REFERENCES runs(id),
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    approval_id TEXT NOT NULL UNIQUE,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    risk TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a trace-store connection; the file and parent directory are created."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Create the schema; safe to run repeatedly (everything is IF NOT EXISTS)."""
    conn.executescript(SCHEMA)
    # Databases predating the UI redesign have no `pinned` column: ALTER instead of
    # recreate, so existing sessions survive the upgrade (DEFAULT fills the rows).
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "pinned" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
