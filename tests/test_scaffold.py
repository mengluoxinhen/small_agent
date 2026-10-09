"""P0 — the project skeleton must be real, not aspirational.

These are the first tests written for this repo: they were RED before `app/` existed,
and they stay green as a tripwire if the layout ever drifts.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from app.main import create_app

REQUIRED_DIRS = ["app", "app/testing", "tests", "scripts", "docs", "frontend/src"]


@pytest.mark.parametrize("rel", REQUIRED_DIRS)
def test_directory_exists(repo_root: Path, rel: str):
    path = repo_root / rel
    assert path.is_dir(), f"missing directory: {path}"


def test_plan_document_exists(repo_root: Path):
    plan = repo_root / "docs" / "PLAN.md"
    assert plan.is_file(), "docs/PLAN.md is the source of truth and must exist"
    text = plan.read_text(encoding="utf-8")
    for phase in ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"):
        assert phase in text, f"PLAN.md lost phase {phase}"


def test_git_repository_initialised(repo_root: Path):
    assert (repo_root / ".git").is_dir(), "run: git init"


def test_gitignore_protects_env_and_venv(repo_root: Path):
    text = (repo_root / ".gitignore").read_text(encoding="utf-8")
    for entry in (".env", ".venv", "node_modules", "data/"):
        assert entry in text, f".gitignore must exclude {entry}"


def test_env_example_documents_all_settings_keys(repo_root: Path):
    text = (repo_root / ".env.example").read_text(encoding="utf-8")
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "MODEL_BACKEND", "DEFAULT_MODE", "MAX_TURNS"):
        assert key in text, f".env.example must document {key}"


def test_pytest_is_configured_to_find_app_package(repo_root: Path):
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'pythonpath = ["."]' in pyproject, "tests import `app` from the repo root"
    assert "live" in pyproject, "the `live` marker must be registered"


def test_frontend_is_a_vite_vue3_js_project_with_vitest(repo_root: Path):
    pkg = json.loads((repo_root / "frontend" / "package.json").read_text(encoding="utf-8"))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert "vue" in deps, "frontend must depend on vue"
    assert "vitest" in deps, "frontend must have a test runner"
    assert "test" in pkg.get("scripts", {}), 'package.json needs a "test" script'
    # Plain JavaScript, as decided: no typescript in the frontend dependency set.
    assert "typescript" not in deps, "frontend was agreed to be JS, not TS"


async def test_healthz_endpoint_answers_200():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_app_is_a_factory_not_a_module_singleton():
    assert create_app() is not create_app(), "each call returns a fresh app (needed for test isolation)"
