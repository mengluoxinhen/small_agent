"""Settings and their validation.

Two deliberate choices:

* `Settings` never reads `.env` by itself. Only `get_settings()` opts in, by pointing at
  the repo's `.env`. That way a unit test can build a `Settings` without accidentally
  picking up the developer's real DeepSeek key.
* Every failure raises `ConfigError` with a sentence that says what to do next, because
  config mistakes are the most common way this project fails to start on another machine.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]

RunMode = Literal["review", "full_access"]
ModelBackend = Literal["openai", "fake"]

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class ConfigError(RuntimeError):
    """Raised when the app cannot start from the current configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- model ---
    llm_api_key: str = ""
    llm_base_url: str = DEFAULT_BASE_URL
    llm_model: str = DEFAULT_MODEL
    model_backend: ModelBackend = "openai"

    # --- agent behaviour ---
    default_mode: RunMode = "review"
    max_turns: int = Field(default=25, ge=1, le=200)

    # --- storage ---
    data_dir: Path = REPO_ROOT / "data"
    log_level: str = "INFO"

    @field_validator("llm_base_url")
    @classmethod
    def _base_url_must_be_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"LLM_BASE_URL must start with http(s)://, got {value!r}")
        return value.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}, got {value!r}")
        return upper

    def require_api_key(self) -> str:
        """Return the API key, or explain how to get one into the environment."""
        if self.model_backend == "fake":
            return self.llm_api_key
        if not self.llm_api_key.strip():
            raise ConfigError(
                "LLM_API_KEY is not set. Copy .env.example to .env and paste your DeepSeek "
                "key there (or export LLM_API_KEY in your shell). To develop without any key, "
                "set MODEL_BACKEND=fake."
            )
        return self.llm_api_key

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    @property
    def database_path(self) -> Path:
        return self.ensure_data_dir() / "small_dify.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read once from environment + repo `.env`."""
    env_file = REPO_ROOT / ".env"
    return Settings(_env_file=env_file if env_file.exists() else None)


def reset_settings_cache() -> None:
    get_settings.cache_clear()
