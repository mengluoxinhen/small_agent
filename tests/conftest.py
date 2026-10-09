"""Shared fixtures for the small_dify test suite.

Project rule: nothing in this suite touches the network unless the test carries
`@pytest.mark.live`. Tests build `Settings` directly, and `Settings` never reads a
`.env` on its own — only `get_settings()` does — so a developer's real key can never
leak into a unit test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

MANAGED_ENV_KEYS = [
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "MODEL_BACKEND",
    "DEFAULT_MODE",
    "MAX_TURNS",
    "DATA_DIR",
    "LOG_LEVEL",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isolate every test from whatever the developer exported in their shell."""
    for key in MANAGED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def reset_settings_cache():
    from app.config import reset_settings_cache

    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def make_settings():
    """Build Settings with explicit values, ignoring any .env file on disk."""
    from app.config import Settings

    def _factory(**overrides):
        overrides.setdefault("_env_file", None)
        return Settings(**overrides)

    return _factory


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
