"""FastAPI server for the Research Math Agent web app.

Serves a single-page UI and a Server-Sent Events endpoint that streams the
agent loop step by step — the same shape TheAgentCompany/OpenHands uses to push
agent activity to a watcher, but pointed at the *First Proof* math benchmark.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import DEFAULT_MODEL, AgentConfig, run_agent
from .tools import _extract_title, _problem_sort_key  # reuse internal helpers

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROBLEM_RE = re.compile(r"^q(?:10|[1-9])$")

app = FastAPI(title="Research Math Agent", version="0.1.0")


@app.get("/api/problems")
def list_problems() -> JSONResponse:
    problems_dir = REPO_ROOT / "problems"
    items = []
    if problems_dir.is_dir():
        for tex in sorted(problems_dir.glob("q*.tex"), key=_problem_sort_key):
            items.append({"id": tex.stem, "title": _extract_title(tex)})
    return JSONResponse({"problems": items})


@app.get("/api/solve")
def solve(
    problem: str = Query(..., description="Problem id, e.g. q6"),
    model: str = Query(DEFAULT_MODEL),
    thinking: int = Query(1),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(problem, model, bool(thinking)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(problem: str, model: str, thinking: bool):
    def send(event: dict) -> str:
        return f"data: {json.dumps(event)}\n\n"

    if not _PROBLEM_RE.match(problem):
        yield send({"type": "error", "message": f"Invalid problem id '{problem}'."})
        yield send({"type": "done", "reason": "error"})
        return

    problem_path = REPO_ROOT / "problems" / f"{problem}.tex"
    if not problem_path.is_file():
        yield send({"type": "error", "message": f"Problem '{problem}' not found."})
        yield send({"type": "done", "reason": "error"})
        return

    cfg = AgentConfig(
        problem_id=problem,
        problem_text=problem_path.read_text(encoding="utf-8", errors="replace"),
        model=model,
        repo_root=REPO_ROOT,
        workspace=REPO_ROOT / "webapp" / ".runs" / f"{problem}_{int(time.time())}",
        thinking=thinking,
    )

    yield send({"type": "start", "problem": problem, "model": model})
    try:
        for event in run_agent(cfg):
            yield send(event.to_dict())
    except Exception as exc:  # noqa: BLE001 - keep the stream well-formed
        yield send({"type": "error", "message": f"Server error: {exc}"})
        yield send({"type": "done", "reason": "error"})


# Serve the SPA. Mounted last so /api/* routes take precedence.
if STATIC_DIR.is_dir():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
