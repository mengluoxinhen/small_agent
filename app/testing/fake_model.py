"""Deterministic stand-in for a real LLM, used by tests and by `MODEL_BACKEND=fake`.

This is production code, not a throwaway stub: from P3 onwards the agent loop, the
approval flow and the SSE contract are all tested against it. It is a genuine
implementation of `agents.models.interface.Model`, so the Agents SDK drives it exactly
the way it drives DeepSeek.

Design constraints that make it trustworthy:

* It replays a **script** of turns in order. Running out of script raises
  `FakeScriptExhaustedError` instead of repeating itself — a silently repeating fake
  would let loop tests pass for the wrong reason.
* Every call is recorded in `.calls`, so a test can assert what the model was actually
  shown (e.g. "the tool result was fed back into the next turn").
"""

from __future__ import annotations

import itertools
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from agents.exceptions import ModelBehaviorError
from agents.items import ModelResponse
from agents.model_settings import ModelSettings
from agents.models.interface import Model, ModelTracing
from agents.usage import Usage
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseTextDeltaEvent,
    ResponseUsage,
)
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails

_counter = itertools.count(1)

DEFAULT_REPLY = "（fake model）已收到，但没有更多脚本回合。"


def _dumps(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))


def text_reply(text: str) -> ModelResponse:
    """A scripted turn where the model just answers in plain text."""
    message = ResponseOutputMessage(
        type="message",
        id=f"msg_fake_{next(_counter)}",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )
    return ModelResponse(
        output=[message],
        usage=Usage(requests=1, input_tokens=10, output_tokens=max(1, len(text))),
        response_id=None,
    )


def tool_call_reply(name: str, arguments: dict[str, Any] | None = None) -> ModelResponse:
    """A scripted turn where the model asks to run one tool."""
    call = ResponseFunctionToolCall(
        type="function_call",
        call_id=f"call_fake_{next(_counter)}",
        name=name,
        arguments=_dumps(arguments or {}),
    )
    return ModelResponse(
        output=[call],
        usage=Usage(requests=1, input_tokens=10, output_tokens=5),
        response_id=None,
    )


@dataclass
class RecordedCall:
    """What the SDK actually passed to the model on one turn."""

    system_instructions: str | None
    input: Any
    tools: list[Any]
    model_settings: ModelSettings
    all_tools: list[str] = field(default_factory=list)


class FakeScriptExhaustedError(ModelBehaviorError):
    """Raised when the script has no more turns but the agent keeps calling the model.

    Subclasses the SDK's `ModelBehaviorError` deliberately: the streaming runner ships
    model-side failures out of `stream_events()` through that channel, so a "fake model
    ran out of answers" surfaces as exactly the same *kind* of failure a real provider
    timeout or malformed response would — which is what the event contract asserts.
    """


class FakeModel(Model):
    def __init__(self, script: Sequence[ModelResponse] | None = None, *, default_reply: str = DEFAULT_REPLY):
        self._script = list(script) if script is not None else []
        self._default_reply = default_reply
        self.calls: list[RecordedCall] = []

    # ------------------------------------------------------------- interface

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: ModelSettings,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> ModelResponse:
        self._record(system_instructions, input, model_settings, tools)
        return self._next_response()

    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: ModelSettings,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> AsyncIterator[Any]:
        self._record(system_instructions, input, model_settings, tools)
        response = self._next_response()
        return self._emit(response)

    # ------------------------------------------------------------- internals

    def _record(self, system_instructions, input, model_settings, tools) -> None:
        self.calls.append(
            RecordedCall(
                system_instructions=system_instructions,
                input=input,
                tools=list(tools),
                model_settings=model_settings,
                all_tools=[getattr(t, "name", getattr(t, "function", None)) for t in tools],
            )
        )

    def _next_response(self) -> ModelResponse:
        turn = len(self.calls)
        if self._script:
            if turn > len(self._script):
                raise FakeScriptExhaustedError(
                    f"FakeModel script exhausted: no scripted response for turn {turn}, "
                    f"script holds {len(self._script)} turn(s)."
                )
            return self._script[turn - 1]
        return text_reply(self._default_reply)

    async def _emit(self, response: ModelResponse):
        """Turn a scripted response into OpenAI-Responses-style stream events.

        The streaming runner ignores bare deltas: it only assembles a turn once it has
        seen `response.output_item.done` events and a terminal `response.completed`.
        (P3 probe learned this the hard way: delta-only emission dies with
        "Model did not produce a final response!".)
        """
        sequence = 0
        for output_index, item in enumerate(response.output):
            sequence += 1
            yield ResponseOutputItemAddedEvent(
                type="response.output_item.added",
                output_index=output_index,
                item=item,
                sequence_number=sequence,
            )
            if item.type == "message":
                for block in item.content:
                    for char in block.text:
                        sequence += 1
                        yield ResponseTextDeltaEvent(
                            type="response.output_text.delta",
                            delta=char,
                            item_id=item.id,
                            content_index=0,
                            output_index=output_index,
                            sequence_number=sequence,
                            logprobs=[],
                        )
            elif item.type == "function_call":
                sequence += 1
                yield ResponseFunctionCallArgumentsDeltaEvent(
                    type="response.function_call_arguments.delta",
                    delta=item.arguments,
                    item_id=item.call_id,
                    output_index=output_index,
                    sequence_number=sequence,
                )
            sequence += 1
            yield ResponseOutputItemDoneEvent(
                type="response.output_item.done",
                output_index=output_index,
                item=item,
                sequence_number=sequence,
            )

        sequence += 1
        yield ResponseCompletedEvent(
            type="response.completed",
            response=Response(
                id=response.response_id or f"resp_fake_{next(_counter)}",
                model="fake",
                object="response",
                created_at=0,
                output=list(response.output),
                parallel_tool_calls=True,
                tool_choice="auto",
                tools=[],
                status="completed",
                usage=ResponseUsage(
                    input_tokens=response.usage.input_tokens if response.usage else 0,
                    output_tokens=response.usage.output_tokens if response.usage else 0,
                    total_tokens=(
                        (response.usage.input_tokens + response.usage.output_tokens)
                        if response.usage
                        else 0
                    ),
                    # All three detail fields are required by the openai type models;
                    # the fake reports zeros because it simulates no caching/reasoning.
                    input_tokens_details=InputTokensDetails(cache_write_tokens=0, cached_tokens=0),
                    output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                ),
            ),
            sequence_number=sequence,
        )
