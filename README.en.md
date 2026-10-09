# small_dify

[中文](README.md) | English

A personal agent driven by natural language: the model decides which tools to call, reads the results, and keeps going until the task is done. Every step is visible (SSE event stream + trace panel), and high-risk operations pause for your approval. Backend: FastAPI + [OpenAI Agents SDK](https://github.com/openai/openai-agents-python); frontend: Vue 3 (plain JavaScript); traces: SQLite. Full design and per-phase acceptance notes live in `docs/PLAN.md` (Chinese).

## Quick start (3 steps)

```bash
# 1) Backend deps (uv recommended; or plain pip: python -m venv .venv && pip install -r requirements-dev.txt)
uv sync

# 2) Start the backend — pick one:
#    a. No API key: deterministic fake model, every feature playable (approval flow included)
MODEL_BACKEND=fake uv run uvicorn scripts.serve:app --reload --port 8000
#    b. Real model: cp .env.example .env and set LLM_API_KEY (the current config points at
#    Aliyun DashScope's OpenAI-compatible endpoint with qwen3.8-flash; any compatible provider works)
uv run uvicorn scripts.serve:app --reload --port 8000

# 3) Start the frontend (separate terminal)
cd frontend
NODE_OPTIONS=--use-system-ca npm install
npm run dev          # http://localhost:5173 (use "localhost", not 127.0.0.1 — see Gotchas)
```

Just open the page and ask. In `review` mode, read-only tools (calculator, read/list files) run
automatically; write/dangerous tools (write/delete files) pop an approval dialog — nothing executes
until you approve, and a rejection sends your reason back to the model. The header toggles between
`review` and `full_access` (fully automatic); it applies to the next message.

## Plug in your own Python scripts as tools

Tools are auto-discovered: drop a module **not starting with `_`** into `app/tools/builtin/`,
define functions with `@function_tool`, and declare each tool's risk level in that module
(a missing declaration rejects registration instead of silently defaulting to safe):

```python
# app/tools/builtin/my_tool.py
from agents import RunContextWrapper, function_tool
from app.tools.context import AppContext
from app.tools.errors import describe_failure

TOOL_RISK = {"summarize_case": "read"}   # read | write | dangerous

@function_tool(failure_error_function=describe_failure)
async def summarize_case(ctx: RunContextWrapper[AppContext], filename: str) -> str:
    """One sentence on what this tool does (the model picks tools by it; state param constraints).

    Args:
        filename: a plain file name inside the session workspace.
    """
    ...  # call your own script; ctx.context.workspace is this session's private directory
```

Restart the backend to pick it up (verify with `uv run python scripts/list_tools.py`). Conventions:

- All file operations are relative to the session workspace; never write absolute paths
  (escapes are rejected, and error messages never leak host paths into the model's context).
- Mark side-effecting tools honestly as `write`/`dangerous`; the approval policy is derived
  from this table per mode.
- Do not give parameters default values (the SDK's strict schema would mark them required anyway).

## Tests & checks

```bash
# Backend (repo root)
uv run pytest                       # full suite (live tests needing a real key are auto-excluded)
uv run pytest --cov=app             # with coverage
uv run pytest -m live               # the only networked suite: needs a real key in .env
uv run ruff check app tests scripts
uv run python scripts/ping_model.py # one real round-trip against the configured model endpoint

# Frontend
cd frontend && npm run test         # vitest (42 tests: event reducer / SSE client / components / wiring)
npm run build
```

Project discipline: test-first (RED before implementation), full regression of all earlier
phases' tests after every phase, and dead-code cleanup in the same round.

## Gotchas (all measured on Windows)

- **npm TLS**: a local proxy does HTTPS interception with certs in the Windows trust store,
  which Node ignores by default — use `NODE_OPTIONS=--use-system-ca`, never disable `strict-ssl`.
- **Browser access**: vite binds the IPv6 loopback only; use `http://localhost:5173`
  (`127.0.0.1:5173` refuses connections).
- **Chinese output**: tests and scripts set `encoding="utf-8"` explicitly.

## Architecture at a glance

```
app/
  config.py          # pydantic-settings, .env as the single source
  model.py           # build_model: any OpenAI-compatible endpoint (currently qwen3.8-flash) or fake
  agent/             # factory (two modes) + prompts + events (SDK → contract-event translation)
  tools/             # registry (auto-discovery + risk table) / builtin (tool face) / impl (pure funcs)
  approval.py        # pure-function approval policy (6-cell matrix)
  store.py / db.py   # trace DB: sessions/runs/events/approvals, dense per-session seq
  runtime.py         # background run lifecycle: persist events → queue → pause/resume/cancel
  main.py            # FastAPI: session CRUD, messages, approvals, SSE replay + live tail
frontend/src/
  api/               # client (fetch) + sse (EventSource, cursor via ?last_event_id=)
  stores/agent.js    # pinia single reducer: 10 contract event types → UI state
  components/        # ChatView / TracePanel / ApprovalDialog
```

State lives under `DATA_DIR` (default `./data`, gitignored): `small_dify.db` (traces),
`sdk_memory.db` (SDK conversation memory), `workspaces/<session_id>/` (per-session files).
The SSE contract (10 event types, PLAN §6) is both the reconnect/replay protocol and the
frontend's only data source — refreshing a page restores every tool call and approval decision
from the database.

## License

MIT (see `LICENSE`). Forks and adaptations welcome; attribution appreciated.
