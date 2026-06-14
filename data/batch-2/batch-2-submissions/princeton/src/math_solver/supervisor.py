"""Child-supervisor coordinator.

Spawned (detached) by an Orchestrator when the Conjecture Extractor yields
exactly one conjecture mid-run AND the lineage has budget for child + successor.

Responsibilities:
  1. Launch a child pipeline run on the self-contained conjecture
     (W=child_w, D=child_d, --no-child-spawn).  Children NEVER spawn
     grandchildren — that is the only depth restriction.
  2. Block on the child subprocess until it completes.
  3. Extract the child's best output(s):
       - highest BS-clean solver score,
       - highest grader score overall,
       - child's final notebook content.
     Concatenate into a single labelled seed file.
  4. Launch a successor parent run on the original parent problem,
     seeded with the original parent (--seed-run) AND the concatenated
     seed file (--seed-notebook-file).  The successor IS the parent
     continuing — it inherits the remaining budget and is allowed to
     spawn another child of its own if it again gets stuck on a single
     conjecture and the budget permits.  This is how the parent lineage
     (A → S1 → S2 → …) can issue many sequential child runs over its
     lifetime while the "no grandchildren" invariant still holds.

This script is intentionally standalone: it does not import the Orchestrator.
It reads everything it needs from the manifest written by the parent and
queries the child's run.db directly for results.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# Repo + runs paths (RUNS_DIR honors the same env override the rest of the package uses)
REPO_ROOT = Path(__file__).resolve().parents[2]
from .config import RUNS_DIR  # noqa: E402


def log(msg: str) -> None:
    """Emit a timestamped line to the supervisor's redirected stdout."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[supervisor {ts}] {msg}", flush=True)


def launch_run(
    *,
    problem_file: Path,
    width: int,
    depth: int,
    total_budget: int,
    allow_child_spawn: bool,
    seed_run: str | None = None,
    seed_notebook_file: Path | None = None,
    lineage_parent_id: str,
    lineage_role: str,
    label: str,
    extra_args: list[str] | None = None,
) -> str:
    """Launch a math_solver run, block until it exits, return its run_id.

    We capture the new run's run_id from the subprocess's stdout. The
    subprocess's full output is also tee'd to a log file under RUNS_DIR.

    `allow_child_spawn` should be False for child runs (no grandchildren)
    and True for successor parent runs (they are the parent continuing,
    and may themselves spawn further children if budget permits).
    """
    spawn_flag = "--allow-child-spawn" if allow_child_spawn else "--no-child-spawn"
    cmd = [
        sys.executable, "-m", "math_solver.main", "run",
        str(problem_file),
        "--width", str(width),
        "--depth", str(depth),
        "--no-search",
        spawn_flag,
        "--total-budget", str(total_budget),
        "--lineage-parent-id", lineage_parent_id,
        "--lineage-role", lineage_role,
        "--label", label,
    ]
    if seed_run:
        cmd += ["--seed-run", seed_run]
    if seed_notebook_file:
        cmd += ["--seed-notebook-file", str(seed_notebook_file.resolve())]
    if extra_args:
        cmd += extra_args

    log(f"Launching: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(REPO_ROOT),
        text=True,
        bufsize=1,
    )

    # Stream subprocess output to our log, capturing run_id as we go
    run_id: str | None = None
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        # Capture the "New run: <id>" line
        if run_id is None and line.startswith("New run:"):
            run_id = line.split(":", 1)[1].strip()
    proc.wait()

    if run_id is None:
        raise RuntimeError("Failed to capture run_id from subprocess output.")
    log(f"Run {run_id} exited with code {proc.returncode}")
    return run_id


def _detect_child_direction(child_problem_text: str) -> str:
    """Heuristic: was the child tasked with the conjecture's statement form
    or its negation? Return 'statement' | 'negation' | 'unknown'."""
    head = child_problem_text[:4000].lower()
    if "construct a counterexample" in head or "construct counterexample" in head:
        return "negation"
    if "disprove" in head and "prove the following" not in head:
        return "negation"
    if "prove the following" in head or "prove that" in head:
        return "statement"
    return "unknown"


def _derive_conjecture_verdict(direction: str, verdict_on_problem: str) -> str:
    """Map (what the child was tasked with, what the proof actually showed)
    to the verdict on the CONJECTURE itself.

    direction          verdict_on_problem    → conjecture verdict
    statement          PROVED                → PROVED
    statement          DISPROVED             → DISPROVED
    negation           PROVED                → DISPROVED
    negation           DISPROVED             → PROVED
    anything           UNCLEAR               → UNCLEAR
    unknown direction  anything              → UNCLEAR (can't safely map)
    """
    if verdict_on_problem == "UNCLEAR" or direction == "unknown":
        return "UNCLEAR"
    if direction == "statement":
        return verdict_on_problem
    # direction == "negation"
    return "DISPROVED" if verdict_on_problem == "PROVED" else "PROVED"


def extract_child_best_output(child_run_id: str) -> str:
    """Query the child's run.db for best outputs and assemble a seed bundle.

    Sections:
      - Best BS-clean proof (highest grader score among solutions with a
        BS-aggregator verdict of 'no surviving gaps').
      - Best grader-scored proof (highest score regardless of BS verdict).
      - Final notebook content (from root NotebookState).
    """
    import sqlite3
    import re

    db_path = RUNS_DIR / child_run_id / "run.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Child run.db not found at {db_path}")
    conn = sqlite3.connect(str(db_path))

    # Load run state (Pydantic-serialized JSON in the state table)
    state_row = conn.execute(
        "SELECT value FROM state WHERE key='run_state'"
    ).fetchone()
    if not state_row:
        raise RuntimeError(f"No run_state found in {db_path}")
    state = json.loads(state_row[0])
    all_solutions = state.get("all_solutions", [])
    nb_content = (state.get("root_notebook") or {}).get("content", "")

    # Map (stage, solver_index) -> BS aggregator output
    bs_rows = conn.execute(
        "SELECT agent, inputs, output FROM agent_calls "
        "WHERE agent LIKE 'bs_detector_%_agg'"
    ).fetchall()
    bs_by_solver: dict[tuple[int, int], str] = {}
    for agent, inputs_json, output in bs_rows:
        try:
            inputs = json.loads(inputs_json)
        except Exception:
            continue
        si = inputs.get("solver_index")
        # bs aggregator inputs don't always record stage; infer from agent name
        # is enough for "clean" detection on the latest stage; conservative:
        # we treat the LAST BS aggregator for each solver as authoritative.
        if si is not None:
            bs_by_solver[(0, si)] = output  # stage=0 placeholder; we take the last write

    def is_bs_clean(text: str) -> bool:
        return bool(re.search(r"no surviving gaps", text or "", re.IGNORECASE))

    # Best grader-scored solution
    if all_solutions:
        best_grader = max(all_solutions, key=lambda s: (s.get("score", 0), s.get("stage", 0)))
    else:
        best_grader = None

    # Best BS-clean solution
    best_bs_clean = None
    for s in sorted(all_solutions, key=lambda s: (-s.get("score", 0), -s.get("stage", 0))):
        bs_out = bs_by_solver.get((0, s.get("solver_index")))
        if bs_out and is_bs_clean(bs_out):
            best_bs_clean = s
            break

    # Build the seed bundle
    parts: list[str] = []
    parts.append(f"# Child run results — {child_run_id}\n")
    parts.append(
        f"(Child run completed at supervisor handoff. The sections below are "
        f"the supervisor's best-output extraction from the child's run.db, "
        f"intended as additional material for the successor parent run.)\n"
    )

    if best_bs_clean:
        parts.append(
            f"\n## Best BS-clean proof "
            f"(stage {best_bs_clean['stage']}, solver {best_bs_clean['solver_index']}, "
            f"score {best_bs_clean['score']})\n\n"
            f"{best_bs_clean['output']}\n"
        )
    else:
        parts.append(
            "\n## Best BS-clean proof\n\n"
            "(none — no solution in the child run passed the BS gate cleanly)\n"
        )

    if best_grader and best_grader is not best_bs_clean:
        parts.append(
            f"\n## Best grader-scored proof "
            f"(stage {best_grader['stage']}, solver {best_grader['solver_index']}, "
            f"score {best_grader['score']})\n\n"
            f"{best_grader['output']}\n"
        )

    if nb_content:
        parts.append(f"\n## Child's final notebook\n\n{nb_content}\n")

    conn.close()
    return "\n".join(parts)


async def compose_resolution_header(
    *,
    conjecture_id: str,
    child_problem_text: str,
    child_run_id: str,
    conjecture_target: str | None = None,
) -> str:
    """Build the 'Resolved Conjecture from Child Sub-run' header block.

    Reads the child's run.db to find the best (highest-scored) proof,
    fires the Flash verdict classifier on its tail, and combines with
    the tasked direction (inferred from child_problem_text) to derive
    the verdict on the conjecture itself.

    Returns the formatted markdown block when verdict is PROVED or
    DISPROVED. Returns empty string when verdict is UNCLEAR — the
    conjecture remains OPEN in the parent's notebook (no header
    prepended; the seed bundle's normal proof+notebook sections carry
    forward partial work as before).
    """
    import sqlite3
    from .gemini import flash_classify_proof_verdict

    db_path = RUNS_DIR / child_run_id / "run.db"
    conn = sqlite3.connect(str(db_path))
    state_row = conn.execute(
        "SELECT value FROM state WHERE key='run_state'"
    ).fetchone()
    if not state_row:
        conn.close()
        return ""
    state = json.loads(state_row[0])
    all_solutions = state.get("all_solutions", [])
    if not all_solutions:
        conn.close()
        return ""

    # Best by score (matches extract_child_best_output's "best grader" pick)
    best = max(all_solutions, key=lambda s: (s.get("score", 0), s.get("stage", 0)))

    # BS-clean flag for the best
    bs_rows = conn.execute(
        "SELECT inputs, output FROM agent_calls "
        "WHERE agent LIKE 'bs_detector_%_agg'"
    ).fetchall()
    bs_clean = "N/A"
    for inputs_json, bs_out in bs_rows:
        try:
            inputs = json.loads(inputs_json)
        except Exception:
            continue
        if inputs.get("solver_index") == best.get("solver_index"):
            import re
            bs_clean = "clean" if re.search(
                r"no surviving gaps", bs_out or "", re.IGNORECASE
            ) else "open"

    # Pull the highest-scoring grader's "Overall Strategy" block for the
    # winning solver (the GraderResult.summary field added in 22ffd7c).
    summary = ""
    grader_rows = conn.execute(
        "SELECT inputs, output FROM agent_calls "
        "WHERE agent LIKE 'grader_%' AND agent NOT LIKE '%_agg'"
    ).fetchall()
    import re
    for inputs_json, grader_out in grader_rows:
        try:
            inputs = json.loads(inputs_json)
        except Exception:
            continue
        if (inputs.get("solver_index") == best.get("solver_index")
                and inputs.get("stage") == best.get("stage")):
            m = re.search(
                r"\*\*Overall Strategy:\*\*\s*(.+?)(?=\n\s*\*\*[A-Z])",
                grader_out or "",
                re.DOTALL,
            )
            if m:
                summary = m.group(1).strip()
            break
    conn.close()

    # Classify the proof's actual verdict (PROVED / DISPROVED / UNCLEAR)
    proof_text = best.get("output", "")
    verdict_on_problem = await flash_classify_proof_verdict(proof_text)
    # Prefer the manifest-supplied direction (authoritative); fall back to
    # keyword scan for older manifests that pre-date the conjecture_target
    # field. The heuristic agreed with the manifest in all observed cases
    # but is brittle to rewriter phrasing changes.
    direction = conjecture_target or _detect_child_direction(child_problem_text)
    conjecture_verdict = _derive_conjecture_verdict(direction, verdict_on_problem)

    if conjecture_verdict == "UNCLEAR":
        return ""  # leave conjecture OPEN; no header prepended

    status_phrase = (
        "proved — pending vetting"
        if conjecture_verdict == "PROVED"
        else "blocked"
    )

    header = (
        f"## Resolved Conjecture from Child Sub-run\n\n"
        f"**Conjecture {conjecture_id}** (verbatim from "
        f"`child_{conjecture_id}_problem.txt`):\n\n"
        f"> {child_problem_text.strip()[:3000]}\n\n"
        f"**Verdict:** {conjecture_verdict} by child run `{child_run_id}`.\n"
        f"- Direction: {direction}\n"
        f"- Confirming proof: stage {best.get('stage')}, "
        f"solver {best.get('solver_index')}, "
        f"score {best.get('score')}/7, BS-{bs_clean}.\n\n"
        f"**Strategy summary** (verbatim from the grader of the confirming proof):\n\n"
        f"> {summary or '(none extracted — grader output lacked Overall Strategy block)'}\n\n"
        f"---\n\n"
        f"**Instruction to the notebook agent:** Record this conjecture as "
        f"an Open Conjecture entry with `Status: CLOSED ({status_phrase})`, "
        f"and move the approach into the IPT registry as a new IPT-N with "
        f"`Reason failed:` populated from the strategy summary above. Do not "
        f"re-list this conjecture as an OPEN conjecture in the updated "
        f"notebook, and do not restate its negation as a fresh conjecture "
        f"in any subsequent stage.\n\n"
        f"---\n\n"
    )
    return header


def main() -> int:
    p = argparse.ArgumentParser(description="Child-supervisor coordinator.")
    p.add_argument("--manifest", required=True, type=Path,
                   help="Path to manifest JSON written by the parent Orchestrator.")
    args = p.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    parent_run_id: str = manifest["parent_run_id"]
    parent_problem_file = Path(manifest["parent_problem_file"])
    child_problem_file = Path(manifest["child_problem_file"])
    child_w: int = manifest["child_w"]
    child_d: int = manifest["child_d"]
    successor_w: int = manifest["successor_w"]
    successor_d: int = manifest["successor_d"]
    remaining_budget: int = manifest["remaining_budget"]
    conjecture_id: str = manifest["conjecture_id"]
    # Direction the child was tasked with (statement | negation). Older
    # manifests don't carry this; supervisor.compose_resolution_header
    # falls back to a keyword scan when this is None.
    conjecture_target: str | None = manifest.get("conjecture_target")
    additional_materials_file: str | None = manifest.get("additional_materials_file")

    log(f"Supervisor starting. Parent {parent_run_id}, conjecture {conjecture_id}.")
    log(f"Remaining budget: {remaining_budget}. Child cost: {child_w*child_d}. "
        f"Successor cost: {successor_w*successor_d}.")

    # Re-attach the parent's --additional-materials file to spawned runs.
    materials_args = (
        ["--additional-materials", additional_materials_file]
        if additional_materials_file else None
    )

    # ── Phase 1: launch child (no grandchildren allowed) ─────────────────────
    log("Phase 1: launching child run on the self-contained conjecture.")
    child_budget = remaining_budget   # child sees the full remaining; its own check uses W*D
    child_run_id = launch_run(
        problem_file=child_problem_file,
        width=child_w,
        depth=child_d,
        total_budget=child_budget,
        allow_child_spawn=False,   # ENFORCE: children never spawn grandchildren
        lineage_parent_id=parent_run_id,
        lineage_role="child",
        label=f"Child of {parent_run_id} — conjecture {conjecture_id}",
        extra_args=materials_args,
    )

    # ── Phase 2: extract child's best output, write seed bundle ──────────────
    log(f"Phase 2: extracting best output from child {child_run_id}.")
    seed_bundle = extract_child_best_output(child_run_id)

    # Prepend structured resolution header when the child run actually
    # resolved the conjecture (PROVED or DISPROVED). For UNCLEAR results
    # the header is empty and the seed bundle carries only the partial
    # work — conjecture remains OPEN in the parent's notebook.
    child_problem_text = child_problem_file.read_text(encoding="utf-8")
    import asyncio
    resolution_header = asyncio.run(
        compose_resolution_header(
            conjecture_id=conjecture_id,
            child_problem_text=child_problem_text,
            child_run_id=child_run_id,
            conjecture_target=conjecture_target,
        )
    )
    if resolution_header:
        log(f"Conjecture {conjecture_id} resolved; prepending structured header "
            f"({len(resolution_header)} chars).")
        seed_bundle = resolution_header + seed_bundle
    else:
        log(f"Conjecture {conjecture_id} UNRESOLVED by child run; "
            f"no resolution header prepended.")

    seed_file = RUNS_DIR / parent_run_id / f"child_{conjecture_id}_seed.txt"
    seed_file.write_text(seed_bundle, encoding="utf-8")
    log(f"Seed bundle written to {seed_file} ({len(seed_bundle)} chars).")

    # ── Phase 3: launch successor parent run ────────────────────────────────
    successor_budget = remaining_budget - (child_w * child_d)
    if successor_budget < successor_w * successor_d:
        log(f"[abort] Successor budget {successor_budget} < successor cost "
            f"{successor_w*successor_d}. Not launching successor.")
        return 0

    log("Phase 3: launching successor parent run (allow-child-spawn=True).")
    successor_run_id = launch_run(
        problem_file=parent_problem_file,
        width=successor_w,
        depth=successor_d,
        total_budget=successor_budget,
        allow_child_spawn=True,   # successor IS the parent continuing; may spawn another child
        seed_run=parent_run_id,
        seed_notebook_file=seed_file,
        lineage_parent_id=parent_run_id,
        lineage_role="successor",
        label=f"Successor of {parent_run_id} — after child {child_run_id}",
        extra_args=materials_args,
    )
    log(f"Supervisor done. Successor run: {successor_run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
