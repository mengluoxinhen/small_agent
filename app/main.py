"""FastAPI application factory.

`create_app()` is a factory rather than a module-level singleton so that tests can build
an isolated app per case. Routes arrive in P6; P0 only needs proof that the app can be
built and served.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="small_dify agent",
        version="0.1.0",
        description="Natural-language agent over self-written Python tools",
    )
    app.state.settings = settings or get_settings()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
