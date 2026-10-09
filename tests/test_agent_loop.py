"""T3 — the agent core loop, driven entirely by FakeModel.

Every case here asserts the *project event contract* (§6): `stream_run` must yield
dicts of `{"type": ..., "payload": ...}` with the names run_started / tool_call_args /
tool_call_start / tool_call_end / tool_result / text_message_content / run_finished /
run_error, in the order the SDK's real stream produces them.

The loop itself is the SDK's `Runner.run_streamed`; what we own is the factory wiring
(system prompt + registry + model) and the translation layer the frontend will consume.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.agent.events import stream_run
from app.agent.factory import build_agent
from app.agent.prompts import SYSTEM_PROMPT
from app.testing.fake_model import FakeModel, text_reply, tool_call_reply
from app.tools.context import AppContext


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "ws"


async def collect(agent: Any, user_text: str, context: AppContext, **kwargs: Any) -> list[dict]:
    return [ev async for ev in stream_run(agent, user_text, context=context, **kwargs)]


def types_of(events: list[dict]) -> list[str]:
    return [event["type"] for event in events]


def make_agent(script: list, mode: str = "full_access"):
    """Factory-built agent on a scripted FakeModel; returns (agent, fake).

    Mode defaults to `full_access` because T3 tests the loop mechanics; the approval
    matrix itself lives in T2 (`test_approval.py`) and is asserted per mode there.
    """
    fake = FakeModel(script)
    return build_agent(model=fake, mode=mode), fake


# ---------------------------------------------------------------- happy paths


async def test_direct_answer_without_any_tool_call(workspace: Path):
    agent, _ = make_agent([text_reply("你好，我是助手")])
    events = await collect(agent, "打个招呼", AppContext(workspace=workspace))

    assert types_of(events)[0] == "run_started"
    assert types_of(events)[-1] == "run_finished"
    streamed_text = "".join(e["payload"]["delta"] for e in events if e["type"] == "text_message_content")
    assert streamed_text == "你好，我是助手"
    assert "tool_call_start" not in types_of(events)


async def test_single_tool_call_then_final_answer(workspace: Path):
    agent, fake = make_agent(
        [tool_call_reply("calculator", {"expression": "6*7"}), text_reply("答案是 42")],
    )
    events = await collect(agent, "算一下 6 乘 7", AppContext(workspace=workspace))
    by_type = {e["type"] for e in events}
    assert {"tool_call_start", "tool_result", "run_finished"} <= by_type

    start = next(e for e in events if e["type"] == "tool_call_start")
    assert start["payload"]["tool"] == "calculator"
    assert start["payload"]["risk"] == "read"

    result = next(e for e in events if e["type"] == "tool_result")
    assert result["payload"]["ok"] is True
    assert "42" in result["payload"]["output"]

    # The whole point of the loop: the tool output must reach the *next* model call.
    second_call_input = json.dumps(fake.calls[1].input, default=str, ensure_ascii=False)
    assert "42" in second_call_input


async def test_two_chained_tool_calls(workspace: Path):
    agent, fake = make_agent(
        [
            tool_call_reply("calculator", {"expression": "1+1"}),
            tool_call_reply("write_text_file", {"filename": "r.txt", "content": "答案是2"}),
            text_reply("已写入 r.txt"),
        ],
    )
    events = await collect(agent, "算 1+1 并把结果写进文件", AppContext(workspace=workspace))

    tool_starts = [e for e in events if e["type"] == "tool_call_start"]
    assert [t["payload"]["tool"] for t in tool_starts] == ["calculator", "write_text_file"]
    assert len(fake.calls) == 3
    assert (workspace / "r.txt").read_text(encoding="utf-8") == "答案是2"


async def test_run_opens_with_the_user_message_event(workspace: Path):
    """P7 finding: history replay had no user bubble — the user's own text was never
    a persisted contract event. The run now opens with run_started + user_message."""
    agent, _ = make_agent([text_reply("你好")])
    events = await collect(agent, "帮我看看这件事", AppContext(workspace=workspace))
    assert types_of(events)[0] == "run_started"
    assert types_of(events)[1] == "user_message"
    assert events[1]["payload"] == {"text": "帮我看看这件事"}


async def test_event_sequence_matches_the_contract(workspace: Path):
    """The skeleton order the UI replays on: started → user → tool → result → finished."""
    agent, _ = make_agent(
        [tool_call_reply("calculator", {"expression": "6*7"}), text_reply("答案是 42")],
    )
    events = await collect(agent, "算一下", AppContext(workspace=workspace))
    skeleton = [t for t in types_of(events) if t not in {"tool_call_args", "text_message_content"}]
    assert skeleton == [
        "run_started",
        "user_message",
        "tool_call_start",
        "tool_call_end",
        "tool_result",
        "run_finished",
    ]
    first_text_idx = next(i for i, e in enumerate(events) if e["type"] == "text_message_content")
    result_idx = next(i for i, e in enumerate(events) if e["type"] == "tool_result")
    assert result_idx < first_text_idx < len(events) - 1


# ---------------------------------------------------------------- failure paths


async def test_tool_exception_is_fed_back_and_the_loop_continues(workspace: Path):
    agent, fake = make_agent(
        [tool_call_reply("calculator", {"expression": "1/0"}), text_reply("除数是零，我换个写法")],
    )
    events = await collect(agent, "算 1 除以 0", AppContext(workspace=workspace))

    result = next(e for e in events if e["type"] == "tool_result")
    assert result["payload"]["ok"] is False
    assert "零" in result["payload"]["output"]

    assert types_of(events)[-1] == "run_finished"
    second_call_input = json.dumps(fake.calls[1].input, default=str, ensure_ascii=False)
    assert "调用失败" in second_call_input


async def test_max_turns_exceeded_becomes_run_error_not_a_crash(workspace: Path):
    script = [tool_call_reply("calculator", {"expression": "1+1"}) for _ in range(4)]
    agent, _ = make_agent(script)
    events = await collect(agent, "循环算", AppContext(workspace=workspace), max_turns=2)

    assert types_of(events)[-1] == "run_error"
    assert events[-1]["payload"]["kind"] == "max_turns"
    assert events[-1]["payload"]["message"]


async def test_model_error_becomes_run_error(workspace: Path):
    """Script ends after one tool call; the second model turn hits FakeScriptExhaustedError."""
    agent, _ = make_agent([tool_call_reply("calculator", {"expression": "1+1"})])
    events = await collect(agent, "然后呢", AppContext(workspace=workspace))

    assert types_of(events)[-1] == "run_error"
    assert events[-1]["payload"]["kind"] == "model"
    assert "run_finished" not in types_of(events)


# ---------------------------------------------------------------- wiring


async def test_factory_installs_the_chinese_system_prompt(workspace: Path):
    fake = FakeModel([text_reply("ok")])
    agent = build_agent(model=fake)
    await collect(agent, "你好", AppContext(workspace=workspace))

    instructions = fake.calls[0].system_instructions or ""
    assert instructions == SYSTEM_PROMPT
    # The two disciplines the product depends on must be in the prompt, verbatim-checked.
    assert "工具" in instructions
    assert "编造" in instructions


async def test_factory_registers_all_five_builtin_tools(workspace: Path):
    fake = FakeModel([text_reply("ok")])
    agent = build_agent(model=fake)
    await collect(agent, "你好", AppContext(workspace=workspace))
    tool_names = {name for name in fake.calls[0].all_tools}
    assert tool_names == {
        "calculator",
        "read_text_file",
        "write_text_file",
        "delete_session_file",
        "list_session_files",
    }


async def test_run_started_and_run_finished_payloads_carry_metadata(workspace: Path):
    agent, _ = make_agent([tool_call_reply("calculator", {"expression": "1+1"}), text_reply("2")])
    events = await collect(
        agent, "算", AppContext(workspace=workspace), run_id="run_42", mode="review", model_label="deepseek-chat"
    )

    started = events[0]["payload"]
    assert started == {"run_id": "run_42", "mode": "review", "model": "deepseek-chat"}

    finished = events[-1]["payload"]
    assert finished["turns"] == 2
    assert finished["usage"]["requests"] >= 2


@pytest.mark.live
async def test_real_deepseek_model_completes_a_tool_roundtrip(tmp_path: Path):
    """Manual acceptance: `uv run pytest -m live` with a real key in .env."""
    from app.config import get_settings
    from app.model import build_model

    settings = get_settings()
    agent = build_agent(model=build_model(settings))
    events = await collect(
        agent,
        "请使用计算器工具计算 12*12，然后把结果告诉我。",
        AppContext(workspace=tmp_path / "ws"),
        model_label=settings.llm_model,
    )
    assert types_of(events)[-1] == "run_finished"
    text = "".join(e["payload"]["delta"] for e in events if e["type"] == "text_message_content")
    assert "144" in text
