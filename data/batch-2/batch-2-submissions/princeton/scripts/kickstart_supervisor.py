"""Kickstart a child supervisor from an EXISTING completed parent run.

Use case: a parent run finished (DONE/FAILED) before the automated Mode A
machinery was in place, but it left a self-contained conjecture in its
notebook. This script does the same thing the Orchestrator's
_spawn_child_supervisor would have done:

  1. Pulls the conjecture from the parent's run.db.
  2. Runs the self-containment LLM pass.
  3. Writes the child problem file + supervisor manifest into the parent's
     run directory.
  4. Launches math_solver.supervisor as a detached subprocess.

Usage:
  python -m scripts.kickstart_supervisor \\
      --parent-run-id 63aa9904e368 \\
      --parent-problem-file problems/nelson_q2.txt \\
      --total-budget 48 \\
      --child-w 4 --child-d 4 \\
      --successor-w 4 --successor-d 4 \\
      --conjecture-index 0
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from math_solver.config import RUNS_DIR
from math_solver.gemini import call_gemini
from math_solver.state import RunStore


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parent-run-id", required=True)
    p.add_argument("--parent-problem-file", required=True, type=Path)
    p.add_argument("--total-budget", required=True, type=int,
                   help="Total W*D budget for the child + successor chain.")
    p.add_argument("--child-w", type=int, default=4)
    p.add_argument("--child-d", type=int, default=4)
    p.add_argument("--successor-w", type=int, default=4)
    p.add_argument("--successor-d", type=int, default=4)
    p.add_argument("--conjecture-index", type=int, default=0,
                   help="Index into parent's conjectures list (0 = first).")
    args = p.parse_args()

    # ── 1. Pull the conjecture from the parent's run.db ────────────────────
    parent_run_dir = RUNS_DIR / args.parent_run_id
    db_path = parent_run_dir / "run.db"
    if not db_path.exists():
        print(f"[error] Parent run.db not found: {db_path}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT value FROM state WHERE key='run_state'").fetchone()
    if not row:
        print(f"[error] No run_state in {db_path}", file=sys.stderr)
        return 1
    state = json.loads(row[0])
    conjectures = (state.get("root_notebook") or {}).get("conjectures", [])
    if not conjectures:
        print(f"[error] No conjectures in parent's notebook.", file=sys.stderr)
        return 1
    if args.conjecture_index >= len(conjectures):
        print(f"[error] --conjecture-index {args.conjecture_index} out of range "
              f"(parent has {len(conjectures)} conjecture(s)).", file=sys.stderr)
        return 1
    conjecture = conjectures[args.conjecture_index]
    conj_id = conjecture.get("id") or f"C{args.conjecture_index+1}"
    print(f"[kickstart] Pulled conjecture {conj_id} from parent {args.parent_run_id}.")

    # Also grab the most-recent extractor raw output for context
    ext_row = conn.execute(
        "SELECT output FROM agent_calls WHERE agent='conjecture_extractor' "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    extractor_raw = ext_row[0] if ext_row else ""
    conn.close()

    # ── 2. Self-containment rewrite via LLM ─────────────────────────────────
    print(f"[kickstart] Running self-containment LLM pass...")
    rewrite_prompt = (
        "You will rewrite a mathematical conjecture so that it is fully "
        "self-contained — readable as a standalone problem by someone who "
        "has not seen any parent context.\n\n"
        "Rules:\n"
        "1. Inline every variable, set, function, and notation used. Do not "
        "refer to 'the proof above', 'the problem', or any external object.\n"
        "2. If the conjecture relies on standard objects (local fields, "
        "groups, representations, etc.), state their definitions inline at "
        "the top of the problem.\n"
        "3. Preserve the mathematical content exactly — no weakening, no "
        "strengthening, no paraphrasing of the claim.\n"
        "4. End with a clear ask: 'Prove the following:' followed by the "
        "self-contained statement.\n\n"
        f"Original conjecture statement:\n{conjecture['statement']}\n\n"
        f"Original conjecture negation (for context, do not include in "
        f"output):\n{conjecture['negation']}\n\n"
        f"For additional context, here is the surrounding extractor output "
        f"showing how the conjecture was used in the parent proof "
        f"(use only to resolve any ambiguous notation — do not embed):\n"
        f"{extractor_raw[:4000]}\n\n"
        "Output ONLY the rewritten self-contained problem statement. "
        "No preamble, no commentary."
    )
    store = RunStore(args.parent_run_id)
    rewrite_call = await call_gemini(
        rewrite_prompt,
        run_id=args.parent_run_id,
        notebook_id="ROOT",
        agent="conjecture_self_containment_kickstart",
        inputs={"source_conjecture_id": conj_id},
        store=store,
    )
    child_problem_text = rewrite_call.output.strip()
    print(f"[kickstart] Self-containment done ({len(child_problem_text)} chars).")

    # ── 3. Write child problem + manifest ──────────────────────────────────
    child_problem_file = parent_run_dir / f"child_{conj_id}_problem.txt"
    child_problem_file.write_text(child_problem_text, encoding="utf-8")
    print(f"[kickstart] Wrote {child_problem_file}")

    # Remaining budget = total budget (we're treating this as a fresh start
    # for the child + successor; parent A's prior cost is sunk and not counted)
    remaining_budget = args.total_budget
    manifest = {
        "parent_run_id": args.parent_run_id,
        "parent_problem_file": str(args.parent_problem_file.resolve()),
        "child_problem_file": str(child_problem_file.resolve()),
        "child_w": args.child_w,
        "child_d": args.child_d,
        "successor_w": args.successor_w,
        "successor_d": args.successor_d,
        "remaining_budget": remaining_budget,
        "stage_when_paused": -1,   # synthetic kickstart
        "conjecture_id": conj_id,
        "kickstart": True,
    }
    manifest_file = parent_run_dir / "supervisor_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[kickstart] Wrote {manifest_file}")

    # ── 4. Launch supervisor (detached) ────────────────────────────────────
    supervisor_log = parent_run_dir / "supervisor.log"
    cmd = [
        sys.executable, "-m", "math_solver.supervisor",
        "--manifest", str(manifest_file.resolve()),
    ]
    log_fh = open(supervisor_log, "w")
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(REPO_ROOT),
    )
    print(
        f"\n[kickstart] Supervisor launched (PID {proc.pid}).\n"
        f"  Manifest:        {manifest_file}\n"
        f"  Child problem:   {child_problem_file}\n"
        f"  Supervisor log:  {supervisor_log}\n"
        f"  Remaining budget: {remaining_budget}\n"
        f"  Child W×D = {args.child_w}×{args.child_d} = {args.child_w*args.child_d}\n"
        f"  Successor W×D = {args.successor_w}×{args.successor_d} = "
        f"{args.successor_w*args.successor_d}\n"
        f"\nMonitor with:  tail -f {supervisor_log}"
    )
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
