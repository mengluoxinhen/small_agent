# small_dify

中文 | [English](README.en.md)

用自然语言驱动的个人 Agent：模型自己决定调用哪些工具、看到工具结果后继续推进，直到任务完成。执行全程可视化（SSE 事件流 + 轨迹面板），高风险操作可暂停等你审批。后端 FastAPI + [OpenAI Agents SDK](https://github.com/openai/openai-agents-python)，前端 Vue 3（纯 JS），轨迹存 SQLite。完整设计与各阶段验收见 `docs/PLAN.md`。

## 三步启动

```bash
# 1) 后端依赖（推荐 uv；或 plain pip：python -m venv .venv && pip install -r requirements-dev.txt）
uv sync

# 2) 起后端 —— 两种任选其一：
#    a. 没有 API key：确定性 fake 模型，全功能可玩（含审批流）
MODEL_BACKEND=fake uv run uvicorn scripts.serve:app --reload --port 8000
#    b. 真实模型：cp .env.example .env，填入你的 LLM_API_KEY（当前配置指向
#    阿里云 DashScope 兼容模式的 qwen3.8-flash，任何 OpenAI 兼容端点均可）
uv run uvicorn scripts.serve:app --reload --port 8000

# 3) 起前端（另开终端）
cd frontend
NODE_OPTIONS=--use-system-ca npm install
npm run dev          # http://localhost:5173 （注意用 localhost，见下方排坑）
```

打开页面即可提问。`review` 模式下，读类工具（calculator、读文件、列文件）自动执行；
写类/危险类工具（写文件、删文件）会弹出审批窗——批准后才真正执行，拒绝会把理由回灌给模型。
顶栏可在 `review` 和 `full_access`（全自动）之间切换，对下一条消息生效。

## 把自己的 Python 脚本挂成工具

工具自动发现：往 `app/tools/builtin/` 放一个**不以 `_` 开头**的模块，里面用
`@function_tool` 定义函数，并在模块里声明每个工具的风险等级（缺声明会被拒绝注册，而不是默认安全）：

```python
# app/tools/builtin/my_tool.py
from agents import RunContextWrapper, function_tool
from app.tools.context import AppContext
from app.tools.errors import describe_failure

TOOL_RISK = {"summarize_case": "read"}   # read | write | dangerous

@function_tool(failure_error_function=describe_failure)
async def summarize_case(ctx: RunContextWrapper[AppContext], filename: str) -> str:
    """一句话说明这个工具干什么（模型靠它做选择，写清楚参数约束）。

    Args:
        filename: 会话工作区内的纯文件名。
    """
    ...  # 调你自己的脚本；ctx.context.workspace 是本会话的私有目录
```

重启后端即生效（`uv run python scripts/list_tools.py` 可核对）。约定：

- 文件操作一律相对会话工作区，不要写绝对路径（越界会被拒绝，且错误信息不会泄露宿主机路径）。
- 有副作用的工具如实标 `write`/`dangerous`，审批策略按模式从此表推导。
- 参数不设默认值（SDK strict schema 会把带默认值的参数也列为必填）。

## 测试与检查

```bash
# 后端（仓库根目录）
uv run pytest                      # 全量（自动排除需要真实 API key 的 live 用例）
uv run pytest --cov=app            # 带覆盖率
uv run pytest -m live              # 唯一联网套件：需要 .env 里的真实 key
uv run ruff check app tests scripts
uv run python scripts/ping_model.py  # 真调一次所配置的模型端点冒烟

# 前端
cd frontend && npm run test        # vitest（42 条，覆盖事件 reducer/SSE/组件/装配）
npm run build
```

项目纪律：测试先行（先 RED 后实现）、每阶段全量回归历史测试、死代码当轮清理。

## 排坑（Windows 实测）

- **npm 证书**：本机代理做 HTTPS 中间人，证书在 Windows 系统信任库，Node 默认不读——
  统一用 `NODE_OPTIONS=--use-system-ca`，不要关 `strict-ssl`。
- **浏览器访问**：vite 默认只绑 IPv6 回环，请用 `http://localhost:5173`，`127.0.0.1:5173` 会拒绝连接。
- **中文输出**：测试与脚本显式 `encoding="utf-8"`。

## 架构一瞥

```
app/
  config.py          # pydantic-settings，.env 单一来源
  model.py           # build_model：任意 OpenAI 兼容端点（当前配 qwen3.8-flash）或 fake
  agent/             # factory(两模式) + prompts + events(SDK→契约事件转译)
  tools/             # registry(自动发现+风险表) / builtin(工具面) / impl(纯函数)
  approval.py        # 纯函数审批策略（六格矩阵）
  store.py / db.py   # 轨迹库：sessions/runs/events/approvals，seq 会话内密集单调
  runtime.py         # 后台 run 生命周期：落事件→推队列→暂停/恢复/取消
  main.py            # FastAPI：会话 CRUD、消息、审批、SSE 重放+跟读
frontend/src/
  api/               # client(fetch) + sse(EventSource，游标走 ?last_event_id=)
  stores/agent.js    # pinia 单一 reducer：10 类契约事件 → 界面状态
  components/        # ChatView / TracePanel / ApprovalDialog
```

数据落在 `DATA_DIR`（默认 `./data`，已 gitignore）：`small_dify.db`（轨迹）、
`sdk_memory.db`（SDK 会话记忆）、`workspaces/<session_id>/`（会话私有文件区）。

## 许可

MIT（见 `LICENSE`）。欢迎fork改造，注明出处即可。

