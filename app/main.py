"""FastAPI application factory: the HTTP surface over `Runtime` (PLAN §6, §10 P6).

The layer is deliberately thin: validate JSON, delegate to `Runtime`/`Store`, map
KeyError -> 404 and state-machine refusals -> 409. No agent logic lives here — runs
execute as background jobs, and the SSE endpoint is a pure replay-and-tail reader of
the `events` table, which is what makes `Last-Event-ID` resume exact.

`create_app(settings, *, agent_factory=...)` is the test seam: T5/T6 inject scripted
FakeModel factories, so the whole surface is exercised without any network. Production
wiring (`scripts/serve.py`) uses the default factory built from `Settings`.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from agents import Agent
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import db
from app.agent.factory import build_agent
from app.config import RunMode, Settings, get_settings
from app.model import build_model
from app.runtime import (
    AgentFactory,
    NotCancellableError,
    RunNotPausedError,
    Runtime,
)
from app.store import InvalidTransitionError, Store
from app.tools.errors import ToolInputError
from app.tools.impl.files import safe_path

MAX_UPLOAD_BYTES = 1_000_000

STREAM_CLOSE_EVENTS = frozenset({"run_finished", "run_error", "approval_required"})
"""Terminal-for-SSE-close: a client reconnects with Last-Event-ID after a pause."""

SSE_POLL_SECONDS = 15.0
"""Idle wake-up while tailing; also the cadence of disconnect checks."""


class SessionCreate(BaseModel):
    title: str = "新会话"
    mode: RunMode | None = None


class SessionPatch(BaseModel):
    title: str | None = None
    mode: RunMode | None = None
    pinned: bool | None = None


class AttachmentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class ApprovalChoice(BaseModel):
    decision: Literal["approve", "reject"]
    always: bool = False
    reason: str | None = None


def default_agent_factory(settings: Settings) -> AgentFactory:
    """Build the model lazily on the first run, one Agent per run (mode pins policy).

    Deferring `build_model` keeps `create_app()` alive without an API key: startup,
    /healthz and session CRUD stay usable, and the first message fails as a normal
    `run_error` event with `ConfigError`'s "how to fix this" sentence instead of
    refusing to boot.
    """
    memo: dict[str, Any] = {}

    def factory(mode: str) -> Agent:
        if "model" not in memo:
            memo["model"] = build_model(settings)
        return build_agent(model=memo["model"], mode=mode)

    return factory


def create_app(settings: Settings | None = None, *, agent_factory: AgentFactory | None = None) -> FastAPI:
    settings = settings or get_settings()
    conn = db.connect(settings.database_path)
    db.migrate(conn)
    store = Store(conn)
    runtime = Runtime(
        settings=settings,
        store=store,
        agent_factory=agent_factory or default_agent_factory(settings),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await runtime.shutdown()

    app = FastAPI(
        title="small_dify agent",
        version="0.1.0",
        description="Natural-language agent over self-written Python tools",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.runtime = runtime

    def _require_session(session_id: str) -> dict[str, Any]:
        try:
            return store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _require_run(run_id: str) -> dict[str, Any]:
        try:
            return store.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _decoded_event(row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["payload"] = json.loads(row.pop("payload_json"))
        return row

    # ------------------------------------------------------------- meta

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # ------------------------------------------------------------- sessions

    @app.post("/sessions", status_code=201)
    async def create_session(body: SessionCreate) -> dict[str, Any]:
        return runtime.create_session(title=body.title, mode=body.mode or settings.default_mode)

    @app.get("/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        return store.list_sessions()

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        return _require_session(session_id)

    @app.patch("/sessions/{session_id}")
    async def patch_session(session_id: str, body: SessionPatch) -> dict[str, Any]:
        _require_session(session_id)
        try:
            return store.update_session(session_id, **body.model_dump(exclude_none=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> None:
        _require_session(session_id)
        runtime.cancel_session_runs(session_id)
        store.delete_session(session_id)

    @app.post("/sessions/{session_id}/files", status_code=201)
    async def upload_attachment(session_id: str, body: AttachmentCreate) -> dict[str, Any]:
        """Put a user-attached file into the session workspace (base64 JSON, no new deps).

        The agent then sees it through the existing list/read tools; filenames go
        through the same workspace-conf validation as the tools, so `../` never escapes.
        """
        _require_session(session_id)
        workspace = runtime.workspace_for(session_id)
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            payload = base64.b64decode(body.content_base64, validate=True)
        except binascii.Error as exc:
            raise HTTPException(status_code=400, detail="content_base64 不是合法的 base64") from exc
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"附件过大：{len(payload)} 字节，上限 {MAX_UPLOAD_BYTES} 字节",
            )
        try:
            target = safe_path(workspace, body.filename)
        except ToolInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        target.write_bytes(payload)
        return {"filename": target.name, "bytes": len(payload)}

    # ------------------------------------------------------------- runs

    @app.post("/sessions/{session_id}/messages", status_code=202)
    async def post_message(session_id: str, body: MessageCreate) -> dict[str, str]:
        session = _require_session(session_id)
        return {"run_id": runtime.start_message(session, body.text)}

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        return _require_run(run_id)

    @app.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, str]:
        _require_run(run_id)
        try:
            runtime.cancel_run(run_id)
        except NotCancellableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "cancelled"}

    # ------------------------------------------------------------- approvals

    @app.get("/runs/{run_id}/approvals")
    async def list_approvals(run_id: str) -> list[dict[str, Any]]:
        _require_run(run_id)
        return [
            {**row, "arguments": json.loads(row["arguments_json"])}
            for row in store.list_approvals(run_id)
        ]

    @app.post("/runs/{run_id}/approvals", status_code=202)
    async def decide_approvals(run_id: str, body: dict[str, ApprovalChoice]) -> dict[str, str]:
        run = _require_run(run_id)
        # Order matters: a decision for a run that is not paused is 409 no matter which
        # approval ids are in the body; ownership (404) is only checked while paused.
        if run["status"] != "awaiting_approval":
            raise HTTPException(
                status_code=409,
                detail=f"run 当前状态为 {run['status']}，不在等待审批",
            )
        owned = {row["approval_id"] for row in store.list_approvals(run_id)}
        unknown = sorted(set(body) - owned)
        if unknown:
            raise HTTPException(status_code=404, detail=f"审批不属于该 run：{', '.join(unknown)}")
        decisions = {key: choice.model_dump() for key, choice in body.items()}
        try:
            runtime.resume_with_decisions(run_id, decisions)
        except (RunNotPausedError, InvalidTransitionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "resumed"}

    # ------------------------------------------------------------- events (SSE)

    @app.get("/sessions/{session_id}/events")
    async def session_events(
        session_id: str,
        request: Request,
        fmt: str | None = Query(default=None, alias="format"),
    ) -> Any:
        _require_session(session_id)
        after_seq = _last_event_id(request)

        if fmt == "json":
            return [_decoded_event(e) for e in store.list_events(session_id, after_seq=after_seq)]

        queue = runtime.subscribe(session_id)

        async def tail() -> AsyncIterator[str]:
            cursor = after_seq
            try:
                while True:
                    rows = store.list_events(session_id, after_seq=cursor)
                    for row in rows:
                        cursor = int(row["seq"])
                        yield _sse_frame(row)
                        if row["type"] in STREAM_CLOSE_EVENTS:
                            return
                    if await request.is_disconnected():
                        return
                    try:
                        # Woken by the runtime when new events land; the timeout only
                        # bounds how long a silent tail waits before re-checking.
                        await asyncio.wait_for(queue.get(), timeout=SSE_POLL_SECONDS)
                    except TimeoutError:
                        pass
                    while not queue.empty():
                        queue.get_nowait()
            finally:
                runtime.unsubscribe(session_id, queue)

        return StreamingResponse(
            tail(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _sse_frame(row: dict[str, Any]) -> str:
    data = json.dumps(json.loads(row["payload_json"]), ensure_ascii=False)
    return f"id: {row['seq']}\nevent: {row['type']}\ndata: {data}\n\n"


def _last_event_id(request: Request) -> int:
    """Resume cursor: standard header first, then the `last_event_id` query param.

    The query form exists because a browser's native EventSource cannot set headers;
    garbage in either place means "from the beginning" rather than a 400.
    """
    raw = request.headers.get("last-event-id") or request.query_params.get("last_event_id") or ""
    try:
        return max(0, int(raw))
    except ValueError:
        return 0
