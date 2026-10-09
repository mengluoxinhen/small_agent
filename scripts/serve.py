"""Dev server entry: `uvicorn scripts.serve:app --reload` from the repo root.

Keeps `app.main` import-clean (no settings side effects at import time), while this
module deliberately *does* the production wiring: repo `.env` -> `get_settings()`.
For a key-free demo run, set `MODEL_BACKEND=fake` in the environment.
"""

from __future__ import annotations

from app.main import create_app

app = create_app()
