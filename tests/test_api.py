"""T5 — FastAPI surface: sessions, messages, approvals, cancel, error mapping.

The HTTP layer must stay thin: it validates input, delegates to `Runtime`, and maps
storage errors to status codes. Everything here runs against FakeModel injected via
`create_app(agent_factory=...)`; no network, deterministic.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from app.agent.factory import build_agent
from app.config import Settings
from app.main import create_app
from app.testing.fake_model import FakeModel, text_reply, tool_call_reply


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_api_key="",
        llm_base_url="http://127.0.0.1:9/v1",
        model_backend="fake",
        default_mode="review",
        data_dir=tmp_path / "data",
    )


def client_for(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def scripted_factory(scripts: list[list[Any]]):
    """Each new run consumes the next scripted FakeModel; mode selects the policy."""
    pending = list(scripts)

    def factory(mode: str) -> Any:
        return build_agent(model=FakeModel(pending.pop(0)), mode=mode)

    return factory


async def wait_run(client: httpx.AsyncClient, run_id: str, statuses: set[str], timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        resp = await client.get(f"/runs/{run_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last["status"] in statuses:
            return last
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} stuck; last state: {last}")


async def create_session(client: httpx.AsyncClient, **body: Any) -> str:
    resp = await client.post("/sessions", json={"title": "测试会话", **body})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------- sessions CRUD


async def test_session_crud_roundtrip(tmp_path: Path):
    app = create_app(make_settings(tmp_path), agent_factory=scripted_factory([]))
    async with client_for(app) as client:
        sid = await create_session(client)

        got = await client.get(f"/sessions/{sid}")
        assert got.status_code == 200
        assert got.json()["title"] == "测试会话"
        assert got.json()["mode"] == "review"

        patched = await client.patch(f"/sessions/{sid}", json={"mode": "full_access", "title": "改名"})
        assert patched.status_code == 200
        assert patched.json()["mode"] == "full_access" and patched.json()["title"] == "改名"

        listed = (await client.get("/sessions")).json()
        assert [s["id"] for s in listed] == [sid]

        assert (await client.delete(f"/sessions/{sid}")).status_code == 204
        assert (await client.get(f"/sessions/{sid}")).status_code == 404


async def test_unknown_session_message_is_404(tmp_path: Path):
    app = create_app(make_settings(tmp_path), agent_factory=scripted_factory([]))
    async with client_for(app) as client:
        resp = await client.post("/sessions/nope/messages", json={"text": "hi"})
        assert resp.status_code == 404


# ---------------------------------------------------------------- message runs


async def test_full_access_message_runs_to_success_with_tool_trace(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = create_app(
        settings,
        agent_factory=scripted_factory([[tool_call_reply("calculator", {"expression": "6*7"}), text_reply("42")]]),
    )
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "算 6*7"})
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        run = await wait_run(client, run_id, {"succeeded"})
        assert run["turns"] == 2
        assert "requests" in (run["usage_json"] or "")
        assert run["finished_at"]


async def test_review_write_pauses_then_approve_completes(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = create_app(
        settings,
        agent_factory=scripted_factory(
            [[tool_call_reply("write_text_file", {"filename": "a.txt", "content": "落地"}), text_reply("已写入")]]
        ),
    )
    async with client_for(app) as client:
        sid = await create_session(client)
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "写 a.txt"})
        run_id = resp.json()["run_id"]

        run = await wait_run(client, run_id, {"awaiting_approval"})
        assert run["status"] == "awaiting_approval"

        approvals = (await client.get(f"/runs/{run_id}/approvals")).json()
        assert len(approvals) == 1
        assert approvals[0]["decision"] == "pending"
        assert approvals[0]["tool_name"] == "write_text_file"
        assert approvals[0]["risk"] == "write"

        decided = await client.post(
            f"/runs/{run_id}/approvals", json={approvals[0]["approval_id"]: {"decision": "approve"}}
        )
        assert decided.status_code == 202
        await wait_run(client, run_id, {"succeeded"})

        workspace = settings.data_dir / "workspaces" / sid
        assert (workspace / "a.txt").read_text(encoding="utf-8") == "落地"

        approvals_after = (await client.get(f"/runs/{run_id}/approvals")).json()
        assert approvals_after[0]["decision"] == "approved"


async def test_approve_on_non_paused_run_is_409(tmp_path: Path):
    app = create_app(make_settings(tmp_path), agent_factory=scripted_factory([[text_reply("hi")]]))
    async with client_for(app) as client:
        sid = await create_session(client)
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "打招呼"})
        run_id = resp.json()["run_id"]
        await wait_run(client, run_id, {"succeeded"})

        denied = await client.post(f"/runs/{run_id}/approvals", json={"whatever": {"decision": "approve"}})
        assert denied.status_code == 409


# ---------------------------------------------------------------- cancel


async def test_cancel_paused_run_is_recorded(tmp_path: Path):
    app = create_app(
        make_settings(tmp_path),
        agent_factory=scripted_factory([[tool_call_reply("write_text_file", {"filename": "x", "content": "y"}), text_reply("?")]]),
    )
    async with client_for(app) as client:
        sid = await create_session(client)
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "写"})
        run_id = resp.json()["run_id"]
        await wait_run(client, run_id, {"awaiting_approval"})

        cancelled = await client.post(f"/runs/{run_id}/cancel")
        assert cancelled.status_code == 200
        assert (await client.get(f"/runs/{run_id}")).json()["status"] == "cancelled"

        again = await client.post(f"/runs/{run_id}/cancel")
        assert again.status_code == 409


class SlowFake(FakeModel):
    """First delta arrives promptly; then the run idles so cancel has a target."""

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        inner = super().stream_response(*args, **kwargs)

        async def gen() -> AsyncIterator[Any]:
            yield await inner.__anext__()
            await asyncio.sleep(30)
            async for event in inner:
                yield event

        return gen()


async def test_cancel_running_task_stops_the_loop(tmp_path: Path):
    fake = SlowFake([tool_call_reply("calculator", {"expression": "1+1"}), text_reply("永远不会到")])
    app = create_app(
        make_settings(tmp_path),
        agent_factory=lambda mode: build_agent(model=fake, mode="full_access"),
    )
    async with client_for(app) as client:
        sid = await create_session(client)
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "算"})
        run_id = resp.json()["run_id"]
        await wait_run(client, run_id, {"running"})

        await asyncio.sleep(0.15)  # the job must be inside its model wait now
        assert (await client.post(f"/runs/{run_id}/cancel")).status_code == 200
        assert (await wait_run(client, run_id, {"cancelled"}))["status"] == "cancelled"

        # A cancelled run must still close its event stream: the trace ends in a
        # terminal run_error so SSE subscribers don't tail forever.
        events = (await client.get(f"/sessions/{sid}/events?format=json")).json()
        errors = [e for e in events if e["type"] == "run_error"]
        assert errors and errors[-1]["payload"]["kind"] == "cancelled"


# ---------------------------------------------------------------- model failure


class BoomFake(FakeModel):
    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        import httpx as _httpx
        from openai import InternalServerError

        raise InternalServerError(
            "5xx from upstream",
            response=_httpx.Response(500, request=_httpx.Request("POST", "http://fake/v1/chat/completions")),
            body=None,  # APIStatusError requires the keyword; real SDKs pass the parsed body
        )


async def test_model_5xx_becomes_run_error_and_failed_run(tmp_path: Path):
    app = create_app(
        make_settings(tmp_path),
        agent_factory=lambda mode: build_agent(model=BoomFake([text_reply("x")]), mode="full_access"),
    )
    async with client_for(app) as client:
        sid = await create_session(client)
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "触发故障"})
        run_id = resp.json()["run_id"]

        run = await wait_run(client, run_id, {"failed"})
        assert run["error"]
        # The run_error event must be part of the persisted trace, not just the table.
        types = [e["type"] for e in (await client.get(f"/sessions/{sid}/events?format=json")).json()]
        assert "run_error" in types


# ---------------------------------------------------------------- conversation memory


async def test_second_message_model_sees_the_first_exchange(tmp_path: Path):
    """PLAN §7 dual persistence: the SDK `SQLiteSession` gives cross-message memory.

    The runtime must hand every run of one session the same SDK session, so the model
    is *shown* the previous exchange on the next turn — our trace tables are for humans.
    """
    models: list[FakeModel] = []

    def factory(mode: str) -> Any:
        model = FakeModel([text_reply("第一条回复"), text_reply("第二条回复")])
        models.append(model)
        return build_agent(model=model, mode=mode)

    app = create_app(make_settings(tmp_path), agent_factory=factory)
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        first = await client.post(f"/sessions/{sid}/messages", json={"text": "第一问"})
        await wait_run(client, first.json()["run_id"], {"succeeded"})
        second = await client.post(f"/sessions/{sid}/messages", json={"text": "第二问"})
        await wait_run(client, second.json()["run_id"], {"succeeded"})

    assert len(models) == 2
    prompt_seen_by_second_model = str(models[1].calls[0].input)
    assert "第一条回复" in prompt_seen_by_second_model
    assert "第一问" in prompt_seen_by_second_model


# ---------------------------------------------------------------- runtime seams


async def test_agent_factory_failure_becomes_a_failed_run_not_a_500(tmp_path: Path):
    """`setup` runs inside the pump: construction errors land in the trace, not HTTP."""

    def broken_factory(mode: str) -> Any:
        raise RuntimeError("模型不可用")

    app = create_app(make_settings(tmp_path), agent_factory=broken_factory)
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "任意"})
        assert resp.status_code == 202
        run = await wait_run(client, resp.json()["run_id"], {"failed"})
        assert "模型不可用" in run["error"]
        types = [e["type"] for e in (await client.get(f"/sessions/{sid}/events?format=json")).json()]
        assert types[0] == "run_started" or "run_error" in types
        assert "run_error" in types


async def test_deleting_a_session_cancels_and_erases_its_inflight_run(tmp_path: Path):
    fake = SlowFake([tool_call_reply("calculator", {"expression": "1+1"}), text_reply("永远不会到")])
    app = create_app(
        make_settings(tmp_path),
        agent_factory=lambda mode: build_agent(model=fake, mode=mode),
    )
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "算"})
        run_id = resp.json()["run_id"]
        await wait_run(client, run_id, {"running"})

        assert (await client.delete(f"/sessions/{sid}")).status_code == 204
        assert (await client.get(f"/sessions/{sid}")).status_code == 404
        assert (await client.get(f"/runs/{run_id}")).status_code == 404

        # The cancelled pump wakes *after* the rows are gone: it must swallow the
        # KeyError quietly instead of killing the server.
        await asyncio.sleep(0.3)
        assert (await client.get("/healthz")).status_code == 200


async def test_runtime_shutdown_cancels_inflight_runs(tmp_path: Path):
    """uvicorn lifespan -> `Runtime.shutdown()`; no zombie runs survive the server."""
    fake = SlowFake([tool_call_reply("calculator", {"expression": "1+1"}), text_reply("x")])
    app = create_app(
        make_settings(tmp_path),
        agent_factory=lambda mode: build_agent(model=fake, mode=mode),
    )
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "算"})
        run_id = resp.json()["run_id"]
        await wait_run(client, run_id, {"running"})

        await app.state.runtime.shutdown()
        assert (await client.get(f"/runs/{run_id}")).json()["status"] == "cancelled"
