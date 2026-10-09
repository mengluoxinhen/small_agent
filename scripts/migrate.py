"""Idempotent migration entry point: `uv run python scripts/migrate.py [db-path]`.

Default path comes from the same `Settings` the app boots with (repo `.env` respected),
so the CLI and `create_app()` can never diverge into two different databases. Re-running
is always safe — the whole schema is `IF NOT EXISTS`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.db import connect, migrate


def main() -> int:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        from app.config import get_settings

        path = get_settings().database_path
    conn = connect(path)
    migrate(conn)
    tables = sorted(
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    )
    conn.close()
    print(f"migrated {path}: {', '.join(tables)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
