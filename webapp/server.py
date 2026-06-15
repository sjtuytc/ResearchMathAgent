"""FastAPI server for the Research Math Agent web app.

Serves a single-page UI with three views per question — the Question file, its
Issue, and a live Agent runner — and an SSE endpoint that streams the agent loop
step by step. The agent can run via the paid Messages API or via the local
``claude`` CLI (Pro/Max subscription, no API credits).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import Body, FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import threading
import uuid

from .agent import DEFAULT_MODEL, AgentConfig, run_agent
from .claude_code import claude_code_available, run_claude_code_agent
from .documents import list_documents, read_document
from .proofs import get_proof, list_experiments
from .issues import append_activity, get_issue, save_issue
from .latex import compile_tex, latex_available, pdf_dir, safe_pdf_name
from .runs import REGISTRY
from .tools import _extract_title, _problem_sort_key  # reuse internal helpers

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROBLEM_RE = re.compile(r"^q(?:10|[1-9])$")

app = FastAPI(title="Research Math Agent", version="0.2.0")


@app.get("/api/problems")
def list_problems() -> JSONResponse:
    problems_dir = REPO_ROOT / "problems"
    items = []
    if problems_dir.is_dir():
        for tex in sorted(problems_dir.glob("q*.tex"), key=_problem_sort_key):
            items.append({"id": tex.stem, "title": _extract_title(tex)})
    return JSONResponse({"problems": items, "claude_code": bool(claude_code_available())})


@app.get("/api/problem/{problem_id}")
def get_problem(problem_id: str) -> JSONResponse:
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    path = REPO_ROOT / "problems" / f"{problem_id}.tex"
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "id": problem_id,
        "title": _extract_title(path),
        "tex": path.read_text(encoding="utf-8", errors="replace"),
    })


@app.get("/api/issue/{problem_id}")
def read_issue(problem_id: str) -> JSONResponse:
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    return JSONResponse({"id": problem_id, "markdown": get_issue(REPO_ROOT, problem_id)})


@app.post("/api/issue/{problem_id}")
def write_issue(problem_id: str, payload: dict = Body(...)) -> JSONResponse:
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    save_issue(REPO_ROOT, problem_id, str(payload.get("markdown", "")))
    return JSONResponse({"ok": True})


@app.post("/api/issue/{problem_id}/activity")
def log_activity(problem_id: str, payload: dict = Body(...)) -> JSONResponse:
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    append_activity(REPO_ROOT, problem_id, str(payload.get("entry", "")))
    return JSONResponse({"ok": True})


@app.get("/api/solve")
def solve(
    problem: str = Query(..., description="Problem id, e.g. q6"),
    model: str = Query(""),
    provider: str = Query("claude-code", description="claude-code | api"),
    thinking: int = Query(1),
    run_id: str = Query(""),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(problem, model, provider, bool(thinking), run_id or uuid.uuid4().hex),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/cancel")
def cancel(payload: dict = Body(...)) -> JSONResponse:
    run_id = str(payload.get("run_id", ""))
    return JSONResponse({"ok": REGISTRY.cancel(run_id), "run_id": run_id})


@app.get("/api/runs")
def runs() -> JSONResponse:
    return JSONResponse({"runs": REGISTRY.active()})


@app.get("/api/documents")
def documents() -> JSONResponse:
    return JSONResponse({"documents": list_documents(REPO_ROOT)})


@app.get("/api/document/{name}")
def document(name: str) -> JSONResponse:
    content = read_document(REPO_ROOT, name)
    if content is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"name": name, "markdown": content})


@app.post("/api/compile")
def compile_pdf(payload: dict = Body(...)) -> JSONResponse:
    content = str(payload.get("content", ""))
    name = str(payload.get("name", "solution"))
    result = compile_tex(REPO_ROOT, content, name)
    if result["ok"]:
        result["pdf_url"] = f"/api/pdf/{result['pdf']}"
    return JSONResponse(result)


@app.get("/api/pdf/{name}")
def get_pdf(name: str):
    safe = safe_pdf_name(name)
    path = pdf_dir(REPO_ROOT) / safe
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=safe)


@app.get("/api/proofs")
def proofs_list() -> JSONResponse:
    return JSONResponse({"experiments": list_experiments()})


@app.get("/api/proof/{exp_name}/{problem_id}")
def proof_detail(exp_name: str, problem_id: str) -> JSONResponse:
    data = get_proof(exp_name, problem_id)
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(data)


@app.get("/api/capabilities")
def capabilities() -> JSONResponse:
    return JSONResponse({"claude_code": bool(claude_code_available()),
                         "latex": bool(latex_available())})


_FINAL_PROOFS_PATH = (
    Path(__file__).resolve().parents[2]
    / "ResearchMathAgent" / "data" / "first_proof_1" / "final_solutions" / "all_proofs_merged.tex"
)

def _split_final_proofs(tex: str) -> list[dict]:
    """Split all_proofs_merged.tex into per-problem sections."""
    import re
    chunks = re.split(r"% =====\s*Begin (q\d+)_solution\.tex\s*=====", tex)
    problems = []
    # chunks[0] is preamble, then alternating: problem_id, content
    for i in range(1, len(chunks), 2):
        pid = chunks[i]
        body = chunks[i + 1] if i + 1 < len(chunks) else ""
        # strip trailing end marker
        body = re.sub(r"\s*% =====\s*End.*?=====\s*$", "", body.rstrip())
        # extract title from \section*{Problem N}
        m = re.search(r"\\section\*\{([^}]+)\}", body)
        title = m.group(1) if m else pid
        problems.append({"id": pid, "title": title, "tex": body.strip()})
    return problems


@app.get("/api/final-proofs")
def final_proofs_list() -> JSONResponse:
    if not _FINAL_PROOFS_PATH.is_file():
        return JSONResponse({"problems": [], "error": "file not found"})
    tex = _FINAL_PROOFS_PATH.read_text(encoding="utf-8", errors="replace")
    problems = _split_final_proofs(tex)
    return JSONResponse({"problems": [{"id": p["id"], "title": p["title"]} for p in problems]})


@app.get("/api/final-proof/{problem_id}")
def final_proof_detail(problem_id: str) -> JSONResponse:
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    if not _FINAL_PROOFS_PATH.is_file():
        return JSONResponse({"error": "file not found"}, status_code=404)
    tex = _FINAL_PROOFS_PATH.read_text(encoding="utf-8", errors="replace")
    problems = {p["id"]: p for p in _split_final_proofs(tex)}
    if problem_id not in problems:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(problems[problem_id])


@app.post("/api/run-daily")
def run_daily() -> JSONResponse:
    """Trigger one daily-report run in the background (returns immediately)."""
    from .daily import run_daily_job

    active = [r for r in REGISTRY.active() if r.get("kind") == "daily"]
    if active:
        return JSONResponse({"started": False, "reason": "a daily run is already in progress"})
    threading.Thread(target=run_daily_job, daemon=True).start()
    return JSONResponse({"started": True})


def _sse(problem: str, model: str, provider: str, thinking: bool, run_id: str):
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
        model=model or (DEFAULT_MODEL if provider == "api" else ""),
        repo_root=REPO_ROOT,
        workspace=REPO_ROOT / "webapp" / ".runs" / f"{problem}_{int(time.time())}",
        thinking=thinking,
        provider=provider,
    )
    runner = run_claude_code_agent if provider == "claude-code" else run_agent
    handle = REGISTRY.register(run_id, {"problem": problem, "provider": provider, "model": cfg.model})

    yield send({"type": "start", "problem": problem, "model": cfg.model,
                "provider": provider, "run_id": run_id})
    try:
        for event in runner(cfg, handle):
            yield send(event.to_dict())
    except Exception as exc:  # noqa: BLE001 - keep the stream well-formed
        yield send({"type": "error", "message": f"Server error: {exc}"})
        yield send({"type": "done", "reason": "error"})
    finally:
        REGISTRY.unregister(run_id)


# Serve the SPA. Mounted last so /api/* routes take precedence.
if STATIC_DIR.is_dir():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.ico")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
