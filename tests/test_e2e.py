"""T7 — P8 端到端整合：跨层冒烟 + §6 契约完整性快照。

一条 run 走完 API→Runtime→SSE→审批→恢复→落库 的全部层次（前端不参与，走同一
HTTP/SSE 契约）；另一条把「契约表里恰好有哪些事件、每个 payload 的字段」钉成快照
——事件契约是前后端唯一接口，漂移必须在这里先红。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agent.factory import build_agent
from app.main import create_app
from app.testing.fake_model import text_reply, tool_call_reply

from tests.test_api import (
    BoomFake,
    client_for,
    create_session,
    make_settings,
    scripted_factory,
    wait_run,
)
from tests.test_sse import sse_collect

CONTRACT_FIELDS: dict[str, set[str]] = {
    "run_started": {"run_id", "mode", "model"},
    "user_message": {"text"},
    "text_message_content": {"delta"},
    "tool_call_args": {"call_id", "delta"},
    "tool_call_start": {"call_id", "tool", "risk"},
    "tool_call_end": {"call_id"},
    "tool_result": {"call_id", "ok", "output", "duration_ms"},
    "approval_required": {"approval_id", "tool", "arguments", "risk"},
    "run_finished": {"usage", "turns"},
    "run_error": {"kind", "message"},
}


async def test_full_lifecycle_smoke_across_every_layer(tmp_path: Path):
    """提问→读工具→写工具(审批暂停)→批准→回答→完成：一个 run 打通所有层。"""
    app = create_app(
        make_settings(tmp_path),
        agent_factory=scripted_factory(
            [
                [
                    tool_call_reply("calculator", {"expression": "21*2"}),
                    tool_call_reply("write_text_file", {"filename": "summary.txt", "content": "答案是 42"}),
                    text_reply("已计算并写入 summary.txt"),
                ]
            ]
        ),
    )
    async with client_for(app) as client:
        sid = await create_session(client)  # 默认 review：write 要人工确认
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "算 21*2 并把结果写进文件"})
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        # 暂停段：SSE 第一程必须止于 approval_required
        await wait_run(client, run_id, {"awaiting_approval"})
        first = await sse_collect(app, sid)
        types = [f["event"] for f in first]
        assert types[0] == "run_started" and types[1] == "user_message"
        assert types[-1] == "approval_required"
        pause = first[-1]["data"]
        assert pause["tool"] == "write_text_file" and pause["risk"] == "write"
        # 暂停段的工具：calculator 已有结果，write 只有调用没有结果
        calc = next(f for f in first if f["event"] == "tool_result")
        assert calc["data"]["output"] == "21*2 = 42" and calc["data"]["ok"] is True

        # 审批台账：pending 行与事件一致
        approvals = (await client.get(f"/runs/{run_id}/approvals")).json()
        assert approvals[0]["approval_id"] == pause["approval_id"]
        assert approvals[0]["decision"] == "pending"

        # 批准 → 恢复段：游标续流，终到 run_finished
        decided = await client.post(f"/runs/{run_id}/approvals", json={pause["approval_id"]: {"decision": "approve"}})
        assert decided.status_code == 202
        run = await wait_run(client, run_id, {"succeeded"})
        tail = await sse_collect(app, sid, last_event_id=first[-1]["id"])
        assert tail[-1]["event"] == "run_finished"
        assert tail[0]["id"] == first[-1]["id"] + 1  # seq 跨暂停仍然密集无缝

        # 落库视图与流一致；run 元数据齐全
        everything = await client.get(f"/sessions/{sid}/events?format=json")
        rows = everything.json()
        assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1))
        assert len(rows) == len(first) + len(tail)
        assert run["turns"] == 3
        assert json.loads(run["usage_json"])["requests"] == 3
        assert run["mode"] == "review"

        # 工具真的执行了：审批门后的文件落在会话工作区
        written = tmp_path / "data" / "workspaces" / sid / "summary.txt"
        assert written.read_text(encoding="utf-8") == "答案是 42"

        # 审批决定回写台账
        after = (await client.get(f"/runs/{run_id}/approvals")).json()
        assert after[0]["decision"] == "approved" and after[0]["decided_at"]


async def test_event_contract_is_exactly_the_documented_table(tmp_path: Path):
    """两条 run（暂停-批准-完成 + 模型故障）覆盖 §6 全部 10 类事件，且一类不多。"""
    app = create_app(
        make_settings(tmp_path),
        agent_factory=scripted_factory(
            [
                [
                    tool_call_reply("calculator", {"expression": "1+1"}),
                    tool_call_reply("write_text_file", {"filename": "x.txt", "content": "2"}),
                    text_reply("好了"),
                ],
            ]
        ),
    )
    seen: dict[str, dict[str, Any]] = {}
    async with client_for(app) as client:
        sid = await create_session(client)
        resp = await client.post(f"/sessions/{sid}/messages", json={"text": "算 1+1 写文件"})
        run_id = resp.json()["run_id"]
        await wait_run(client, run_id, {"awaiting_approval"})
        approvals = (await client.get(f"/runs/{run_id}/approvals")).json()
        await client.post(
            f"/runs/{run_id}/approvals", json={approvals[0]["approval_id"]: {"decision": "approve"}}
        )
        await wait_run(client, run_id, {"succeeded"})
        for row in (await client.get(f"/sessions/{sid}/events?format=json")).json():
            seen.setdefault(row["type"], row["payload"])

        # 故障 run 补上最后一类：run_error
        boom = create_app(
            make_settings(tmp_path / "boom"),
            agent_factory=lambda mode: build_agent(model=BoomFake([text_reply("x")]), mode=mode),
        )
        async with client_for(boom) as bclient:
            bsid = await create_session(bclient, mode="full_access")
            bresp = await bclient.post(f"/sessions/{bsid}/messages", json={"text": "炸"})
            await wait_run(bclient, bresp.json()["run_id"], {"failed"})
            for row in (await bclient.get(f"/sessions/{bsid}/events?format=json")).json():
                seen.setdefault(row["type"], row["payload"])

    assert set(seen) == set(CONTRACT_FIELDS), (
        f"契约漂移：多出 {set(seen) - set(CONTRACT_FIELDS)}，缺失 {set(CONTRACT_FIELDS) - set(seen)}"
    )
    for etype, payload in seen.items():
        assert set(payload) == CONTRACT_FIELDS[etype], f"{etype} payload 字段漂移：{sorted(payload)}"
