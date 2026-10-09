"""T4 — persistence layer: the human-facing trajectory store (PLAN §7).

Deliberate separation of duties: the SDK's `SQLiteSession` owns what the *model*
remembers; these tables own what the *UI* replays (events with per-session monotonic
seq, run status machine, approval records, resume state). Concurrency and restart are
tested here at the storage level so P6 can stay thin.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest
from app.db import connect, migrate
from app.store import (
    TERMINAL_STATUSES,
    VALID_TRANSITIONS,
    InvalidTransitionError,
    Store,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "trace.db"
    conn = connect(path)
    migrate(conn)
    conn.close()
    return path


@pytest.fixture
def store(db_path: Path) -> Store:
    conn = connect(db_path)
    s = Store(conn)
    yield s
    conn.close()


def fresh_session(store: Store, sid: str = "s1") -> Store:
    store.create_session(id=sid, title="测试会话", mode="review", model="deepseek-chat")
    return store


# ---------------------------------------------------------------- migrations


def test_migrate_is_idempotent(db_path: Path):
    conn = connect(db_path)
    migrate(conn)  # second run against an already-migrated file must not raise
    migrate(conn)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"sessions", "runs", "events", "approvals"} <= tables
    conn.close()


# ---------------------------------------------------------------- run state machine


def test_legal_run_lifecycle_with_timestamps(store: Store):
    fresh_session(store)
    store.start_run(id="r1", session_id="s1", input_text="算一下", mode="review")
    assert store.get_run("r1")["status"] == "running"

    store.transition_run("r1", "awaiting_approval")
    store.transition_run("r1", "running")
    store.finish_run("r1", "succeeded", usage={"requests": 2, "input_tokens": 10}, turns=2)

    run = store.get_run("r1")
    assert run["status"] == "succeeded"
    assert run["usage_json"] and "requests" in run["usage_json"]
    assert run["turns"] == 2
    assert run["finished_at"]


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        ("running", "succeeded"),
        ("running", "failed"),
        ("running", "cancelled"),
        ("running", "awaiting_approval"),
        ("awaiting_approval", "running"),
        ("awaiting_approval", "cancelled"),
        ("awaiting_approval", "failed"),
    ],
)
def test_every_declared_transition_is_allowed(store: Store, frm: str, to: str):
    fresh_session(store)
    store.start_run(id="r1", session_id="s1", input_text="x", mode="review")
    if frm != "running":
        store.transition_run("r1", frm)
    store.transition_run("r1", to)
    assert store.get_run("r1")["status"] == to


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        ("succeeded", "running"),
        ("succeeded", "failed"),
        ("failed", "running"),
        ("cancelled", "awaiting_approval"),
        ("awaiting_approval", "succeeded"),  # must pass back through running first
    ],
)
def test_illegal_transitions_are_rejected(store: Store, frm: str, to: str):
    fresh_session(store)
    store.start_run(id="r1", session_id="s1", input_text="x", mode="review")
    if frm == "awaiting_approval":
        store.transition_run("r1", "awaiting_approval")
    else:
        store.finish_run("r1", frm, usage=None, turns=1)

    with pytest.raises(InvalidTransitionError):
        store.transition_run("r1", to)
    # The same guard must protect the convenience path too:
    with pytest.raises(InvalidTransitionError):
        store.finish_run("r1", to if to != "running" else "succeeded", usage=None, turns=1)


def test_terminal_states_have_no_exits():
    for terminal in TERMINAL_STATUSES:
        assert VALID_TRANSITIONS[terminal] == frozenset()


def test_unknown_target_status_is_rejected(store: Store):
    fresh_session(store)
    store.start_run(id="r1", session_id="s1", input_text="x", mode="review")
    with pytest.raises(InvalidTransitionError, match="未知"):
        store.transition_run("r1", "paused_forever")


# ---------------------------------------------------------------- events


def test_seq_is_monotonic_per_session_and_shared_across_runs(store: Store):
    fresh_session(store)
    store.start_run(id="r1", session_id="s1", input_text="a", mode="review")
    store.start_run(id="r2", session_id="s1", input_text="b", mode="review")
    store.append_event(session_id="s1", run_id="r1", type="run_started", payload={"x": 1})
    store.append_event(session_id="s1", run_id="r2", type="run_started", payload={"x": 2})
    store.append_event(session_id="s1", run_id="r1", type="tool_call_start", payload={"y": "气动力学"})

    seqs = [row["seq"] for row in store.list_events("s1")]
    assert seqs == [1, 2, 3]
    payloads = [json.loads(row["payload_json"]) for row in store.list_events("s1")]
    assert payloads[-1] == {"y": "气动力学"}


def test_last_event_id_replay_returns_only_the_tail(store: Store):
    fresh_session(store)
    store.start_run(id="r1", session_id="s1", input_text="a", mode="review")
    for i in range(5):
        store.append_event(session_id="s1", run_id="r1", type="text_message_content", payload={"delta": str(i)})

    tail = store.list_events("s1", after_seq=3)
    assert [e["seq"] for e in tail] == [4, 5]
    assert [json.loads(e["payload_json"]) for e in tail] == [{"delta": "3"}, {"delta": "4"}]


def test_seq_is_unique_per_session_across_two_sessions(store: Store):
    store.create_session(id="s1", title="A", mode="review", model="m")
    store.create_session(id="s2", title="B", mode="review", model="m")
    store.start_run(id="r1", session_id="s1", input_text="a", mode="review")
    store.start_run(id="r2", session_id="s2", input_text="b", mode="review")
    store.append_event(session_id="s2", run_id="r2", type="run_started", payload={})
    store.append_event(session_id="s1", run_id="r1", type="run_started", payload={})
    assert [e["seq"] for e in store.list_events("s1")] == [1]
    assert [e["seq"] for e in store.list_events("s2")] == [1]


def test_concurrent_appends_never_collide_or_deadlock(db_path: Path):
    conn = connect(db_path)
    store = Store(conn)
    store.create_session(id="s1", title="A", mode="review", model="m")
    store.start_run(id="r1", session_id="s1", input_text="a", mode="review")
    conn.close()

    errors: list[BaseException] = []

    def writer(worker: int) -> None:
        wconn = connect(db_path)
        wstore = Store(wconn)
        try:
            for i in range(10):
                wstore.append_event(
                    session_id="s1", run_id="r1", type="text_message_content", payload={"w": worker, "i": i}
                )
        except sqlite3.Error as exc:  # recorded and re-surfaced through the assertions below
            errors.append(exc)
        finally:
            wconn.close()

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(not t.is_alive() for t in threads), "a writer deadlocked"
    assert not errors, f"concurrent writes raised: {errors!r}"

    conn = connect(db_path)
    events = Store(conn).list_events("s1")
    conn.close()
    assert [e["seq"] for e in events] == list(range(1, 41))


# ---------------------------------------------------------------- state + restart


def test_state_json_roundtrip_keeps_identical_dict(store: Store):
    state = {
        "schema_version": "1",
        "context": {"workspace": "C:\\ws\\s1", "max_read_bytes": 200000},
        "note": "气动力学 ✓",
        "nested": {"list": [1, 2.5, True, None]},
    }
    fresh_session(store)
    store.start_run(id="r1", session_id="s1", input_text="a", mode="review")
    store.save_run_state("r1", state)
    assert store.load_run_state("r1") == state


def test_full_trajectory_survives_reconnect(db_path: Path):
    conn = connect(db_path)
    store = Store(conn)
    fresh_session(store)
    store.start_run(id="r1", session_id="s1", input_text="算", mode="review")
    store.append_event(session_id="s1", run_id="r1", type="run_started", payload={"run_id": "r1"})
    store.append_event(session_id="s1", run_id="r1", type="tool_call_start", payload={"tool": "calculator"})
    store.transition_run("r1", "awaiting_approval")
    store.save_run_state("r1", {"v": 1})
    store.create_approval(run_id="r1", approval_id="a1", tool_name="write_text_file", arguments={"filename": "x"}, risk="write")
    conn.close()

    reopened = Store(connect(db_path))
    run = reopened.get_run("r1")
    assert run["status"] == "awaiting_approval"
    assert reopened.load_run_state("r1") == {"v": 1}
    assert [e["type"] for e in reopened.list_events("s1")] == ["run_started", "tool_call_start"]
    approval = reopened.get_approval("a1")
    assert approval["decision"] == "pending" and approval["risk"] == "write"


def test_approval_decision_lifecycle(store: Store):
    fresh_session(store)
    store.start_run(id="r1", session_id="s1", input_text="a", mode="review")
    store.create_approval(run_id="r1", approval_id="a1", tool_name="delete_session_file", arguments={}, risk="dangerous")

    store.decide_approval("a1", "always_approved")
    approval = store.get_approval("a1")
    assert approval["decision"] == "always_approved"
    assert approval["decided_at"]

    with pytest.raises(InvalidTransitionError):
        store.decide_approval("a1", "approved")  # already decided must not flip
