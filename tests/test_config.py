"""P1 — configuration layer.

Configuration is where a "runs on someone's laptop" project dies, so the failure modes
matter more than the happy path: a missing key must produce a sentence a human can act on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import ConfigError, Settings, get_settings, reset_settings_cache
from pydantic import ValidationError


def test_defaults_target_deepseek(make_settings):
    s = make_settings()
    assert s.llm_base_url == "https://api.deepseek.com"
    assert s.llm_model == "deepseek-chat"
    assert s.model_backend == "openai"


def test_default_mode_is_review_for_safety(make_settings):
    assert make_settings().default_mode == "review"


def test_max_turns_has_a_sane_default(make_settings):
    assert make_settings().max_turns == 25


def test_reads_values_from_environment(make_settings, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-from-shell")
    monkeypatch.setenv("LLM_MODEL", "deepseek-reasoner")
    s = make_settings()
    assert s.llm_api_key == "sk-from-shell"
    assert s.llm_model == "deepseek-reasoner"


def test_reads_values_from_a_dotenv_file(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("LLM_API_KEY=sk-from-file\nLLM_MODEL=deepseek-chat\nDEFAULT_MODE=full_access\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.llm_api_key == "sk-from-file"
    assert s.default_mode == "full_access"


def test_settings_do_not_read_dotenv_on_their_own(repo_root: Path, monkeypatch):
    """`get_settings()` opts into .env; bare `Settings()` must not, or unit tests leak keys."""
    env = repo_root / ".env"
    created = False
    if not env.exists():
        env.write_text("LLM_API_KEY=sk-must-not-leak\n", encoding="utf-8")
        created = True
    try:
        assert Settings(_env_file=None).llm_api_key == ""
        assert get_settings().llm_api_key == "sk-must-not-leak"
    finally:
        if created:
            env.unlink()
        reset_settings_cache()


def test_unknown_backend_is_rejected(make_settings):
    with pytest.raises(ValidationError):
        make_settings(model_backend="anthropic")


def test_unknown_mode_is_rejected(make_settings):
    with pytest.raises(ValidationError):
        make_settings(default_mode="yolo")


def test_non_numeric_max_turns_is_rejected(make_settings):
    with pytest.raises(ValidationError):
        make_settings(max_turns="lots")


def test_negative_max_turns_is_rejected(make_settings):
    with pytest.raises(ValidationError):
        make_settings(max_turns=-1)


def test_require_api_key_gives_an_actionable_message(make_settings):
    s = make_settings(llm_api_key="")
    with pytest.raises(ConfigError) as exc:
        s.require_api_key()
    message = str(exc.value)
    assert "LLM_API_KEY" in message
    assert ".env.example" in message, "tell the user where to copy the template from"


def test_require_api_key_returns_the_key(make_settings):
    assert make_settings(llm_api_key="sk-good").require_api_key() == "sk-good"


def test_data_dir_is_created_on_demand(make_settings, tmp_data_dir: Path):
    s = make_settings(data_dir=tmp_data_dir)
    resolved = s.ensure_data_dir()
    assert resolved == tmp_data_dir.resolve() or resolved == tmp_data_dir
    assert resolved.is_dir()


def test_get_settings_is_cached_until_reset(make_settings, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "first")
    a = get_settings()
    b = get_settings()
    assert a is b, "get_settings must be cached (it is called per request)"
    monkeypatch.setenv("LLM_MODEL", "second")
    assert get_settings().llm_model == "first", "cache is intentional"
    reset_settings_cache()
    assert get_settings().llm_model == "second"
