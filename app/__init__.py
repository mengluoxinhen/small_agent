"""small_dify backend package.

Layout (filled in phase by phase, see docs/PLAN.md):
    app/config.py   settings + validation          (P1)
    app/model.py    Settings -> Agents-SDK Model   (P1)
    app/testing/    deterministic FakeModel        (P1)
    app/tools/      @function_tool registry        (P2)
    app/agent/      agent factory + approval policy (P3, P4)
    app/db/         SQLite repositories            (P5)
    app/api/        REST + SSE                     (P6)
"""
