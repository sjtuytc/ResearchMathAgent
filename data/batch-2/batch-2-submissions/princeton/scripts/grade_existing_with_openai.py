"""Run the OpenAI grader on every parent-stage proof scoring >=5 across
a list of math_solver runs, then dump a side-by-side comparison with the
Gemini scores from each run.db.

Pulls OPENAI_API_KEY from SSM (same source the AWS container uses), so a
single command on the operator's laptop suffices — no manual key export.

Usage:
  python scripts/grade_existing_with_openai.py \
      --runs cb22e72ea052 58fce13b3dbf d370060ca7cf 3266aafb652b \
      --out /Users/arora/claudecode/math_solver_fix/scratch/2026-05-27_openai_disagreement/

Output:
  <out>/comparison.json     per-(run, stage, solver) Gemini vs OpenAI scores
  <out>/comparison.md       human-readable table + per-proof OpenAI verdict excerpt
  <out>/openai_outputs/     full OpenAI grader output text per proof
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

# Pull OpenAI key from SSM on demand, only if not already in env. Operator
# can override by exporting OPENAI_API_KEY before running.
def _ensure_openai_key() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    proc = subprocess.run(
        ["/opt/homebrew/bin/aws", "ssm", "get-parameter",
         "--region", "us-east-1",
         "--name", "/firstproof/openai_api_key",
         "--with-decryption",
         "--query", "Parameter.Value",
         "--output", "text"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise click.UsageError(
            f"OPENAI_API_KEY not in env and SSM fetch failed: {proc.stderr[:300]}"
        )
    os.environ["OPENAI_API_KEY"] = proc.stdout.strip()


def _runs_dir() -> Path:
    return Path("/Users/arora/claudecode/runs")


def _load_state(run_id: str) -> dict:
    db_path = _runs_dir() / run_id / "run.db"
    if not db_path.exists():
        raise click.UsageError(f"no run.db at {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM state LIMIT 1").fetchone()
    finally:
        conn.close()
    return json.loads(row[0])


def _extract_proof(solver_output: str) -> str:
    """Pull the clean proof section between PROOF_START / PROOF_END if present,
    else return the whole output (matches agents/grader._proof_only behavior)."""
    s = solver_output
    if "PROOF_START" in s:
        s = s.split("PROOF_START", 1)[1]
    if "PROOF_END" in s:
        s = s.split("PROOF_END", 1)[0]
    return s.strip()


def _eligible_parents(state: dict, *, min_score: float = 5.0,
                      score_buckets: list[int] | None = None,
                      per_bucket: int = 2) -> list[dict]:
    """Pick parents (or legacy stage_type=None) for grading.

    Two modes:
      - score_buckets=None (default): single-threshold mode. Keep all
        proofs with score >= min_score, deduplicated by (stage, solver),
        keeping the highest-scoring record per (stage, solver) pair.
      - score_buckets=[3, 7] etc.: stratified-sample mode. For each
        integer in score_buckets, pick up to `per_bucket` proofs whose
        floor(score) == that integer. Useful for studying disagreement
        across the score range, not only at the top.
    """
    sols = state.get("all_solutions", [])
    parents = [
        s for s in sols
        if s.get("stage_type") in ("parent", None) and s.get("score", 0) >= 0
    ]
    best: dict[tuple[int, int], dict] = {}
    for s in parents:
        key = (s.get("stage"), s.get("solver_index"))
        prev = best.get(key)
        if prev is None or s.get("score", 0) > prev.get("score", 0):
            best[key] = s
    deduped = list(best.values())

    if score_buckets is None:
        return [s for s in deduped if s.get("score", 0) >= min_score]

    out: list[dict] = []
    for bucket in score_buckets:
        in_bucket = [s for s in deduped if int(s.get("score", 0)) == bucket]
        # Within bucket, prefer most-recent stage (higher = later) so we sample
        # post-notebook-update solvers when there are many at the same score.
        in_bucket.sort(key=lambda s: (-(s.get("stage") or 0), -(s.get("solver_index") or 0)))
        out.extend(in_bucket[:per_bucket])
    return out


async def _grade_one(run_id: str, problem: str, sol: dict,
                     model: str, out_dir: Path) -> dict:
    from openai_grader import grade_proof  # noqa: E402
    proof = _extract_proof(sol.get("output", ""))
    rec = {
        "run_id": run_id,
        "stage": sol.get("stage"),
        "solver_index": sol.get("solver_index"),
        "gemini_score": sol.get("score"),
        "gemini_bs_clean": sol.get("bs_clean"),
        "proof_chars": len(proof),
    }
    print(f"  [grade] {run_id} stage{rec['stage']} solver{rec['solver_index']} "
          f"(gemini={rec['gemini_score']}, {len(proof)} chars)...")
    result = await grade_proof(problem=problem, proof=proof, model=model)
    rec.update({
        "openai_score": result.score,
        "openai_duration_s": round(result.duration_s, 1),
        "openai_tokens": {
            "input": result.tokens_in,
            "output": result.tokens_out,
            "reasoning": result.tokens_reasoning,
        },
        "openai_model": result.model,
        "openai_error": result.error,
    })
    # Persist full output
    tag = f"{run_id}_stage{rec['stage']}_solver{rec['solver_index']}.md"
    (out_dir / "openai_outputs").mkdir(parents=True, exist_ok=True)
    (out_dir / "openai_outputs" / tag).write_text(result.output, encoding="utf-8")
    delta = (result.score - (rec["gemini_score"] or 0)) if result.score >= 0 else None
    print(f"    -> openai={result.score}/7  gemini={rec['gemini_score']}/7  "
          f"delta={delta if delta is not None else 'ERR'}  "
          f"({result.duration_s:.0f}s)")
    return rec


async def _run(run_ids: list[str], out_dir: Path, model: str,
               min_score: float, max_per_run: int,
               score_buckets: list[int] | None, per_bucket: int) -> None:
    _ensure_openai_key()
    out_dir.mkdir(parents=True, exist_ok=True)

    if score_buckets:
        print(f"[study] runs={run_ids}  model={model}  "
              f"stratified buckets={score_buckets}  per_bucket={per_bucket}")
    else:
        print(f"[study] runs={run_ids}  model={model}  "
              f"min_score={min_score}  max_per_run={max_per_run}")
    all_jobs: list[tuple[str, str, dict]] = []
    for run_id in run_ids:
        state = _load_state(run_id)
        problem = state.get("problem", "")
        eligible = _eligible_parents(
            state, min_score=min_score,
            score_buckets=score_buckets, per_bucket=per_bucket,
        )
        if score_buckets is None:
            eligible.sort(key=lambda s: -s.get("score", 0))
            eligible = eligible[:max_per_run]
        print(f"  {run_id}: {len(eligible)} proofs to grade "
              f"(scores: {sorted(s.get('score',0) for s in eligible)})")
        for sol in eligible:
            all_jobs.append((run_id, problem, sol))

    if not all_jobs:
        print("[study] nothing to grade.")
        return

    print(f"[study] grading {len(all_jobs)} proofs in parallel...")
    t0 = time.time()
    results = await asyncio.gather(*[
        _grade_one(run_id, problem, sol, model, out_dir)
        for (run_id, problem, sol) in all_jobs
    ])
    wall = time.time() - t0
    print(f"\n[study] done in {wall:.0f}s wallclock")

    # Persist comparison.json
    (out_dir / "comparison.json").write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(),
            "model": model,
            "min_score": min_score,
            "n_graded": len(results),
            "results": results,
        }, indent=2),
        encoding="utf-8",
    )

    # Persist comparison.md
    lines = [
        f"# OpenAI vs Gemini Grader Disagreement Study",
        f"",
        f"**Generated:** {datetime.now().isoformat()}",
        f"**Model:** {model}",
        f"**Min Gemini score to grade:** {min_score}",
        f"**Total proofs graded:** {len(results)}",
        f"",
        "| Run | Stage | Solver | Gemini | BS-clean | OpenAI | Δ | Time |",
        "|---|---|---|---|---|---|---|---|",
    ]
    deltas: list[float] = []
    for r in sorted(results, key=lambda x: (x["run_id"], x.get("stage", 0), x.get("solver_index", 0))):
        if r.get("openai_error"):
            row = (f"| {r['run_id']} | {r.get('stage')} | {r.get('solver_index')} | "
                   f"{r.get('gemini_score')} | {r.get('gemini_bs_clean')} | "
                   f"ERR | — | — |")
        else:
            g = r.get("gemini_score") or 0
            o = r.get("openai_score") or 0
            d = o - g
            deltas.append(d)
            row = (f"| {r['run_id']} | {r.get('stage')} | {r.get('solver_index')} | "
                   f"{g} | {r.get('gemini_bs_clean')} | "
                   f"{o} | {d:+.1f} | {r.get('openai_duration_s')}s |")
        lines.append(row)
    if deltas:
        lines += [
            "",
            f"**Summary:** n={len(deltas)}  "
            f"mean Δ={sum(deltas)/len(deltas):+.2f}  "
            f"min Δ={min(deltas):+.1f}  max Δ={max(deltas):+.1f}  "
            f"|Δ|>=2 count={sum(1 for d in deltas if abs(d) >= 2)}",
        ]
    (out_dir / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[study] wrote {out_dir/'comparison.md'} and {out_dir/'comparison.json'}")


@click.command()
@click.option("--runs", required=True, multiple=True,
              help="Run id(s) to grade. Pass --runs ID --runs ID ... or comma-separated.")
@click.option("--out", required=True, type=click.Path(path_type=Path),
              help="Output directory.")
@click.option("--model", default="gpt-5.5-pro", show_default=True,
              help="OpenAI model id.")
@click.option("--min-score", default=5.0, type=float, show_default=True,
              help="Minimum Gemini score to include the proof.")
@click.option("--max-per-run", default=4, type=int, show_default=True,
              help="Cap on proofs to grade per run (single-threshold mode).")
@click.option("--score-buckets", default="", type=str,
              help="Comma-separated integer score buckets to stratify-sample, "
                   "e.g. --score-buckets 3,7. When set, --min-score and "
                   "--max-per-run are ignored.")
@click.option("--per-bucket", default=2, type=int, show_default=True,
              help="Proofs to pick per score bucket per run (stratified mode).")
def cli(runs: tuple[str, ...], out: Path, model: str,
        min_score: float, max_per_run: int,
        score_buckets: str, per_bucket: int) -> None:
    flat: list[str] = []
    for r in runs:
        flat.extend(s.strip() for s in r.split(",") if s.strip())
    buckets: list[int] | None = None
    if score_buckets.strip():
        buckets = [int(b.strip()) for b in score_buckets.split(",") if b.strip()]
    asyncio.run(_run(flat, out, model, min_score, max_per_run,
                     buckets, per_bucket))


if __name__ == "__main__":
    cli()
