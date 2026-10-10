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
| `user_message` | `{text}` | 用户原文回显（P7 手验新增：历史还原的用户气泡只能来自持久化事件） |
| `text_message_content` | `{delta}` | 模型流式 token |
| `tool_call_start` | `{call_id, tool, risk}` | `ToolCallItem` |
| `tool_call_args` | `{call_id, delta}` | 参数流式 |
| `tool_call_end` | `{call_id}` | 参数齐 |
| `tool_result` | `{call_id, ok, output, duration_ms}` | `ToolCallOutputItem` |
| `approval_required` | `{approval_id, tool, arguments, risk}` | 中断 |
| `run_finished` | `{usage, turns}` | 正常结束 |
| `run_error` | `{kind, message}` | 异常/max_turns/工具失败兜底 |

**所有事件同时落 `events` 表**，SSE 支持 `Last-Event-ID` 断线重放——刷新页面也能完整还原执行轨迹（这是"看得到 Agent 在想什么"的核心体验，不能省）。浏览器 `EventSource` 无法自定义请求头，续流游标另走 `?last_event_id=` 查询参数，服务端两条路径等价（T6 有对照测试锁死）。

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
uv run uvicorn scripts.serve:app --reload                           # P6 起：同一工厂的具名入口

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
| 模型 | ~~DeepSeek~~ → **阿里云 DashScope `qwen3.8-flash`**（`https://dashscope.aliyuncs.com/compatible-mode/v1`，OpenAI 兼容协议；2026-10-09 下午改拍板，key 已配入本地 `.env`，已确认该 key 的 `/models` 目录含此模型） |
| 首批工具 | 5 个内置示例工具，真实脚本 P8 后再挂 |
| 开工授权 | 直接干 P0+P1 |

### 进度门
| 阶段 | 状态 | 证据 |
|---|---|---|
| P0 脚手架 | **通过** | 43 条后端用例全绿；`frontend` vitest 3 条全绿；`git init` 完成；`.env.example`/`.gitignore` 由测试断言内容 |
| P1 配置与模型客户端 | **通过（联网门已过，qwen3.8-flash）** | 同上测试；`uv run ruff check` 干净；覆盖率 TOTAL 94%（`app/model.py`、`app/main.py` 100%）；`MODEL_BACKEND=fake` 起 uvicorn，`GET /healthz` 返回 `{"status":"ok"}` 实测 200；2026-10-09 `scripts/ping_model.py` 对 DashScope 实弹通过 |
| P2 工具层 | **通过** | 全量回归 180 passed / 1 skipped（symlink 用例，本机卷不支持符号链接）；`ruff check` 干净；覆盖率 TOTAL 93%；前端 vitest 3 passed（P0/P1 未破坏）；5 工具 read/write/dangerous 三档齐全，schema 全部 strict（properties==required 有测试锁死） |
| P3 Agent 核心循环 | **通过（live 用例待你跑）** | T3 共 10 条全绿（`live` 1 条按 `-m live` 才执行）；全量回归 191 passed / 1 skipped；`ruff` 干净；覆盖率 TOTAL 93%（`app/agent/*` 91–100%）；前端 vitest 3 passed |
| P4 审批与两模式 | **通过** | T2 共 18 条全绿（六格矩阵 6 + 流程/状态 12）；全量回归 209 passed / 1 skipped；`ruff` 干净；覆盖率 TOTAL 93%（`approval.py` 95%、`events.py` 91%）；前端 3 passed |
| P5 持久化 | **通过** | T4 共 24 条全绿；迁移脚本连跑两次幂等（`scripts/migrate.py` 实跑）；全量回归 232 passed / 1 skipped；`ruff` 干净；覆盖率 TOTAL 93%（`db.py` 100%、`store.py` 94%）；前端 3 passed |
| P6 FastAPI 后端 | **通过** | T5+T6 共 18 条全绿；全量回归 250 passed / 1 skipped；`ruff` 干净；覆盖率 TOTAL 93%（`runtime.py` 88%）；前端 3 passed；手验门实跑：`uvicorn`（scripted fake 注入）+ curl 走完 会话→消息 202→SSE(id 1..5，止于 approval_required)→审批 202→`Last-Event-ID: 5` 续流(seq 6..18，止于 run_finished)→文件落地→重复审批 409→未知会话 404 |
| P7 Vue3 前端 | **通过** | vitest 38 passed（7 文件：reducer/SSE 客户端/actions/TracePanel/ApprovalDialog/ChatView/scaffold）；后端契约新增 `user_message` 后全量回归 252 passed / 1 skipped；`ruff` 干净；覆盖率 TOTAL 93%；`vite build` 成功；手验门浏览器实跑：提问→calculator 步骤(4.9ms)→approval_required 弹窗(工具/参数/风险齐全)→批准→run_finished(tokens 78·turns 3)→轨迹折叠/展开可见参数与输出→切 full_access 后二次发送免审批直达 done→删除并重新加载历史会话，用户/助手气泡与两步轨迹完整还原 |
| P8 端到端整合 | **通过（含真模型 3 任务门，qwen3.8-flash）** | T7 新增 2 条：跨层冒烟（API→SSE→审批→恢复→落库，seq 跨暂停密集无缝、台账与事件一致、文件落地、turns/usage 核对）+ 契约快照（10 类事件一类不多、payload 字段逐类钉死）；后端全量 254 passed / 1 skipped，`ruff` 干净，覆盖率 TOTAL 93%；前端 vitest 42 passed（新增错误边界 3 条 + 模式同步 1 条，均先 RED 后绿）；`vite build` 成功；README 启动三步按生产 wiring 实跑核验；**真模型门 2026-10-09 用 DashScope qwen3.8-flash 跑通**：`ping_model.py` 返回"连接正常"（1 请求 in=67/out=37）、`uv run pytest -m live` 通过、真实 uvicorn 上三任务全过——①review 审批链（7×8→暂停→批准→result.txt=="56"，turns=4）②纯问答不碰工具（涡扇 vs 涡喷）③full_access 工具串联（写 numbers.txt→读回→calculator 求和，答案含 600，turns=3），事件日志存 `data/live_gate/`。**16:27 二次复跑再一次 3/3**（gate1 turns=3、工具链顺序 write→read→calc，与首轮 write→calc→read 略有出入——模型自主决策差异，断言只钉集合不钉顺序，符合契约设计） |

### P0/P1 实施中的偏差与发现
1. **FakeModel 落在 `app/testing/` 而非 `tests/`**：`MODEL_BACKEND=fake` 让没 key 的人也能跑起整个后端，替身因此是生产可用代码，必须被测试覆盖（现 93%），不适合藏在测试目录里。
2. **`Settings` 不自动读 `.env`**：只有 `get_settings()` 显式指向仓库 `.env`。裸 `Settings()` 读文件会让单元测试意外捡到开发者的真实 key——已有一条测试专门锁死这个行为。
3. **测试抓到两个真 bug**（都发生在实现侧，不是猜的）：`ResponseOutputMessage` 缺 `role` 必填字段；`ResponseTextDeltaEvent.logprobs` 必须是 `[]` 而不是 `None`。
4. **`create_app` 是工厂**，启动命令因此是 `uvicorn app.main:create_app --factory`，已同步进 §12。
5. **npm 在本机需 `NODE_OPTIONS=--use-system-ca`**（代理中间人证书在 Windows 信任库），已记入 §12；未使用 `strict-ssl=false`。
6. 前端脚手架为手写（`package.json` + `vite.config.js`），未用 `npm create vite`：可控且避开其交互式提问，依赖均为纯 JS。

### 进入 P2 前需要知道的
P2 将新建 `app/tools/`（注册表 + 5 个 builtin 工具 + 风险声明），并首次让 `@function_tool` 生成的 schema 进入断言。P1 的联网验收门（`scripts/ping_model.py`）不阻塞 P2，可在你方便时补跑。

### P2 实施中的偏差与发现
1. **`http_get` 换成 `delete_session_file`**（偏差）：原计划首批工具含 http_get，但它需要网络 mock 才能测，且风险上只是 read 档；换成删除文件后 read/write/dangerous 三档全部有真实样本，P4 审批链路的测试才能当场覆盖 dangerous 档。真实脚本工具按计划 P8 再挂。
2. **SDK 对参数错误的真实行为（探针实测，非推测）**：缺参/类型错/坏 JSON 统一抛 `ModelBehaviorError("Invalid JSON input for tool X")`，**不含任何参数名**；多余的未知参数被静默忽略、工具照常执行。因此 `describe_failure` 对 `ModelBehaviorError` 分支会回查注册表 schema，把必填参数名（如 `expression`）写进给模型的中文提示里。
3. **`function_tool` 的关键字参数名是 `failure_error_function`**，不是 `error_function`；SDK 默认失败文案 "An error occurred while running the tool..." 对模型零信息量，已全部替换。
4. **手工构造 SDK 调用上下文必须用 `ToolContext`**（含 `run_config`），裸 `RunContextWrapper` 会在 `on_invoke_tool` 深处抛 AttributeError——该陷阱已封进 `app/testing/context.py::make_tool_context`。
5. **strict_mode 默认会把带默认值的参数也放进 required**，故本项目工具一律不设可选参数，测试用 `set(properties)==set(required)` 锁死。
6. **计算器实测修复**：`ast.parse(..., mode="eval")` 拒绝前导缩进与运算符后的换行，而模型常输出多行排版表达式；实现改为先折叠空白再解析（白名单语言无字符串字面量，折叠安全）。
7. **每阶段收尾纪律已执行**：P2 完成后做了死代码清理（删 `AppContext.session_id`、`make_tool_context` 的未用参数），并对 P0/P1 全量回归。该规则已记入项目记忆，P3 起每阶段照做。

### P3 实施中的偏差与发现
1. **流式 runner 不看裸 delta**：`Runner.run_streamed` 只在收到 `response.output_item.done` + 终态 `response.completed` 时才组装回合；FakeModel 原来只发 text/args delta，探针直接触发 "Model did not produce a final response!"。已升级 `_emit` 发完整事件序列（added→delta→done→completed，含 `ResponseUsage` 必填的 total/details 字段）。
2. **`FakeScriptExhaustedError` 基类改为 SDK `ModelBehaviorError`**（动了 P1 文件，理由）：流式循环把模型侧异常经 `stream_events()` 原样抛出，走 `ModelBehaviorError` 通道；脚本耗尽语义上就是"模型没给出应有的行为"，归一后事件契约的 `run_error.kind=="model"` 对真假模型一致。P1 断言不受影响（`pytest.raises` 仍精确）。
3. **`Usage` 是裸 dataclass，没有 `model_dump`**（实测 v0.23.1）：事件层的 `_usage_dict` 用 `dataclasses.asdict` 并只保留数值字段。
4. **SDK 只在参数齐后才发出 `tool_called` run-item**：契约里的 `tool_call_start/end` 背靠背发出；参数增量在此之前以 `tool_call_args` 流式给出。这是转译层的映射决定，已写进 events.py 模块头。
5. **max_turns 超限是迭代期异常**（`MaxTurnsExceeded`），不是结果状态：`stream_run` 捕获后落成终态 `run_error{kind:"max_turns"}`，绝不向上崩给调用方。
6. **`stream_run` 暂不接收 `session` 参数**：P4/P6 带测试接入 SQLiteSession 时再加；本轮清理时删掉了这个推测性形参（收尾纪律）。
7. **工具失败与成功在 SDK 输出里不可区分**（都返回字符串）：`tool_result.ok` 以 `describe_failure` 的固定措辞 "调用失败" 判定，常量集中定义；P4 若引入结构化失败标记再替换。

### P4 实施中的偏差与发现
1. **`RunState.from_json` 先用纯 JSON 类型校验整棵状态树，`context_override` 要在校验之后才生效**：`AppContext.workspace` 是 `Path`，默认 `to_json()` 产出的 dict 含非 JSON 原生值，恢复时直接失败且异常被 redact 成 "Error details are redacted"（极难诊断，探针实测）。方案：`to_json(context_serializer=...)` 把 Path 转 str；恢复时 `context_override` 传服务端 AppContext（SDK 自动包成 RunContextWrapper）。
2. **`to_json` 返回 dict 而非字符串；`from_json` 是协程**：审批令牌在 P5 落库时才序列化，`on_state` 回调传递的是 dict。
3. **`tool_called` 在暂停前就已发出**（SDK 语义 = 模型请求了调用）：暂停流里有 `tool_call_start/end` 但没有 `tool_result`；结果出现在恢复流中。`approval_required` 是暂停流的终态事件。
4. **always_approve 实测行为**：恢复流含 2 条 `tool_result`（首个被批准的 + 第二个免审的），且不再产生新中断——测试预期按实测修正（一次预期写错，是实现没错）。
5. **reject 的 `rejection_message` 确实回灌进模型下一回合输入**（`fake.calls` 断言实测通过），拒绝理由可被模型遵守。
6. **无决策的中断默认拒绝**（`decisions` 缺失该 approval_id → reject + 默认理由）：用户沉默不等于同意。
7. **审批策略经 `dataclasses.replace` 克隆到工具实例**：注册表共享实例绝不被改写，同一进程可并存不同模式的 run；`should_pause` 是纯函数，六格矩阵逐格断言。

### P5 实施中的偏差与发现
1. **连接以 `isolation_level=None`（autocommit）打开，事务全部显式 `BEGIN IMMEDIATE`**：Python 默认的延迟事务会让"SELECT MAX(seq)+1 再 INSERT"在并发下交错；IMMEDIATE 直接拿写锁串行化，`UNIQUE(session_id, seq)` 兜底。4 线程×10 事件实测 seq=1..40 无撞无死锁（busy_timeout=5000）。
2. **seq 语义按计划微调**：会话内单调密集（断线重放游标所需），跨 run 也共享（同一会话的多个 run 连续编号）——§7 只要求"每会话单调"，实现取密集无缺口最强保证。
3. **`finish_run` 与 `transition_run` 共用同一跃迁校验**：便利路径不得绕过状态机（非法跃迁测试对两条路径都断言）。
4. **状态字符串先校验成员再校验边**：`transition_run("未知状态")` 报"未知的 run 状态"，避免脏字符串进库（清理轮补的测试）。
5. **JSON 一律 `ensure_ascii=False` 落库**：中文 payload 在 sqlite 工具里直读；时间戳统一 UTC ISO 毫秒。
6. **审批决定不可翻转**：`decide_approval` 对非 pending 记录报 `InvalidTransitionError`（重复点击/重放防护留给 P6 层复用）。

### P6 实施中的偏差与发现
1. **取消的终态必须由取消方同步写，不能指望被取消协程自己收尾**（实测踩坑）：纯内存 await（ASGITransport、busy loop）可能让 pump 任务从未被调度，对未启动任务 `cancel()` 不执行任何函数体——包括 except 分支。`cancel_run`/`shutdown` 现在先同步落 `cancelled` 状态 + `run_error{kind:"cancelled"}` 事件，再 cancel 任务；`_finish_cancelled` 幂等，pump 后醒来自我跳过。
2. **`run_error.kind` 契约扩展**：新增 `cancelled`（取消）与 setup 失败时的 `internal`（agent 工厂炸，如缺 key）；`openai.APIError`（真实 5xx 通道）归入既有 `model` kind。§6 的 kind 集合以代码为准：max_turns | model | internal | cancelled。
3. **SSE 端点 = events 表的"重放 + 跟读"**：先订阅内存队列再读库（先读后订会丢交错事件）；载荷始终从库里取，队列只送"醒了"信号；`run_finished/run_error/approval_required` 三种事件关闭流——审批暂停后前端断开、决定后带 `Last-Event-ID` 重连，正好复用同一契约。
4. **恢复暂停 run 需要"同一个 Agent 对象"的深层原因**：`RunState.from_json` 校验依赖工具集合，且 FakeModel 的脚本位置存在实例上——Runtime 因此把暂停时的 agent 存进 `_paused_agents`，跨请求复用；进程重启则回退工厂重建（工具与审批策略由 mode 唯一决定，成立）。
5. **SQLiteSession 用独立文件 `data/sdk_memory.db`**（偏差，§7 未指明文件名）：与轨迹库同文件时 SDK 的惰性事务会和 `BEGIN IMMEDIATE` 写者抢锁；`sdk_*` 表依旧"不碰不迁移"。
6. **`create_app()` 不再要求开机有 API key**（改了 P0/P1 行为，理由充分）：默认工厂把 `build_model` 推迟到首个 run 的 setup 阶段，配置错误以 run_error 事件呈现（含修复指引），/healthz 与会话 CRUD 照常可用——server 可先起、后补 key。P0 两条脚手架测试同步改为自带 Settings（fake 后端 + 临时数据目录），顺带修掉了它们读开发者真实 `.env` 的旧隐患。
7. **手验门的 scripted 注入**：默认 fake 无脚本、不会暂停，手验审批流时以临时 launcher 注入 `FakeModel([tool_call, text])` 工厂（与测试同一 seam），uvicorn 真进程 + curl 全链路通过，见进度门 P6 行。
8. **`scripts/migrate.py` 默认库路径改为 `get_settings().database_path`**（清理轮发现）：P5 写死的 `data/trace.db` 与 P6 实际挂载的 `small_dify.db` 会分裂成两个库；现在 CLI 与应用读同一配置源。
9. **raw-ASGI 测试泵必须声明 `spec_version: "2.4"`**：2.3 会触发 starlette 旧版 disconnect 任务组，对永不挂起的 `receive()` 忙轮询、饿死事件循环（第一次跑 T6 直接整机冻住 20 秒才现形）。
10. 每阶段收尾纪律执行：T5/T6 完成后清理了测试脚手架里的占位垃圾（`with pytest.suppress`、`_noop`、死断言），并全量回归 P0–P5（250 条无破坏）。

### P7 实施中的偏差与发现
1. **手验门抓到契约级真 bug：持久化事件里没有用户原文**。live 时用户气泡是前端 send() 本地推的，历史 `?format=json` 还原时缺 `user_message` 事件 → 重载后只剩助手气泡。按测试先行修复：后端 2 条 RED（T3 skeleton + T6 replay）→ `stream_run` 在 `run_started` 后回显 `user_message{text}` → 前端 EVENT_TYPES 与 reducer 同步。§6 契约表现为 10 类事件。
2. **EventSource 不能带自定义请求头**：续流游标另走 `?last_event_id=`（后端 header/query 等价路径 P6 已有对照测试），前端只用查询参数一条路。
3. **`approval_required` = 本轮连接终点**：弹窗"决定→POST→带游标重连"复用与断线重放完全相同的机制，没有第二条代码路径。
4. **store 是唯一 reducer**：`tool_call_args` 增量可能先于 `tool_call_start` 到达（SDK 先发参数流），按 call_id 缓冲进 `argsBuffer`，start 落地时合并——reducer 测试专门锁死这个乱序。
5. **EventSource 句柄不放 pinia state**（模块级私有）：把活的套接字对象塞进响应式状态只会招 Proxy 意外；单人应用同时只有一条活跃流。
6. **user_message 去重**：live 路径 send() 先本地推气泡、事件随后到达，reducer 按"最后一条同文本 user 消息"去重；历史重放（本地无推入）照常还原。
7. **测试自身两枚陷阱**：同一个 pinia 里 `useAgentStore()` 返回同一实例——"fresh 应为 idle"必须先 `setActivePinia(createPinia())`；jsdom 里点击按钮不触发表单隐式提交，发送按钮改为 `type=button + @click`。
8. **手验 launcher 复用固定 SCRIPT 会使两次运行共享 call_id**，store 的 ensureStep 按 id 合并步骤——launcher 产物而非前端缺陷（真实模型每次 call_id 唯一）。记录在案防误报。
9. **vite `/api` 代理必须 `rewrite` 剥前缀**（后端路由挂在根上）；本机 vite 7 只绑 `[::1]`，用 127.0.0.1 探它会 ECONNREFUSED，手验与文档统一 `http://localhost:5173`。
10. **markstream-vue 2.0.16**：直接使用组件是命名导出 `MarkdownRender`（props `content`/`final`），流式期间 `final=false`；生产构建有 >500kB chunk 警告（含代码高亮/图表异步块），本地单人应用接受，不做手工分包。
11. 收尾纪律执行：删除 client.js 中未被任何调用方使用的 `getRun`/`listApprovals` 占名接口；清掉 P5 遗留的死库 `data/trace.db`；回归 252 + 38 全绿后才勾选手验门。

### P8 实施中的偏差与发现
1. **T7 集成冒烟一次转绿**：P0–P7 的分层测试没有掩盖跨层缺口（seq 跨暂停无缝、审批台账与事件一致、恢复段游标衔接在 T5/T6/T7 三处独立成立）。契约快照测试的价值在"钉死"而非"抓到"——10 类事件、每类 payload 字段集合逐一对表 §6，未来漂移会先在这里红。
2. **错误边界收进 store action（先 RED 3 条）**：`decide` 409、`send` 500、`cancel` 竞态若以 rejection 冒泡，Vue 组件层就是未处理 Promise。现在 `send/decide` 失败落 `status='error'+store.error`（弹窗因暂停已失效而关闭），`cancel` 失败**只报不改状态**——取消没成功时流还活着，状态机不许撒谎。ChatView 里重复的 try/catch 随之删除。
3. **模式开关与所加载会话对齐**（契约微调，先 RED）：`sessionMode` 的权威来源从"事件里的历史 run_started / 侧栏行"改为 `GET /sessions/{id}` 的当前行——开关反映的是"下一条消息会怎样"，重载会话后必须与服务端一致。为此在 client.js 恢复了 `getSession`（P7 清理时因无调用方删掉，现在有真实调用方，清理决定没有被推翻）。
4. **README 的启动三步按生产 wiring 实跑核验**（`scripts.serve:app` + `MODEL_BACKEND=fake` + curl 全流程），不是照抄命令约定；`.env.example` 的 `DATA_DIR` 注释补上双库布局说明。
5. **真模型门（§10 P8 的最后一格）不在我手里**：`-m live`、`ping_model.py` 和"3 个真实任务留日志"需要你的 DeepSeek key。fake 侧的等价证据链已完整（同一 SDK 通道、同一事件契约、T3 的 live 用例与 fake 用例断言同一组事实）。
6. 收尾纪律执行：ruff 抓到 T7 初稿的未用变量与 import 排序并清零；三台验证用的后台服务（8000/8011/5173）全部关停、临时脚本与临时数据目录删除；`git status` 全清单核对无游离文件。P2–P8 尚未提交，等你发话。

### U 系列：会话式界面改造（2026-10-10，需求=把网页改成 DeepSeek 式双栏会话布局）

| 阶段 | 状态 | 证据 |
|---|---|---|
| U1 现状与缺口调研 | **通过** | 逐条对照 6 点需求列出缺口：后端缺 pinned/上传接口、前端缺分组侧栏/URL 恢复/每消息步骤/复制/重生成/附件 |
| U2 后端 | **通过** | `sessions.pinned`（INTEGER DEFAULT 0 + `PRAGMA table_info` 幂等 ALTER 兼容旧库）；PATCH 放行 title/mode/pinned（bool→int，`exclude_none` 不误丢 false）；列表 `pinned DESC, updated_at DESC` 排序；`POST /sessions/{id}/files` base64 附件上传（≤1MB、workspace 内 `safe_path` 复用、非法 base64/越界/超限分别 400/400/413）；后端全量 261 passed / 1 skipped，`ruff` 干净；真实库 `scripts/migrate.py` 实跑升级 |
| U3 前端 | **通过** | 先 RED 20+ 条再实现（后修正 3 条 RED 自身缺陷：togglePin 用例 GET 分支引用 null body、failFetch 作用域、pin 翻转期望值）；新增 SessionSidebar（新建/搜索/分组/行内重命名/置顶/删除/折叠/底部设置）与 utils（groups.js、attachment.js）；ChatView 重写（标题栏、Enter/Shift+Enter、复制、重新生成、每消息可折叠步骤、实时轨迹、吸底多行输入 + 附件）；store 新增 renameSession/togglePin/uploadAttachment/regenerate、removeSession 相邻切换、run_started→runAnchor、run_finished/error→flushSteps 步骤快照；vitest 80 passed（10 文件），`vite build` 成功 |
| U4 回归 + 手验 | **通过** | 后端 261 + ruff + migrate 幂等；前端 80 + build；浏览器实跑（fake 后端 + 临时 scripted launcher 走 `create_app(agent_factory=...)` seam）：发消息→URL ?sid=→刷新历史完整恢复→置顶分组迁移→重命名同步标题→搜索过滤→新建自动切换→切换/删除会话（相邻→空白兜底）→附件 chip→带附件消息附注→服务器 workspace 落盘→复制/重新生成→折叠步骤（data-status=success、耗时）→审批弹窗（awaiting→展示参数→批准→恢复直达 done）→错误态诚实展示；验证后临时脚本/临时数据目录删除、端口 8000/5173 清空（含一枚历史 vite 残留进程）。**同日 DashScope 充值后真模型三门复跑全过**：ping（in=67/out=36）、`pytest -m live`、三任务门 gate1 review 审批链 turns=4·result.txt=="56" / gate2 纯问答零工具 / gate3 full_access write→read→calculator 含 600，日志 `data/live_gate/gate*.jsonl` |

### U 系列实施中的偏差与发现
1. **附件上传不引 multipart 依赖**：`{filename, content_base64}` JSON + 服务端校验（大小上限、base64 合法性、`safe_path` 防越界），复用既有工具层防线，前端 `FileReader.readAsDataURL` 切割前缀即可，零新依赖。
2. **步骤归属用 `runAnchor` 钉死**：`run_started` 记录 `messages.length` 锚点，`flushSteps` 只把步骤挂到"本 run 创建的气泡"；无锚点时一次无正文的 run 会把步骤错接到上一条答案上。
3. **pinned=false 必须原样下发**：SQLite 无 BOOLEAN 靠 int 存；前端若用"falsy 即删字段"的通用 patch 写法会永远无法取消置顶——专门一条 RED 锁死 `{pinned:false}` 上线。
4. **URL 同步不走 vue-router**：单人应用一页一屏，`?sid=` + `history.replaceState` 足够，路由依赖为零（偏差于"刷新恢复"的常见实现路径）。
5. **重命名内联编辑器不加确认弹窗**：Enter 确认、Esc 取消、✓ 按钮兜底；测试锁死"Esc 不得触发 PATCH"。
6. **真模型手验被外部阻断**：DashScope 账号欠费（错误码 `Arrearage`），qwen3.8-flash 暂不可用；界面改造本身不依赖模型侧（工具步骤/审批用测试同一 seam 的 scripted fake 全链路验证），真实模型回归等你把账号恢复后 `-m live` + `ping_model.py` 复跑即可。**（2026-10-10 已解除：充值后三扇真模型门复跑全过——ping in=67/out=36；`pytest -m live` 通过；三任务门 gate1 review 审批链 turns=4、result.txt=="56"，gate2 纯问答零工具零审批，gate3 full_access write→read→calculator 链、答案含 600；日志 `data/live_gate/gate*.jsonl`；临时驱动脚本与临时数据目录已删）**
7. **手验抓到一处 RED 期望自错**（非实现 bug）：pin 翻转用例把"已置顶行"的期望写成 pin=true；以 fixture 语义修正为 unpin 方向，并保留"翻转值原样下发"断言。
8. 收尾纪律执行：删除临时演示 `scripts/_ui_demo.py`、充值后复跑用的临时真模型门驱动 `scripts/_live_gate_scratch.py`，以及 `data_ui_check/`、`data_ui_live/`、`data/live_gate_run/`；`scripts/__pycache__` 残留清除；`git status` 核对——改动只落 U 系列相关文件。**U2–U4 已于 2026-10-10 提交 `f00e07d` 并推送 master（远端 API 核验：head 一致、`.env` 仍 404）**。

### V 系列：商业级界面精修（2026-10-10，需求=资深前端+产品设计师一次性自主交付，禁止中途确认）

| 阶段 | 状态 | 证据 |
|---|---|---|
| V1 设计系统 | **通过** | 新增 `styles/theme.css`：全部规格令牌（亮 #F9FAFB/#FFF，暗 #171717/#212121，渐变 135deg #4D6BFE→#7C5CFF，四状态色，玻璃拟态、12–16px 圆角、Inter/PingFang SC 15px/1.7、meta 12px #6B7280）、9 组 keyframes、`.msg-enter`、prefers-reduced-motion 总开关；`index.html` 预渲染内联脚本按 localStorage 定 `data-theme` 防白闪；`main.js` 挂载前 `applyTheme()+watchSystemTheme()` |
| V2 布局外壳 | **通过** | `App.vue` grid 双栏（100dvh、overflow-hidden）：拖拽手柄 pointer 事件（240–360 clamp+持久化）、折叠 44px 轨道、<768px 覆盖抽屉（scrim 模糊、左滑关闭）；0 视口 webview 内实测桌面态：拖 280→320 生效、localStorage 同步、列模板 `320px 5px 0px`、折叠 `44px 0px` |
| V3 侧栏精修 | **通过** | 分组（置顶/今天/昨天/7 天内/更早，本地日界）、搜索 `<mark>` 高亮、首字母恒定色相头像、行 ⋯ 菜单（重命名/置顶/复制链接/删除）、删除走 `ConfirmDialog` 弹层（禁 window.confirm，测试锁死 spy 未调用）、骨架屏、底部设置/主题/头像；修复 Vue scoped `v-bind` 模板串编译出畸形自定义属性的缺陷（列宽改由 App grid 决定，组件 `width:100%`） |
| V4 聊天区精修 | **通过** | 玻璃吸顶头栏（内联改标题、状态胶囊呼吸点、分享/导出/清空、模式段）、用户气泡右 70%/AI 头像+气泡、悬停操作条（复制/赞/踩/重新生成）、typing 三点+流式光标、自动增高玻璃输入区（≤6 行）、发送↔停止（红脉冲环）、Enter/Shift+Enter、空态 4 快捷卡、`/chat/:sid` 路径路由（兼容旧 `?sid=`）、无 id 自动选最近会话、错误卡+重试；浏览器实测：发送→calculator 步骤卡（success/耗时/pretty 参数结果）、审批弹窗→批准→恢复、导出 toast、空态快捷卡只填充 |
| V5 步骤卡重做 | **通过** | TracePanel：lucide 状态图标（pending 圈/running 自旋/success 勾/error 叉，显式 class 不依赖 `.lucide`）、垂直时间线连接线、running 流光渐变边框、展开 pretty JSON；折叠交互契约不变 |
| V6 全局反馈+自检 | **通过** | toast store+ToastHost（右上、自动消失、kind 色）、Skeleton、错误重试；全量回归：**vitest 110/110、vite build ✓、后端 261 passed/1 skipped、ruff 干净**；浏览器自检（fake 后端 scripted seam）：深色令牌单帧翻转、刷新 `/chat/:sid` 恢复 4 条消息、重命名→行+标题同步、置顶→分组迁移、搜索命中/空/还原、删除弹层取消、模式段切换持久化 |

### V 系列实施中的偏差与发现
1. **不引 Tailwind/vue-router**：规格令牌全部落 CSS 变量 + scoped style；"路由"用 replaceState + path 解析自研数十行，依赖面零增长（构建仅原有 markstream >500kB 警告）。
2. **图标全部 lucide-vue-next（1.75 描边意图靠显式 class），零 emoji**；lucide v1 不保证自动 `.lucide` class，所有状态类显式绑定。
3. **"思考过程"无后端事件**：以"执行过程"可折叠步骤列表（虚线左轨）代替，诚实降级不造假数据。
4. **赞/踩仅本地态**（后端无反馈字段，UI 保留 toggle）；"清空"是视图清空（startNewSession），历史仍在库。
5. **隐藏 webview 视口 0×0**：matchMedia 强制 mobile 假象、rAF 停摆导致 CSS transition 停在起始值——深色"未变色"实为检查环境假象（令牌与 fresh 渲染均正确）；桌面态验证通过直接翻转 App 的 `isMobile` 完成。
6. **Vue scoped `v-bind("`…${}…`")` 模板串是编译器陷阱**：生成畸形自定义属性名并静默失效，必须用简单表达式或由外层 grid 控制宽度。
7. 收尾纪律：删除 `scripts/_v_demo.py`、`data_v_check/`，8000/5173 端口清空（含一枚 vite 残留进程）；需求变更引发死代码审计：动画/工具类/符号/lucide 导入逐一扫过均有引用，前期已清 Loader 冗余导入、`--glass-border` 死令牌、`<Pin :size="0">` 占位、App 空全局 style 块、▸/✓ 字形→lucide。

### W 系列：侧栏局部修改（2026-10-10，需求=只改左侧会话栏：头像→运行状态指示器 + 顶部品牌区）

| 阶段 | 状态 | 证据 |
|---|---|---|
| W1 状态指示器 | **通过** | 删除首字母头像与 `hueFor` 色相逻辑（`.avatar`/`--av-hue` 一并清）；行首改为 7px 状态点/lucer 自旋圈：`idle` 灰点、`running`（streaming/awaiting）主色 Loader 自旋、`done` 绿点 #10B981+呼吸动画、`error` 红点 #EF4444；**状态纯派生**：`statusFor(s)` 只读 `agent.sessionId`/`agent.status`，非当前会话恒 idle，未新造状态系统；150–200ms 过渡、垂直居中；W 测试 8 条（先 RED）：flipped 顺序、awaiting=running、done→error 需 `nextTick`、cancelled 诚实回落 idle |
| W2 品牌区 | **通过** | aside 首位 `.brand-bar`（56–64px、下分割线）：渐变 chip logo（lucide `Sparkles` 26px）+ 产品名 15px semibold；`BRAND = { name, logo }` 常量置顶并带⚙注释，改图标/名称一处生效；折叠态只留居中 logo（测试锁死 collapsed 时名称不渲染）；底部原 `.brand` 文字随之下线；移动端抽屉天然保留 |
| W3 回归+手验 | **通过** | vitest 118/118、`vite build` ✓；浏览器（fake 后端 scripted seam）：pinia 直接poke `status=streaming` → 该行 spinner 出现、其余行灰点；done→绿点呼吸；折叠→只显 logo；刷新深链不误报。收尾：临时 launcher/数据删除、端口清空 |

### W 系列实施中的偏差与发现
1. **done 态只可能属于当前会话**：SSE 状态机是会话级单流（`agent.status` 描述打开中的会话），历史会话无 last-run 状态持久化，故非打开会话统一 idle——诚实派生，不伪造"完成"历史。
2. **品牌区在 aside 内部**而非 App 外壳：折叠/抽屉/宽度全部沿用既有 grid 与 ui store，零跨组件改动，符合"只改侧栏"约束。

### 聊天区巨型 Python 图标 Bug 修复（2026-10-10，现象=代码块语言图标撑满半屏）

| 项 | 结论 |
|---|---|
| 根因 | 不是产物卡片（项目中不存在该组件）。`ChatView.vue:345` 的 markstream-vue `<MarkdownRender>` 渲染代码块头部 `.icon-slot` 语言图标，其 SVG **只有 viewBox 无 width/height**，16px 尺寸规则全在包自带样式表 `markstream-vue/index.css`（`.h-4{height:1rem}`、`.icon-slot svg{width:100%;height:100%}`，README 明确要求引入），而 `main.js` 从未 import → SVG 退化默认尺寸被父容器撑大。js（16 viewBox）/go/无语言同路径同病。此前 fake 回复均为纯文本 + ChatView 单测 mock 掉 MarkdownRender，路径从未执行故未暴露 |
| 修复 | 双防线：① `main.js` 补 `import 'markstream-vue/index.css'`（theme 之前，主题可覆盖）；② ChatView scoped `:deep` 兜底钉死 `.icon-slot svg/img` 16px（width/height/max-* 四锁 + flex-shrink:0，不依赖父容器与外部 CSS），`.code-block-container` `max-width:100%; overflow-x:auto` 保证代码块高度=内容高度、不横向撑破 |
| 验证 | 新增 `markdown_render.spec.js` 6 条：两防线内容锁 + 真实 MarkdownRender 跑 python/js/go/无语言断言图标带尺寸约束；vitest **124/124**、`vite build` ✓ 且 dist CSS 含 `.h-4`/`icon-slot svg` 规则；浏览器端到端复现用户场景（"写一个 python 脚本计算 1 到 100 的平方和"→"脚本已保存到 square_sum.py"+```python 围栏）：svg 计算尺寸 16×16、复制按钮在位、流式 status done、控制台零报错；0 宽视口下 slot 仍 16×16——"不随父容器撑开"直接证据（375/1920 因固定 px+max-width 守卫天然安全；像素级截图受 webview 0×0 限制，验证到 computed 层面） |
| 偏差 | 兜底取 16px 与代码块头部既有比例（图标与文件名/复制按钮同体量）而非规格下限 20px；如需 20–24px 只改 `:deep` 一处。测试内容锁用 `path.resolve(process.cwd(), …)` 读文件——jsdom 下 `new URL(rel, import.meta.url)` 抛 "must be of scheme file" |

收尾纪律：本轮删除 `scripts/_icon_demo.py`、`data_icon_check/`、探测用 `markdown_probe.spec.js`，端口 8000/5173 清空。





