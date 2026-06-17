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

from .agent import DEFAULT_MODEL, AgentConfig, run_agent, run_agent_vertex
from .claude_code import claude_code_available, run_claude_code_agent
from .documents import list_documents, read_document
from .dataset_store import (
    list_datasets, get_dataset_meta, list_problems as ds_list_problems,
    get_problem as ds_get_problem, compute_solvability_scores, get_solvability_scores,
    _validate_slug, _validate_id,
)
from .issue_agents import run_discovery_agent, run_resolver_agent, run_verifier_agent, get_working_proof, save_working_proof, run_discussion_agent, generate_issue_summary
from .proofs import get_proof, list_experiments, get_best_proof, list_best_proofs, consolidate_best, maybe_update_best, compile_best_pdf, _proof_outputs_root, _best_dir
from .issues import append_activity, list_issues, get_issue, create_issue, add_comment, update_issue, log_event, get_activity_log, link_issue, add_issue_document
from .meet import (
    create_room as meet_create, get_room as meet_get, list_rooms as meet_list,
    post_message as meet_post_message, set_plan as meet_set_plan,
    mark_step_done as meet_mark_step_done, PERSONAS as meet_personas,
)
from .meet_agents import run_discussion_turn, run_synthesis, run_step_execution
from . import github_issues as _gh
from .latex import compile_tex, compile_problem_pdf, latex_available, pdf_dir, safe_pdf_name
from .runs import REGISTRY
from .token_log import append_usage, read_log, daily_summary, per_problem_summary, today_summary
from .tools import _extract_title, _problem_sort_key  # reuse internal helpers
from .solvability_eval import load_eval, evaluate_all, ensure_all_evaluated
from .literature import load_index as lit_load, add_paper as lit_add, update_paper as lit_update, delete_paper as lit_delete, discover_literature, ensure_all_lit
from .concepts import load_concepts, save_concepts, generate_concepts, ensure_all_concepts
from .devlog import read_log as devlog_read, append_entry as devlog_append

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROBLEM_RE = re.compile(r"^q(?:10|[1-9])$")

_Q_TITLES = {
    "q1":  "Stochastic Analysis — Φ⁴₃ measure equivalence (Hairer)",
    "q2":  "Representation Theory — Whittaker functions & Rankin–Selberg (Nelson)",
    "q3":  "Algebraic Combinatorics — Macdonald stationary distribution (Williams)",
    "q4":  "Spectral Graph Theory — Subharmonicity of 1/Φₙ (Srivastava)",
    "q5":  "Algebraic Topology — Slice filtration for N∞ operads (Blumberg)",
    "q6":  "Spectral Graph Theory — ε-light subsets (Spielman)",
    "q7":  "Lattices in Lie Groups — Uniform lattices with 2-torsion (Weinberger)",
    "q8":  "Symplectic Geometry — Lagrangian smoothings (Abouzaid)",
    "q9":  "Tensor Analysis — Algebraic relations on determinantal tensors (Kileel)",
    "q10": "Numerical Linear Algebra — Preconditioned CG for RKHS-CP (Kolda, Ward)",
}
_Q_AREAS = {
    "q1": "Stochastic Analysis", "q2": "Representation Theory",
    "q3": "Algebraic Combinatorics", "q4": "Spectral Graph Theory",
    "q5": "Algebraic Topology", "q6": "Spectral Graph Theory",
    "q7": "Lattices in Lie Groups", "q8": "Symplectic Geometry",
    "q9": "Tensor Analysis", "q10": "Numerical Linear Algebra",
}
_Q_LABELS: dict[str, list[str]] = {
    "q1":  ["open problem", "stochastic PDE", "measure theory", "quantum field theory", "frontier"],
    "q2":  ["open problem", "automorphic forms", "L-functions", "representation theory", "frontier"],
    "q3":  ["open problem", "algebraic combinatorics", "Markov chains", "symmetric functions"],
    "q4":  ["open problem", "spectral graph theory", "free probability", "polynomial methods"],
    "q5":  ["open problem", "algebraic topology", "equivariant homotopy", "operads"],
    "q6":  ["open problem", "spectral graph theory", "graph theory", "linear algebra", "current focus"],
    "q7":  ["open problem", "geometric topology", "Lie groups", "lattices"],
    "q8":  ["open problem", "symplectic geometry", "Floer theory", "tropical geometry"],
    "q9":  ["open problem", "algebraic geometry", "tensor decomposition", "matrix theory"],
    "q10": ["open problem", "numerical linear algebra", "optimization", "algorithmic", "machine learning"],
}


def _question_summary(repo_root: Path, qid: str) -> dict:
    """Build per-question summary from strategy_memory.jsonl + best proof + Opus eval."""
    import re as _re
    # Load cached Opus solvability evaluation (set by background evaluator)
    opus_eval = load_eval(repo_root, qid)
    base: dict = {
        "qid": qid,
        "title": _Q_TITLES.get(qid, qid),
        "area": _Q_AREAS.get(qid, ""),
        "has_doc": False,
        "candidate_answer": None,
        "total_runs": 0,
        "success_runs": 0,
        "fail_runs": 0,
        "last_outcome": None,
        "last_run_date": None,
        "opus_eval": opus_eval,
        "labels": _Q_LABELS.get(qid, []),
    }
    # Primary source: strategy_memory.jsonl (authoritative run log)
    mem_path = repo_root / "documents" / "strategy_memory.jsonl"
    if mem_path.is_file():
        entries = []
        for line in mem_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if e.get("problem_id") == qid:
                entries.append(e)
        if entries:
            base["has_doc"] = True
            total = len(entries)
            success = sum(1 for e in entries if e.get("outcome") == "success")
            last = entries[-1]
            base.update(
                total_runs=total,
                success_runs=success,
                fail_runs=total - success,
                last_run_date=last.get("date"),
                last_outcome=last.get("outcome"),
            )
    # Secondary: best proof — if verified, that counts as at least one success
    try:
        best = get_best_proof(qid)
        if best and best.get("verification_passed"):
            base["has_doc"] = True
            if base["success_runs"] == 0:
                base["success_runs"] = 1
                base["total_runs"] = max(base["total_runs"], 1)
            base["last_outcome"] = "success"
        elif best and best.get("issue_count", 99) < 99:
            base["has_doc"] = True
    except Exception:  # noqa: BLE001
        pass
    # Candidate answer from overview.md (new hierarchy)
    overview = repo_root / "documents" / "questions" / qid / "overview.md"
    if overview.is_file():
        try:
            text = overview.read_text(encoding="utf-8", errors="replace")
            m = _re.search(r"##+ Candidate Answer\s*\n+(.+)", text)
            if m:
                base["candidate_answer"] = _re.sub(r"\*+", "", m.group(1)).strip()
            base["has_doc"] = True
        except Exception:  # noqa: BLE001
            pass
    return base


app = FastAPI(title="Research Math Agent", version="0.2.0")


def _precompile_problems():
    """Compile all problem PDFs in the background at startup so first click is fast."""
    import re as _re
    problems_dir = REPO_ROOT / "problems"
    if not problems_dir.is_dir():
        return
    for tex in sorted(problems_dir.glob("q*.tex")):
        pid = tex.stem
        if _re.match(r"^q(?:10|[1-9])$", pid):
            compile_problem_pdf(REPO_ROOT, pid)


threading.Thread(target=_precompile_problems, daemon=True).start()
threading.Thread(
    target=ensure_all_evaluated, args=(REPO_ROOT,), daemon=True
).start()
threading.Thread(
    target=ensure_all_lit, args=(REPO_ROOT, _Q_TITLES), daemon=True
).start()
threading.Thread(
    target=ensure_all_concepts, args=(REPO_ROOT, _Q_TITLES), daemon=True
).start()
from .issue_loop import run_issue_loop, evolve_once as _evolve_issues_once
threading.Thread(target=run_issue_loop, args=(REPO_ROOT,), daemon=True).start()


@app.get("/api/problems")
def list_problems() -> JSONResponse:
    problems_dir = REPO_ROOT / "problems"
    items = []
    if problems_dir.is_dir():
        for tex in sorted(problems_dir.glob("q*.tex"), key=_problem_sort_key):
            items.append({"id": tex.stem, "title": _extract_title(tex)})
    return JSONResponse({"problems": items, "claude_code": bool(claude_code_available())})


# ── Multi-dataset API ────────────────────────────────────────────────────────

@app.get("/api/datasets")
def api_list_datasets() -> JSONResponse:
    return JSONResponse({"datasets": list_datasets()})


@app.get("/api/datasets/{slug}")
def api_dataset_meta(slug: str) -> JSONResponse:
    try:
        _validate_slug(slug)
    except ValueError:
        return JSONResponse({"error": "invalid slug"}, status_code=400)
    meta = get_dataset_meta(slug)
    if meta is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(meta)


@app.get("/api/ds/problems")
def api_ds_problems(
    dataset: str = Query(None),
    sort: str = Query("id"),
    tags: str = Query(None),          # comma-separated
    min_difficulty: float = Query(None),
    max_difficulty: float = Query(None),
    min_solvability: float = Query(None),
    max_solvability: float = Query(None),
    search: str = Query(None),
) -> JSONResponse:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    if dataset:
        try:
            _validate_slug(dataset)
        except ValueError:
            return JSONResponse({"error": "invalid dataset slug"}, status_code=400)
    problems = ds_list_problems(
        dataset=dataset, sort=sort, tags=tag_list,
        min_difficulty=min_difficulty, max_difficulty=max_difficulty,
        min_solvability=min_solvability, max_solvability=max_solvability,
        search=search,
    )
    return JSONResponse({"problems": problems, "claude_code": bool(claude_code_available())})


@app.get("/api/ds/problem/{dataset}/{problem_id}")
def api_ds_problem(dataset: str, problem_id: str) -> JSONResponse:
    try:
        _validate_slug(dataset)
        _validate_id(problem_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    p = ds_get_problem(dataset, problem_id)
    if p is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(p)


@app.post("/api/ds/solvability/{dataset}/refresh")
def api_refresh_solvability(dataset: str) -> JSONResponse:
    try:
        _validate_slug(dataset)
    except ValueError:
        return JSONResponse({"error": "invalid slug"}, status_code=400)
    scores = compute_solvability_scores(dataset)
    return JSONResponse({"dataset": dataset, "scores": scores})


@app.get("/api/ds/solvability")
def api_solvability(dataset: str = Query(None)) -> JSONResponse:
    return JSONResponse({"solvability": get_solvability_scores(dataset)})


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


_ID_RE_LOOSE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


def _ds_from_query(dataset: str | None) -> str:
    return dataset if dataset and re.match(r"^[A-Za-z0-9_-]{1,80}$", dataset) else "first_proof_1"


@app.get("/api/issues/{problem_id}")
def list_issues_ep(problem_id: str, dataset: str = Query(None)) -> JSONResponse:
    ds = _ds_from_query(dataset)
    pid = problem_id
    if ds == "first_proof_1" and not _PROBLEM_RE.match(pid):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    elif not _ID_RE_LOOSE.match(pid):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    return JSONResponse({"issues": list_issues(REPO_ROOT, pid, ds)})


@app.post("/api/issues/{problem_id}")
def create_issue_ep(problem_id: str, payload: dict = Body(...), dataset: str = Query(None)) -> JSONResponse:
    ds = _ds_from_query(dataset)
    pid = problem_id
    if ds == "first_proof_1" and not _PROBLEM_RE.match(pid):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    issue = create_issue(
        REPO_ROOT, pid,
        title=str(payload.get("title", "Untitled")),
        body=str(payload.get("body", "")),
        author=str(payload.get("author", "human")),
        labels=payload.get("labels", []),
        dataset=ds,
    )
    return JSONResponse(issue)


@app.get("/api/issues/{problem_id}/{issue_id}")
def get_issue_ep(problem_id: str, issue_id: str, dataset: str = Query(None)) -> JSONResponse:
    ds = _ds_from_query(dataset)
    issue = get_issue(REPO_ROOT, problem_id, issue_id, ds)
    if issue is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(issue)


@app.post("/api/issues/{problem_id}/{issue_id}/comment")
def add_comment_ep(problem_id: str, issue_id: str, payload: dict = Body(...), dataset: str = Query(None)) -> JSONResponse:
    ds = _ds_from_query(dataset)
    issue = add_comment(
        REPO_ROOT, problem_id, issue_id,
        author=str(payload.get("author", "human")),
        body=str(payload.get("body", "")),
        dataset=ds,
    )
    if issue is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(issue)


@app.patch("/api/issues/{problem_id}/{issue_id}")
def update_issue_ep(problem_id: str, issue_id: str, payload: dict = Body(...), dataset: str = Query(None)) -> JSONResponse:
    ds = _ds_from_query(dataset)
    issue = update_issue(REPO_ROOT, problem_id, issue_id, ds, **payload)
    if issue is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(issue)


@app.post("/api/issues/{problem_id}/activity")
def log_activity(problem_id: str, payload: dict = Body(...), dataset: str = Query(None)) -> JSONResponse:
    ds = _ds_from_query(dataset)
    append_activity(REPO_ROOT, problem_id, str(payload.get("entry", "")),
                    agent=str(payload.get("agent", "solver-agent")), dataset=ds)
    return JSONResponse({"ok": True})


@app.post("/api/issues/{problem_id}/{issue_id}/note")
def add_note_ep(problem_id: str, issue_id: str, payload: dict = Body(...), dataset: str = Query(None)) -> JSONResponse:
    ds = _ds_from_query(dataset)
    issue = add_comment(
        REPO_ROOT, problem_id, issue_id,
        author=str(payload.get("author", "human")),
        body=str(payload.get("body", "")),
        dataset=ds,
        role="note",
    )
    if issue is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(issue)


@app.post("/api/issues/{problem_id}/{issue_id}/link")
def link_issue_ep(problem_id: str, issue_id: str, payload: dict = Body(...), dataset: str = Query(None)) -> JSONResponse:
    ds = _ds_from_query(dataset)
    issue = link_issue(
        REPO_ROOT, problem_id, issue_id,
        target_id=str(payload.get("target_id", "")),
        target_dataset=payload.get("target_dataset"),
        relation=str(payload.get("relation", "related")),
        added_by=str(payload.get("added_by", "human")),
        dataset=ds,
    )
    if issue is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(issue)


@app.get("/api/issues/{problem_id}/{issue_id}/discuss")
def discuss_issue_ep(
    problem_id: str,
    issue_id: str,
    dataset: str = Query(None),
    n_turns: int = Query(3),
    run_id: str = Query(""),
) -> StreamingResponse:
    ds = _ds_from_query(dataset)
    rid = run_id or uuid.uuid4().hex
    handle = REGISTRY.register(rid, {"kind": "discuss", "problem": problem_id, "issue": issue_id})

    def _gen():
        for ev in run_discussion_agent(REPO_ROOT, problem_id, issue_id, ds, n_turns=n_turns, handle=handle):
            yield f"data: {json.dumps({'type': ev.type, 'data': ev.data})}\n\n"
        REGISTRY.unregister(rid)

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/issues/{problem_id}/{issue_id}/generate-doc")
def generate_doc_ep(
    problem_id: str,
    issue_id: str,
    dataset: str = Query(None),
) -> JSONResponse:
    ds = _ds_from_query(dataset)
    result = generate_issue_summary(REPO_ROOT, problem_id, issue_id, ds)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return JSONResponse(result)


@app.post("/api/meets/{problem_id}/from-issue/{issue_id}")
def create_meet_from_issue(
    problem_id: str,
    issue_id: str,
    payload: dict = Body(default={}),
    dataset: str = Query(None),
) -> JSONResponse:
    """Create a meeting room seeded with the issue context, and link them."""
    ds = _ds_from_query(dataset)
    issue = get_issue(REPO_ROOT, problem_id, issue_id, ds)
    if issue is None:
        return JSONResponse({"error": "issue not found"}, status_code=404)
    topic = str(payload.get("topic", f"Discuss: {issue.get('title', issue_id)[:60]}"))
    goal = str(payload.get("goal", "Agree on a concrete resolution strategy."))
    room = meet_create(REPO_ROOT, problem_id, topic=topic, goal=goal)
    # Embed issue reference in room and link back
    room["issue_id"] = issue_id
    room["issue_dataset"] = ds
    import json as _json
    (REPO_ROOT / "webapp" / "meets" / problem_id / f"{room['id']}.json").write_text(
        _json.dumps(room, indent=2), encoding="utf-8"
    )
    # Record the meeting link on the issue
    issue = add_issue_document(
        REPO_ROOT, problem_id, issue_id,
        title=f"Meeting: {topic[:50]}",
        path=f"__meet__{problem_id}/{room['id']}",
        created_by="system",
        dataset=ds,
    )
    return JSONResponse({"room": room, "issue": issue})


@app.post("/api/meets/{problem_id}/{room_id}/save-to-issue")
def meet_save_to_issue(
    problem_id: str,
    room_id: str,
    payload: dict = Body(default={}),
    dataset: str = Query(None),
) -> JSONResponse:
    """Save meeting synthesis/transcript as a document linked to an issue."""
    ds = _ds_from_query(dataset)
    room = meet_get(REPO_ROOT, problem_id, room_id)
    if room is None:
        return JSONResponse({"error": "room not found"}, status_code=404)
    issue_id = str(payload.get("issue_id", room.get("issue_id", "")))
    if not issue_id:
        return JSONResponse({"error": "no issue_id"}, status_code=400)

    # Build a markdown document from the room transcript + plan
    from .meet import transcript_text
    lines = [
        f"# Meeting Notes: {room.get('topic', room_id)}",
        f"**Goal:** {room.get('goal', '')}",
        "",
        "## Discussion Transcript",
        transcript_text(room),
    ]
    plan = room.get("plan")
    if plan:
        lines += ["", "## Action Plan", plan.get("summary", "")]
        for i, step in enumerate(plan.get("steps", []), 1):
            done = "✅" if step.get("done") else "⬜"
            lines.append(f"{i}. {done} {step.get('description', '')}")

    doc_text = "\n".join(lines)
    doc_dir = REPO_ROOT / "documents" / "questions" / problem_id / "meets"
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_path = doc_dir / f"{room_id}-notes.md"
    doc_path.write_text(doc_text, encoding="utf-8")

    rel_path = f"questions/{problem_id}/meets/{room_id}-notes.md"
    title = f"Meeting Notes — {room.get('topic', room_id)[:50]}"
    updated_issue = add_issue_document(
        REPO_ROOT, problem_id, issue_id, title, rel_path, created_by="system", dataset=ds
    )
    return JSONResponse({"ok": True, "path": rel_path, "issue": updated_issue})


# legacy single-issue endpoints kept for backward compatibility
@app.post("/api/issue/{problem_id}/activity")
def log_activity_legacy(problem_id: str, payload: dict = Body(...)) -> JSONResponse:
    return log_activity(problem_id, payload)


@app.get("/api/activity/{problem_id}")
def unified_activity(problem_id: str, dataset: str = Query(None), limit: int = Query(200)) -> JSONResponse:
    """Unified chronological activity log: issue comments/events + strategy_memory runs."""
    ds = _ds_from_query(dataset)
    entries: list[dict] = []

    # Issue events and comments
    for entry in get_activity_log(REPO_ROOT, problem_id, ds, limit=limit):
        entries.append({
            "source": "issue",
            "ts": entry.get("created_at", ""),
            "author": entry.get("author", ""),
            "role": entry.get("role", "human"),
            "event_type": entry.get("event_type", ""),
            "body": entry.get("body", ""),
            "issue_id": entry.get("issue_id", ""),
            "issue_title": entry.get("issue_title", ""),
        })

    # Strategy memory runs
    mem = REPO_ROOT / "documents" / "strategy_memory.jsonl"
    if mem.is_file():
        for line in mem.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("problem_id") != problem_id:
                continue
            icon = "✅" if e.get("outcome") == "success" else "❌"
            issues_n = e.get("issue_count", "?")
            model = e.get("model", "skeleton")
            strategy_short = (e.get("strategy", "")[:120] + "…") if len(e.get("strategy", "")) > 120 else e.get("strategy", "")
            entries.append({
                "source": "solver",
                "ts": e.get("date", ""),
                "author": model,
                "role": "solver",
                "event_type": "solver_run",
                "body": f"{icon} **{model}** — {e.get('outcome','?')} — {issues_n} verifier issues\n\n{strategy_short}",
                "issue_id": "",
                "issue_title": "",
                "outcome": e.get("outcome"),
                "issue_count": e.get("issue_count"),
            })

    entries.sort(key=lambda e: e.get("ts", ""))
    return JSONResponse({"entries": entries[-limit:]})


@app.post("/api/activity/{problem_id}/event")
def post_event(problem_id: str, payload: dict = Body(...), dataset: str = Query(None)) -> JSONResponse:
    """Post a structured event to the activity log (writes into the relevant issue)."""
    ds = _ds_from_query(dataset)
    log_event(
        REPO_ROOT, problem_id,
        event_type=str(payload.get("event_type", "note")),
        description=str(payload.get("description", "")),
        author=str(payload.get("author", "system")),
        dataset=ds,
        issue_id=payload.get("issue_id"),
    )
    return JSONResponse({"ok": True})


# ── Virtual Meet endpoints ────────────────────────────────────────────────────

@app.get("/api/meets/{problem_id}")
def list_meets(problem_id: str) -> JSONResponse:
    return JSONResponse({"rooms": meet_list(REPO_ROOT, problem_id)})


@app.post("/api/meets/{problem_id}")
def create_meet(problem_id: str, payload: dict = Body(...)) -> JSONResponse:
    room = meet_create(
        REPO_ROOT, problem_id,
        topic=str(payload.get("topic", "Proof strategy discussion")),
        goal=str(payload.get("goal", "")),
        participants=payload.get("participants") or None,
    )
    return JSONResponse(room)


@app.get("/api/meets/{problem_id}/{room_id}")
def get_meet(problem_id: str, room_id: str) -> JSONResponse:
    room = meet_get(REPO_ROOT, problem_id, room_id)
    if room is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(room)


@app.post("/api/meets/{problem_id}/{room_id}/message")
def post_meet_message(problem_id: str, room_id: str, payload: dict = Body(...)) -> JSONResponse:
    room = meet_post_message(
        REPO_ROOT, problem_id, room_id,
        author=str(payload.get("author", "human")),
        body=str(payload.get("body", "")),
        role=payload.get("role"),
    )
    if room is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(room)


@app.post("/api/meets/{problem_id}/{room_id}/plan")
def post_meet_plan(problem_id: str, room_id: str, payload: dict = Body(...)) -> JSONResponse:
    steps = payload.get("steps", [])
    summary = str(payload.get("summary", ""))
    room = meet_set_plan(REPO_ROOT, problem_id, room_id, steps=steps, summary=summary)
    if room is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(room)


@app.post("/api/meets/{problem_id}/{room_id}/steps/{step_idx}/done")
def meet_step_done(problem_id: str, room_id: str, step_idx: int, payload: dict = Body(...)) -> JSONResponse:
    room = meet_mark_step_done(
        REPO_ROOT, problem_id, room_id, step_idx,
        outcome=str(payload.get("outcome", "success")),
        notes=str(payload.get("notes", "")),
    )
    if room is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(room)


@app.get("/api/meets/{problem_id}/{room_id}/turn/{participant}")
def meet_agent_turn(problem_id: str, room_id: str, participant: str, run_id: str = Query("")) -> StreamingResponse:
    rid = run_id or uuid.uuid4().hex
    handle = REGISTRY.register(rid, f"meet-turn/{room_id}/{participant}")

    def _stream():
        yield f"data: {json.dumps({'type': 'status', 'data': {'state': 'running', 'label': f'meet/{room_id}/{participant}'}})}\n\n"
        for ev in run_discussion_turn(REPO_ROOT, problem_id, room_id, participant, handle):
            yield f"data: {json.dumps({'type': ev.type, 'data': ev.data})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.get("/api/meets/{problem_id}/{room_id}/synthesize")
def meet_synthesize(problem_id: str, room_id: str, run_id: str = Query("")) -> StreamingResponse:
    rid = run_id or uuid.uuid4().hex
    handle = REGISTRY.register(rid, f"meet-synth/{room_id}")

    def _stream():
        yield f"data: {json.dumps({'type': 'status', 'data': {'state': 'running', 'label': f'synthesize/{room_id}'}})}\n\n"
        for ev in run_synthesis(REPO_ROOT, problem_id, room_id, handle):
            yield f"data: {json.dumps({'type': ev.type, 'data': ev.data})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.get("/api/meets/{problem_id}/{room_id}/execute/{step_idx}")
def meet_execute_step(problem_id: str, room_id: str, step_idx: int, run_id: str = Query("")) -> StreamingResponse:
    rid = run_id or uuid.uuid4().hex
    handle = REGISTRY.register(rid, f"meet-exec/{room_id}/{step_idx}")

    def _stream():
        yield f"data: {json.dumps({'type': 'status', 'data': {'state': 'running', 'label': f'execute/{room_id}/step{step_idx}'}})}\n\n"
        for ev in run_step_execution(REPO_ROOT, problem_id, room_id, step_idx, handle):
            yield f"data: {json.dumps({'type': ev.type, 'data': ev.data})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.get("/api/meets/personas")
def get_personas() -> JSONResponse:
    return JSONResponse(meet_personas)


@app.get("/api/solve")
def solve(
    problem: str = Query(..., description="Problem id, e.g. q6"),
    model: str = Query(""),
    provider: str = Query("claude-code", description="claude-code | api | vertex"),
    thinking: int = Query(1),
    run_id: str = Query(""),
    gcp_project: str = Query("", description="GCP project ID for Vertex AI provider"),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(problem, model, provider, bool(thinking), run_id or uuid.uuid4().hex, gcp_project=gcp_project),
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


@app.get("/api/document/{name:path}")
def document(name: str) -> JSONResponse:
    content = read_document(REPO_ROOT, name)
    if content is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"name": name, "markdown": content})


@app.get("/api/problem-pdf/{problem_id}")
def problem_pdf(problem_id: str) -> JSONResponse:
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    result = compile_problem_pdf(REPO_ROOT, problem_id)
    return JSONResponse(result)


@app.get("/api/ds/problem-pdf/{dataset}/{problem_id}")
def ds_problem_pdf(dataset: str, problem_id: str) -> JSONResponse:
    try:
        _validate_slug(dataset)
        _validate_id(problem_id)
    except ValueError:
        return JSONResponse({"error": "invalid"}, status_code=400)
    p = ds_get_problem(dataset, problem_id)
    if p is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    tex = p.get("tex") or p.get("statement", "")
    if not tex:
        return JSONResponse({"ok": False, "pdf_url": None, "log": "no tex source"})
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", f"{dataset}_{problem_id}")
    result = compile_tex(REPO_ROOT, tex, safe_name)
    if result["ok"]:
        result["pdf_url"] = f"/api/pdf/{result['pdf']}"
    return JSONResponse(result)


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


@app.get("/api/proof-pdf/{exp_name}/{problem_id}")
def proof_pdf(exp_name: str, problem_id: str) -> JSONResponse:
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    data = get_proof(exp_name, problem_id)
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    safe_exp = re.sub(r"[^A-Za-z0-9_-]", "_", exp_name)
    name = f"proof_{safe_exp}_{problem_id}"
    cached = pdf_dir(REPO_ROOT) / (name + ".pdf")

    # Check for a pre-compiled PDF sitting next to the .tex in the experiment folder
    prebuilt = _proof_outputs_root() / exp_name / f"{problem_id}_solution.pdf"
    if prebuilt.is_file():
        import shutil as _shutil
        _shutil.copyfile(prebuilt, cached)
        return JSONResponse({"ok": True, "pdf_url": f"/api/pdf/{name}.pdf", "log": "pre-compiled"})

    tex = data.get("solution_tex", "")
    if not tex:
        return JSONResponse({"ok": False, "pdf_url": None, "log": "no solution tex"})
    result = compile_tex(REPO_ROOT, tex, name)
    if result["ok"]:
        result["pdf_url"] = f"/api/pdf/{result['pdf']}"
    return JSONResponse(result)


@app.get("/api/proofs")
def proofs_list() -> JSONResponse:
    return JSONResponse({"experiments": list_experiments()})


@app.get("/api/proof/{exp_name}/{problem_id}")
def proof_detail(exp_name: str, problem_id: str) -> JSONResponse:
    data = get_proof(exp_name, problem_id)
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(data)


@app.get("/api/best-proofs")
def best_proofs_list() -> JSONResponse:
    dataset = "first_proof_1"
    proofs = list_best_proofs(dataset)
    return JSONResponse({"proofs": proofs, "dataset": dataset})


@app.get("/api/best-proof/{problem_id}")
def best_proof_detail(problem_id: str) -> JSONResponse:
    data = get_best_proof(problem_id)
    if data is None:
        return JSONResponse({"error": "no best proof found — run consolidate or rma solve first"}, status_code=404)
    return JSONResponse(data)


@app.post("/api/consolidate-best")
def consolidate_best_ep() -> JSONResponse:
    result = consolidate_best("first_proof_1", compile_pdfs=True)
    return JSONResponse({"updated": len(result), "problems": list(result.keys())})


@app.get("/api/best-proof-pdf/{problem_id}")
def best_proof_pdf(problem_id: str):
    """Serve the pre-compiled PDF for the best proof, compiling it on demand if needed."""
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    pdf_path = _best_dir("first_proof_1") / problem_id / "solution.pdf"
    if not pdf_path.is_file():
        # Compile on demand and store
        ok = compile_best_pdf(problem_id, "first_proof_1")
        if not ok or not pdf_path.is_file():
            return JSONResponse({"error": "PDF not available — run Consolidate first"}, status_code=404)
    return FileResponse(pdf_path, media_type="application/pdf",
                        filename=f"{problem_id}_best_proof.pdf")


_FINAL_SOLUTIONS_DIR = (
    Path(__file__).resolve().parents[2]
    / "ResearchMathAgent" / "data" / "first_proof_1" / "final_solutions"
)
_AUTHOR_SOLUTIONS_DIR = _FINAL_SOLUTIONS_DIR / "first_proof_author_solutions"
_ALLOWED_EXTS = {".pdf", ".tex"}


@app.get("/api/final-proof-files")
def final_proof_files() -> JSONResponse:
    files = []
    if _FINAL_SOLUTIONS_DIR.is_dir():
        for f in sorted(_FINAL_SOLUTIONS_DIR.iterdir()):
            if f.is_file() and f.suffix in _ALLOWED_EXTS:
                files.append({"name": f.name, "path": f.name, "group": "merged"})
    if _AUTHOR_SOLUTIONS_DIR.is_dir():
        for f in sorted(_AUTHOR_SOLUTIONS_DIR.iterdir()):
            if f.is_file() and f.suffix in _ALLOWED_EXTS:
                files.append({"name": f.name, "path": f"first_proof_author_solutions/{f.name}", "group": "author"})
    return JSONResponse({"files": files})


@app.get("/api/final-proof-file/{file_path:path}")
def final_proof_file(file_path: str) -> FileResponse:
    # Sanitize: only allow files inside the final_solutions dir
    safe = (_FINAL_SOLUTIONS_DIR / file_path).resolve()
    if not str(safe).startswith(str(_FINAL_SOLUTIONS_DIR.resolve())):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if not safe.is_file() or safe.suffix not in _ALLOWED_EXTS:
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "application/pdf" if safe.suffix == ".pdf" else "text/plain"
    return FileResponse(safe, media_type=media, filename=safe.name)


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


@app.get("/api/working-proof/{problem_id}")
def get_working_proof_ep(problem_id: str) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    tex = get_working_proof(REPO_ROOT, problem_id)
    return JSONResponse({"problem_id": problem_id, "tex": tex, "has_proof": bool(tex)})


@app.post("/api/working-proof/{problem_id}")
def save_working_proof_ep(problem_id: str, payload: dict = Body(...)) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    tex = str(payload.get("tex", ""))
    save_working_proof(REPO_ROOT, problem_id, tex)
    return JSONResponse({"ok": True})


@app.get("/api/agent/discover/{problem_id}")
def agent_discover(problem_id: str, run_id: str = Query(""), dataset: str = Query(None)) -> StreamingResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    ds = _ds_from_query(dataset)
    rid = run_id or uuid.uuid4().hex
    return StreamingResponse(
        _sse_issue_agent(run_discovery_agent, REPO_ROOT, problem_id, rid, dataset=ds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/agent/resolve/{problem_id}/{issue_id}")
def agent_resolve(problem_id: str, issue_id: str, run_id: str = Query(""), dataset: str = Query(None)) -> StreamingResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    ds = _ds_from_query(dataset)
    rid = run_id or uuid.uuid4().hex
    return StreamingResponse(
        _sse_issue_agent(run_resolver_agent, REPO_ROOT, problem_id, rid, issue_id=issue_id, dataset=ds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/agent/verify/{problem_id}/{issue_id}")
def agent_verify(problem_id: str, issue_id: str, run_id: str = Query(""), dataset: str = Query(None)) -> StreamingResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    ds = _ds_from_query(dataset)
    rid = run_id or uuid.uuid4().hex
    return StreamingResponse(
        _sse_issue_agent(run_verifier_agent, REPO_ROOT, problem_id, rid, issue_id=issue_id, dataset=ds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse_issue_agent(runner_fn, repo_root, problem_id, run_id, issue_id=None, dataset="first_proof_1"):
    def send(event: dict) -> str:
        return f"data: {json.dumps(event)}\n\n"

    fn_name = getattr(runner_fn, "__name__", "")
    kind = "discover" if "discovery" in fn_name else "resolve" if "resolver" in fn_name else "verify"
    handle = REGISTRY.register(run_id, {
        "problem": problem_id,
        "issue": issue_id or "",
        "kind": "issue-agent",
    })
    yield send({"type": "start", "problem": problem_id, "issue": issue_id, "run_id": run_id})
    try:
        if issue_id:
            gen = runner_fn(repo_root, problem_id, issue_id, handle, dataset=dataset)
        else:
            gen = runner_fn(repo_root, problem_id, handle, dataset=dataset)
        for event in gen:
            if event.type == "usage":
                try:
                    d = event.data or {}
                    append_usage(repo_root, problem_id, kind,
                                 d.get("input_tokens", 0), d.get("output_tokens", 0),
                                 d.get("cost_usd"))
                except Exception:  # noqa: BLE001
                    pass
            yield send(event.to_dict())
    except Exception as exc:  # noqa: BLE001
        yield send({"type": "error", "message": f"Server error: {exc}"})
        yield send({"type": "done", "reason": "error"})
    finally:
        REGISTRY.unregister(run_id)


@app.get("/api/overview")
def overview_ep() -> JSONResponse:
    import subprocess as _sp
    from datetime import datetime, timedelta
    now = datetime.now()
    nxt = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    seconds_until = int((nxt - now).total_seconds())

    daemon_pid = None
    try:
        r = _sp.run(["pgrep", "-f", "webapp.daily"], capture_output=True, text=True)
        pids = [p.strip() for p in r.stdout.splitlines() if p.strip()]
        daemon_pid = int(pids[0]) if pids else None
    except Exception:  # noqa: BLE001
        pass

    issue_stats: dict[str, dict] = {}
    for i in range(1, 11):
        pid = f"q{i}"
        try:
            issues = list_issues(REPO_ROOT, pid)
        except Exception:  # noqa: BLE001
            issues = []
        issue_stats[pid] = {
            "open": sum(1 for x in issues if x.get("status") == "open"),
            "in_progress": sum(1 for x in issues if x.get("status") == "in_progress"),
            "resolved": sum(1 for x in issues if x.get("status") == "resolved"),
            "total": len(issues),
        }

    recent: list[dict] = []
    for i in range(1, 11):
        pid = f"q{i}"
        try:
            for iss in list_issues(REPO_ROOT, pid):
                for c in iss.get("comments", []):
                    recent.append({
                        "problem": pid,
                        "issue_id": iss.get("id", ""),
                        "issue_title": (iss.get("title") or "")[:60],
                        "author": c.get("author", ""),
                        "body": (c.get("body") or "")[:200],
                        "ts": c.get("created_at", ""),
                    })
        except Exception:  # noqa: BLE001
            pass
    recent.sort(key=lambda x: x["ts"], reverse=True)
    recent = recent[:30]

    log_entries = read_log(REPO_ROOT, days=14)
    daily = daily_summary(log_entries)
    by_prob = per_problem_summary(log_entries)
    total_in = sum(e.get("in", 0) for e in log_entries)
    total_out = sum(e.get("out", 0) for e in log_entries)
    total_cost = sum(e.get("cost") or 0.0 for e in log_entries)

    # Simple improvement suggestions based on issue stats
    suggestions: list[str] = []
    most_open = sorted(issue_stats.items(), key=lambda x: x[1]["open"], reverse=True)
    if most_open and most_open[0][1]["open"] > 0:
        pid, s = most_open[0]
        suggestions.append(f"{pid} has {s['open']} open issue(s) — run Auto-Resolve to tackle them.")
    unresolved = [(p, s) for p, s in issue_stats.items() if s["total"] > 0 and s["resolved"] == 0]
    if unresolved:
        pids = ", ".join(p for p, _ in unresolved[:3])
        suggestions.append(f"{pids}: issues exist but none resolved — verifier may need more passes.")
    zero_issues = [p for p, s in issue_stats.items() if s["total"] == 0]
    if zero_issues:
        suggestions.append(f"{', '.join(zero_issues[:5])}: no issues discovered yet — run Discover on these problems.")
    if by_prob:
        top = by_prob[0]
        suggestions.append(f"{top['problem']} consumed the most tokens ({(top['in']+top['out']):,}) — consider shorter prompts or fewer resolve cycles.")

    # Per-question summaries: merge doc info + issue stats
    question_summaries: list[dict] = []
    for i in range(1, 11):
        pid = f"q{i}"
        qs = _question_summary(REPO_ROOT, pid)
        ist = issue_stats.get(pid, {"open": 0, "in_progress": 0, "resolved": 0, "total": 0})
        total_iss = ist["total"]
        resolved = ist["resolved"]
        # Proof status: best proof verification takes priority over issue counts
        try:
            best = get_best_proof(pid)
            best_verified = bool(best and best.get("verification_passed"))
            best_issues = int(best.get("issue_count", 99)) if best else 99
        except Exception:  # noqa: BLE001
            best_verified, best_issues = False, 99
        if best_verified:
            proof_status = "verified"
        elif total_iss == 0 and not qs["has_doc"]:
            proof_status = "not_started"
        elif resolved == total_iss and total_iss > 0:
            proof_status = "verified"
        elif resolved > 0:
            proof_status = "in_progress"
        elif ist["in_progress"] > 0:
            proof_status = "exploring"
        elif qs["has_doc"]:
            proof_status = "open_issues"
        else:
            proof_status = "not_started"
        # Accuracy = issue resolution rate
        accuracy_pct = round(resolved / total_iss * 100) if total_iss > 0 else None
        # Solvability: hierarchy of evidence (best first)
        # 1. Verified proof → 100%
        # 2. Partial proof progress → heuristic from issue count
        # 3. Opus evaluation (authoritative AI solvability score)
        # 4. Run history success rate
        # 5. Issue resolution rate as proxy
        total_runs = qs["total_runs"]
        success_runs = qs["success_runs"]
        opus_eval = qs.get("opus_eval")
        if best_verified:
            solvability_pct = 100
        elif best_issues < 99:
            solvability_pct = max(0, round((1 - best_issues / 18) * 100))
        elif opus_eval and "score" in opus_eval:
            solvability_pct = int(opus_eval["score"])
        elif total_runs > 0:
            solvability_pct = round(success_runs / total_runs * 100)
        elif total_iss > 0:
            solvability_pct = accuracy_pct
        else:
            solvability_pct = None
        question_summaries.append({
            **qs,
            "issue_stats": ist,
            "proof_status": proof_status,
            "accuracy_pct": accuracy_pct,
            "solvability_pct": solvability_pct,
        })

    return JSONResponse({
        "daemon_running": daemon_pid is not None,
        "daemon_pid": daemon_pid,
        "next_run_iso": nxt.strftime("%Y-%m-%dT%H:%M:%S"),
        "seconds_until_next": seconds_until,
        "active_runs": REGISTRY.active(),
        "issue_stats": issue_stats,
        "recent_activity": recent,
        "token_daily": daily,
        "token_by_problem": by_prob,
        "token_total": {
            "in": total_in, "out": total_out,
            "cost": round(total_cost, 6), "runs": len(log_entries),
        },
        "suggestions": suggestions,
        "today": today_summary(REPO_ROOT),
        "question_summaries": question_summaries,
    })


@app.post("/api/run-daily")
def run_daily() -> JSONResponse:
    """Trigger one daily-report run in the background (returns immediately)."""
    from .daily import run_daily_job

    active = [r for r in REGISTRY.active() if r.get("kind") == "daily"]
    if active:
        return JSONResponse({"started": False, "reason": "a daily run is already in progress"})
    threading.Thread(target=run_daily_job, daemon=True).start()
    return JSONResponse({"started": True})


@app.post("/api/evolve-issues")
def api_evolve_issues() -> JSONResponse:
    """Trigger a one-shot issue-evolution pass: discover + resolve for all open issues."""
    active = [r for r in REGISTRY.active() if r.get("kind") == "issue-loop"]
    if active:
        return JSONResponse({"started": False, "reason": "issue evolution already running"})
    def _run():
        handle = REGISTRY.register(f"issue-loop-{int(__import__('time').time())}",
                                   {"kind": "issue-loop"})
        try:
            _evolve_issues_once(REPO_ROOT)
        finally:
            REGISTRY.unregister(handle.run_id)
    threading.Thread(target=_run, daemon=True).start()
    return JSONResponse({"started": True})


@app.post("/api/eval/solvability/refresh")
def refresh_solvability_eval(force: bool = Query(False)) -> JSONResponse:
    """Re-evaluate AI solvability for all q1-q10 using Claude Opus (background)."""
    from .solvability_eval import evaluate_all as _eval_all
    def _run():
        _eval_all(REPO_ROOT, force=force)
    threading.Thread(target=_run, daemon=True).start()
    return JSONResponse({"started": True, "force": force,
                         "message": "Opus solvability evaluation running in background; check /api/overview in ~3 minutes."})


def _sse(problem: str, model: str, provider: str, thinking: bool, run_id: str, gcp_project: str = ""):
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
        model=model or (DEFAULT_MODEL if provider in ("api", "vertex") else ""),
        repo_root=REPO_ROOT,
        workspace=REPO_ROOT / "webapp" / ".runs" / f"{problem}_{int(time.time())}",
        thinking=thinking,
        provider=provider,
        gcp_project=gcp_project,
    )
    if provider == "claude-code":
        runner = run_claude_code_agent
    elif provider == "vertex":
        runner = run_agent_vertex
    else:
        runner = run_agent
    handle = REGISTRY.register(run_id, {"problem": problem, "provider": provider, "model": cfg.model})

    yield send({"type": "start", "problem": problem, "model": cfg.model,
                "provider": provider, "run_id": run_id})
    try:
        for event in runner(cfg, handle):
            if event.type == "usage":
                try:
                    d = event.data or {}
                    append_usage(REPO_ROOT, problem, "solve",
                                 d.get("input_tokens", 0), d.get("output_tokens", 0),
                                 d.get("cost_usd"))
                except Exception:  # noqa: BLE001
                    pass
            yield send(event.to_dict())
    except Exception as exc:  # noqa: BLE001 - keep the stream well-formed
        yield send({"type": "error", "message": f"Server error: {exc}"})
        yield send({"type": "done", "reason": "error"})
    finally:
        REGISTRY.unregister(run_id)


# ── GitHub Issues agentic API ────────────────────────────────────────────────
# Agents can call these endpoints to fully control GitHub Issues on the repo.
# All write endpoints require GITHUB_TOKEN env var on the server.

import requests as _requests


def _gh_error(e: Exception) -> JSONResponse:
    if isinstance(e, _requests.HTTPError) and e.response is not None:
        try:
            msg = e.response.json().get("message", str(e))
        except Exception:
            msg = str(e)
        return JSONResponse({"error": msg, "gh_status": e.response.status_code},
                            status_code=e.response.status_code)
    return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/gh/status")
def gh_status() -> JSONResponse:
    """Check GitHub API connectivity and token availability."""
    return JSONResponse({
        "token_available": _gh.token_available(),
        "repo": _gh.REPO,
    })


@app.get("/api/gh/issues")
def gh_list_issues(
    problem_id: str = Query(None),
    state: str = Query("open"),
    per_page: int = Query(30),
    page: int = Query(1),
) -> JSONResponse:
    """List GitHub issues, optionally filtered by problem_id (e.g. q1)."""
    try:
        issues = _gh.list_issues(problem_id=problem_id, state=state,
                                 per_page=per_page, page=page)
        return JSONResponse({"issues": issues, "count": len(issues)})
    except Exception as e:
        return _gh_error(e)


@app.post("/api/gh/issues")
def gh_create_issue(payload: dict = Body(...)) -> JSONResponse:
    """Create a GitHub issue.

    Body: {problem_id, title, body?, labels?}
    Requires GITHUB_TOKEN.
    """
    problem_id = str(payload.get("problem_id", ""))
    title = str(payload.get("title", ""))
    if not title:
        return JSONResponse({"error": "title is required"}, status_code=400)
    try:
        issue = _gh.create_issue(
            problem_id=problem_id,
            title=title,
            body=str(payload.get("body", "")),
            labels=payload.get("labels"),
        )
        return JSONResponse(issue)
    except Exception as e:
        return _gh_error(e)


@app.get("/api/gh/issues/{issue_number}")
def gh_get_issue(issue_number: int, comments: bool = Query(True)) -> JSONResponse:
    """Get a specific GitHub issue by number, with optional comments."""
    try:
        issue = _gh.get_issue(issue_number, include_comments=comments)
        return JSONResponse(issue)
    except Exception as e:
        return _gh_error(e)


@app.post("/api/gh/issues/{issue_number}/comment")
def gh_add_comment(issue_number: int, payload: dict = Body(...)) -> JSONResponse:
    """Post a comment on a GitHub issue.

    Body: {body}
    Requires GITHUB_TOKEN.
    """
    body = str(payload.get("body", "")).strip()
    if not body:
        return JSONResponse({"error": "body is required"}, status_code=400)
    try:
        comment = _gh.add_comment(issue_number, body)
        return JSONResponse(comment)
    except Exception as e:
        return _gh_error(e)


@app.patch("/api/gh/issues/{issue_number}")
def gh_update_issue(issue_number: int, payload: dict = Body(...)) -> JSONResponse:
    """Update a GitHub issue (title, state, labels, body).

    Body: {title?, state?, labels?, body?}
    state: "open" | "closed"
    Requires GITHUB_TOKEN.
    """
    try:
        issue = _gh.update_issue(
            issue_number,
            title=payload.get("title"),
            state=payload.get("state"),
            labels=payload.get("labels"),
            body=payload.get("body"),
        )
        return JSONResponse(issue)
    except Exception as e:
        return _gh_error(e)


@app.post("/api/gh/issues/{issue_number}/close")
def gh_close_issue(issue_number: int) -> JSONResponse:
    """Close a GitHub issue (mark resolved). Requires GITHUB_TOKEN."""
    try:
        issue = _gh.close_issue(issue_number)
        return JSONResponse(issue)
    except Exception as e:
        return _gh_error(e)


@app.post("/api/gh/issues/{issue_number}/reopen")
def gh_reopen_issue(issue_number: int) -> JSONResponse:
    """Reopen a closed GitHub issue. Requires GITHUB_TOKEN."""
    try:
        issue = _gh.reopen_issue(issue_number)
        return JSONResponse(issue)
    except Exception as e:
        return _gh_error(e)


@app.get("/api/gh/search")
def gh_search_issues(q: str = Query(...)) -> JSONResponse:
    """Search GitHub issues using GitHub search syntax.

    Example: ?q=q1+prove+epsilon-light
    """
    try:
        issues = _gh.search_issues(q)
        return JSONResponse({"issues": issues, "count": len(issues)})
    except Exception as e:
        return _gh_error(e)


# ── Literature ──────────────────────────────────────────────────────────────

@app.get("/api/literature/{problem_id}")
def lit_list(problem_id: str) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    return JSONResponse({"papers": lit_load(REPO_ROOT, problem_id)})


@app.post("/api/literature/{problem_id}")
def lit_add_ep(problem_id: str, payload: dict = Body(...)) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    paper = lit_add(
        REPO_ROOT, problem_id,
        url=str(payload.get("url", "")),
        title=str(payload.get("title", "Untitled")),
        authors=payload.get("authors", []),
        year=payload.get("year"),
        abstract=str(payload.get("abstract", "")),
        tags=payload.get("tags", []),
        relevance=str(payload.get("relevance", "medium")),
        notes=str(payload.get("notes", "")),
        added_by="human",
    )
    return JSONResponse(paper)


@app.patch("/api/literature/{problem_id}/{paper_id}")
def lit_update_ep(problem_id: str, paper_id: str, payload: dict = Body(...)) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    result = lit_update(REPO_ROOT, problem_id, paper_id, **payload)
    if result is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(result)


@app.delete("/api/literature/{problem_id}/{paper_id}")
def lit_delete_ep(problem_id: str, paper_id: str) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    ok = lit_delete(REPO_ROOT, problem_id, paper_id)
    return JSONResponse({"ok": ok})


@app.get("/api/literature/{problem_id}/discover")
def lit_discover_ep(problem_id: str) -> StreamingResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    title = _Q_TITLES.get(problem_id, problem_id)

    def _gen():
        def send(e): return f"data: {json.dumps(e)}\n\n"
        try:
            for ev in discover_literature(REPO_ROOT, problem_id, title):
                yield send(ev.to_dict())
        except Exception as exc:
            yield send({"type": "error", "message": str(exc)})
            yield send({"type": "done", "reason": "error"})

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Concepts ─────────────────────────────────────────────────────────────────

@app.get("/api/concepts/{problem_id}")
def concepts_list(problem_id: str) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    return JSONResponse({"concepts": load_concepts(REPO_ROOT, problem_id)})


@app.post("/api/concepts/{problem_id}")
def concepts_save(problem_id: str, payload: dict = Body(...)) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    save_concepts(REPO_ROOT, problem_id, payload.get("concepts", []))
    return JSONResponse({"ok": True})


@app.get("/api/concepts/{problem_id}/generate")
def concepts_generate_ep(problem_id: str) -> StreamingResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    title = _Q_TITLES.get(problem_id, problem_id)

    def _gen():
        def send(e): return f"data: {json.dumps(e)}\n\n"
        try:
            for ev in generate_concepts(REPO_ROOT, problem_id, title):
                yield send(ev.to_dict())
        except Exception as exc:
            yield send({"type": "error", "message": str(exc)})
            yield send({"type": "done", "reason": "error"})

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Dev Log ──────────────────────────────────────────────────────────────────

@app.get("/api/devlog")
def devlog_list() -> JSONResponse:
    return JSONResponse({"entries": devlog_read(REPO_ROOT)})


# Serve the SPA. Mounted last so /api/* routes take precedence.
if STATIC_DIR.is_dir():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.ico", headers={"Cache-Control": "public, max-age=86400"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
