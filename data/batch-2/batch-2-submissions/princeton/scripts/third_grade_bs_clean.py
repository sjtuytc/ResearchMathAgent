"""Third-grader study: for each BS-clean proof in a list of runs, give
Gemini 3.1 Pro the problem, the proof, and the two prior graders'
critiques (scores stripped), then ask it to grade independently and
say which prior critique it sides with.

Inputs:
  - run.db at /Users/arora/claudecode/runs/<run_id>/  for proof + Gemini
    grader critique
  - openai_outputs/<run>_stage<S>_solver<I>.md  for OpenAI critique

Output:
  <out>/third_grade.json
  <out>/third_grade.md
  <out>/outputs/<run>_stage<S>_solver<I>.md
"""
from __future__ import annotations
import asyncio
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from math_solver.gemini import call_gemini  # noqa: E402

RUNS_DIR = Path("/Users/arora/claudecode/runs")
OAI_DIR = Path("/Users/arora/claudecode/openai_study_2026-05-28_q2q5_smoke/openai_outputs")

# (run_id, stage, solver_index)  — BS-clean proofs from comparison.md
TARGETS: list[tuple[str, int, int]] = [
    ("373728106bd3", 3, 2),
    ("e49ba1ce6013", 5, 0),
    ("e49ba1ce6013", 5, 2),
    ("e49ba1ce6013", 5, 4),
    ("e49ba1ce6013", 5, 5),
]

PROMPT = """You are an expert mathematician acting as a third independent grader on a research-level math problem. Two graders have already evaluated the proof below and produced detailed critiques. Read the problem and proof on your own merits first, then read the two critiques, then issue your own grade.

=== PROBLEM ===
{problem_text}

=== PROOF UNDER REVIEW ===
{proof_text}

=== GRADER A — critique ===
{grader_a}

=== GRADER B — critique ===
{grader_b}

=== YOUR TASK ===
1. Independently read the proof. Identify the load-bearing steps and check whether each is correctly justified. Do not defer to either prior grader at this stage.
2. Read both critiques. For each substantive criticism raised by either grader, state whether you agree (and why) or reject it (and why).
3. Issue your own grade on the 0-7 scale (0 = no progress, 7 = complete and correct proof).
4. State in one sentence which prior critique you find more persuasive overall, or "neither" if you side with neither.

End your response with exactly two lines:
AGREES_WITH: <A | B | neither>
SCORE: N/7
"""


def _load_state(run_id: str) -> dict:
    db = RUNS_DIR / run_id / "run.db"
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT value FROM state LIMIT 1").fetchone()
    finally:
        conn.close()
    return json.loads(row[0])


def _extract_proof(solver_output: str) -> str:
    s = solver_output
    if "PROOF_START" in s:
        s = s.split("PROOF_START", 1)[1]
    if "PROOF_END" in s:
        s = s.split("PROOF_END", 1)[0]
    return s.strip()


def _find_solution(state: dict, stage: int, solver_index: int) -> dict:
    for s in state.get("all_solutions", []):
        if s.get("stage") == stage and s.get("solver_index") == solver_index \
                and s.get("stage_type") in ("parent", None):
            return s
    raise RuntimeError(f"no solution for stage={stage} solver={solver_index}")


def _gemini_critique(run_id: str, stage: int, solver_index: int) -> str:
    """Concatenate all grader_* call outputs for this (stage, solver_index).
    Strips trailing 'SCORE: N/7' so the third grader does not see the score."""
    db = RUNS_DIR / run_id / "run.db"
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT agent, inputs, output, created_at FROM agent_calls "
            "WHERE agent LIKE 'grader%' ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    pieces: list[str] = []
    for agent, inputs_json, output, _ in rows:
        try:
            inp = json.loads(inputs_json)
        except Exception:
            continue
        if inp.get("stage") != stage or inp.get("solver_index") != solver_index:
            continue
        pieces.append(f"--- {agent} ---\n{output.strip()}")
    if not pieces:
        raise RuntimeError(f"no grader calls for stage={stage} solver={solver_index}")
    full = "\n\n".join(pieces)
    return _strip_score_lines(full)


def _oai_critique(run_id: str, stage: int, solver_index: int) -> str:
    p = OAI_DIR / f"{run_id}_stage{stage}_solver{solver_index}.md"
    return _strip_score_lines(p.read_text(encoding="utf-8"))


def _strip_score_lines(text: str) -> str:
    """Remove lines that explicitly state a numerical score on the 0-7
    scale, so the third grader is not anchored. Matches:
      SCORE: 3/7
      **SCORE:** 7/7
      Score: 3 / 7
    Leaves the surrounding critique prose intact."""
    pat = re.compile(r"^\s*\**\s*score\s*:?\**\s*\d+\s*/\s*7\s*\**\s*$",
                     re.IGNORECASE | re.MULTILINE)
    return pat.sub("", text).strip()


async def _grade_one(run_id: str, stage: int, solver_index: int,
                     out_dir: Path) -> dict:
    state = _load_state(run_id)
    problem = state.get("problem", "")
    sol = _find_solution(state, stage, solver_index)
    proof = _extract_proof(sol.get("output", ""))
    grader_a = _gemini_critique(run_id, stage, solver_index)
    grader_b = _oai_critique(run_id, stage, solver_index)

    prompt = PROMPT.format(
        problem_text=problem,
        proof_text=proof,
        grader_a=grader_a,
        grader_b=grader_b,
    )

    print(f"  [grade] {run_id} stage{stage} solver{solver_index} "
          f"(proof {len(proof)} chars, A {len(grader_a)} ch, B {len(grader_b)} ch)")
    t0 = time.time()
    call = await call_gemini(
        prompt=prompt,
        run_id=f"third_grade_{run_id}",
        notebook_id="third_grade",
        agent=f"third_grader_{run_id}_s{stage}_v{solver_index}",
        inputs={"run_id": run_id, "stage": stage, "solver_index": solver_index},
    )
    elapsed = time.time() - t0

    text = call.output
    tag = f"{run_id}_stage{stage}_solver{solver_index}.md"
    (out_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (out_dir / "outputs" / tag).write_text(text, encoding="utf-8")

    # Parse trailing AGREES_WITH and SCORE
    m_agrees = re.search(r"AGREES_WITH:\s*(A|B|neither)", text, re.IGNORECASE)
    m_score = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)\s*/\s*7", text)
    agrees = m_agrees.group(1).lower() if m_agrees else None
    score = float(m_score.group(1)) if m_score else None

    print(f"    -> agrees={agrees}  score={score}/7  ({elapsed:.0f}s)")
    return {
        "run_id": run_id,
        "stage": stage,
        "solver_index": solver_index,
        "gemini_25_score": sol.get("score"),
        "bs_clean": sol.get("bs_clean"),
        "third_score": score,
        "agrees_with": agrees,
        "duration_s": round(elapsed, 1),
        "tokens_in": call.tokens_in,
        "tokens_out": call.tokens_out,
    }


@click.command()
@click.option("--out", required=True, type=click.Path(path_type=Path))
def cli(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    print(f"[study] {len(TARGETS)} BS-clean proofs, in parallel")

    async def main():
        results = await asyncio.gather(*[
            _grade_one(r, s, v, out) for (r, s, v) in TARGETS
        ])
        (out / "third_grade.json").write_text(
            json.dumps({
                "generated_at": datetime.now().isoformat(),
                "results": results,
            }, indent=2),
            encoding="utf-8",
        )
        lines = [
            "# Third-grader study (Gemini 3.1 Pro) — Q2 / Q5 BS-clean proofs",
            "",
            f"**Generated:** {datetime.now().isoformat()}",
            "",
            "| Run | Stage | Solver | Gemini 2.5 | OAI (gpt-5.5-pro) | Gemini 3.1 | Agrees with | Time |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in results:
            lines.append(
                f"| {r['run_id']} | {r['stage']} | {r['solver_index']} | "
                f"{r['gemini_25_score']} | 3.0 | {r['third_score']} | "
                f"{r['agrees_with']} | {r['duration_s']}s |"
            )
        (out / "third_grade.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"[study] wrote {out/'third_grade.md'}")

    asyncio.run(main())


if __name__ == "__main__":
    cli()
