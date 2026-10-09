# small_dify · Agent 平台开发计划

> 状态：P0 / P1 已完成并通过验收门，等待确认进入 P2。进度与决定记录见 §14。
> 本文件是开发前的唯一事实来源。每个阶段以「测试先行 → 实现 → 验收门 → Engineering Report」为一个闸门，报告经确认后才进入下一阶段。

## 1. 需求确认（已拍板）

| 项 | 决定 |
|---|---|
| 核心能力 | 自然语言 → LLM 自主选择并调用**我写的工具** → 结果回灌 LLM → 循环直到产出最终答案 |
| Agent 编排 | **不自己实现循环**，复用 `openai-agents-python`（OpenAI Agents SDK） |
| 后端 | FastAPI（Python 3.12.6 本机已装，`uv` 0.10.7 管依赖） |
| 前端 | Vue 3 + **JavaScript**（明确不用 TS）+ Vite + Pinia |
| 模型 | 国内 OpenAI 兼容 API（DeepSeek / 通义 / Kimi，`base_url` + `api_key` 可配） |
| 工具形态 | 仓库内 Python 函数文件，`@function_tool` 注册，启动时自动发现 |
| 持久化 | SQLite，会话可恢复、刷新页面可继续 |
| 运行模式 | 两种：`full_access`（全自动）/ `review`（审批模式，详见 §5） |
| 使用规模 | 单人本机使用，不做鉴权、不做多租户 |

**待你确认的一处语义**：你写的"完全访问和自动审批"，我理解为
- `full_access`：所有工具直接执行，绝不停顿；
- `review`：**低风险工具自动审批放行（这就是"自动审批"），高风险工具暂停等前端点确认**。

若你的意思是"两种模式都全自动、只是审批规则不同"，告诉我，改 §5 一张表即可，不影响其它设计。

## 2. 分层复用结论（调研数据见 §8）

| 层 | 复用来源 | 自研工作量 |
|---|---|---|
| Agent 循环 / 工具调用 / 流式 / 记忆 / 审批中断 | `openai-agents-python` 100% 承担 | 0（只写配置） |
| 工具函数 | SDK `@function_tool` 自动生成 JSON Schema；错误回传有现成机制 | 每个工具本体 |
| SSE 事件契约 | **对齐 AG-UI 协议的事件命名与语义**，不自己发明 | 一个事件转译器 |
| 会话持久化 | SDK 自带 `SQLiteSession`（模型的记忆视图） | 0 |
| 前端流式 Markdown 渲染 | `markstream-vue`（Vue3 生态里最硬的一块，尤雨溪推荐） | 0 |
| 前端组件 / 布局 | Naive UI（Vue3 原生、自动审批表格与折叠面板好用） | 0 |
| 前后端胶水层（REST+SSE+审批回路） | 无成熟同栈开源，**必须自研** | 约 30% 的总工作量 |

一句话：**胶水层是我们唯一真正要写的东西**，也是本项目最值得自己控制、最该被测试覆盖的部分。

## 3. 已验证的技术事实（非猜测）

本机：Python 3.12.6 / Node v24.16.0 / npm 11.13.0 / git 2.54 / uv 0.10.7。

`openai-agents==0.23.1`（PyPI 可下载，`Requires-Python >=3.10`，MIT）。从 wheel 源码实测确认：

- `function_tool`、`Runner.run / run_sync / run_streamed` 均为公开导出。
- `FunctionTool.needs_approval` 类型为
  `bool | Callable[[RunContextWrapper, dict[str, Any] args, str tool_name], Awaitable[bool]]`
  → **可以用一个异步策略函数实现"按风险等级决定是否暂停"**，无需改动 SDK。
- `RunState.get_interruptions() -> list[ToolApprovalItem]`、`RunState.approve(item, always_approve=False)`、`RunState.reject(...)`，以及 `RunState.to_json()` / `async RunState.from_json()`
  → **审批可以跨 HTTP 请求恢复**：暂停时把 state 序列化进 SQLite，前端点确认后读回来继续跑。这是本方案成立的关键，已核实存在。
- `Runner.run_streamed(starting_agent, input, ...)` 的 `input` 参数类型为 `str | list[TResponseInputItem] | RunState`
  → 恢复只需 `Runner.run_streamed(agent, input=restored_state, session=...)`。
- SDK docstring 原文即你要的循环：*"The agent will run in a loop until a final output is generated... Else, we run tool calls (if any), and re-run the loop."*
- `agents.memory.sqlite_session.SQLiteSession` 公开导出 → 会话记忆直接用。
- `agents.models.openai_chatcompletions.OpenAIChatCompletionsModel` + `agents.models.multi_provider` → 接任意 OpenAI 兼容 base_url。
- 事件类型公开导出：`StreamEvent`、`RunItemStreamEvent`、`RawResponsesStreamEvent`、`AgentUpdatedStreamEvent`、`ToolCallItem`、`ToolCallOutputItem`、`ToolApprovalItem`。
- SDK 依赖较重（mcp、openai、starlette、websockets 等），但**不会拖进数据库或 Web 框架冲突**（它依赖的 starlette 与 FastAPI 同源）。

尚未验证（开工时会用一次性脚本确认，不影响架构）：`markstream-vue` 的具体导入 API、Naive UI 版本兼容。

## 4. 架构

```
┌───────────────────────── Vue3 SPA ─────────────────────────┐
│ ChatView   TracePanel(折叠工具链)  ApprovalDialog  模式开关 │
│   ▲ SSE 订阅              ▲ POST /approvals                │
│   │                       │                                │
│  EventSource            fetch → REST                       │
└───┼───────────────────────┼────────────────────────────────┘
    │ events                │ messages / approvals
┌───┴───────────────────────┴────────────────────────────────┐
│ FastAPI                                                     │
│  routes_chat ──► RunManager(asyncio task) ──► AgentRunner   │
│  routes_events ◄── Broker(内存队列) + events 表(可重放)      │
│  routes_approvals ──► RunState.from_json ► 恢复 run         │
└────────────────────────────┬───────────────────────────────┘
                     ┌───────┴────────┐
                     │ openai-agents  │  ← 循环/工具调用/审批中断
                     │ SDK            │
                     └───┬────────┬───┘
              tools/*  │          │ SQLiteSession / 我们的表
                     Python 函数  ┌┴─────────────┐
                     (自动发现)    │  SQLite      │
                                  └──────────────┘
```

一次带审批的完整时序：

1. `POST /api/sessions/{sid}/messages {content, mode:"review"}` → 建 run（status=running），起后台 asyncio 任务，返回 `run_id`。
2. 前端 `new EventSource('/api/sessions/{sid}/events?run_id=..&last_id=..')`。
3. SDK 内部：模型返回 tool_calls → `needs_approval` 策略判定 → 高风险 → `RunResultStreaming.interruptions` 非空。
4. 我们把 `RunState.to_json()` 存入 `runs.state_json`，写 `approval_required` 事件到 `events` 表，run 状态改为 `awaiting_approval`，**后台任务正常结束**（不占用协程干等）。
5. 前端点「允许」→ `POST /api/runs/{rid}/approvals {approval_id, decision:"approve", always:false}`。
6. 后端读回 `state_json` → `await RunState.from_json(...)` → `state.approve(item)` → 再次 `Runner.run_streamed(agent, input=state, session=...)` → 事件继续推流到同一通道。
7. 直到 `run_finished`。拒绝则把拒绝原因作为工具输出回灌模型，让它换个做法。

## 5. 两种运行模式与审批策略

风险等级在工具定义处声明（`@risk("write")` 或注册表元数据），策略是**纯函数**，最容易测：

| 工具风险 | `full_access` | `review`（默认） |
|---|---|---|
| `read`（计算器、读文件、查询时间） | 直接执行 | 自动审批放行 |
| `write`（写文件、发请求改状态） | 直接执行 | **暂停等确认** |
| `dangerous`（删文件、执行命令、任何花钱的） | 直接执行 | **暂停等确认**，且前端二次确认 |

`always_approve` 用于同一 run 内同工具不再询问（SDK 原生支持）。模式在会话级设定、每条消息可临时覆盖。

首批示例工具（覆盖三种风险，也作为前端展示素材）：`calculator`（read）、`read_text_file`（read，限定目录）、`http_get`（read）、`write_text_file`（write，限定目录）、`list_session_files`（read）。

## 6. SSE 事件契约（对齐 AG-UI 命名）

| 事件 | payload | 触发 |
|---|---|---|
| `run_started` | `{run_id, mode, model}` | 任务启动 |
| `text_message_content` | `{delta}` | 模型流式 token |
| `tool_call_start` | `{call_id, tool, risk}` | `ToolCallItem` |
| `tool_call_args` | `{call_id, delta}` | 参数流式 |
| `tool_call_end` | `{call_id}` | 参数齐 |
| `tool_result` | `{call_id, ok, output, duration_ms}` | `ToolCallOutputItem` |
| `approval_required` | `{approval_id, tool, arguments, risk}` | 中断 |
| `run_finished` | `{usage, turns}` | 正常结束 |
| `run_error` | `{kind, message}` | 异常/max_turns/工具失败兜底 |

**所有事件同时落 `events` 表**，SSE 支持 `Last-Event-ID` 断线重放——刷新页面也能完整还原执行轨迹（这是"看得到 Agent 在想什么"的核心体验，不能省）。

## 7. 数据模型

`SQLiteSession` 管「模型看到的记忆」，我们的表管「人看到的轨迹」，二者刻意分离（职责不同、生命周期不同，强行合并会让测试变复杂）。

```sql
sessions(id, title, mode, model, created_at, updated_at)
runs(id, session_id, input_text, mode, status,             -- running|awaiting_approval|succeeded|failed|cancelled
     state_json, error, usage_json, turns, started_at, finished_at)
events(id INTEGER PK, session_id, run_id, seq, type, payload_json, created_at)  -- seq 每会话单调
approvals(id, run_id, tool_name, arguments_json, risk,
          decision,                                          -- pending|approved|rejected|always_approved
          created_at, decided_at)
```
外加 SDK 自建的 `sdk_*` 表（不碰、不迁移）。

## 8. 调研到的外部资产清单

| 仓库 | Stars / License | 用途 | 明确不做什么 |
|---|---|---|---|
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | 29.9k★ / MIT | **核心**。`examples/model_providers`(接国产 API)、`examples/memory`、`examples/tools` 直接抄用法；`tests/` 是我们测试写法的范本；仓库自带 `PLANS.md`/`AGENTS.md`，其"计划先行"流程可直接借鉴 | 不 fork 整个仓库；不引入其 realtime/voice/sandbox 分支 |
| [ag-ui-protocol/ag-ui](https://github.com/ag-ui-protocol/ag-ui) | 协议 / 有 FastAPI 集成 | 借它的事件语义当我们的 SSE 契约（§6），避免自造轮子、日后接现成前端 | 不装它的 Python SDK（多一层抽象，收益小）；前端不用它的 React 组件 |
| [Simon-He95/markstream-vue](https://github.com/Simon-He95/markstream-vue) | Vue3 / MIT | 前端流式 Markdown 渲染，直接依赖 | 不自己写增量 Markdown parser |
| [qyhua0/TinyClaw](https://github.com/qyhua0/TinyClaw) | **1★** / MIT | 唯一"FastAPI+Vue3+Tool Calling+折叠工具链"同栈项目：读它的 `backend/app.py` + `core/agent.py` 和前端连线方式，作为布局参考 | **不作骨架**：无测试、无法验证、单人项目，照抄风险高 |
| [vstorm-co/full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template) | Apache-2.0 | 后端工程分层参考（settings / alembic / docker-compose / 目录约定） | 前端是 **Next.js**，与需求冲突，不采用；不引入 LangGraph 与它的 Postgres 依赖 |
| [ahmad2b/openai-agents-streaming-api](https://github.com/ahmad2b/openai-agents-streaming-api) | 10★ / MIT | OpenAI Agents SDK + FastAPI + 流式 + 会话记忆的最小可行示例，可先读它验证我们的接法 | 结构太薄，不作骨架 |
| langchain-ai/agent-chat-ui、Dify | — | 只看**交互形态**（工具链折叠展示、审批条位置） | **不改造 Dify**：多服务(Flask+Celery+Redis+React)体量与"small"目标冲突，本地起环境就要半天，且与 pytest 先行流程完全不兼容 |

## 9. 测试策略

分层金字塔，每层先写红灯用例：

| 层 | 工具 | 隔离方式 |
|---|---|---|
| T1 工具函数 | pytest | 纯函数，tmp_path 造文件，零网络 |
| T2 审批策略 | pytest | 纯函数矩阵：mode × risk × always_approve |
| T3 Agent 循环 | pytest-asyncio + **FakeModel** | 实现 SDK 的 `Model` 接口，按脚本返回预设 tool_calls / 最终答案 → **完全确定性，不花一分钱**。位置：`app/testing/fake_model.py`（放生产侧是因为 `MODEL_BACKEND=fake` 也要用它，且它本身有测试覆盖） |
| T4 仓储层 | pytest + `:memory:` SQLite | 真 SQL，不 mock ORM |
| T5 API | httpx `ASGITransport` | 注入 FakeModel 驱动的 AgentRunner，不启进程 |
| T6 SSE | httpx 流式 + 假事件 | 含 `Last-Event-ID` 重放、断线重连 |
| T7 前端 | Vitest + @vue/test-utils（jsdom） | EventSource / fetch 全 mock |
| T8 端到端冒烟 | 1 条真模型用例 | 需 `SMOKE=1` 显式开启，CI 默认跳过 |

硬规矩：
- FakeModel 是本项目**唯一允许出现在测试里的"模型"**；任何调用真实 API 的测试必须标记 `@pytest.mark.live` 且默认 deselect。
- 每阶段结束跑全量 `pytest`，**旧用例必须仍全绿**才允许进入下一阶段（防返工的唯一保险）。
- 覆盖率闸门：`agent/`、`tools/`、`approval_policy` ≥ 90%，整体 ≥ 80%。
- 一次只推进一个阶段，阶段内不顺手重构别的模块。

## 10. 分阶段计划

估时按你 5–15 h/周排布，总计约 33 h ≈ 3–6 周。

**P0 脚手架（1.5h）**
红：`test_scaffold.py`（settings 可导入、`uv run pytest` 退出码 0、前端 `vitest run` 存在且至少 1 条用例通过、目录齐备）。
做：uv + pyproject（agents-sdk/openai/pydantic-settings/fastapi/uvicorn/pytest/pytest-asyncio/pytest-cov/httpx）、`.env.example`、`vitest` 空用例、git init。
门：`uv run pytest -q` 与 `npm run test` 均绿。

**P1 配置与模型客户端（2h）**
红：缺 key 时 `Settings` 报清晰错误；`base_url` 生效；`build_model()` 返回 `OpenAIChatCompletionsModel`；测试环境可用 FakeModel 顶替。
门：一段 5 行的 `scripts/ping_model.py` 真调一次 API 拿到回复（唯一一次联网验证）。

**P2 工具层（4h）**
红：`@function_tool` 生成的 schema 与预期参数一致；缺参/类型错时 SDK 的错误回传文本可断言；`discover_tools()` 能发现 builtin 且忽略 `_` 前缀；每个工具的正常/异常/边界各 1 条；目录越界访问被拒。
门：`tests/T1` 全绿 + `scripts/list_tools.py` 打印 5 个工具的 schema。

**P3 Agent 核心循环（5h）** ← 全项目心脏
红（全部用 FakeModel）：单次工具调用后返回最终答案；连续两次工具调用串联；无工具时直接回答；`max_turns` 超限走 `run_error` 不崩；工具抛异常时错误信息回灌模型且循环继续；事件序列严格为 `run_started → tool_call_start → tool_result → text_message_content → run_finished`。
做：`agent/factory.py`、`agent/prompts.py`（中文系统提示，含"必须调用工具、不许编造结果"约束）。
门：`tests/T3` ≥ 8 条全绿，其中 1 条真模型 `live` 用例手动跑通。

**P4 审批与两种模式（4h）**
红：§5 那张 6 格矩阵逐一断言；`to_json/from_json` 往返后 `get_interruptions()` 一致；approve 后循环继续；reject 后拒绝理由进入模型输入；`always_approve` 后同工具不再中断；state 为空/损坏时报错不崩。
门：`tests/T2`+`T3(approval 子集)` 全绿。

**P5 持久化（3h）**
红：run 状态机每条合法/非法跃迁；`events.seq` 会话内单调无重复；`state_json` 写读一致；重启后按 sid 完整还原轨迹；并发写不锁死。
门：`tests/T4` 全绿 + 迁移脚本可重复执行（幂等）。

**P6 FastAPI 后端（5h）**
红：会话 CRUD；发消息 202 + `run_id`；FakeModel 驱动下 `/events` 收到完整事件流；审批接口能唤醒暂停的 run；`Last-Event-ID` 重放；run 取消；未知会话 404；模型 5xx 转成 `run_error`。
门：`tests/T5`+`T6` 全绿，`uvicorn` 起真服务用 `curl` 手验一遍完整审批流。

**P7 Vue3 前端（6h）**
红（Vitest）：SSE 客户端按事件类型正确更新 store；store 状态机（idle/streaming/awaiting/cancelled）；TracePanel 折叠/展开与耗时显示；ApprovalDialog 三种决策上送正确 payload；历史会话加载还原轨迹；模式开关影响下条消息 payload。
做：`ChatView` + `TracePanel` + `ApprovalDialog` + 会话侧栏，接 `markstream-vue`。
门：`npm run test` 全绿；浏览器里手动走完一次「提问→工具→审批→回答」。

**P8 端到端整合与打磨（3.5h）**
红：1 条跨层冒烟（前端不测，走 API→SSE→审批→完成）；§6 事件契约完整性快照测试。
做：`README.md`（启动三步）、错误边界、耗时/usage 展示。
门：全量后端+前端测试绿 + 真模型跑通 3 个真实任务并留日志。

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| 国产 API 的 function calling 兼容性差异（参数偶尔非 JSON、`reasoning_content` 混入） | P3 起事件转译层做容错断言；SDK 已有 `reasoning_content_replay` 模块；P1 用真 API 探一次即知 |
| 后台 asyncio 任务与 SSE 生命周期（客户端断开导致 run 中断） | run 独立于 SSE 连接继续跑，事件先落库再推流；P6 专测断线场景 |
| `RunState.from_json` 需要 agent 对象才能重建 | run 记录 agent 名+model，恢复时由 factory 重建同构 agent；P4 专门测往返 |
| 审批长期挂起后 state 过期 | `approvals.decided_at` 为空且超 30 分钟的 run 标记 `cancelled`，前端提示重跑 |
| SDK 版本迭代快（0.23.x） | `pyproject.toml` 锁 0.23.x，升级另开阶段，不在本项目内顺手动 |
| Windows 路径/编码 | 全局 `PYTHONUTF8=1`，工具一律用 `pathlib` + 显式 encoding |

## 12. 命令约定（P0/P1 实测有效）

```bash
# 后端（仓库根目录，uv 管理，项目为非打包虚拟工程）
uv sync                                  # 装依赖
uv run pytest                            # 全量测试（addopts 已默认排除 live）
uv run pytest --cov=app                  # 带覆盖率
uv run ruff check app tests scripts      # lint
uv run uvicorn app.main:create_app --factory --reload --port 8000   # create_app 是工厂
MODEL_BACKEND=fake uv run uvicorn app.main:create_app --factory     # 无 key 起服务

# 前端（frontend/，纯 JS，脚手架为手写而非 create-vite）
NODE_OPTIONS=--use-system-ca npm install # 见下方"本机网络"
npm run dev                              # 5173，vite 代理 /api → 127.0.0.1:8000
npm run test                             # vitest run
```

**本机环境两个坑（已踩已解）**：
1. npm 走本机代理的 HTTPS 中间人，证书在 Windows 系统信任库而 Node 默认不读 → 必须 `NODE_OPTIONS=--use-system-ca`；不要用 `strict-ssl=false`。
2. Windows 中文输出需 UTF-8，测试与脚本一律显式 `encoding="utf-8"`。

**P1 的联网验收门**（需要你的 key，只能你本人跑）：
```bash
cp .env.example .env   # 填入 LLM_API_KEY=sk-...
uv run python scripts/ping_model.py
```

## 13. 开工前待你确认

1. §1 末尾：`full_access` / `review`（低风险自动审批、高风险人工确认）这个理解对不对？
2. 首批 5 个示例工具够不够？有你自己真正想接进去的工具（比如你已有的 CFD/PPT 相关脚本）现在报上来，我把它放进 P2 的用例里当第一个真实靶子。
3. 确认后我从 **P0** 开始，做完发 Engineering Report 再进 P1。

## 14. 拍板记录与进度

### 已拍板（2026-10-09）
| 问题 | 决定 |
|---|---|
| 两种模式语义 | `full_access` 全自动；`review` = 低风险自动审批 + 高风险人工确认 |
| 模型 | DeepSeek（`https://api.deepseek.com` / `deepseek-chat`），OpenAI 兼容协议 |
| 首批工具 | 5 个内置示例工具，真实脚本 P8 后再挂 |
| 开工授权 | 直接干 P0+P1 |

### 进度门
| 阶段 | 状态 | 证据 |
|---|---|---|
| P0 脚手架 | **通过** | 43 条后端用例全绿；`frontend` vitest 3 条全绿；`git init` 完成；`.env.example`/`.gitignore` 由测试断言内容 |
| P1 配置与模型客户端 | **通过（联网门待你跑）** | 同上测试；`uv run ruff check` 干净；覆盖率 TOTAL 94%（`app/model.py`、`app/main.py` 100%）；`MODEL_BACKEND=fake` 起 uvicorn，`GET /healthz` 返回 `{"status":"ok"}` 实测 200 |
| P2–P8 | 未开工 | — |

### P0/P1 实施中的偏差与发现
1. **FakeModel 落在 `app/testing/` 而非 `tests/`**：`MODEL_BACKEND=fake` 让没 key 的人也能跑起整个后端，替身因此是生产可用代码，必须被测试覆盖（现 93%），不适合藏在测试目录里。
2. **`Settings` 不自动读 `.env`**：只有 `get_settings()` 显式指向仓库 `.env`。裸 `Settings()` 读文件会让单元测试意外捡到开发者的真实 key——已有一条测试专门锁死这个行为。
3. **测试抓到两个真 bug**（都发生在实现侧，不是猜的）：`ResponseOutputMessage` 缺 `role` 必填字段；`ResponseTextDeltaEvent.logprobs` 必须是 `[]` 而不是 `None`。
4. **`create_app` 是工厂**，启动命令因此是 `uvicorn app.main:create_app --factory`，已同步进 §12。
5. **npm 在本机需 `NODE_OPTIONS=--use-system-ca`**（代理中间人证书在 Windows 信任库），已记入 §12；未使用 `strict-ssl=false`。
6. 前端脚手架为手写（`package.json` + `vite.config.js`），未用 `npm create vite`：可控且避开其交互式提问，依赖均为纯 JS。

### 进入 P2 前需要知道的
P2 将新建 `app/tools/`（注册表 + 5 个 builtin 工具 + 风险声明），并首次让 `@function_tool` 生成的 schema 进入断言。P1 的联网验收门（`scripts/ping_model.py`）不阻塞 P2，可在你方便时补跑。

