"""T2 — approval policy and the two run modes (PLAN §5 matrix).

Six matrix cells are asserted as a pure function first, then through the real SDK loop:
`review` pauses `write`/`dangerous` tools into `approval_required` events whose RunState
JSON survives a to_json/from_json round trip; decisions resume or reject the run without
the caller ever seeing a raised exception from the loop itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agents import RunState
from app.agent.approval import should_pause
from app.agent.events import StateRestoreError, resume_run, stream_run
from app.agent.factory import build_agent
from app.testing.fake_model import FakeModel, text_reply, tool_call_reply
from app.tools.context import AppContext


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


async def collect(agent: Any, text: str, context: AppContext, states: list | None = None, **kw: Any) -> list[dict]:
    """Drive stream_run to completion, optionally capturing paused RunState dicts."""
    sink = states if states is not None else []
    return [ev async for ev in stream_run(agent, text, context=context, on_state=sink.append, **kw)]


def types_of(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def build(script: list, mode: str):
    fake = FakeModel(script)
    return build_agent(model=fake, mode=mode), fake


# ---------------------------------------------------------------- matrix (pure)


@pytest.mark.parametrize(
    ("risk", "mode", "pauses"),
    [
        ("read", "full_access", False),
        ("write", "full_access", False),
        ("dangerous", "full_access", False),
        ("read", "review", False),
        ("write", "review", True),
        ("dangerous", "review", True),
    ],
)
def test_full_mode_risk_matrix(risk: str, mode: str, pauses: bool):
    assert should_pause(risk, mode) is pauses


# ---------------------------------------------------------------- review mode


async def test_review_runs_read_tools_without_pausing(workspace: Path):
    agent, _ = build([tool_call_reply("calculator", {"expression": "6*7"}), text_reply("42")], "review")
    events = await collect(agent, "算一下", AppContext(workspace=workspace))

    assert "approval_required" not in types_of(events)
    assert types_of(events)[-1] == "run_finished"


async def test_review_pauses_write_tool_and_emits_approval_required(workspace: Path):
    agent, _ = build([tool_call_reply("write_text_file", {"filename": "a.txt", "content": "hi"}), text_reply("...")], "review")
    states: list[dict] = []
    events = await collect(agent, "写个文件", AppContext(workspace=workspace), states)

    assert types_of(events)[-1] == "approval_required"
    assert "run_finished" not in types_of(events)
    payload = events[-1]["payload"]
    assert payload["tool"] == "write_text_file"
    assert payload["risk"] == "write"
    assert payload["arguments"] == {"filename": "a.txt", "content": "hi"}
    assert payload["approval_id"]

    # Paused means NOT executed: the file must not exist yet.
    assert not (workspace / "a.txt").exists()
    # And the caller received a resume token.
    assert len(states) == 1 and isinstance(states[0], dict)


async def test_runstate_roundtrip_keeps_identical_interruptions(workspace: Path):
    agent, _ = build([tool_call_reply("delete_session_file", {"filename": "x.txt"}), text_reply("...")], "review")
    states: list[dict] = []
    ctx = AppContext(workspace=workspace)
    events = await collect(agent, "删掉 x.txt", ctx, states)
    assert events[-1]["payload"]["risk"] == "dangerous"

    restored = await RunState.from_json(agent, states[0], context_override=ctx)
    original_ids = [e["payload"]["approval_id"] for e in events if e["type"] == "approval_required"]
    restored_ids = [i.raw_item.call_id for i in restored.get_interruptions()]
    assert restored_ids == original_ids


async def test_approve_resumes_and_executes_the_tool(workspace: Path):
    script = [tool_call_reply("write_text_file", {"filename": "ok.txt", "content": "落地"}), text_reply("已写入")]
    agent, _ = build(script, "review")
    ctx = AppContext(workspace=workspace)
    states: list[dict] = []
    paused = await collect(agent, "写 ok.txt", ctx, states)
    approval_id = paused[-1]["payload"]["approval_id"]

    resumed = [
        ev
        async for ev in resume_run(agent, states[0], decisions={approval_id: {"decision": "approve"}}, context=ctx)
    ]

    assert "tool_result" in types_of(resumed)
    assert types_of(resumed)[-1] == "run_finished"
    assert (workspace / "ok.txt").read_text(encoding="utf-8") == "落地"


async def test_reject_feeds_the_reason_back_to_the_model(workspace: Path):
    script = [
        tool_call_reply("write_text_file", {"filename": "no.txt", "content": "x"}),
        text_reply("好的，我不写了"),
    ]
    agent, fake = build(script, "review")
    ctx = AppContext(workspace=workspace)
    states: list[dict] = []
    paused = await collect(agent, "写 no.txt", ctx, states)
    approval_id = paused[-1]["payload"]["approval_id"]

    resumed = [
        ev
        async for ev in resume_run(
            agent,
            states[0],
            decisions={approval_id: {"decision": "reject", "reason": "用户拒绝：不要创建这个文件"}},
            context=ctx,
        )
    ]

    assert types_of(resumed)[-1] == "run_finished"
    assert not (workspace / "no.txt").exists()
    next_input = json.dumps(fake.calls[-1].input, default=str, ensure_ascii=False)
    assert "用户拒绝：不要创建这个文件" in next_input


async def test_always_approve_stops_asking_for_the_same_tool(workspace: Path):
    script = [
        tool_call_reply("write_text_file", {"filename": "f1.txt", "content": "1"}),
        tool_call_reply("write_text_file", {"filename": "f2.txt", "content": "2"}),
        text_reply("两个都写了"),
    ]
    agent, _ = build(script, "review")
    ctx = AppContext(workspace=workspace)
    states: list[dict] = []
    paused = await collect(agent, "写两个文件", ctx, states)
    approval_id = paused[-1]["payload"]["approval_id"]

    resumed = [
        ev
        async for ev in resume_run(
            agent, states[0], decisions={approval_id: {"decision": "approve", "always": True}}, context=ctx
        )
    ]

    results = [e for e in resumed if e["type"] == "tool_result"]
    # Both executed inside the resumed stream: the approved call itself plus the
    # follow-up that always_approve let through without a second pause.
    assert len(results) == 2
    assert "approval_required" not in types_of(resumed)
    assert types_of(resumed)[-1] == "run_finished"
    assert (workspace / "f1.txt").exists() and (workspace / "f2.txt").exists()


async def test_unanswered_approval_is_rejected_by_default(workspace: Path):
    agent, _ = build([tool_call_reply("write_text_file", {"filename": "u.txt", "content": "?"}), text_reply("算了")], "review")
    ctx = AppContext(workspace=workspace)
    states: list[dict] = []
    await collect(agent, "写 u.txt", ctx, states)

    resumed = [ev async for ev in resume_run(agent, states[0], decisions={}, context=ctx)]

    assert types_of(resumed)[-1] == "run_finished"
    assert not (workspace / "u.txt").exists()


# ---------------------------------------------------------------- full_access


async def test_full_access_executes_dangerous_tool_without_pausing(workspace: Path):
    (workspace / "doomed.txt").write_text("bye", encoding="utf-8")
    agent, _ = build([tool_call_reply("delete_session_file", {"filename": "doomed.txt"}), text_reply("已删除")], "full_access")
    events = await collect(agent, "删掉 doomed.txt", AppContext(workspace=workspace))

    assert "approval_required" not in types_of(events)
    assert types_of(events)[-1] == "run_finished"
    assert not (workspace / "doomed.txt").exists()


# ---------------------------------------------------------------- broken state


@pytest.mark.parametrize("bad_state", [None, {}, "not-a-dict", {"junk": True}])
async def test_corrupted_state_raises_clear_error_not_a_crash(workspace: Path, bad_state: Any):
    agent, _ = build([text_reply("unused")], "review")
    with pytest.raises(StateRestoreError, match="审批状态"):
        [ev async for ev in resume_run(agent, bad_state, decisions={}, context=AppContext(workspace=workspace))]
