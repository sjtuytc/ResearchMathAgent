"""FastAPI server for the Research Math Agent web app.

Serves a single-page UI with three views per question — the Question file, its
Issue, and a live Agent runner — and an SSE endpoint that streams the agent loop
step by step. The agent runs via Google Cloud Vertex AI (default) or the
Anthropic Messages API.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from fastapi import Body, FastAPI, Header, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import threading
import uuid

from .agent import DEFAULT_MODEL, AgentConfig, run_agent, build_prefix_context
from .documents import list_documents, read_document
from .dataset_store import (
    list_datasets, get_dataset_meta, list_problems as ds_list_problems,
    get_problem as ds_get_problem, compute_solvability_scores, get_solvability_scores,
    _validate_slug, _validate_id,
)
from .issue_agents import run_discovery_agent, run_resolver_agent, run_verifier_agent, get_working_proof, save_working_proof, run_discussion_agent, generate_issue_summary
from .proofs import get_proof, list_experiments, get_best_proof, list_best_proofs, consolidate_best, maybe_update_best, compile_best_pdf, _proof_outputs_root, _best_dir
from .issues import append_activity, list_issues, get_issue, create_issue, add_comment, update_issue, log_event, get_activity_log, link_issue, add_issue_document, list_all_issues, list_all_issues_system
from .todos import list_todos, create_todo, update_todo, delete_todo
from .meet import (
    create_room as meet_create, get_room as meet_get, list_rooms as meet_list,
    post_message as meet_post_message, set_plan as meet_set_plan,
    mark_step_done as meet_mark_step_done, PERSONAS as meet_personas,
    MATHEMATICIAN_PERSONAS as meet_mathematician_personas,
    get_personas_for_problem as meet_get_personas,
)
from . import github_issues as _gh
from .latex import compile_tex, compile_problem_pdf, latex_available, pdf_dir, safe_pdf_name
from .runs import REGISTRY
from .token_log import append_usage, read_log, daily_summary, per_problem_summary, today_summary, usage_summary, log_usage_delta
from .solve_finalize import finalize_solve_run
from .tools import _expand_tex_inputs, _extract_title, _problem_sort_key
from .solvability_eval import load_eval, evaluate_all, ensure_all_evaluated
from .literature import (
    load_index as lit_load, add_paper as lit_add, update_paper as lit_update,
    delete_paper as lit_delete, discover_literature, ensure_all_lit,
    list_global as lit_list_global, add_to_global as lit_add_global,
    update_global as lit_update_global, delete_from_global as lit_del_global,
    pdf_path_for as lit_pdf_path, get_pdf_status as lit_pdf_status,
    download_paper_pdf as lit_download_pdf, seed_global_library,
    discover_system_literature, pin_paper_to_prefix, _SYSTEM_LIT_QID,
)
from .concepts import load_concepts, save_concepts, generate_concepts, ensure_all_concepts, ensure_fp2_concepts
from .devlog import read_log as devlog_read, append_entry as devlog_append
from .insights import get_system_insight, get_dataset_insight, get_question_insight
from .issue_pdf import compile_issue_pdf
from .doc_bundle import build_bundle_pdf, prebuild_bundle_pdf, _bundle_cache_path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROBLEM_RE = re.compile(r"^(?:q(?:10|[1-9])|prob-\d{2})$")


def _default_provider() -> str:
    # The user's Claude AI subscription (Claude Code CLI) is the only managed
    # backend. An Anthropic API key may be used if explicitly configured.
    from .claude_code import claude_code_available
    if claude_code_available():
        return "claude-code"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    return "claude-code"


def _capabilities_payload() -> dict:
    from .claude_code import claude_code_available
    return {
        "claude_code": bool(claude_code_available()),
        "latex": bool(latex_available()),
        "default_provider": _default_provider(),
        "default_model": DEFAULT_MODEL,
    }

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
threading.Thread(target=seed_global_library, args=(REPO_ROOT,), daemon=True).start()
threading.Thread(
    target=ensure_all_concepts, args=(REPO_ROOT, _Q_TITLES), daemon=True
).start()
threading.Thread(target=ensure_fp2_concepts, args=(REPO_ROOT,), daemon=True).start()
# NOTE: the old indiscriminate context bundle (all raw .tex fragments concatenated)
# has been retired in favour of per-problem comprehensive Context Reports
# (see context_report.py + /api/context-report/*). No startup prebuild needed.
from .issue_loop import run_issue_loop, evolve_once as _evolve_issues_once
threading.Thread(target=run_issue_loop, args=(REPO_ROOT,), daemon=True).start()


@app.get("/api/problems")
def list_problems() -> JSONResponse:
    problems_dir = REPO_ROOT / "problems"
    items = []
    if problems_dir.is_dir():
        for tex in sorted(problems_dir.glob("q*.tex"), key=_problem_sort_key):
            items.append({"id": tex.stem, "title": _extract_title(tex)})
    return JSONResponse({"problems": items, **_capabilities_payload()})


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
    sort: str = Query("solvability_desc"),  # default: rank by AI-solvability
    tags: str = Query(None),          # comma-separated
    min_difficulty: float = Query(None),
    max_difficulty: float = Query(None),
    min_solvability: float = Query(None),
    max_solvability: float = Query(None),
    tier: str = Query(None),          # solvability category: likely|plausible|hard|open
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
        tier=tier, search=search,
    )
    return JSONResponse({"problems": problems, **_capabilities_payload()})


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


@app.get("/api/issues-all")
def list_issues_all_ep(level: str = Query("dataset"), dataset: str = Query(None)) -> JSONResponse:
    if level == "system":
        return JSONResponse({"issues": list_all_issues_system(REPO_ROOT)})
    ds = _ds_from_query(dataset)
    return JSONResponse({"issues": list_all_issues(REPO_ROOT, ds)})


@app.get("/api/issues/{problem_id}")
def list_issues_ep(problem_id: str, dataset: str = Query(None), status: str = Query(None)) -> JSONResponse:
    ds = _ds_from_query(dataset)
    pid = problem_id
    if ds == "first_proof_1" and not _PROBLEM_RE.match(pid):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    elif not _ID_RE_LOOSE.match(pid):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    return JSONResponse({"issues": list_issues(REPO_ROOT, pid, ds, status=status)})


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


@app.post("/api/issues/{problem_id}/{issue_id}/doc")
def add_doc_to_issue_ep(problem_id: str, issue_id: str, payload: dict = Body(...), dataset: str = Query(None)) -> JSONResponse:
    """Link a document path/title to an issue (used by agents and the UI)."""
    ds = _ds_from_query(dataset)
    issue = add_issue_document(
        REPO_ROOT, problem_id, issue_id,
        title=str(payload.get("title", "Document")),
        path=str(payload.get("path", "")),
        created_by=str(payload.get("created_by", "agent")),
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


@app.get("/api/issue-pdf/{problem_id}/{issue_id}")
def issue_pdf_ep(
    problem_id: str,
    issue_id: str,
    dataset: str = Query(None),
    force: bool = Query(False),
) -> JSONResponse:
    ds = _ds_from_query(dataset)
    issue = get_issue(REPO_ROOT, problem_id, issue_id, ds)
    if issue is None:
        return JSONResponse({"error": "issue not found"}, status_code=404)
    result = compile_issue_pdf(REPO_ROOT, issue, force=force)
    return JSONResponse(result)


@app.get("/api/all-issues-pdf/{scope}")
def all_issues_pdf_ep(
    scope: str,
    dataset: str = Query(None),
    force: bool = Query(False),
) -> JSONResponse:
    """Render ALL issues for a problem (scope=problem_id) or a whole dataset
    (scope=_dataset) into one combined PDF."""
    ds = _ds_from_query(dataset)
    from .issue_pdf import compile_all_issues_pdf
    problem_id = None if scope in ("_dataset", "_all", "") else scope
    return JSONResponse(compile_all_issues_pdf(REPO_ROOT, ds, problem_id, force=force))


@app.get("/api/master-pdf")
def master_pdf_ep(dataset: str = Query(None), force: bool = Query(False)) -> JSONResponse:
    """The Documents tab document: ONE huge combined PDF of all tabs for a dataset.
    Serves the cached file instantly when present; (re)builds on force / first use."""
    ds = _ds_from_query(dataset)
    name = f"master_{ds}.pdf"
    dest = pdf_dir(REPO_ROOT) / name
    if not force and dest.is_file():
        return JSONResponse({"ok": True, "pdf_url": f"/api/pdf/{name}", "log": "cached"})
    if not force:
        return JSONResponse({"ok": False, "pdf_url": None,
                             "log": "No master PDF built yet — run `rma push` or click Build now."})
    from .context_report import compile_master_pdf
    return JSONResponse(compile_master_pdf(REPO_ROOT, ds, force=True))




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

@app.get("/api/meet-personas/{problem_id}")
def get_meet_personas(problem_id: str) -> JSONResponse:
    personas = meet_get_personas(problem_id)
    # Strip the long 'character' field — keep only display info for the UI
    ui_personas = [
        {k: v for k, v in p.items() if k != "character"}
        for p in personas
    ]
    return JSONResponse({"personas": ui_personas})


@app.get("/api/meets/{problem_id}")
def list_meets(problem_id: str, include_empty: bool = Query(False)) -> JSONResponse:
    from .meet_pdf import room_is_substantive
    rooms = meet_list(REPO_ROOT, problem_id)
    if not include_empty:
        rooms = [r for r in rooms if room_is_substantive(r)]
    return JSONResponse({"rooms": rooms})


@app.get("/api/meet-pdf/{problem_id}/{room_id}")
def meet_pdf_ep(
    problem_id: str,
    room_id: str,
    force: bool = Query(False),
) -> JSONResponse:
    from .meet_pdf import compile_meet_pdf
    room = meet_get(REPO_ROOT, problem_id, room_id)
    if room is None:
        return JSONResponse({"error": "room not found"}, status_code=404)
    result = compile_meet_pdf(REPO_ROOT, room, force=force)
    return JSONResponse(result)


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




@app.get("/api/todos/{problem_id}")
def get_todos(problem_id: str) -> JSONResponse:
    return JSONResponse({"todos": list_todos(REPO_ROOT, problem_id)})


@app.post("/api/todos/{problem_id}")
def add_todo(problem_id: str, payload: dict = Body(...)) -> JSONResponse:
    item = create_todo(
        REPO_ROOT, problem_id,
        title=str(payload.get("title", "")),
        priority=str(payload.get("priority", "medium")),
        note=str(payload.get("note", "")),
        action_tab=str(payload.get("action_tab", "")),
        action_target=str(payload.get("action_target", "")),
    )
    return JSONResponse(item)


@app.patch("/api/todos/{problem_id}/{todo_id}")
def patch_todo(problem_id: str, todo_id: str, payload: dict = Body(...)) -> JSONResponse:
    item = update_todo(REPO_ROOT, problem_id, todo_id, **payload)
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(item)


@app.delete("/api/todos/{problem_id}/{todo_id}")
def remove_todo(problem_id: str, todo_id: str) -> JSONResponse:
    ok = delete_todo(REPO_ROOT, problem_id, todo_id)
    return JSONResponse({"ok": ok})


@app.get("/api/q-detail/{problem_id}")
def question_detail(problem_id: str) -> JSONResponse:
    """Rich per-question data for the overview dashboard."""
    pid = problem_id
    issues = list_issues(REPO_ROOT, pid)
    open_issues = [
        {"id": i["id"], "title": i.get("title", ""), "status": i.get("status", ""), "labels": i.get("labels", [])}
        for i in issues if i.get("status") in ("open", "in_progress")
    ]
    activity = get_activity_log(REPO_ROOT, pid, limit=8)
    # Best proof
    best_proof: dict = {}
    try:
        bp = get_best_proof(pid)
        if bp:
            best_proof = {
                "verified": bool(bp.get("verification_passed")),
                "issue_count": bp.get("issue_count"),
                "model": bp.get("model", ""),
                "date": bp.get("date", "") or bp.get("created_at", ""),
            }
    except Exception:  # noqa: BLE001
        pass
    # Document availability
    qdir = REPO_ROOT / "documents" / "questions" / pid
    docs = {
        "overview": (qdir / "overview.md").is_file(),
        "timeline": (qdir / "timeline.md").is_file(),
        "progress": (qdir / "progress.md").is_file(),
        "strategies": (qdir / "strategies.md").is_file(),
    }
    # Strategies excerpt (first 800 chars of strategies.md for quick display)
    strategy_excerpt = ""
    strategies_path = qdir / "strategies.md"
    if strategies_path.is_file():
        try:
            strategy_excerpt = strategies_path.read_text(encoding="utf-8", errors="replace")[:800]
        except Exception:  # noqa: BLE001
            pass
    return JSONResponse({
        "open_issues": open_issues,
        "recent_activity": activity,
        "best_proof": best_proof,
        "docs": docs,
        "strategy_excerpt": strategy_excerpt,
        "user_todos": list_todos(REPO_ROOT, pid),
    })


@app.get("/api/meets/personas")
def get_personas() -> JSONResponse:
    return JSONResponse(meet_personas)


@app.get("/api/solve")
def solve(
    problem: str = Query(..., description="Problem id, e.g. q6"),
    model: str = Query(""),
    provider: str = Query("", description="claude-code | api (default: auto)"),
    thinking: int = Query(1),
    run_id: str = Query(""),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(problem, model, provider or _default_provider(), bool(thinking), run_id or uuid.uuid4().hex),
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


@app.get("/api/context-report/index")
def context_report_index(dataset: str = Query(None)) -> JSONResponse:
    """Lightweight per-problem status index for the Documents sidebar."""
    from .context_report import problem_ids, _issues, _best_proof, _meetings, _profile, _status_label
    ds = _ds_from_query(dataset)
    items = []
    for pid in problem_ids(ds):
        issues = _issues(REPO_ROOT, pid, ds)
        best = _best_proof(pid, ds)
        meetings = _meetings(REPO_ROOT, pid)
        open_n = sum(1 for i in issues if i.get("status") in ("open", "in_progress"))
        res_n = sum(1 for i in issues if i.get("status") == "resolved")
        emoji, status = _status_label(pid, issues, best)
        prof = _profile(pid)
        _title = prof.get("title") or ""
        if not _title:
            try:
                from .dataset_store import get_problem as _ds_gp
                _p = _ds_gp(ds, pid) or {}
                _title = _p.get("title") or ""
            except Exception:
                pass
        _title = _title or pid.upper()
        items.append({
            "scope": pid,
            "title": _title,
            "area": prof.get("area", ""),
            "status": status,
            "status_emoji": emoji,
            "open_issues": open_n,
            "resolved_issues": res_n,
            "meetings": len(meetings),
            "has_proof": bool(best and best.get("has_solution")),
        })
    return JSONResponse({"dataset": ds, "items": items})


@app.get("/api/context-report/{scope}")
def context_report_ep(scope: str, dataset: str = Query(None)) -> JSONResponse:
    from .context_report import build_report
    ds = _ds_from_query(dataset)
    try:
        return JSONResponse(build_report(REPO_ROOT, scope, ds))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/context-report/{scope}/pdf")
def context_report_pdf_ep(scope: str, dataset: str = Query(None), force: bool = Query(False)) -> JSONResponse:
    from .context_report import compile_report_pdf
    ds = _ds_from_query(dataset)
    return JSONResponse(compile_report_pdf(REPO_ROOT, scope, ds, force=force))


@app.get("/api/document/{name:path}")
def document(name: str) -> JSONResponse:
    content = read_document(REPO_ROOT, name)
    if content is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    fmt = "latex" if name.endswith(".tex") else "markdown"
    return JSONResponse({"name": name, "format": fmt, "markdown": content, "content": content})


@app.get("/api/documents/bundle.pdf")
def documents_bundle(dataset: str | None = None, question: str | None = None):
    """Return a combined PDF of all documents (or filtered by dataset/question).

    For the unfiltered full bundle, serves the pre-built cache written at startup.
    Filtered requests (dataset or question) are compiled on demand.
    """
    from fastapi.responses import Response
    if dataset is None and question is None:
        cached = _bundle_cache_path(REPO_ROOT)
        if cached.is_file():
            return Response(
                content=cached.read_bytes(),
                media_type="application/pdf",
                headers={"Content-Disposition": "inline; filename=context_bundle.pdf"},
            )
        return JSONResponse(
            {"error": "bundle not ready yet — server is still building it at startup"},
            status_code=503,
        )
    try:
        pdf_bytes = build_bundle_pdf(REPO_ROOT, dataset=dataset, qid=question)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=context_bundle.pdf"})


@app.get("/api/problem-pdf/{problem_id}")
def problem_pdf(problem_id: str, force: bool = Query(False)) -> JSONResponse:
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    # PDF-only Question tab: render the statement via the robust pipeline
    # (handles custom macros / markdown; never hard-fails). first_proof_1 lives
    # in the dataset store; fall back to the legacy problems/*.tex if needed.
    from .problem_pdf import compile_problem_statement_pdf
    p = ds_get_problem("first_proof_1", problem_id)
    title = (p or {}).get("title", problem_id)
    statement = (p or {}).get("tex") or (p or {}).get("statement") or ""
    if not statement:
        tex_path = REPO_ROOT / "problems" / f"{problem_id}.tex"
        if tex_path.is_file():
            statement = tex_path.read_text(encoding="utf-8", errors="replace")
    result = compile_problem_statement_pdf(REPO_ROOT, "first_proof_1", problem_id,
                                           title, statement, force=force)
    return JSONResponse(result)


@app.get("/api/ds/problem-pdf/{dataset}/{problem_id}")
def ds_problem_pdf(dataset: str, problem_id: str, force: bool = Query(False)) -> JSONResponse:
    try:
        _validate_slug(dataset)
        _validate_id(problem_id)
    except ValueError:
        return JSONResponse({"error": "invalid"}, status_code=400)
    p = ds_get_problem(dataset, problem_id)
    if p is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    # PDF-only Question tab: render via the robust pipeline (markdown/LaTeX,
    # custom macros, never hard-fails).
    from .problem_pdf import compile_problem_statement_pdf
    statement = p.get("tex") or p.get("statement") or ""
    result = compile_problem_statement_pdf(
        REPO_ROOT, dataset, problem_id, p.get("title", problem_id), statement, force=force)
    return JSONResponse(result)


@app.post("/api/compile")
def compile_pdf(payload: dict = Body(...)) -> JSONResponse:
    content = str(payload.get("content", ""))
    name = str(payload.get("name", "solution"))
    result = compile_tex(REPO_ROOT, content, name)
    if result["ok"]:
        result["pdf_url"] = f"/api/pdf/{result['pdf']}"
    return JSONResponse(result)


@app.api_route("/api/pdf/{name}", methods=["GET", "HEAD"])
def get_pdf(name: str):
    safe = safe_pdf_name(name)
    path = pdf_dir(REPO_ROOT) / safe
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    # HEAD/GET both supported: HEAD lets the UI read Content-Length to decide
    # whether a PDF is small enough to render inline vs. offer as a download.
    # Inline so the browser renders it in-page (iframe/pdf viewer); the UI's
    # Download links use the <a download> attribute for manual saving.
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{safe}"'})


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
def best_proofs_list(dataset: str = Query("first_proof_1")) -> JSONResponse:
    proofs = list_best_proofs(dataset)
    return JSONResponse({"proofs": proofs, "dataset": dataset})


@app.get("/api/best-proof/{problem_id}")
def best_proof_detail(problem_id: str, dataset: str = Query("first_proof_1")) -> JSONResponse:
    data = get_best_proof(problem_id, dataset)
    if data is None:
        return JSONResponse({"error": "no best proof found — run consolidate or rma solve first"}, status_code=404)
    return JSONResponse(data)


@app.post("/api/consolidate-best")
def consolidate_best_ep(dataset: str = Query("first_proof_1")) -> JSONResponse:
    result = consolidate_best(dataset, compile_pdfs=True)
    return JSONResponse({"updated": len(result), "problems": list(result.keys())})


@app.get("/api/best-proof-pdf/{problem_id}")
def best_proof_pdf(problem_id: str, dataset: str = Query("first_proof_1")):
    """Serve the pre-compiled PDF for the best proof, compiling it on demand if needed."""
    if not _PROBLEM_RE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    pdf_path = _best_dir(dataset) / problem_id / "solution.pdf"
    if not pdf_path.is_file():
        ok = compile_best_pdf(problem_id, dataset)
        if not ok or not pdf_path.is_file():
            return JSONResponse({"error": "PDF not available — run Consolidate first"}, status_code=404)
    return FileResponse(pdf_path, media_type="application/pdf",
                        filename=f"{problem_id}_best_proof.pdf")


_FINAL_SOLUTIONS_DIR = (
    Path(__file__).resolve().parents[3]
    / "shared" / "data" / "first_proof_1" / "final_solutions"
)
_AUTHOR_SOLUTIONS_DIR = _FINAL_SOLUTIONS_DIR / "first_proof_author_solutions"
_ALLOWED_EXTS = {".pdf", ".tex"}


@app.get("/api/final-proof-files")
def final_proof_files() -> JSONResponse:
    # Author Solution tab is a PDF viewer — only list .pdf files (raw .tex is
    # not human-readable in the UI and is intentionally excluded here).
    files = []
    if _FINAL_SOLUTIONS_DIR.is_dir():
        for f in sorted(_FINAL_SOLUTIONS_DIR.iterdir()):
            if f.is_file() and f.suffix == ".pdf":
                files.append({"name": f.name, "path": f.name, "group": "merged"})
    if _AUTHOR_SOLUTIONS_DIR.is_dir():
        for f in sorted(_AUTHOR_SOLUTIONS_DIR.iterdir()):
            if f.is_file() and f.suffix == ".pdf":
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
    return JSONResponse(_capabilities_payload())


@app.get("/api/usage")
def usage() -> JSONResponse:
    """Estimated spend from the webapp token log."""
    return JSONResponse(usage_summary(REPO_ROOT))


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
    save_working_proof(REPO_ROOT, problem_id, tex, agent="human")
    return JSONResponse({"ok": True})


@app.get("/api/proof-history/{problem_id}")
def proof_history_ep(problem_id: str) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    from .proof_history import list_proof_history
    history = list_proof_history(REPO_ROOT, problem_id)
    return JSONResponse({"problem_id": problem_id, "history": history})


@app.get("/api/proof-history/{problem_id}/{version}")
def proof_history_version_ep(problem_id: str, version: int) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    from .proof_history import get_proof_version_tex
    tex = get_proof_version_tex(REPO_ROOT, problem_id, version)
    if tex is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    return JSONResponse({"problem_id": problem_id, "version": version, "tex": tex})


# ── agent-run authentication + per-problem concurrency guard ──────────────────
# These endpoints each kick off an expensive agentic LLM run. They are reachable
# on the public tunnel, and EventSource (the browser stream API) can't send custom
# headers — so the UI passes a shared secret as the `key` query param, which the
# server injects into the page (see _index_html). Anonymous crawlers/bots hitting
# the URLs directly have no key and are rejected. The concurrency guard then caps
# cost: at most one in-flight run per (kind, problem), plus a cooldown, so SSE
# auto-reconnect storms and repeat triggers can't fan out into parallel runs.
_AGENT_KEY = os.environ.get("RMA_AGENT_KEY", "")
_AGENT_COOLDOWN_S = int(os.environ.get("RMA_AGENT_COOLDOWN", "20"))
_agent_guard_lock = threading.Lock()
_agent_inflight: set[str] = set()
_agent_last_start: dict[str, float] = {}


def _agent_auth_ok(key: str | None) -> bool:
    """Open when RMA_AGENT_KEY is unset; otherwise the key must match."""
    return not _AGENT_KEY or key == _AGENT_KEY


def _agent_guard_acquire(guard_key: str) -> str | None:
    """Mark a run in-flight. Returns an error message if it should be rejected."""
    now = time.time()
    with _agent_guard_lock:
        if guard_key in _agent_inflight:
            return "an agent run for this problem is already in progress"
        wait = _AGENT_COOLDOWN_S - (now - _agent_last_start.get(guard_key, 0.0))
        if wait > 0:
            return f"rate limited — wait {int(wait) + 1}s before starting another run on this problem"
        _agent_inflight.add(guard_key)
        _agent_last_start[guard_key] = now
    return None


def _agent_guard_release(guard_key: str) -> None:
    with _agent_guard_lock:
        _agent_inflight.discard(guard_key)


def _start_agent_stream(runner_fn, kind, problem_id, issue_id, run_id, ds, key):
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    if not _agent_auth_ok(key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    guard_key = f"{kind}:{problem_id}:{issue_id or ''}"
    rejected = _agent_guard_acquire(guard_key)
    if rejected:
        return JSONResponse({"error": rejected}, status_code=429)
    return StreamingResponse(
        _sse_issue_agent(runner_fn, REPO_ROOT, problem_id, run_id or uuid.uuid4().hex,
                         issue_id=issue_id, dataset=ds, guard_key=guard_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/agent/discover/{problem_id}")
def agent_discover(problem_id: str, run_id: str = Query(""), dataset: str = Query(None),
                   key: str = Query(""), x_api_key: str = Header(None)):
    return _start_agent_stream(run_discovery_agent, "discover", problem_id, None,
                               run_id, _ds_from_query(dataset), key or x_api_key)


@app.get("/api/agent/resolve/{problem_id}/{issue_id}")
def agent_resolve(problem_id: str, issue_id: str, run_id: str = Query(""), dataset: str = Query(None),
                  key: str = Query(""), x_api_key: str = Header(None)):
    return _start_agent_stream(run_resolver_agent, "resolve", problem_id, issue_id,
                               run_id, _ds_from_query(dataset), key or x_api_key)


@app.get("/api/agent/verify/{problem_id}/{issue_id}")
def agent_verify(problem_id: str, issue_id: str, run_id: str = Query(""), dataset: str = Query(None),
                 key: str = Query(""), x_api_key: str = Header(None)):
    return _start_agent_stream(run_verifier_agent, "verify", problem_id, issue_id,
                               run_id, _ds_from_query(dataset), key or x_api_key)


def _sse_issue_agent(runner_fn, repo_root, problem_id, run_id, issue_id=None,
                     dataset="first_proof_1", guard_key=None):
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
    usage_prev: dict = {}
    try:
        if issue_id:
            gen = runner_fn(repo_root, problem_id, issue_id, handle, dataset=dataset)
        else:
            gen = runner_fn(repo_root, problem_id, handle, dataset=dataset)
        for event in gen:
            if event.type == "usage":
                try:
                    d = event.data or {}
                    log_usage_delta(
                        repo_root, problem_id, kind, d, usage_prev,
                        provider="claude-code", model="",
                    )
                except Exception:  # noqa: BLE001
                    pass
            yield send(event.to_dict())
    except Exception as exc:  # noqa: BLE001
        yield send({"type": "error", "message": f"Server error: {exc}"})
        yield send({"type": "done", "reason": "error"})
    finally:
        REGISTRY.unregister(run_id)
        if guard_key:
            _agent_guard_release(guard_key)


@app.get("/api/overview")
def overview_ep(dataset: str = Query(None)) -> JSONResponse:
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

    # ── Determine the active problem set based on dataset param ──────────────
    _use_fp1 = not dataset or dataset == "first_proof_1"
    _ds_eff = "first_proof_1" if _use_fp1 else dataset

    if _use_fp1:
        active_pids = [f"q{i}" for i in range(1, 11)]
        _ds_problems: list[dict] = []  # not needed for fp1 path
    else:
        try:
            _ds_problems = ds_list_problems(dataset=_ds_eff, sort="id")
        except Exception:  # noqa: BLE001
            _ds_problems = []
        active_pids = [p["id"] for p in _ds_problems]

    # ── Issue stats ───────────────────────────────────────────────────────────
    issue_stats: dict[str, dict] = {}
    for pid in active_pids:
        try:
            issues = list_issues(REPO_ROOT, pid, _ds_eff)
        except Exception:  # noqa: BLE001
            issues = []
        issue_stats[pid] = {
            "open": sum(1 for x in issues if x.get("status") == "open"),
            "in_progress": sum(1 for x in issues if x.get("status") == "in_progress"),
            "resolved": sum(1 for x in issues if x.get("status") == "resolved"),
            "total": len(issues),
        }

    # ── Recent activity ───────────────────────────────────────────────────────
    recent: list[dict] = []
    for pid in active_pids:
        try:
            for iss in list_issues(REPO_ROOT, pid, _ds_eff):
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

    # ── Suggestions ───────────────────────────────────────────────────────────
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

    # ── Per-question summaries ────────────────────────────────────────────────
    question_summaries: list[dict] = []

    if _use_fp1:
        # fp1 path: rich summaries from strategy_memory, opus evals, best proofs
        for pid in active_pids:
            qs = _question_summary(REPO_ROOT, pid)
            ist = issue_stats.get(pid, {"open": 0, "in_progress": 0, "resolved": 0, "total": 0})
            total_iss = ist["total"]
            resolved = ist["resolved"]
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
            accuracy_pct = round(resolved / total_iss * 100) if total_iss > 0 else None
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
            last_model = ""
            mem_path = REPO_ROOT / "documents" / "strategy_memory.jsonl"
            if mem_path.is_file():
                for line in reversed(mem_path.read_text(encoding="utf-8", errors="replace").splitlines()):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        if e.get("problem_id") == pid:
                            last_model = e.get("model", "")
                            break
                    except Exception:  # noqa: BLE001
                        continue
            has_critic_run = False
            for iss in list_issues(REPO_ROOT, pid):
                if any(c.get("author") == "critic-agent" for c in iss.get("comments", [])):
                    has_critic_run = True
                    break
            question_summaries.append({
                **qs,
                "issue_stats": ist,
                "proof_status": proof_status,
                "accuracy_pct": accuracy_pct,
                "solvability_pct": solvability_pct,
                "best_issues": best_issues if best_issues < 99 else None,
                "best_verified": best_verified,
                "last_model": last_model,
                "has_critic_run": has_critic_run,
            })
    else:
        # Non-fp1 dataset: lighter summaries built from dataset store + issue counts
        _ds_prob_map = {p["id"]: p for p in _ds_problems}
        for pid in active_pids:
            p = _ds_prob_map.get(pid, {})
            ist = issue_stats.get(pid, {"open": 0, "in_progress": 0, "resolved": 0, "total": 0})
            total_iss = ist["total"]
            resolved = ist["resolved"]
            if total_iss == 0:
                proof_status = "not_started"
            elif resolved == total_iss:
                proof_status = "verified"
            elif resolved > 0:
                proof_status = "in_progress"
            elif ist["in_progress"] > 0:
                proof_status = "exploring"
            else:
                proof_status = "open_issues"
            accuracy_pct = round(resolved / total_iss * 100) if total_iss > 0 else None
            raw_solv = p.get("solvability_score")
            solvability_pct = int(round(raw_solv * 100)) if raw_solv is not None else None
            has_critic_run = any(
                c.get("author") == "critic-agent"
                for iss in list_issues(REPO_ROOT, pid, _ds_eff)
                for c in iss.get("comments", [])
            )
            question_summaries.append({
                "qid": pid,
                "title": p.get("title", pid),
                "area": p.get("area", ""),
                "dataset": _ds_eff,
                "has_doc": total_iss > 0,
                "candidate_answer": None,
                "total_runs": 0,
                "success_runs": 0,
                "fail_runs": 0,
                "last_outcome": None,
                "last_run_date": None,
                "opus_eval": None,
                "labels": (p.get("tags") or [])[:6],
                "issue_stats": ist,
                "proof_status": proof_status,
                "accuracy_pct": accuracy_pct,
                "solvability_pct": solvability_pct,
                "best_issues": None,
                "best_verified": False,
                "last_model": "",
                "has_critic_run": has_critic_run,
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
        "dataset": _ds_eff,
    })


@app.post("/api/seed/first_proof_2")
def api_seed_fp2() -> JSONResponse:
    """Seed skeleton .tex docs + Vertex-generated concepts/literature for all fp2 problems."""
    from .seed_fp2 import seed_fp2_background
    threading.Thread(target=seed_fp2_background, args=(REPO_ROOT,), daemon=True).start()
    return JSONResponse({"started": True, "message": "Seeding first_proof_2 in background (check server logs)"})


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


@app.post("/api/push-forward")
def push_forward_ep(payload: dict = Body(default={})) -> JSONResponse:
    """Trigger the global daily push-forward across ALL problems (background thread).

    For each problem: runs issue discovery + resolution, then conducts a full
    meeting (multiple discussion rounds + synthesis + documented notes).
    Gated to once-per-day unless force=true is passed.

    Optional payload fields:
      force (bool): bypass once-per-day gate
      problems (list[str]): restrict to specific problem IDs
      n_meeting_rounds (int): discussion rounds per meeting (default 3)
    """
    from .push_forward import run_push_forward, already_ran_today, running_job, _DEFAULT_MEETING_ROUNDS

    force = bool(payload.get("force", False))
    problems = payload.get("problems") or None
    n_meeting_rounds = int(payload.get("n_meeting_rounds", _DEFAULT_MEETING_ROUNDS))
    max_resolve = int(payload.get("max_resolve", 2))
    dataset = payload.get("dataset", "first_proof_1")

    if not force and already_ran_today(REPO_ROOT):
        return JSONResponse({
            "started": False,
            "reason": "already ran today — pass {\"force\": true} to override",
        })

    active = running_job()
    if active:
        return JSONResponse({
            "started": False,
            "reason": "push-forward already running",
            "job_id": active["job_id"],
        })

    job_id = uuid.uuid4().hex
    threading.Thread(
        target=run_push_forward,
        args=(REPO_ROOT, job_id),
        kwargs={"problems": problems, "n_meeting_rounds": n_meeting_rounds,
                "max_resolve": max_resolve, "dataset": dataset},
        daemon=True,
    ).start()
    return JSONResponse({"started": True, "job_id": job_id, "dataset": dataset,
                         "n_meeting_rounds": n_meeting_rounds, "max_resolve": max_resolve})


@app.get("/api/push-forward/status")
def push_forward_status_ep() -> JSONResponse:
    """Return the state of all push-forward jobs (in-memory) + persisted run history."""
    from .push_forward import list_jobs, load_state
    return JSONResponse({"jobs": list_jobs(), "state": load_state(REPO_ROOT)})


@app.get("/api/push-forward/status/{job_id}")
def push_forward_job_ep(job_id: str) -> JSONResponse:
    from .push_forward import get_job
    info = get_job(job_id)
    if info is None:
        return JSONResponse({"status": "unknown"}, status_code=404)
    return JSONResponse(info)


@app.get("/api/push-forward/metrics")
def push_forward_metrics_ep() -> JSONResponse:
    """Return persisted per-round metrics from data/push_forward_metrics.json."""
    from .push_forward import load_metrics
    return JSONResponse(load_metrics(REPO_ROOT))


@app.get("/api/proof-eval/{problem_id}")
def proof_eval_get(problem_id: str) -> JSONResponse:
    """Return cached proof evaluation scores, or {cached:false} if none exist."""
    from .proof_eval import load_proof_eval
    data = load_proof_eval(REPO_ROOT, problem_id)
    if data is None:
        return JSONResponse({"cached": False})
    return JSONResponse({"cached": True, **data})


@app.get("/api/proof-eval/{problem_id}/run")
def proof_eval_run_ep(problem_id: str, dataset: str = Query(None), force: bool = Query(False)):
    """SSE: run proof evaluation and stream back the result."""
    from .proof_eval import evaluate_proof

    def _stream():
        result = evaluate_proof(REPO_ROOT, problem_id, _ds_from_query(dataset), force=force)
        if "error" in result:
            yield f"data: {json.dumps({'type': 'error', 'message': result['error']})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'result', **result})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/api/eval/solvability/refresh")
def refresh_solvability_eval(force: bool = Query(False)) -> JSONResponse:
    """Re-evaluate AI solvability for all q1-q10 using Claude Opus (background)."""
    from .solvability_eval import evaluate_all as _eval_all
    def _run():
        _eval_all(REPO_ROOT, force=force)
    threading.Thread(target=_run, daemon=True).start()
    return JSONResponse({"started": True, "force": force,
                         "message": "Opus solvability evaluation running in background; check /api/overview in ~3 minutes."})


def _sse(problem: str, model: str, provider: str, thinking: bool, run_id: str):
    def send(event: dict) -> str:
        return f"data: {json.dumps(event)}\n\n"

    if not _PROBLEM_RE.match(problem):
        yield send({"type": "error", "message": f"Invalid problem id '{problem}'."})
        yield send({"type": "done", "reason": "error"})
        return

    problem_path = REPO_ROOT / "problems" / f"{problem}.tex"
    provider = provider or _default_provider()

    if problem_path.is_file():
        # first_proof_1 (q1–q10): load from .tex file
        problem_text = _expand_tex_inputs(
            problem_path.read_text(encoding="utf-8", errors="replace"), REPO_ROOT
        )
    else:
        # first_proof_2 (prob-01–prob-10): load from dataset store
        fp2 = ds_get_problem("first_proof_2", problem)
        if fp2 is None:
            yield send({"type": "error", "message": f"Problem '{problem}' not found."})
            yield send({"type": "done", "reason": "error"})
            return
        problem_text = fp2.get("tex") or fp2.get("statement") or ""
        if not problem_text:
            yield send({"type": "error", "message": f"Problem '{problem}' has no LaTeX content."})
            yield send({"type": "done", "reason": "error"})
            return

    prefix_context = build_prefix_context(REPO_ROOT, problem)

    cfg = AgentConfig(
        problem_id=problem,
        problem_text=problem_text,
        model=model or (DEFAULT_MODEL if provider == "api" else ""),
        repo_root=REPO_ROOT,
        workspace=REPO_ROOT / "webapp" / ".runs" / f"{problem}_{int(time.time())}",
        thinking=thinking,
        provider=provider,
        prefix_context=prefix_context,
    )
    if provider == "claude-code":
        runner = run_claude_code_agent
    else:
        runner = run_agent
    handle = REGISTRY.register(run_id, {"problem": problem, "provider": provider, "model": cfg.model})

    transcript_parts: list[str] = []
    artifact: dict | None = None
    usage: dict = {}
    reason = "end_turn"

    yield send({"type": "start", "problem": problem, "model": cfg.model,
                "provider": provider, "run_id": run_id})
    usage_prev: dict = {}
    try:
        for event in runner(cfg, handle):
            if event.type == "text_delta":
                transcript_parts.append(event.data.get("text", ""))
            elif event.type == "artifact":
                artifact = event.data
            elif event.type == "usage":
                usage = dict(event.data or {})
                try:
                    log_usage_delta(
                        REPO_ROOT, problem, "solve", usage, usage_prev,
                        provider=provider, model=cfg.model,
                    )
                except Exception:  # noqa: BLE001
                    pass
            elif event.type == "done":
                reason = event.data.get("reason", "end_turn")
                try:
                    saved = finalize_solve_run(
                        REPO_ROOT,
                        problem,
                        transcript="".join(transcript_parts),
                        artifact=artifact,
                        usage=usage,
                        reason=reason,
                        provider=provider,
                        model=cfg.model,
                    )
                    yield send({"type": "saved", **saved})
                except Exception as exc:  # noqa: BLE001
                    yield send({"type": "error", "message": f"Failed to save results: {exc}"})
                yield send(event.to_dict())
                return
            yield send(event.to_dict())
    except Exception as exc:  # noqa: BLE001 - keep the stream well-formed
        yield send({"type": "error", "message": f"Server error: {exc}"})
        try:
            saved = finalize_solve_run(
                REPO_ROOT,
                problem,
                transcript="".join(transcript_parts),
                artifact=artifact,
                usage=usage,
                reason="error",
                provider=provider,
                model=cfg.model,
            )
            yield send({"type": "saved", **saved})
        except Exception:  # noqa: BLE001
            pass
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


@app.get("/api/lit-global")
def lit_global_list_ep() -> JSONResponse:
    papers = lit_list_global(REPO_ROOT)
    for p in papers:
        p["pdf_status"] = lit_pdf_status(REPO_ROOT, p["id"])
    return JSONResponse({"papers": papers})


@app.post("/api/lit-global")
def lit_global_add_ep(payload: dict = Body(...)) -> JSONResponse:
    paper = lit_add_global(REPO_ROOT, payload)
    return JSONResponse({"paper": paper})


@app.patch("/api/lit-global/{paper_id}")
def lit_global_update_ep(paper_id: str, payload: dict = Body(...)) -> JSONResponse:
    result = lit_update_global(REPO_ROOT, paper_id, **payload)
    if result is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"paper": result})


@app.delete("/api/lit-global/{paper_id}")
def lit_global_delete_ep(paper_id: str) -> JSONResponse:
    ok = lit_del_global(REPO_ROOT, paper_id)
    return JSONResponse({"ok": ok})


@app.post("/api/lit-global/{paper_id}/download")
def lit_global_download_ep(paper_id: str) -> JSONResponse:
    papers = lit_list_global(REPO_ROOT)
    p = next((x for x in papers if x["id"] == paper_id), None)
    if not p:
        return JSONResponse({"error": "paper not found"}, status_code=404)
    def _do_download():
        lit_download_pdf(REPO_ROOT, paper_id, p.get("url", ""))
    threading.Thread(target=_do_download, daemon=True).start()
    return JSONResponse({"status": "downloading", "paper_id": paper_id})


@app.get("/api/lit-global/{paper_id}/pdf")
def lit_global_pdf_ep(paper_id: str):
    pdf = lit_pdf_path(REPO_ROOT, paper_id)
    if not pdf.is_file():
        return JSONResponse({"error": "PDF not available"}, status_code=404)
    return FileResponse(str(pdf), media_type="application/pdf")


@app.post("/api/lit-global/seed")
def lit_global_seed_ep() -> JSONResponse:
    count = seed_global_library(REPO_ROOT)
    return JSONResponse({"seeded": count})


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


@app.get("/api/literature/system")
def lit_system_list_ep() -> JSONResponse:
    papers = lit_load(REPO_ROOT, _SYSTEM_LIT_QID)
    return JSONResponse({"papers": papers})


@app.get("/api/literature/system/discover")
def lit_system_discover_ep() -> StreamingResponse:
    def _gen():
        def send(e): return f"data: {json.dumps(e)}\n\n"
        try:
            for ev in discover_system_literature(REPO_ROOT):
                yield send(ev.to_dict())
        except Exception as exc:
            yield send({"type": "error", "message": str(exc)})
            yield send({"type": "done", "reason": "error"})
    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/literature/{problem_id}/{paper_id}/pin")
def lit_pin_ep(problem_id: str, paper_id: str) -> JSONResponse:
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem_id"}, status_code=400)
    # Find paper in per-question index or system index
    papers = lit_load(REPO_ROOT, problem_id) + lit_load(REPO_ROOT, _SYSTEM_LIT_QID)
    paper = next((p for p in papers if p.get("id") == paper_id), None)
    if not paper:
        # Try global library
        paper = next((p for p in lit_list_global(REPO_ROOT) if p.get("id") == paper_id), None)
    if not paper:
        return JSONResponse({"error": "paper not found"}, status_code=404)

    def _do_pin():
        pin_paper_to_prefix(REPO_ROOT, problem_id, paper)

    threading.Thread(target=_do_pin, daemon=True).start()
    return JSONResponse({"status": "pinning", "paper_id": paper_id, "problem_id": problem_id})


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


@app.get("/api/concepts/{problem_id}/pdf")
def concepts_pdf_ep(problem_id: str, force: bool = False) -> JSONResponse:
    """Compile the question's concepts to a PDF (rendered inline in the Concepts tab)."""
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid id"}, status_code=400)
    from .concepts_pdf import compile_concepts_pdf
    concepts = load_concepts(REPO_ROOT, problem_id)
    title = _Q_TITLES.get(problem_id, problem_id)
    result = compile_concepts_pdf(REPO_ROOT, problem_id, title, concepts, force=force)
    status = 200 if result.get("ok") else 422
    return JSONResponse(result, status_code=status)


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


# ── Insights endpoints ────────────────────────────────────────────────────────

@app.get("/api/insights/system")
def insights_system() -> JSONResponse:
    data = get_system_insight(REPO_ROOT)
    if not data:
        return JSONResponse({"summary": None}, status_code=404)
    return JSONResponse(data)


@app.get("/api/export/problems-pdf")
def export_problems_pdf(
    datasets: str = Query(None),       # comma-separated slugs; default = all
    max_per_dataset: int = Query(0),   # 0 = no cap
    offset: int = Query(0),
):
    """Compact PDF of all problems across datasets, tagged with dataset/id keys.

    Cached + built in the background: returns the PDF when ready, or a 202
    ``{"building": true}`` while a large export is still compiling. Poll the
    same URL until it returns the PDF.
    """
    from fastapi.responses import FileResponse
    from .problem_export import get_or_build_catalogue
    slugs = [s.strip() for s in datasets.split(",") if s.strip()] if datasets else None
    try:
        state, path = get_or_build_catalogue(slugs, max_per_dataset, offset)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if state == "ready":
        return FileResponse(str(path), media_type="application/pdf",
                            filename="rma_problems_catalogue.pdf")
    return JSONResponse({"building": True,
                         "message": "Export is compiling in the background; poll this URL again shortly."},
                        status_code=202)


@app.get("/api/export/eval-instructions-pdf")
def export_eval_instructions_pdf():
    """PDF instructing the model how to score solvability and what JSON to return."""
    from fastapi.responses import Response
    from .problem_export import build_eval_instructions_pdf
    try:
        pdf = build_eval_instructions_pdf()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=rma_eval_instructions.pdf"})


@app.post("/api/export/ingest-evaluations")
def export_ingest_evaluations(payload=Body(...)):
    """Ingest the model's solvability JSON into each dataset's solvability cache."""
    from .problem_export import ingest_evaluations
    try:
        result = ingest_evaluations(payload)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse(result)


# ── Smoke-test end-to-end solve (async job; survives proxy/tunnel timeouts) ─────
# Job state lives as a small JSON file in a temp dir (outside the repo so it never
# trips the dev reloader, and shared across workers) — holds only the final answer
# + evaluation, never reasoning/tool steps, and is deleted on fetch (NDA).
import tempfile as _tempfile
_SMOKE_JOB_DIR = Path(_tempfile.gettempdir()) / "rma_solve_jobs"


def _smoke_auth_ok(x_api_key: str | None) -> bool:
    required = os.environ.get("RMA_SMOKE_KEY")
    return not required or x_api_key == required


def _smoke_job_path(job_id: str) -> Path:
    return _SMOKE_JOB_DIR / f"{re.sub(r'[^a-zA-Z0-9]', '', job_id)}.json"


def _load_env_local() -> None:
    """Load <repo>/.env.local (KEY=VALUE lines) into the environment if present, so
    secrets like ANTHROPIC_API_KEY can be dropped in without restarting the server.
    Never overrides a value already set in the real environment."""
    p = REPO_ROOT / ".env.local"
    if not p.is_file():
        return
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


@app.post("/api/solve")
def smoke_solve(payload: dict = Body(...), x_api_key: str = Header(None)) -> JSONResponse:
    """End-to-end solve + evaluation for external use (smoke test).

    A solve takes minutes, longer than most proxies/tunnels hold a connection, so
    this is an async job by default:

        POST {"id","problem","rounds"(=1),"max_wall_seconds"}
          -> {"id","job_id","status":"running","poll":"/api/solve/<job_id>"}
        GET  /api/solve/<job_id>
          -> {"status":"running"}  ... then once finished (one-shot fetch):
             {"id","status":"done","answer":"<proof>",
              "evaluation":{"verdict","score","issues","summary"},"rounds_run"}

    RMA runs its full agentic loop per call — solve -> LLM evaluation, and (when
    rounds>1 and not yet APPROVED) feeds the evaluation back and refines, i.e.
    push-forward for several rounds. Pass {"wait": true} to block and get the
    result in the POST response instead (only for direct callers that can hold a
    long connection — not through the tunnel).

    Ephemeral: throwaway temp workspace, no stored context, nothing persisted to
    disk; results live in memory only and are dropped on fetch (per NDA). Set
    RMA_SMOKE_KEY to require the X-API-Key header.
    """
    from .smoke_pipeline import solve_and_evaluate

    _load_env_local()   # pick up ANTHROPIC_API_KEY from .env.local without a restart
    if not _smoke_auth_ok(x_api_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    pid = str(payload.get("id") or "").strip()
    problem = (payload.get("problem") or "").strip()
    if not problem:
        return JSONResponse({"id": pid, "answer": "", "error": "missing 'problem' text"}, status_code=400)

    try:
        rounds = int(payload.get("rounds") or 1)
    except (TypeError, ValueError):
        rounds = 1
    try:
        max_wall = int(payload.get("max_wall_seconds") or 900)
    except (TypeError, ValueError):
        max_wall = 900

    # Synchronous mode for direct callers that can hold the connection.
    if payload.get("wait"):
        try:
            result = solve_and_evaluate(REPO_ROOT, problem, rounds=rounds, max_wall=max_wall)
            return JSONResponse({"id": pid, "status": "done", **result})
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"id": pid, "answer": "", "error": str(e)})

    # Async job (default): return immediately, caller polls GET /api/solve/<job_id>.
    job_id = uuid.uuid4().hex[:12]
    _SMOKE_JOB_DIR.mkdir(parents=True, exist_ok=True)
    path = _smoke_job_path(job_id)
    path.write_text(json.dumps({"id": pid, "status": "running"}), encoding="utf-8")

    def _work():
        try:
            res = solve_and_evaluate(REPO_ROOT, problem, rounds=rounds, max_wall=max_wall)
            data = {"id": pid, "status": "done", **res}
        except Exception as e:  # noqa: BLE001
            data = {"id": pid, "status": "error", "answer": "", "error": str(e)}
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(path)   # atomic write so a poll never reads a half-written file
        except Exception:
            pass

    threading.Thread(target=_work, daemon=True).start()
    return JSONResponse({"id": pid, "job_id": job_id, "status": "running",
                         "poll": f"/api/solve/{job_id}"})


@app.get("/api/solve/{job_id}")
def smoke_solve_status(job_id: str, x_api_key: str = Header(None)) -> JSONResponse:
    """Poll an async solve job. Returns {status:"running"} until done, then the
    result once (the job file is deleted on terminal fetch — NDA)."""
    if not _smoke_auth_ok(x_api_key):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    path = _smoke_job_path(job_id)
    if not path.is_file():
        return JSONResponse({"error": "unknown or already-fetched job_id"}, status_code=404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"job_id": job_id, "status": "running"})  # mid-write
    if data.get("status") == "running":
        return JSONResponse({"job_id": job_id, "id": data.get("id"), "status": "running"})
    try:
        path.unlink()   # one-shot retrieval; nothing retained on disk
    except OSError:
        pass
    return JSONResponse({"job_id": job_id, **data})


@app.get("/api/design/pdf")
def design_pdf():
    """Serve the ACL-format RMA supplementary PDF."""
    from fastapi.responses import Response
    pdf_path = REPO_ROOT.parent / "rma_supplementary.pdf"
    if not pdf_path.is_file():
        return JSONResponse({"error": "supplementary PDF not found"}, status_code=404)
    return Response(
        content=pdf_path.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=rma_supplementary.pdf"},
    )


@app.get("/api/design/priority-report")
def design_priority_report():
    """Build and serve the solvability×value priority report PDF for the Design tab."""
    from fastapi.responses import Response
    from .problem_export import build_priority_report_pdf
    try:
        pdf = build_priority_report_pdf()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=rma_priority_report.pdf"},
    )


@app.post("/api/docs/regenerate-all")
def docs_regenerate_all() -> JSONResponse:
    """Regenerate all per-question .tex documents from JSONL log."""
    from .rich_documents import seed_all_question_documents
    import threading
    threading.Thread(
        target=seed_all_question_documents, args=(REPO_ROOT,), daemon=True
    ).start()
    return JSONResponse({"started": True})


@app.post("/api/insights/system/regenerate")
def insights_system_regenerate() -> JSONResponse:
    from .insight_agents import generate_system_insight
    data = generate_system_insight(REPO_ROOT)
    return JSONResponse(data)


@app.post("/api/insights/dataset/{slug}/regenerate")
def insights_dataset_regenerate(slug: str) -> JSONResponse:
    from .insight_agents import generate_dataset_insight
    data = generate_dataset_insight(REPO_ROOT, slug)
    return JSONResponse(data)


@app.post("/api/insights/question/{dataset}/{qid}/regenerate")
def insights_question_regenerate(dataset: str, qid: str) -> JSONResponse:
    from .insight_agents import generate_question_insight
    data = generate_question_insight(REPO_ROOT, qid, dataset)
    return JSONResponse(data)


@app.get("/api/insights/dataset/{slug}")
def insights_dataset(slug: str) -> JSONResponse:
    data = get_dataset_insight(REPO_ROOT, slug)
    if not data:
        return JSONResponse({"summary": None}, status_code=404)
    return JSONResponse(data)


@app.get("/api/insights/question/{dataset}/{qid}")
def insights_question(dataset: str, qid: str) -> JSONResponse:
    data = get_question_insight(REPO_ROOT, qid, dataset)
    if not data:
        return JSONResponse({"summary": None}, status_code=404)
    return JSONResponse(data)


# ── Export ───────────────────────────────────────────────────────────────────

_WORKFLOW_INTROS = {
    "verify": (
        "Please **verify the proof** below step by step. Identify any logical gaps, "
        "incorrect lemma applications, or unsupported claims. For each issue found, "
        "describe it clearly and suggest a fix."
    ),
    "fix": (
        "Please **fix the open issues** listed below. For each issue, provide a concrete "
        "resolution — corrected LaTeX, a new lemma, or a revised argument — then output "
        "an updated clean proof incorporating all fixes."
    ),
    "improve": (
        "Please **try to improve the constant** in the proof below. The current best "
        "is c = 1/42 (Spielman). The conjectured tight bound is c = 1/2. Explore whether "
        "a sharper barrier-function argument or a different greedy selection rule can "
        "push the constant higher."
    ),
    "review": (
        "Please give a **general review and feedback** on the proof below. Assess: "
        "(1) overall strategy, (2) correctness of key steps, (3) clarity and completeness, "
        "(4) any promising directions to strengthen the result."
    ),
}

_RESPONSE_FORMAT = """\
=== TASK_VERDICT ===
<your overall assessment — 1-3 paragraphs>
=== END_TASK_VERDICT ===

=== TASK_FIX ===
<corrected LaTeX for any issues found, or "No fix needed.">
=== END_TASK_FIX ===

=== TASK_PROOF ===
<the full clean proof LaTeX (if you produced one), otherwise leave empty>
=== END_TASK_PROOF ===

=== TASK_NEW_ISSUES_JSON ===
[{"title":"...","body":"...","severity":"minor|major|critical"}, ...]
=== END_TASK_NEW_ISSUES_JSON ===
"""


@app.get("/api/export/{problem_id}")
def export_bundle(
    problem_id: str,
    include_problem: int = Query(1),
    include_issues: int = Query(1),
    include_proof: int = Query(1),
    include_docs: int = Query(0),
    workflow: str = Query("verify"),
    dataset: str = Query(None),
) -> JSONResponse:
    """Generate a self-contained markdown bundle to send to a collaborator."""
    if not _ID_RE_LOOSE.match(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    ds = _ds_from_query(dataset)

    lines: list[str] = []
    pid = problem_id

    # ── Header ────────────────────────────────────────────────────────────────
    title = _Q_TITLES.get(pid, pid)
    lines += [
        f"# Research Collaboration Bundle — {pid.upper()}: {title}",
        "*Send this entire document to Claude. Ask Claude to follow the WORKFLOW section.*",
        "",
        "---",
        "",
        "## 0. INSTRUCTIONS FOR YOUR FRIEND",
        "",
        "Hi! Please paste this full document into Claude and say:",
        "",
        '> "Please follow the WORKFLOW at the end of this document exactly, producing all requested deliverables."',
        "",
        "Enable extended thinking if you can (Claude Pro → Extended thinking toggle). "
        "Then copy **the complete Claude response** and send it back to me.",
        "",
        "---",
        "",
    ]

    # ── Problem statement ─────────────────────────────────────────────────────
    if include_problem:
        tex = ""
        tex_path = REPO_ROOT / "problems" / f"{pid}.tex"
        if tex_path.is_file():
            tex = _expand_tex_inputs(
                tex_path.read_text(encoding="utf-8", errors="replace"), REPO_ROOT
            )
        if not tex:
            try:
                p = ds_get_problem(ds, pid)
                if p:
                    tex = p.get("tex") or p.get("statement", "")
            except Exception:  # noqa: BLE001
                pass
        if tex:
            lines += [
                "## 1. PROBLEM STATEMENT",
                "",
                "```latex",
                tex.strip(),
                "```",
                "",
                "---",
                "",
            ]

    # ── Working proof ─────────────────────────────────────────────────────────
    if include_proof:
        from .issue_agents import get_working_proof as _gwp
        proof_tex = _gwp(REPO_ROOT, pid)
        if not proof_tex:
            try:
                best = get_best_proof(pid)
                if best:
                    proof_tex = best.get("solution_tex", "")
            except Exception:  # noqa: BLE001
                pass
        if proof_tex:
            lines += [
                "## 2. CURRENT WORKING PROOF",
                "",
                "```latex",
                proof_tex.strip(),
                "```",
                "",
                "---",
                "",
            ]

    # ── Open issues ───────────────────────────────────────────────────────────
    if include_issues:
        try:
            all_issues = list_issues(REPO_ROOT, pid, ds)
        except Exception:  # noqa: BLE001
            all_issues = []
        open_issues = [i for i in all_issues if i.get("status") in ("open", "in_progress")]
        if open_issues:
            lines += [
                "## 3. OPEN ISSUES",
                "",
                f"There are currently **{len(open_issues)}** open issue(s) for this problem:",
                "",
            ]
            for idx, iss in enumerate(open_issues, 1):
                sev = iss.get("severity", "")
                sev_str = f" [{sev.upper()}]" if sev else ""
                lines.append(f"### Issue {idx}: {iss.get('title','Untitled')}{sev_str}")
                lines.append("")
                body = iss.get("body", "").strip()
                if body:
                    lines.append(body)
                    lines.append("")
                # Latest agent comment (if any)
                comments = iss.get("comments", [])
                agent_comments = [c for c in comments if c.get("role") in ("agent", "assistant")]
                if agent_comments:
                    last = agent_comments[-1]
                    lines.append(f"**Latest analysis ({last.get('author','agent')}):**")
                    lines.append("")
                    lines.append(last.get("body", "").strip()[:800])
                    lines.append("")
            lines += ["---", ""]

    # ── Key documents ─────────────────────────────────────────────────────────
    if include_docs:
        qdir = REPO_ROOT / "documents" / "questions" / pid
        doc_names = ["overview.md", "strategies.md", "progress.md"]
        included_any = False
        for dname in doc_names:
            dp = qdir / dname
            if dp.is_file():
                try:
                    content = dp.read_text(encoding="utf-8", errors="replace")[:2000]
                    if not included_any:
                        lines += ["## 4. KEY DOCUMENTS", ""]
                        included_any = True
                    lines += [
                        f"### {dname}",
                        "",
                        content.strip(),
                        "",
                    ]
                except Exception:  # noqa: BLE001
                    pass
        if included_any:
            lines += ["---", ""]

    # ── Workflow instructions ─────────────────────────────────────────────────
    wf_key = workflow if workflow in _WORKFLOW_INTROS else "verify"
    wf_text = _WORKFLOW_INTROS[wf_key]
    sec_num = 5 if include_docs else (4 if (include_proof or include_issues) else 2)
    lines += [
        f"## {sec_num}. WORKFLOW",
        "",
        wf_text,
        "",
        "Please produce **all four** structured output blocks:",
        "",
        "```",
        _RESPONSE_FORMAT.strip(),
        "```",
        "",
        "---",
        "",
        f"*Bundle generated {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} "
        f"for problem {pid} ({ds}).*",
    ]

    markdown = "\n".join(lines)
    return JSONResponse({
        "problem_id": pid,
        "title": title,
        "markdown": markdown,
        "char_count": len(markdown),
    })


# ── /rmac/solve/ aliases — same SPA, works through the proxy ─────────────────
from fastapi.responses import RedirectResponse as _Redir

@app.get("/rmac/solve")
def rmac_solve_root() -> _Redir:
    return _Redir("/rmac/solve/", status_code=302)

def _index_html() -> HTMLResponse:
    """Serve the SPA, injecting the agent key so same-origin EventSource calls can
    authenticate (they can't set headers). Anonymous callers get no key."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    if _AGENT_KEY:
        html = html.replace(
            "<head>",
            f"<head>\n<script>window.RMA_AGENT_KEY={json.dumps(_AGENT_KEY)};</script>",
            1,
        )
    return HTMLResponse(html)


if STATIC_DIR.is_dir():
    @app.get("/rmac/solve/")
    def rmac_solve_index() -> HTMLResponse:
        return _index_html()


# ── /rmac/filter/ — filter sub-application (read-only, 14k dataset) ──────────
# Mounted as a FastAPI sub-app so it runs in-process but with its own routes.
# This means: if the filter app's request handling fails, only that request
# gets a 500 — the solve app continues. Heavy solve operations (agents, PDF
# compilation, background threads) live only in the solve app and cannot be
# triggered from the filter sub-app.
try:
    from webapp_filter.server import app as _filter_app
    app.mount("/rmac/filter", _filter_app)
except Exception as _e:
    import logging as _logging
    _logging.getLogger(__name__).warning("filter sub-app not available: %s", _e)


# Serve the SPA. Mounted last so /api/* routes take precedence.
if STATIC_DIR.is_dir():
    @app.get("/")
    def index() -> HTMLResponse:
        return _index_html()

    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.ico", headers={"Cache-Control": "public, max-age=86400"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
