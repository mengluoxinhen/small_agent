"""T6 — SSE endpoint: replay, Last-Event-ID resume, live tail to terminal.

These tests drive the ASGI app directly (no port binding): an `httpx.ASGITransport`
buffers whole bodies, which would hide exactly the streaming behavior under test. A
small raw-ASGI pump collects `http.response.body` frames as they arrive.

The SSE frame contract (PLAN §6): every persisted event becomes one frame
`id: <seq>\\nevent: <type>\\ndata: <payload json>\\n\\n`, so replay is exact and
`Last-Event-ID` resume is a plain seq filter.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.agent.factory import build_agent
from app.main import create_app
from app.testing.fake_model import text_reply, tool_call_reply

from tests.test_api import client_for, create_session, make_settings, scripted_factory, wait_run


async def sse_collect(
    app: Any,
    sid: str,
    *,
    last_event_id: int | None = None,
    via_query: bool = False,
    expect_status: int = 200,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Run one GET /sessions/{sid}/events through raw ASGI until the server ends it.

    `via_query` puts the resume cursor in `?last_event_id=` instead of the header — the
    path a browser's native EventSource must take, since it cannot set headers.
    """
    inbox: asyncio.Queue[dict] = asyncio.Queue()

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        await inbox.put(message)

    headers = [(b"accept", b"text/event-stream")]
    query = b""
    if last_event_id is not None:
        if via_query:
            query = f"last_event_id={last_event_id}".encode()
        else:
            headers.append((b"last-event-id", str(last_event_id).encode()))
    scope = {
        "type": "http",
        # 2.4 is what uvicorn speaks; at 2.3 starlette's legacy disconnect task group
        # busy-spins on a receive() that never suspends and starves the test loop.
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/sessions/{sid}/events",
        "raw_path": f"/sessions/{sid}/events".encode(),
        "query_string": query,
        "headers": headers,
        "client": ("test", 1234),
        "server": ("testserver", 80),
        "root_path": "",
    }
    task = asyncio.create_task(app(scope, receive, send))
    frames: list[dict[str, Any]] = []
    buffer = ""
    status: int | None = None
    ended = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not ended:
        try:
            message = await asyncio.wait_for(inbox.get(), timeout=0.1)
        except TimeoutError:
            continue
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            buffer += (message.get("body") or b"").decode("utf-8")
            new_frames, buffer = _parse_frames(buffer)
            frames.extend(new_frames)
            if not message.get("more_body", False):
                ended = True
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert status == expect_status, f"unexpected status {status}"
    return frames


def _parse_frames(buffer: str) -> tuple[list[dict[str, Any]], str]:
    """Split complete SSE frames (`\\n\\n` separated) off the buffer."""
    frames: list[dict[str, Any]] = []
    while "\n\n" in buffer:
        raw, buffer = buffer.split("\n\n", 1)
        frame: dict[str, Any] = {}
        for line in raw.splitlines():
            if line.startswith("id: "):
                frame["id"] = int(line[4:])
            elif line.startswith("event: "):
                frame["event"] = line[7:]
            elif line.startswith("data: "):
                frame["data"] = json.loads(line[6:])
        frames.append(frame)
    return frames, buffer


async def wait_terminal(client: Any, run_id: str) -> dict:
    return await wait_run(client, run_id, {"succeeded", "failed"})


async def test_sse_replay_returns_full_ordered_trace(tmp_path: Any):
    app = create_app(
        make_settings(tmp_path),
        agent_factory=scripted_factory([[tool_call_reply("calculator", {"expression": "6*7"}), text_reply("42")]]),
    )
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "算 6*7"})
        assert resp.status_code == 202, resp.text
        run_id = resp.json()["run_id"]
        await wait_terminal(client, run_id)

    frames = await sse_collect(app, sid)
    types = [f["event"] for f in frames]
    assert types[0] == "run_started"
    assert types[1] == "user_message"
    assert frames[1]["data"]["text"] == "算 6*7"
    assert types[-1] == "run_finished"
    assert "tool_call_start" in types
    assert "tool_result" in types
    # ids are the per-session dense seq: exactly 1..N, in order
    assert [f["id"] for f in frames] == list(range(1, len(frames) + 1))
    assert frames[0]["data"]["run_id"] == run_id
    assert frames[0]["data"]["mode"] == "full_access"
    assert frames[-1]["data"]["usage"]["requests"] >= 1


async def test_sse_last_event_id_resumes_from_the_next_seq(tmp_path: Any):
    app = create_app(
        make_settings(tmp_path),
        agent_factory=scripted_factory([[tool_call_reply("calculator", {"expression": "1+1"}), text_reply("2")]]),
    )
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "算"})
        await wait_terminal(client, resp.json()["run_id"])

    full = await sse_collect(app, sid)
    assert len(full) >= 5
    tail = await sse_collect(app, sid, last_event_id=3)
    assert [f["id"] for f in tail] == [f["id"] for f in full if f["id"] > 3]
    assert tail and tail[0]["id"] == 4


async def test_sse_query_last_event_id_matches_the_header_path(tmp_path: Any):
    """Native EventSource cannot set headers, so `?last_event_id=` must behave identically."""
    app = create_app(
        make_settings(tmp_path),
        agent_factory=scripted_factory([[tool_call_reply("calculator", {"expression": "2*3"}), text_reply("6")]]),
    )
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "算"})
        await wait_terminal(client, resp.json()["run_id"])

    via_header = await sse_collect(app, sid, last_event_id=3)
    via_query = await sse_collect(app, sid, last_event_id=3, via_query=True)
    assert [f["id"] for f in via_query] == [f["id"] for f in via_header]


async def test_sse_live_tail_streams_to_the_terminal_event(tmp_path: Any):
    """Connect while the run is still in flight: the stream must close on run_finished."""
    app = create_app(make_settings(tmp_path), agent_factory=scripted_factory([[text_reply("尾部实时")]]))
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "说一句"})
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

    # no wait: the SSE connection itself is what observes the run finishing
    frames = await sse_collect(app, sid)
    types = [f["event"] for f in frames]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"
    assert frames[-1]["data"]["usage"]["requests"] >= 1
    assert [f["id"] for f in frames] == list(range(1, len(frames) + 1))

    async with client_for(app) as client:
        run = await wait_run(client, run_id, {"succeeded"})
        assert run["turns"] == 1


async def test_sse_approval_pause_terminates_the_stream(tmp_path: Any):
    """approval_required is terminal-for-close: the UI reconnects after deciding."""
    app = create_app(
        make_settings(tmp_path),
        agent_factory=scripted_factory(
            [[tool_call_reply("write_text_file", {"filename": "s.txt", "content": "c"}), text_reply("已写入")]]
        ),
    )
    async with client_for(app) as client:
        sid = await create_session(client)
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "写文件"})
        run_id = resp.json()["run_id"]
        await wait_run(client, run_id, {"awaiting_approval"})

        frames = await sse_collect(app, sid)
        types = [f["event"] for f in frames]
        assert types[-1] == "approval_required"
        pause = frames[-1]["data"]
        assert pause["tool"] == "write_text_file"
        assert pause["risk"] == "write"
        assert pause["approval_id"]

        decided = await client.post(
            f"/runs/{run_id}/approvals", json={pause["approval_id"]: {"decision": "approve"}}
        )
        assert decided.status_code == 202
        await wait_run(client, run_id, {"succeeded"})

    tail = await sse_collect(app, sid, last_event_id=frames[-1]["id"])
    assert tail, "resumed run must produce events after the pause"
    assert tail[-1]["event"] == "run_finished"
    assert tail[0]["id"] == frames[-1]["id"] + 1


async def test_sse_unknown_session_is_404(tmp_path: Any):
    app = create_app(make_settings(tmp_path), agent_factory=scripted_factory([]))
    await sse_collect(app, "nope", expect_status=404)


async def test_sse_run_error_terminates_the_stream(tmp_path: Any):
    from tests.test_api import BoomFake

    app = create_app(
        make_settings(tmp_path),
        agent_factory=lambda mode: build_agent(model=BoomFake([text_reply("x")]), mode=mode),
    )
    async with client_for(app) as client:
        sid = await create_session(client, mode="full_access")
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "触发故障"})
        await wait_run(client, resp.json()["run_id"], {"failed"})

    frames = await sse_collect(app, sid)
    assert frames[-1]["event"] == "run_error"
    assert frames[-1]["data"]["kind"] == "model"
