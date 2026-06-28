#!/usr/bin/env python3
"""Single-turn solver for first_proof_2 (prob-01 to prob-10).

Uses llm.complete() directly — one API call per problem with built-in
60→120→300→600→600→... second retry on quota exhaustion.  Much more quota-friendly
than the full agent loop (which makes many calls and has only short built-in retries).

Outputs to: outputs/output_solutions/fp2_vertex_opus_simple/<problem_id>/solution.tex

Usage:
    python3 scripts/solve_fp2_simple.py [--problems prob-01 ...] [--resume]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

EXP_NAME = "fp2_vertex_opus_simple"
OUTPUT_DIR = REPO_ROOT / "outputs" / "output_solutions" / EXP_NAME
ALL_PROBLEMS = [f"prob-{i:02d}" for i in range(1, 11)]

_SYSTEM = """\
You are an expert research mathematician. You will be given a research-level open problem.
Produce a complete, rigorous proof attempt in LaTeX. Think carefully through all cases.
Your response should be a single LaTeX document body (no \\documentclass or preamble) that
can be compiled after prepending a standard AMSmath preamble. Use \\begin{proof}...\\end{proof}
and standard theorem environments."""

_PROMPT_TMPL = """\
Solve the following research mathematics problem. Write a complete, rigorous proof.

{problem_text}

Respond with LaTeX only — no prose outside of LaTeX comments. Begin your answer directly
with the mathematical content (theorem statement + proof). Do not wrap in a code block."""


def solve_one(problem_id: str, resume: bool) -> bool:
    from webapp.llm import complete
    from webapp.dataset_store import get_problem as ds_get

    out_dir = OUTPUT_DIR / problem_id
    solution_path = out_dir / "solution.tex"

    if resume and solution_path.is_file() and solution_path.stat().st_size > 200:
        log.info("%s: already solved (resume mode), skipping", problem_id)
        return True

    prob = ds_get("first_proof_2", problem_id)
    if prob is None:
        log.error("%s: not found in dataset store", problem_id)
        return False

    problem_text = prob.get("tex") or prob.get("statement") or ""
    if not problem_text:
        log.error("%s: no LaTeX content", problem_id)
        return False

    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = _PROMPT_TMPL.format(problem_text=problem_text)

    log.info("%s: calling llm.complete() (will retry on quota until success)…", problem_id)
    result = complete(
        prompt,
        system=_SYSTEM,
        max_tokens=16384,
    )

    if result:
        solution_path.write_text(result, encoding="utf-8")
        log.info("%s: solution saved (%d chars) → %s", problem_id, len(result), solution_path)
        return True
    else:
        log.error("%s: complete() returned None after all retries", problem_id)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--problems", nargs="*", default=ALL_PROBLEMS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = {}
    for pid in args.problems:
        log.info("=" * 60)
        log.info("Solving %s", pid)
        log.info("=" * 60)
        ok = solve_one(pid, args.resume)
        results[pid] = "ok" if ok else "failed"
        log.info("%s: %s", pid, results[pid])
        if pid != args.problems[-1]:
            log.info("Pausing 15s before next problem…")
            time.sleep(15)

    log.info("=" * 60)
    log.info("Batch complete:")
    for pid, status in results.items():
        log.info("  %s: %s", pid, status)

    ok_count = sum(1 for v in results.values() if v == "ok")
    log.info("%d/%d succeeded", ok_count, len(results))


if __name__ == "__main__":
    main()
