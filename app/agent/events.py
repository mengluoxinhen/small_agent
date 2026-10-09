"""Translate SDK stream events into the project SSE contract (PLAN §6).

`stream_run` is the single funnel every runner output passes through: it yields plain
`{"type": ..., "payload": ...}` dicts using the contract names, and converts *all*
failure modes — max turns, model errors, anything unexpected — into a terminal
`run_error` event instead of raising. The FastAPI layer (P6) and the event table (P5)
consume this stream verbatim, so a name or payload change here is a contract change.

Known mapping decision: the SDK reports a tool call only after its arguments are
complete, so `tool_call_start` and `tool_call_end` are emitted back-to-back; streaming
argument deltas still arrive beforehand as `tool_call_args`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any

from agents import Agent, Runner, RunState
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError
from agents.items import ToolApprovalItem, ToolCallItem, ToolCallOutputItem
from agents.stream_events import (
    AgentUpdatedStreamEvent,
    RawResponsesStreamEvent,
    RunItemStreamEvent,
    StreamEvent,
)
from agents.usage import Usage
from openai import APIError
from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseTextDeltaEvent,
)

from app.tools.registry import UnknownToolError, default_registry

logger = logging.getLogger("small_dify.agent")

TOOL_FAILURE_MARKER = "调用失败"
"""describe_failure()'s fixed wording; the SDK does not flag errored outputs otherwise."""

DEFAULT_REJECTION_REASON = "用户未批准该操作，已默认拒绝"


class StateRestoreError(ValueError):
    """The serialized RunState is missing, malformed, or cannot be restored."""


def _event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": event_type, "payload": payload}


def _risk_for(tool_name: str) -> str:
    try:
        return default_registry().risk_for(tool_name)
    except UnknownToolError:
        # A tool outside the builtin registry (custom tools land in P8) must not kill
        # the stream; "unknown" tells the UI to treat it as high risk by default.
        return "unknown"


def _usage_dict(usage: Usage) -> dict[str, Any]:
    """Flatten the SDK's `Usage` dataclass to plain numbers for the event payload.

    Verified against the installed SDK (v0.23.1): `Usage` is a bare dataclass — there is
    no `model_dump`. Nested token-detail dataclasses are dropped; the UI only needs the
    scalar counters.
    """
    dump = dataclasses.asdict(usage)
    return {key: value for key, value in dump.items() if isinstance(value, (int, float))}


def translate(
    sdk_event: StreamEvent, pending_tool_starts: dict[str, float]
) -> list[dict[str, Any]]:
    """One SDK event -> zero or more contract events (order-preserving)."""
    if isinstance(sdk_event, AgentUpdatedStreamEvent):
        return []

    if isinstance(sdk_event, RawResponsesStreamEvent):
        data = sdk_event.data
        if isinstance(data, ResponseTextDeltaEvent):
            return [_event("text_message_content", {"delta": data.delta})]
        if isinstance(data, ResponseFunctionCallArgumentsDeltaEvent):
            return [_event("tool_call_args", {"call_id": data.item_id, "delta": data.delta})]
        return []

    if isinstance(sdk_event, RunItemStreamEvent):
        if sdk_event.name == "tool_called":
            item: ToolCallItem = sdk_event.item  # type: ignore[assignment]
            call_id = item.call_id or ""
            tool_name = item.tool_name or ""
            pending_tool_starts[call_id] = time.perf_counter()
            return [
                _event(
                    "tool_call_start",
                    {"call_id": call_id, "tool": tool_name, "risk": _risk_for(tool_name)},
                ),
                _event("tool_call_end", {"call_id": call_id}),
            ]
        if sdk_event.name == "tool_output":
            out: ToolCallOutputItem = sdk_event.item  # type: ignore[assignment]
            call_id = out.call_id or ""
            started = pending_tool_starts.pop(call_id, None)
            duration_ms = round((time.perf_counter() - started) * 1000, 1) if started else 0.0
            output = str(out.output)
            return [
                _event(
                    "tool_result",
                    {
                        "call_id": call_id,
                        "ok": TOOL_FAILURE_MARKER not in output,
                        "output": output,
                        "duration_ms": duration_ms,
                    },
                )
            ]
        # message_output_created and everything else: text already streamed via deltas.
        return []

    return []


def _approval_id(item: ToolApprovalItem) -> str:
    return getattr(item, "call_id", None) or getattr(item.raw_item, "call_id", "") or ""


def _serialize_context(ctx: Any) -> Mapping[str, Any]:
    """Turn the app context dataclass into a strictly JSON-safe mapping.

    `RunState.from_json` validates the state tree against built-in JSON types before
    any override is consulted, and `AppContext.workspace` is a `Path` — leaving it raw
    makes restore die with a redacted "unsupported value" error (probe-verified).
    """
    if ctx is None:
        return {}
    if dataclasses.is_dataclass(ctx) and not isinstance(ctx, type):
        return {k: (str(v) if isinstance(v, Path) else v) for k, v in dataclasses.asdict(ctx).items()}
    return {"repr": str(ctx)}


def _approval_payload(item: ToolApprovalItem) -> dict[str, Any]:
    raw_args = getattr(item.raw_item, "arguments", "") or ""
    try:
        arguments = json.loads(raw_args)
    except json.JSONDecodeError:
        arguments = {"raw": raw_args}
    tool_name = item.tool_name or ""
    return {
        "approval_id": _approval_id(item),
        "tool": tool_name,
        "arguments": arguments,
        "risk": _risk_for(tool_name),
    }


async def _drive(
    result: Any,
    *,
    pending_tool_starts: dict[str, float],
    on_state: Callable[[dict[str, Any]], None] | None,
) -> AsyncIterator[dict[str, Any]]:
    """Consume one RunResultStreaming as contract events, terminal event included.

    Terminal outcomes are mutually exclusive: `run_finished` when the loop completes,
    `approval_required` (+ state handoff) when the SDK pauses on a gated tool,
    `run_error` for any failure mode.
    """
    try:
        async for sdk_event in result.stream_events():
            for event in translate(sdk_event, pending_tool_starts):
                yield event
        if result.interruptions:
            for item in result.interruptions:
                yield _event("approval_required", _approval_payload(item))
            if on_state is not None:
                on_state(result.to_state().to_json(context_serializer=_serialize_context))
            return
        yield _event(
            "run_finished",
            {
                "usage": _usage_dict(result.context_wrapper.usage),
                "turns": result.current_turn,
            },
        )
    except MaxTurnsExceeded as exc:
        yield _event("run_error", {"kind": "max_turns", "message": str(exc)})
    except ModelBehaviorError as exc:
        yield _event("run_error", {"kind": "model", "message": str(exc)})
    except APIError as exc:
        # Upstream transport/status failure (a real 5xx from DeepSeek arrives here);
        # same terminal kind as a misbehaving model — the client retries or gives up.
        yield _event("run_error", {"kind": "model", "message": str(exc) or type(exc).__name__})
    except Exception as exc:  # the stream must terminate with an event, not raise
        logger.exception("streamed run failed with unexpected error")
        yield _event("run_error", {"kind": "internal", "message": type(exc).__name__})


async def stream_run(
    agent: Any,
    user_text: str,
    *,
    context: Any,
    run_id: str | None = None,
    mode: str = "review",
    model_label: str | None = None,
    max_turns: int | None = None,
    on_state: Callable[[dict[str, Any]], None] | None = None,
    session: Any | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run one agent turn, yielding contract events; failures become run_error.

    `on_state` hands the caller the serialized RunState whenever a run pauses for
    approval — persistence (P5) and the HTTP layer (P6) own storing it.
    `session` is the SDK conversation-memory object (PLAN §7 dual persistence).
    """
    run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
    yield _event("run_started", {"run_id": run_id, "mode": mode, "model": model_label})
    # The user's own text is part of the trace contract: live UIs show it instantly,
    # but history replay (?format=json / SSE from seq 1) can only render what was
    # persisted. Without this event a reloaded session has no user bubble (P7 finding).
    yield _event("user_message", {"text": user_text})

    result = Runner.run_streamed(agent, user_text, context=context, max_turns=max_turns, session=session)
    async for event in _drive(result, pending_tool_starts={}, on_state=on_state):
        yield event


async def resume_run(
    agent: Agent,
    state_json: Mapping[str, Any],
    *,
    decisions: Mapping[str, Mapping[str, Any]],
    context: Any,
    on_state: Callable[[dict[str, Any]], None] | None = None,
    session: Any | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Apply approval decisions to a paused run and stream its remainder.

    `decisions` maps approval_id -> {"decision": "approve"|"reject", "always": bool,
    "reason": str}. Missing or malformed decisions reject with a stated reason, because
    silence from the user must never be read as consent.
    """
    if not isinstance(state_json, dict) or not state_json:
        raise StateRestoreError("无法恢复：审批状态为空或不是 JSON 对象")

    try:
        state = await RunState.from_json(agent, state_json, context_override=context)
    except Exception as exc:
        raise StateRestoreError(f"无法恢复：审批状态损坏（{type(exc).__name__}）") from exc

    for item in state.get_interruptions():
        decision = decisions.get(_approval_id(item), {})
        if decision.get("decision") == "approve":
            state.approve(item, always_approve=bool(decision.get("always")))
        else:
            state.reject(
                item,
                always_reject=bool(decision.get("always")),
                rejection_message=str(decision.get("reason") or DEFAULT_REJECTION_REASON),
            )

    result = Runner.run_streamed(agent, state, session=session)
    async for event in _drive(result, pending_tool_starts={}, on_state=on_state):
        yield event
