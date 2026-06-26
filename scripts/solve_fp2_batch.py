#!/usr/bin/env python3
"""Batch solver for first_proof_2 (prob-01 to prob-10).

Runs the full agent loop on each problem and saves results to
  outputs/output_solutions/fp2_vertex_opus/<problem_id>/solution.tex

Usage:
    python3 scripts/solve_fp2_batch.py [--problems prob-01 ...] [--resume]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

EXP_NAME = "fp2_vertex_opus"
OUTPUT_DIR = REPO_ROOT / "outputs" / "output_solutions" / EXP_NAME
ALL_PROBLEMS = [f"prob-{i:02d}" for i in range(1, 11)]

# Retry delays (seconds) when quota is exhausted — shared NAIRR cluster.
# After the initial ramp-up, retry every 10 minutes indefinitely until quota clears.
_QUOTA_INITIAL_DELAYS = (60, 120, 300)
_QUOTA_STEADY_DELAY = 600
_QUOTA_MAX_ATTEMPTS = 200  # ~33 hours of retries at 600s each


def solve_one(problem_id: str, resume: bool) -> str:
    """Run the agent on one problem. Returns 'ok', 'quota', or 'failed'."""
    from webapp.agent import AgentConfig, run_agent_vertex, DEFAULT_MODEL
    from webapp.dataset_store import get_problem as ds_get

    out_dir = OUTPUT_DIR / problem_id
    solution_path = out_dir / "solution.tex"

    if resume and solution_path.is_file() and solution_path.stat().st_size > 200:
        log.info("%s: already solved (resume mode), skipping", problem_id)
        return "ok"

    prob = ds_get("first_proof_2", problem_id)
    if prob is None:
        log.error("%s: not found in dataset store", problem_id)
        return "failed"

    problem_text = prob.get("tex") or prob.get("statement") or ""
    if not problem_text:
        log.error("%s: no LaTeX content", problem_id)
        return "failed"

    out_dir.mkdir(parents=True, exist_ok=True)
    ws = REPO_ROOT / "webapp" / ".runs" / f"{problem_id}_{int(time.time())}"
    run_id = uuid.uuid4().hex

    cfg = AgentConfig(
        problem_id=problem_id,
        problem_text=problem_text,
        model=DEFAULT_MODEL,
        repo_root=REPO_ROOT,
        workspace=ws,
        thinking=True,
        provider="vertex",
        gcp_project="nairr-260096-569948",
    )

    log.info("%s: starting agent (model=%s)", problem_id, DEFAULT_MODEL)
    transcript_parts: list[str] = []
    artifact: dict | None = None
    quota_hit = False

    try:
        for event in run_agent_vertex(cfg, None):
            if event.type == "text_delta":
                chunk = event.data.get("text", "")
                transcript_parts.append(chunk)
                sys.stdout.write(chunk)
                sys.stdout.flush()
            elif event.type == "artifact":
                artifact = event.data
                log.info("%s: artifact received (%d chars)", problem_id, len(str(artifact)))
            elif event.type == "status":
                log.info("%s: %s", problem_id, event.data.get("label", ""))
            elif event.type == "error":
                msg = str(event.data)
                log.error("%s: agent error: %s", problem_id, event.data)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "Quota" in msg:
                    quota_hit = True
            elif event.type == "done":
                log.info("%s: agent done (%s)", problem_id, event.data.get("reason", ""))
    except Exception as exc:
        log.exception("%s: agent crashed: %s", problem_id, exc)

    if quota_hit and not transcript_parts and artifact is None:
        return "quota"

    # Save solution
    solution_tex = ""
    if artifact and artifact.get("latex"):
        solution_tex = artifact["latex"]
    else:
        ws_sol = ws / "solution.tex"
        if ws_sol.is_file():
            solution_tex = ws_sol.read_text(encoding="utf-8", errors="replace")

    if solution_tex:
        solution_path.write_text(solution_tex, encoding="utf-8")
        log.info("%s: solution saved (%d chars) → %s", problem_id, len(solution_tex), solution_path)
        return "ok"
    else:
        transcript = "".join(transcript_parts)
        if transcript:
            fallback = out_dir / "transcript.md"
            fallback.write_text(transcript, encoding="utf-8")
            log.warning("%s: no solution.tex — saved transcript (%d chars)", problem_id, len(transcript))
        else:
            log.error("%s: no solution or transcript produced", problem_id)
        return "failed"


def solve_with_quota_retry(problem_id: str, resume: bool) -> bool:
    """Wrap solve_one with quota-aware retry, ramping then steady 600s backoff."""
    for attempt in range(_QUOTA_MAX_ATTEMPTS):
        status = solve_one(problem_id, resume)
        if status == "ok":
            return True
        if status == "quota":
            if attempt < len(_QUOTA_INITIAL_DELAYS):
                delay = _QUOTA_INITIAL_DELAYS[attempt]
            else:
                delay = _QUOTA_STEADY_DELAY
            log.info(
                "%s: quota exhausted (attempt %d), waiting %ds before retry…",
                problem_id, attempt + 1, delay,
            )
            time.sleep(delay)
            continue
        # "failed" — non-quota error, no point retrying
        return False
    log.error("%s: quota exhausted after %d attempts", problem_id, _QUOTA_MAX_ATTEMPTS)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--problems", nargs="*", default=ALL_PROBLEMS)
    parser.add_argument("--resume", action="store_true", help="Skip already-solved problems")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = {}
    for pid in args.problems:
        log.info("=" * 60)
        log.info("Solving %s", pid)
        log.info("=" * 60)
        ok = solve_with_quota_retry(pid, args.resume)
        results[pid] = "ok" if ok else "failed"
        log.info("%s: %s", pid, results[pid])
        if pid != args.problems[-1]:
            log.info("Pausing 30s before next problem…")
            time.sleep(30)

    log.info("=" * 60)
    log.info("Batch complete:")
    for pid, status in results.items():
        log.info("  %s: %s", pid, status)

    ok_count = sum(1 for v in results.values() if v == "ok")
    log.info("%d/%d succeeded", ok_count, len(results))


if __name__ == "__main__":
    main()
