"""Background execution of runs, the single bridge between HTTP requests and the agent.

A run outlives its POST: `start_message` registers the run in the trace store, spawns
an asyncio job that consumes `stream_run`'s contract events, and returns immediately.
Every event follows one path — persist to the `events` table (dense per-session seq),
then notify in-memory subscribers — so an SSE connection can be dropped and re-established
anytime with `Last-Event-ID` and still see exactly the same stream (PLAN §6 replay).

Ownership rules that keep the state machine honest:
* terminal event -> terminal (or paused) run status, in the same pump step;
* `approval_required` also stores the serialized RunState (via `on_state`) and keeps the
  *live agent object* for resume — `RunState.from_json` needs the identical Agent
  (same tools/policy), and a FakeModel must keep its script position across requests;
* process restart falls back to rebuilding the agent from the factory, which is sound
  because the factory pins tools + approval policy to the session's mode.

Concurrency model: one event loop, sqlite writes only via `Store` (BEGIN IMMEDIATE),
SDK memory in `SQLiteSession` on its own `sdk_*` tables (never touched here).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any

from agents.memory import SQLiteSession

from app.agent.events import resume_run, stream_run
from app.config import Settings
from app.store import TERMINAL_STATUSES, InvalidTransitionError, Store
from app.tools.context import AppContext

logger = logging.getLogger("small_dify.runtime")

AgentFactory = Callable[[str], Any]
"""mode -> configured Agent; injected so tests script the model (P1 FakeModel)."""

SDK_DB_FILENAME = "sdk_memory.db"
"""PLAN §7 puts `sdk_*` tables beside the trace db; a separate *file* keeps the SDK's
lazy transactions from ever contending with the trace writer's BEGIN IMMEDIATE."""


class RunNotPausedError(RuntimeError):
    """Approval decisions arrived for a run that is not waiting on one."""


class NotCancellableError(RuntimeError):
    """The run is already in a terminal state."""


def _run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


class Runtime:
    def __init__(self, *, settings: Settings, store: Store, agent_factory: AgentFactory):
        self.settings = settings
        self.store = store
        self.agent_factory = agent_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._paused_agents: dict[str, Any] = {}
        self._subscribers: dict[str, list[asyncio.Queue[int]]] = {}
        self._sdk_sessions: dict[str, SQLiteSession] = {}

    # ------------------------------------------------------------- wiring

    def workspace_for(self, session_id: str) -> Path:
        return self.settings.data_dir / "workspaces" / session_id

    def _context_for(self, session_id: str) -> AppContext:
        return AppContext(workspace=self.workspace_for(session_id))

    def _sdk_session(self, session_id: str) -> SQLiteSession:
        cached = self._sdk_sessions.get(session_id)
        if cached is None:
            cached = SQLiteSession(
                session_id,
                db_path=str(self.settings.data_dir / SDK_DB_FILENAME),
                sessions_table="sdk_sessions",
                messages_table="sdk_messages",
            )
            self._sdk_sessions[session_id] = cached
        return cached

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def create_session(self, *, title: str, mode: str) -> dict[str, Any]:
        session_id = self._new_id("sess")
        self.store.create_session(id=session_id, title=title, mode=mode, model=self.settings.llm_model)
        return self.store.get_session(session_id)

    # ------------------------------------------------------------- subscribe

    def subscribe(self, session_id: str) -> asyncio.Queue[int]:
        queue: asyncio.Queue[int] = asyncio.Queue()
        self._subscribers.setdefault(session_id, []).append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[int]) -> None:
        subs = self._subscribers.get(session_id, [])
        if queue in subs:
            subs.remove(queue)

    def _publish(self, session_id: str, seq: int) -> None:
        for queue in self._subscribers.get(session_id, ()):
            queue.put_nowait(seq)

    # ------------------------------------------------------------- run jobs

    def start_message(self, session: dict[str, Any], text: str) -> str:
        run_id = _run_id()
        session_id = str(session["id"])
        mode = str(session["mode"])
        self.store.start_run(id=run_id, session_id=session_id, input_text=text, mode=mode)

        def setup() -> tuple[Any, AsyncIterator[dict[str, Any]]]:
            agent = self.agent_factory(mode)
            events = stream_run(
                agent,
                text,
                context=self._context_for(session_id),
                run_id=run_id,
                mode=mode,
                model_label=self.settings.llm_model,
                max_turns=self.settings.max_turns,
                on_state=lambda state: self.store.save_run_state(run_id, state),
                session=self._sdk_session(session_id),
            )
            return agent, events

        # `setup` runs inside the pump: a broken agent factory (e.g. missing API key in
        # the default factory) becomes a terminal run_error, not a 500 or a boot failure.
        self._spawn(run_id, session_id, setup)
        return run_id

    def resume_with_decisions(self, run_id: str, decisions: Mapping[str, Mapping[str, Any]]) -> None:
        """Apply approval decisions and spawn the job that streams the resumed run."""
        run = self.store.get_run(run_id)
        if run["status"] != "awaiting_approval":
            raise RunNotPausedError(f"run {run_id} 不在等待审批状态（当前 {run['status']}）")
        state = self.store.load_run_state(run_id)
        agent = self._paused_agents.pop(run_id, None)
        session_id = str(run["session_id"])

        for approval_id, decision in decisions.items():
            self.store.decide_approval(approval_id, _table_decision(decision))
        self.store.transition_run(run_id, "running")

        def setup() -> tuple[Any, AsyncIterator[dict[str, Any]]]:
            live_agent = agent or self.agent_factory(str(run["mode"]))
            events = resume_run(
                live_agent,
                state or {},
                decisions=decisions,
                context=self._context_for(session_id),
                on_state=lambda next_state: self.store.save_run_state(run_id, next_state),
                session=self._sdk_session(session_id),
            )
            return live_agent, events

        self._spawn(run_id, session_id, setup)

    def cancel_run(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if run["status"] in TERMINAL_STATUSES:
            raise NotCancellableError(f"run {run_id} 已是终态（{run['status']}），无法取消")
        session_id = str(run["session_id"])
        task = self._tasks.get(run_id)
        self._paused_agents.pop(run_id, None)
        if task is not None and not task.done():
            task.cancel()
        # Record synchronously instead of relying on the pump's CancelledError branch:
        # in a test transport (and any burst of suspless awaits) the task may never
        # have been scheduled, and cancelling an un-started task runs NO body — except
        # clauses included. `_finish_cancelled` is idempotent, so the pump waking later
        # finds the terminal state already written and skips.
        self._finish_cancelled(run_id, session_id)

    def cancel_session_runs(self, session_id: str) -> None:
        """Best-effort cancel of everything still open in one session (delete hygiene)."""
        for run_id in self.store.active_run_ids(session_id):
            try:
                self.cancel_run(run_id)
            except KeyError:
                continue

    def _spawn(self, run_id: str, session_id: str, setup: Callable[[], tuple[Any, AsyncIterator[dict[str, Any]]]]) -> None:
        task: asyncio.Task[None] = asyncio.create_task(self._pump(run_id, session_id, setup))
        self._tasks[run_id] = task
        # Identity guard: a resumed run re-registers under the same run_id, and the
        # *old* task's done callback must not evict the new entry.
        task.add_done_callback(lambda finished, rid=run_id: self._forget_task(rid, finished))

    def _forget_task(self, run_id: str, finished: asyncio.Task[None]) -> None:
        if self._tasks.get(run_id) is finished:
            self._tasks.pop(run_id, None)

    async def _pump(
        self,
        run_id: str,
        session_id: str,
        setup: Callable[[], tuple[Any, AsyncIterator[dict[str, Any]]]],
    ) -> None:
        """Consume contract events: persist, publish, and mirror status."""
        try:
            agent, events = setup()
        except Exception as exc:
            logger.exception("run %s failed to start", run_id)
            self._fail_internal(run_id, session_id, message=f"运行无法启动：{exc}")
            return
        try:
            async for event in events:
                etype: str = event["type"]
                payload: dict[str, Any] = event["payload"]
                seq = self.store.append_event(
                    session_id=session_id, run_id=run_id, type=etype, payload=payload
                )
                self._publish(session_id, seq)
                self._apply_terminal(etype, payload, run_id, session_id, agent)
        except asyncio.CancelledError:
            self._finish_cancelled(run_id, session_id)
            raise
        except InvalidTransitionError:
            logger.exception("run %s hit an illegal state edge; marking failed", run_id)
            self._fail_internal(run_id, session_id)
        except Exception:
            logger.exception("run %s pump crashed outside the event stream", run_id)
            self._fail_internal(run_id, session_id)

    def _apply_terminal(
        self, etype: str, payload: dict[str, Any], run_id: str, session_id: str, agent: Any
    ) -> None:
        if etype == "run_finished":
            self.store.finish_run(
                run_id, "succeeded", usage=payload.get("usage"), turns=payload.get("turns")
            )
        elif etype == "approval_required":
            self.store.create_approval(
                run_id=run_id,
                approval_id=payload["approval_id"],
                tool_name=payload["tool"],
                arguments=payload["arguments"],
                risk=payload["risk"],
            )
            self._paused_agents[run_id] = agent
            self._transition_to_awaiting(run_id)
        elif etype == "run_error":
            self.store.finish_run(
                run_id,
                "failed",
                usage=None,
                turns=None,
                error=f"{payload['kind']}: {payload['message']}",
            )

    def _transition_to_awaiting(self, run_id: str) -> None:
        """Idempotent for multi-tool pauses: the second interruption is still awaiting."""
        if self.store.get_run(run_id)["status"] == "awaiting_approval":
            return
        self.store.transition_run(run_id, "awaiting_approval")

    def _finish_cancelled(self, run_id: str, session_id: str) -> None:
        # KeyError: the session (and with it the run) was deleted mid-cancel — nothing
        # left to record, the trace is gone by design.
        try:
            if self.store.get_run(run_id)["status"] in TERMINAL_STATUSES:
                return
            seq = self.store.append_event(
                session_id=session_id,
                run_id=run_id,
                type="run_error",
                payload={"kind": "cancelled", "message": "运行已取消"},
            )
            self._publish(session_id, seq)
            self.store.finish_run(run_id, "cancelled", usage=None, turns=None)
        except KeyError:
            logger.info("run %s vanished before cancellation was recorded", run_id)

    def _fail_internal(self, run_id: str, session_id: str, message: str = "运行时故障，请查看服务端日志") -> None:
        try:
            if self.store.get_run(run_id)["status"] in TERMINAL_STATUSES:
                return
            seq = self.store.append_event(
                session_id=session_id,
                run_id=run_id,
                type="run_error",
                payload={"kind": "internal", "message": message},
            )
            self._publish(session_id, seq)
            self.store.finish_run(run_id, "failed", usage=None, turns=None, error=f"internal: {message}")
        except KeyError:
            logger.info("run %s vanished before failure was recorded", run_id)

    # ------------------------------------------------------------- shutdown

    async def shutdown(self) -> None:
        """Cancel every in-flight job; the terminal state is recorded up front.

        Same reasoning as `cancel_run`: a never-scheduled task cannot write its own
        ending, and a real server shuts down precisely when the loop is busy.
        """
        for run_id, task in list(self._tasks.items()):
            if task.done():
                continue
            run = self.store.get_run(run_id)
            self._finish_cancelled(run_id, str(run["session_id"]))
            task.cancel()
        pending = [task for task in self._tasks.values() if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        self._paused_agents.clear()
        for session in self._sdk_sessions.values():
            try:
                # Verified against the installed SDK: `close()` is sync, not a coroutine.
                session.close()
            except Exception:  # best effort on shutdown
                logger.warning("sdk session close failed", exc_info=True)
        self._sdk_sessions.clear()


def _table_decision(decision: Mapping[str, Any]) -> str:
    """Client decision vocabulary -> approvals-table decision (PLAN §7)."""
    if decision.get("decision") == "approve":
        return "always_approved" if decision.get("always") else "approved"
    return "rejected"
