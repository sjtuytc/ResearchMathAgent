#!/usr/bin/env python3
"""Initialize every solve-system tab for every problem across all curated datasets.

For each (dataset, problem) it runs, in order:
  1. Best proof  — full agentic solve (run_agent_vertex) -> outputs/<ds>/init_all_opus/<pid>/solution.tex
  2. Issues      — discovery (critic) + resolve up to N (solver)   [run_issue_cycle]
  3. Meeting     — field personas, multi-round discussion + synthesis + notes
  4. Documents   — refresh the per-problem rich documents
Then consolidate_best per dataset so the Proofs tab shows the winners.

Everything uses Vertex AI (claude-opus-4-8) on the GLOBAL endpoint — the regional
quota for this NAIRR project is dead, so GOOGLE_CLOUD_REGION=global is forced.
Resilient (per-step try/except), resumable (skips a step whose output exists),
and meant to run detached for a long time, spending Vertex credits steadily.

Usage:
  GOOGLE_CLOUD_REGION=global python3 scripts/init_all_tabs.py [--datasets ...] [--limit N] [--no-solve]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import uuid
from pathlib import Path

# Force the working Vertex endpoint before anything imports the SDK.
os.environ.setdefault("GOOGLE_CLOUD_REGION", "global")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "nairr-260096-569948")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("init_all_tabs")

GCP_PROJECT = "nairr-260096-569948"
EXP_NAME = "init_all_opus"
MEETING_ROUNDS = 2
MAX_RESOLVE = 2
SOLVE_WALL_SECONDS = 1800  # cap a single proof attempt at 30 min

# Curated solve-system datasets: benchmarks + the 11 RM14k subdomains.
RM14K_SUBDOMAINS = [
    "tcs_rm14k", "discretemath_rm14k", "mathphysics_rm14k", "probstat_rm14k",
    "analysis_rm14k", "numbertheory_rm14k", "geomtopology_rm14k", "algebra_rm14k",
    "appliedmath_rm14k", "logic_rm14k", "crossdisc_rm14k",
]
DEFAULT_DATASETS = ["first_proof_1", "first_proof_2", *RM14K_SUBDOMAINS]


def dataset_problem_ids(dataset: str) -> list[str]:
    if dataset == "first_proof_1":
        return [f"q{i}" for i in range(1, 11)]
    if dataset == "first_proof_2":
        return [f"prob-{i:02d}" for i in range(1, 11)]
    # RM14k subdomains / any store-backed dataset: read the index file
    import json
    idx = REPO_ROOT / "data" / "datasets" / dataset / "_index.json"
    if idx.is_file():
        try:
            return [p["id"] for p in json.loads(idx.read_text(encoding="utf-8"))]
        except Exception:
            return []
    return []


# ── step 1: best proof ────────────────────────────────────────────────────────

def solve_proof(dataset: str, pid: str) -> str:
    from webapp.agent import AgentConfig, run_agent_vertex, DEFAULT_MODEL
    from webapp.dataset_store import find_problem_tex

    out_dir = REPO_ROOT / "outputs" / dataset / EXP_NAME / pid
    sol_path = out_dir / "solution.tex"
    if sol_path.is_file() and sol_path.stat().st_size > 200:
        return "skip"

    problem_text = find_problem_tex(REPO_ROOT, pid, dataset)
    if not problem_text.strip():
        log.warning("  [proof] %s/%s: no problem text", dataset, pid)
        return "failed"

    out_dir.mkdir(parents=True, exist_ok=True)
    ws = REPO_ROOT / "webapp" / ".runs" / f"init_{pid}_{int(time.time())}"
    cfg = AgentConfig(
        problem_id=pid, problem_text=problem_text, model=DEFAULT_MODEL,
        repo_root=REPO_ROOT, workspace=ws, thinking=True, provider="vertex",
        gcp_project=GCP_PROJECT, max_wall_seconds=SOLVE_WALL_SECONDS,
    )
    artifact = None
    parts: list[str] = []
    try:
        for ev in run_agent_vertex(cfg, None):
            if ev.type == "text_delta":
                parts.append(ev.data.get("text", ""))
            elif ev.type == "artifact":
                artifact = ev.data
            elif ev.type == "error":
                log.warning("  [proof] %s/%s: %s", dataset, pid, str(ev.data)[:120])
    except Exception as exc:
        log.warning("  [proof] %s/%s crashed: %s", dataset, pid, exc)

    sol = ""
    if artifact and artifact.get("latex"):
        sol = artifact["latex"]
    elif (ws / "solution.tex").is_file():
        sol = (ws / "solution.tex").read_text(encoding="utf-8", errors="replace")
    if sol.strip():
        sol_path.write_text(sol, encoding="utf-8")
        log.info("  [proof] %s/%s: saved %d chars", dataset, pid, len(sol))
        return "ok"
    if parts:
        out_dir.joinpath("transcript.md").write_text("".join(parts), encoding="utf-8")
    return "failed"


# ── step 2: issues ────────────────────────────────────────────────────────────

def run_issues(dataset: str, pid: str) -> str:
    from webapp.issue_agents import run_issue_cycle
    from webapp.issues import list_issues
    existing = list_issues(REPO_ROOT, pid, dataset)
    if len([i for i in existing if i.get("status") in ("open", "in_progress", "resolved")]) >= 3:
        return "skip"
    try:
        run_issue_cycle(REPO_ROOT, pid, max_resolve=MAX_RESOLVE, dataset=dataset)
        return "ok"
    except Exception as exc:
        log.warning("  [issues] %s/%s: %s", dataset, pid, exc)
        return "failed"


# ── step 3: meeting ───────────────────────────────────────────────────────────

def run_meeting(dataset: str, pid: str) -> str:
    from webapp.meet import create_room, get_personas_for_problem, list_rooms
    from webapp.meet_agents import run_round_offline, run_synthesis
    from webapp.meet_pdf import room_is_substantive
    from webapp.push_forward import _save_meeting_notes
    from webapp.meet import get_room, delete_room

    if any(room_is_substantive(r) for r in list_rooms(REPO_ROOT, pid)):
        return "skip"
    personas = get_personas_for_problem(pid)
    if not personas:
        return "failed"
    parts = ["coordinator"] + [p["id"] for p in personas[:3]]
    try:
        room = create_room(
            REPO_ROOT, pid,
            topic=f"Init {pid} — proof review",
            goal=f"Review the proof and issues for {pid}; agree on the key remaining gaps and an action plan.",
            participants=parts,
        )
        rid = room["id"]
        run_round_offline(REPO_ROOT, pid, rid, f"init-{pid}-meet", n_rounds=MEETING_ROUNDS)
        for _ in run_synthesis(REPO_ROOT, pid, rid):
            pass
        _save_meeting_notes(REPO_ROOT, pid, rid)
        if not room_is_substantive(get_room(REPO_ROOT, pid, rid)):
            delete_room(REPO_ROOT, pid, rid)
            return "failed"
        return "ok"
    except Exception as exc:
        log.warning("  [meet] %s/%s: %s", dataset, pid, exc)
        return "failed"


# ── step 4: documents ─────────────────────────────────────────────────────────

def run_docs(dataset: str, pid: str) -> str:
    try:
        from webapp.rich_documents import update_question_document
        update_question_document(REPO_ROOT, pid)
        return "ok"
    except Exception as exc:
        log.warning("  [docs] %s/%s: %s", dataset, pid, exc)
        return "failed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="*", default=DEFAULT_DATASETS)
    ap.add_argument("--limit", type=int, default=0, help="max problems per dataset (0=all)")
    ap.add_argument("--no-solve", action="store_true", help="skip the (expensive) proof step")
    args = ap.parse_args()

    log.info("region=%s project=%s datasets=%s",
             os.environ.get("GOOGLE_CLOUD_REGION"), GCP_PROJECT, args.datasets)

    grand = {"proof": 0, "issues": 0, "meeting": 0, "docs": 0}
    for dataset in args.datasets:
        pids = dataset_problem_ids(dataset)
        if args.limit:
            pids = pids[: args.limit]
        log.info("=" * 70)
        log.info("DATASET %s — %d problems", dataset, len(pids))
        for i, pid in enumerate(pids, 1):
            log.info("-" * 60)
            log.info("[%s %d/%d] %s", dataset, i, len(pids), pid)
            if not args.no_solve:
                r = solve_proof(dataset, pid); grand["proof"] += (r == "ok")
                log.info("  proof:%s", r)
            r = run_issues(dataset, pid); grand["issues"] += (r == "ok"); log.info("  issues:%s", r)
            r = run_meeting(dataset, pid); grand["meeting"] += (r == "ok"); log.info("  meeting:%s", r)
            r = run_docs(dataset, pid); grand["docs"] += (r == "ok"); log.info("  docs:%s", r)
        # consolidate best proofs for this dataset so the Proofs tab updates
        try:
            from webapp.proofs import consolidate_best
            res = consolidate_best(dataset, compile_pdfs=True)
            log.info("DATASET %s consolidated %d best proofs", dataset, len(res))
        except Exception as exc:
            log.warning("consolidate_best(%s) failed: %s", dataset, exc)

    log.info("=" * 70)
    log.info("DONE — new this run: proofs=%(proof)d issues=%(issues)d meetings=%(meeting)d docs=%(docs)d", grand)


if __name__ == "__main__":
    main()
