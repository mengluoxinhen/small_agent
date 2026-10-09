"""P1 — model client factory and the deterministic fake model.

Two things are under test here:

1. `build_model()` wires Settings into an Agents-SDK `Model` without any network I/O.
2. `FakeModel` is a *real* implementation of the SDK's `Model` interface. Every later
   phase (P3 loop, P4 approval, P6 API) drives the agent with it, so it must be tested
   like production code, not trusted like a stub.
"""

from __future__ import annotations

import pytest
from agents.items import ModelResponse
from agents.models.interface import Model, ModelTracing
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from app.config import ConfigError
from app.model import build_model
from app.testing.fake_model import FakeModel, FakeScriptExhaustedError, text_reply, tool_call_reply


def _model_settings():
    from agents.agent import ModelSettings

    return ModelSettings()


def _kwargs():
    """The trailing keyword args the SDK always passes to a Model."""
    return {"previous_response_id": None, "conversation_id": None, "prompt": None}


async def _get_response(model, *, instructions="sys", input="hi", tools=None):
    return await model.get_response(
        instructions,
        input,
        _model_settings(),
        tools or [],
        None,
        [],
        ModelTracing.DISABLED,
        **_kwargs(),
    )


# ---------------------------------------------------------------- build_model


def test_build_model_returns_chat_completions_model_for_openai_backend(make_settings):
    s = make_settings(llm_api_key="sk-test", model_backend="openai")
    model = build_model(s)
    assert isinstance(model, OpenAIChatCompletionsModel)
    assert model.model == s.llm_model


def test_build_model_applies_the_configured_base_url(make_settings):
    s = make_settings(llm_api_key="sk-test", llm_base_url="https://api.deepseek.com/v1")
    model = build_model(s)
    # Reaching into `_client` is deliberate: the factory's whole job is to prove the
    # endpoint actually landed on the underlying async client.
    assert str(model._client.base_url).rstrip("/") == "https://api.deepseek.com/v1"


def test_build_model_applies_the_api_key(make_settings):
    s = make_settings(llm_api_key="sk-secret-value")
    model = build_model(s)
    assert model._client.api_key == "sk-secret-value"


def test_build_model_without_a_key_raises_a_clear_config_error(make_settings):
    s = make_settings(llm_api_key="", model_backend="openai")
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        build_model(s)


def test_fake_backend_needs_no_api_key(make_settings):
    s = make_settings(llm_api_key="", model_backend="fake")
    assert isinstance(build_model(s), FakeModel)


def test_building_the_model_performs_no_network_io(make_settings):
    """Construction must be side-effect free: FastAPI builds models at import/startup."""
    build_model(make_settings(llm_api_key="sk-test"))  # no exception, no request


# ---------------------------------------------------------------- FakeModel


def test_fake_model_implements_the_sdk_model_interface():
    assert issubclass(FakeModel, Model)
    assert not getattr(FakeModel, "__abstractmethods__", set()), "FakeModel must be instantiable"


async def test_fake_model_returns_scripted_text_reply(make_settings):
    model = FakeModel([text_reply("结果是 3")])
    response = await _get_response(model)
    assert isinstance(response, ModelResponse)
    assert response.output[0].content[0].text == "结果是 3"


async def test_fake_model_returns_scripted_tool_call():
    model = FakeModel([tool_call_reply("calculator", {"expression": "1+1"})])
    response = await _get_response(model)
    call = response.output[0]
    assert call.type == "function_call"
    assert call.name == "calculator"
    assert call.arguments == '{"expression":"1+1"}'


async def test_fake_model_walks_the_script_in_order_and_records_every_call():
    model = FakeModel(
        [
            tool_call_reply("calculator", {"expression": "1+1"}),
            text_reply("最终答案 2"),
        ]
    )
    first = await _get_response(model, input="帮我算 1+1")
    second = await _get_response(model, input=[{"role": "user", "content": "帮我算 1+1"}])
    assert first.output[0].type == "function_call"
    assert second.output[0].type == "message"
    assert len(model.calls) == 2
    assert model.calls[0].system_instructions == "sys"
    assert model.calls[1].input == [{"role": "user", "content": "帮我算 1+1"}]


async def test_fake_model_exhausting_its_script_fails_loudly():
    """Silent repetition would make loop tests pass for the wrong reason."""
    model = FakeModel([text_reply("only one turn")])
    await _get_response(model)
    with pytest.raises(FakeScriptExhaustedError, match="turn 2"):
        await _get_response(model)


async def test_fake_model_without_a_script_replies_with_a_default_text():
    model = FakeModel()
    response = await _get_response(model, input="hi")
    assert response.output[0].content[0].text
    assert model.calls[0].input == "hi"


async def test_fake_model_stream_response_is_an_async_iterator_of_deltas():
    model = FakeModel([text_reply("你好世界")])
    chunks = []
    agen = model.stream_response(
        "sys",
        "hi",
        _model_settings(),
        [],
        None,
        [],
        ModelTracing.DISABLED,
        **_kwargs(),
    )
    async for event in agen:
        chunks.append(event)
    assert chunks, "stream_response must yield at least one event"
    assert "".join(getattr(e, "delta", "") for e in chunks) == "你好世界"


async def test_fake_model_reports_usage_so_the_ui_can_show_tokens():
    model = FakeModel([text_reply("x")])
    response = await _get_response(model)
    assert response.usage.requests == 1
    assert response.usage.output_tokens >= 0


def test_tool_call_reply_generates_stable_distinct_call_ids():
    a = tool_call_reply("t", {})
    b = tool_call_reply("t", {})
    ids = {o.call_id for o in a.output} | {o.call_id for o in b.output}
    assert len(ids) == 2, "each scripted tool call needs its own call_id"
