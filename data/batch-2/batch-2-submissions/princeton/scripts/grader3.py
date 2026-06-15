"""grader3.py — citation-hypothesis verifier ("Grader 3") for accepted proofs.

For each proof from a pipeline run that scored >= 6.0 by the gauntlet,
runs the full literature-verification chain and produces a structured
PASS / REWRITE / REWORK verdict:

  librarian (Package A)            → librarian_findings.md  (with search queries)
  fetch_and_distill (Package B)    → pdfs/ + summaries/
  verify_pipeline                  → per-step SUPPORTS / NOT FOUND / DOES NOT APPLY / CONTRADICTS
  Flash router                     → PASS | REWRITE | REWORK + severity per proof

Aggregation rule (Sanjeev, 2026-05-26):
  - PASS: every verified step is SUPPORTS (strict). Provisionally accept.
  - REWRITE: only NOT FOUNDs (typically wrong-paper cited; proof math itself OK).
  - REWORK: any DOES NOT APPLY or CONTRADICTS (hypothesis mismatch).
  - If >= 2 proofs PASS for the same problem: accept (no rework launched).
  - Else: optionally launch W=6 D=6 rework with feedback.md as
    --additional-materials.

Invariant: the best proof so far (highest dual-gate score, then highest
verify-pass-rate) is always written to <out-dir>/best_so_far.txt before
any rework launch, so a downstream FirstProof container always has a
provisional answer if the rework runs out of time.

Usage:
  python scripts/grader3.py run --run-id <run_id>
  python scripts/grader3.py run --run-id <id> --auto-rework  --rework-budget 60
  python scripts/grader3.py run --run-id <id> --out-dir /path/to/dir
  python scripts/grader3.py run --run-id <id> --top-n 4

By default this writes outputs to
  /Users/arora/claudecode/math_solver_fix/scratch/<YYYY-MM-DD>_grader3_<run_id>/
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from math_solver.gemini import _get_client  # noqa: E402
from math_solver.config import GEMINI_FLASH_MODEL  # noqa: E402
from google.genai import types as gtypes  # noqa: E402

import librarian  # noqa: E402
import fetch_and_distill  # noqa: E402
import verify_pipeline  # noqa: E402


DEFAULT_TOP_N = 4   # cap on number of proofs to grade per run
SCRATCH_BASE = ROOT / "scratch"

# ─── Run-state extraction ─────────────────────────────────────────────────

def _runs_dir() -> Path:
    """Where runs/<id>/run.db lives.

    Reads RUNS_DIR env var (set to /data/runs in the AWS container's
    Dockerfile); falls back to the laptop path for local dev / inspection.
    Without the env var read, in-container Grader 3 calls failed with
    "no run.db at /Users/arora/claudecode/runs/..." on 2026-05-28's
    Q2+Q5 smoke, silently disabling the autonomous rework loop.
    """
    return Path(os.environ.get("RUNS_DIR", "/Users/arora/claudecode/runs"))


def load_state(run_id: str) -> dict:
    db_path = _runs_dir() / run_id / "run.db"
    if not db_path.exists():
        raise click.UsageError(f"no run.db at {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM state LIMIT 1").fetchone()
    finally:
        conn.close()
    return json.loads(row[0])


def eligible_proofs(state: dict, top_n: int) -> list[dict]:
    """Return the top_n parent solutions sorted by (effective_score, bs_clean),
    deduplicated by (stage, solver_index). No score threshold (2026-05-28):
    we now want literature verification + critique-informed feedback even
    on weak proofs (Q4 capped at 4/7 was getting zero downstream signal).
    Each entry is the parent SolutionRecord dict augmented with
    `gauntlet_score` from the matching gauntlet_draw aggregator if present.
    """
    sols = state.get("all_solutions", [])
    # Index gauntlet_draw aggregator scores by (stage, solver_index).
    # Aggregator records are the LAST per (stage, solver_index) in the
    # gauntlet_draw list per orchestrator.py extended-grading append.
    agg_by_key: dict[tuple[int, int], float] = {}
    for s in sols:
        if s.get("stage_type") != "gauntlet_draw":
            continue
        key = (s.get("stage"), s.get("solver_index"))
        # Last write wins → aggregator's score (per orchestrator append order)
        agg_by_key[key] = s.get("score", 0.0)
    eligible: list[dict] = []
    seen: set[tuple[int, int]] = set()
    # Backward-compat: pre-stage_type runs (e.g., Q5 58fce13b3dbf,
    # 2026-05-19) have stage_type=None on every record — they predate the
    # stage_type field. Treat None as "parent" since that's the only
    # type that existed back then.
    parents = [s for s in sols
               if s.get("stage_type") == "parent" or s.get("stage_type") is None]
    # Augment each parent with the gauntlet score (if any). No threshold;
    # top-K sorting downstream picks the best regardless of absolute score.
    for p in parents:
        key = (p.get("stage"), p.get("solver_index"))
        if key in seen:
            continue
        gauntlet = agg_by_key.get(key)
        score = gauntlet if gauntlet is not None else p.get("score", 0.0)
        seen.add(key)
        eligible.append({
            **p,
            "gauntlet_score": gauntlet,
            "effective_score": score,
        })
    # Rank: higher effective_score first; then bs_clean True over False/None.
    eligible.sort(
        key=lambda s: (s["effective_score"], s.get("bs_clean") is True),
        reverse=True,
    )
    return eligible[:top_n]


# ─── Per-proof problem-dir setup ──────────────────────────────────────────

GAP_REPORT_TEMPLATE = """\
CITATION-SUPPORT + CRITIQUE-INFORMED VERIFICATION REQUEST
=========================================================

Source run: {run_id}
Stage: {stage}  Solver: {solver_index}  Score: {score}/7  BS-clean: {bs_clean}

The accompanying proof was produced by the math_solver pipeline.
It may be incomplete or partially flawed; this request does NOT assume
the proof is correct. Your task has two parts:

1. CANONICAL-CITATION VERIFICATION: for every named theorem and
   nontrivial technique the proof uses, locate the canonical published
   source so the citation chain can be hypothesis-checked downstream.

2. CRITIQUE-INFORMED FOCUS: the two grader reports below identify
   specific steps where the proof may be wrong or unjustified.
   Prioritize finding literature that bears on those contested steps,
   including any results that would CONTRADICT what the proof claims.

Contest-realism rule: cite only works published before 2026-01-01.

---

## Grader A critique

{grader_a_critique}

---

## Grader B critique

{grader_b_critique}
"""


def _proof_dir_name(run_id: str, proof: dict) -> str:
    return f"proof_stage{proof['stage']}_solver{proof['solver_index']}"


def setup_proof_dir(run_id: str, state: dict, proof: dict,
                    base_out_dir: Path,
                    grader_a_critique: str = "(not provided)",
                    grader_b_critique: str = "(not provided)") -> Path:
    """Create <base>/proof_stageX_solverY/inputs/{notebook.md,near_miss_proof.txt,gap_report.txt}.

    `grader_a_critique` and `grader_b_critique` are the two independent
    grader reports (typically: Gemini gauntlet aggregator critique and
    OpenAI gpt-5.5-pro critique), already stripped to critique-only via
    the harvest-time strip helpers (Areas for Improvement + Scaffolding
    Questions; no praise, no SCORE line, no Council deliberation).
    """
    pdir = base_out_dir / _proof_dir_name(run_id, proof)
    inputs = pdir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    # near_miss_proof.txt = the solver's output verbatim
    (inputs / "near_miss_proof.txt").write_text(proof["output"], encoding="utf-8")
    # notebook.md = the run's root_notebook content
    nb = state.get("root_notebook", {}).get("content", "")
    (inputs / "notebook.md").write_text(nb or "(notebook empty)", encoding="utf-8")
    # gap_report.txt = critique-informed verification request
    (inputs / "gap_report.txt").write_text(
        GAP_REPORT_TEMPLATE.format(
            run_id=run_id,
            stage=proof["stage"],
            solver_index=proof["solver_index"],
            score=proof.get("effective_score", proof.get("score", "?")),
            bs_clean=proof.get("bs_clean"),
            grader_a_critique=grader_a_critique.strip() or "(empty)",
            grader_b_critique=grader_b_critique.strip() or "(empty)",
        ),
        encoding="utf-8",
    )
    return pdir


# ─── Flash router: PASS / REWRITE / REWORK per proof ─────────────────────

ROUTER_SI = """You are a triage router for math-proof verification reports.
You are given the per-step verification verdicts produced by a citation
verifier. Each step's verdict is one of:
  SUPPORTS         — the cited theorem matches the step's claim and its
                      hypotheses are satisfied by the proof step.
  NOT FOUND         — the cited result is not in the cited source (usually
                      wrong-paper-cited; the proof math itself may still be
                      correct, only the citation pointer is wrong).
  DOES NOT APPLY    — the cited theorem statement matches the claim but at
                      least one of its hypotheses is NOT established by
                      the proof step. The theorem cannot legally be
                      invoked at this point.
  CONTRADICTS       — the cited source's statement contradicts what the
                      proof step asserts.

Your job: aggregate these per-step verdicts into ONE of:
  PASS         — STRICT requirements (both must hold):
                   (a) every verified step has verdict SUPPORTS
                   (b) coverage threshold: the number of verified steps
                       is at least 70% of (verified + unmatched), and the
                       absolute number of verified steps is at least 3
                       (or all steps if there are fewer than 3 total).
                 PASS = the proof's citation chain is sound AND we
                 actually verified enough of it to certify.
  REWRITE      — verdicts are dominated by NOT FOUND (no DOES NOT APPLY,
                 no CONTRADICTS), and coverage is sufficient (same 70%
                 / 3-step threshold). The proof's math is likely sound;
                 citations need correction. Cheap fix; no re-derivation.
  REWORK       — at least one DOES NOT APPLY or CONTRADICTS verdict in
                 the verified set. The proof leans on a result whose
                 hypotheses fail (or that the source contradicts). The
                 math is in question; proof needs reconsideration.
  UNVERIFIABLE — coverage is too low to issue any of the above
                 confidently. Use this when verified-count is < 3 (with
                 ≥ 3 steps total) OR < 70% of (verified + unmatched).
                 Signals "Grader 3 couldn't get enough PDFs to certify";
                 caller should treat as REWRITE-or-REWORK candidate
                 conservatively.

Output JSON:
  verdict:  "PASS" | "REWRITE" | "REWORK" | "UNVERIFIABLE"
  severity: "low" | "moderate" | "fatal"
  reason:   one short sentence explaining the verdict, INCLUDING the
            verified/unmatched counts you observed.

Counting rule: count each per-step VERDICT BLOCK in the report below
as one verified step. UNMATCHED steps are reported separately as a
count outside the report — they do NOT appear as verdict blocks.

Coverage example (a real case Grader 3 actually saw on 2026-05-27):
  1 SUPPORTS + 5 UNMATCHED → verified=1, total=6, coverage=17%, <3
  steps verified absolutely → UNVERIFIABLE. NOT PASS. The verifier
  only got a PDF for one cited source out of six; we cannot certify
  the proof from 1/6.

DO NOT rationalize unmatched steps as "no logical errors found".
Unmatched = unverified, NOT "verified clean". An unverified step is
not evidence in either direction.
"""


async def flash_route(findings_md: str, n_unmatched: int) -> dict:
    client = _get_client()
    summary = (
        f"Verification report follows. Number of unmatched steps "
        f"(no PDF fetched for cited source): {n_unmatched}\n\n"
        f"---\n\n{findings_md}"
    )
    config = gtypes.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {
                "verdict": {"type": "string"},
                "severity": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["verdict", "severity", "reason"],
        },
        temperature=0.0,
        max_output_tokens=512,
        system_instruction=ROUTER_SI,
    )
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_FLASH_MODEL,
                contents=summary,
                config=config,
            ),
            timeout=90.0,
        )
        return json.loads(response.text or "{}")
    except Exception as e:
        return {"verdict": "UNKNOWN", "severity": "unknown",
                "reason": f"router error: {e}"}


# ─── Per-proof grading (chains the 3 packages) ────────────────────────────

async def grade_one_proof(run_id: str, state: dict, proof: dict,
                          base_out_dir: Path, concurrency: int,
                          grader_a_critique: str = "(not provided)",
                          grader_b_critique: str = "(not provided)") -> dict:
    """Run librarian → fetch → verify → router for one proof.

    `grader_a_critique` / `grader_b_critique` are the two stripped-critique
    grader reports (Gemini gauntlet + OpenAI). Both flow through into
    gap_report.txt for the librarian to use as critique-informed focus.

    Returns a dict with verdict, severity, reason, proof_dir, and pointers
    to the artifact paths so the aggregator can compose the report.
    """
    pdir = setup_proof_dir(run_id, state, proof, base_out_dir,
                           grader_a_critique=grader_a_critique,
                           grader_b_critique=grader_b_critique)
    label = _proof_dir_name(run_id, proof)
    run_tag = f"grader3_{run_id}_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Populate identifying fields up-front so that any early-return (when
    # librarian / fetch_and_distill / verify fail) still carries the proof's
    # (stage, solver_index, score, bs_clean). Without this, downstream
    # write_best_so_far and write_aggregate_report KeyError on best["stage"]
    # whenever any stage fails (observed 2026-05-29 smoke: SERPAPI_API_KEY
    # missing → fetch_and_distill UsageError → early return → KeyError stage).
    log = {
        "proof_dir": str(pdir),
        "label": label,
        "stages": {},
        "stage": proof["stage"],
        "solver_index": proof["solver_index"],
        "score": proof.get("effective_score", proof.get("score")),
        "bs_clean": proof.get("bs_clean"),
    }
    try:
        # Stage A — librarian
        await librarian._run(pdir, run_tag)
        log["stages"]["librarian"] = "ok"
    except Exception as e:
        log["stages"]["librarian"] = f"FAIL: {e}"
        log["verdict"] = "UNKNOWN"
        log["severity"] = "unknown"
        log["reason"] = "librarian stage failed"
        return log

    try:
        # Stage B — fetch + distill VERY RELATED + RELATED buckets.
        # Earlier (2026-05-26 Q2 smoke test) running with only VERY RELATED
        # left the librarian's RELATED-bucket Cogdell-lecture-notes
        # entry un-fetched, causing 5/6 step-citations to land unmatched
        # in the verifier. Widening to two buckets is ~2x more PDFs to
        # download but materially improves coverage on real proofs.
        await fetch_and_distill._run(
            pdir, ("VERY RELATED", "RELATED"), False, run_tag)
        log["stages"]["fetch_and_distill"] = "ok"
    except Exception as e:
        log["stages"]["fetch_and_distill"] = f"FAIL: {e}"
        log["verdict"] = "UNKNOWN"
        log["severity"] = "unknown"
        log["reason"] = "fetch_and_distill stage failed"
        return log

    try:
        # Stage C — verify pipeline
        await verify_pipeline.run_pipeline(
            problem_dir=pdir, proof_path=None,
            concurrency=concurrency, skip_annotate=False,
        )
        log["stages"]["verify"] = "ok"
    except Exception as e:
        log["stages"]["verify"] = f"FAIL: {e}"
        log["verdict"] = "UNKNOWN"
        log["severity"] = "unknown"
        log["reason"] = "verify stage failed"
        return log

    # Stage D — Flash router
    findings_path = pdir / "verify" / "findings.md"
    unmatched_path = pdir / "verify" / "unmatched.md"
    findings_md = findings_path.read_text(encoding="utf-8") if findings_path.exists() else ""
    n_unmatched = 0
    if unmatched_path.exists():
        n_unmatched = sum(1 for ln in unmatched_path.read_text().splitlines()
                          if ln.lstrip().startswith("- Step"))
    verdict = await flash_route(findings_md, n_unmatched)
    log.update(verdict)
    log["n_unmatched"] = n_unmatched
    log["findings_path"] = str(findings_path)
    log["feedback_path"] = str(pdir / "verify" / "feedback.md")
    # stage / solver_index / score / bs_clean already populated up-front.
    return log


# ─── Aggregator + best-so-far invariant ──────────────────────────────────

def write_best_so_far(verdicts: list[dict], state: dict, out_dir: Path) -> Path:
    """Write the best proof so far to <out_dir>/best_so_far.txt.

    Ranking: PASS > REWRITE > REWORK > UNKNOWN. Within tier: higher score,
    then bs_clean True over False/None.
    """
    # Tier order (smaller = better). UNVERIFIABLE sits between REWRITE
    # (likely fixable by citation correction) and REWORK (math itself in
    # question), reflecting the asymmetry: "we didn't get enough PDFs"
    # is less alarming than "the math fails", more alarming than "the
    # citations are merely wrong-paper-cited".
    tier = {"PASS": 0, "REWRITE": 1, "UNVERIFIABLE": 2, "REWORK": 3, "UNKNOWN": 4}
    ranked = sorted(
        verdicts,
        key=lambda v: (
            tier.get(v.get("verdict", "UNKNOWN"), 9),
            -(v.get("score") or 0),
            v.get("bs_clean") is not True,
        ),
    )
    if not ranked:
        return out_dir / "best_so_far.txt"
    best = ranked[0]
    # Pull the proof text from state.all_solutions. Defensive .get so that
    # if best happens to be a verdict from an early-failed pipeline (no stage
    # set), we just fall through to the no-recovered-proof branch rather than
    # KeyError. grade_one_proof now always populates stage/solver_index even
    # on early-return, so this is belt-and-braces.
    best_stage = best.get("stage")
    best_solver = best.get("solver_index")
    proof_text = "(no proof text recovered)"
    if best_stage is not None and best_solver is not None:
        for s in state.get("all_solutions", []):
            if (s.get("stage") == best_stage
                    and s.get("solver_index") == best_solver
                    and s.get("stage_type") == "parent"):
                proof_text = s.get("output", proof_text)
                break
    header = (
        f"Best so far (Grader 3 ranking):\n"
        f"  verdict={best.get('verdict')}  severity={best.get('severity')}\n"
        f"  stage={best.get('stage')}  solver={best.get('solver_index')}\n"
        f"  score={best.get('score')}  bs_clean={best.get('bs_clean')}\n"
        f"  reason: {best.get('reason')}\n"
        f"  findings: {best.get('findings_path')}\n"
        f"  feedback: {best.get('feedback_path')}\n"
        f"---\n\n"
    )
    out = out_dir / "best_so_far.txt"
    out.write_text(header + proof_text, encoding="utf-8")
    return out


def write_aggregate_report(run_id: str, verdicts: list[dict],
                            out_dir: Path) -> Path:
    n_pass = sum(1 for v in verdicts if v.get("verdict") == "PASS")
    n_rewrite = sum(1 for v in verdicts if v.get("verdict") == "REWRITE")
    n_unver = sum(1 for v in verdicts if v.get("verdict") == "UNVERIFIABLE")
    n_rework = sum(1 for v in verdicts if v.get("verdict") == "REWORK")
    n_unknown = sum(1 for v in verdicts if v.get("verdict") == "UNKNOWN")
    lines = [
        f"# Grader 3 — Aggregate Report",
        f"",
        f"**Run:** {run_id}",
        f"**Proofs graded:** {len(verdicts)}",
        f"**Verdicts:** PASS={n_pass}  REWRITE={n_rewrite}  "
        f"UNVERIFIABLE={n_unver}  REWORK={n_rework}  UNKNOWN={n_unknown}",
        f"**Acceptance threshold:** >=2 PASS",
        f"**Provisional acceptance:** {'YES' if n_pass >= 2 else 'NO — best-so-far written'}",
        "",
        "## Per-proof verdicts",
        "",
    ]
    for v in verdicts:
        lines.append(
            f"- **Stage {v.get('stage')} Solver {v.get('solver_index')}** "
            f"(score={v.get('score')}, bs_clean={v.get('bs_clean')})\n"
            f"  - verdict: **{v.get('verdict')}** ({v.get('severity')})\n"
            f"  - reason: {v.get('reason')}\n"
            f"  - n_unmatched: {v.get('n_unmatched')}\n"
            f"  - findings: {v.get('findings_path')}\n"
            f"  - feedback: {v.get('feedback_path')}\n"
        )
    out = out_dir / "aggregate_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# ─── Optional auto-rework launch ──────────────────────────────────────────

def launch_rework(run_id: str, state: dict, verdicts: list[dict],
                  out_dir: Path, rework_budget: int) -> dict:
    """Launch a W=6 D=6 re-solve with the most-flagged proof's feedback
    as additional_materials. Returns process info.
    """
    # Pick the highest-scoring REWORK / REWRITE verdict's feedback
    candidates = [v for v in verdicts if v.get("verdict") in ("REWORK", "REWRITE")]
    if not candidates:
        return {"launched": False, "reason": "no rework/rewrite candidates"}
    candidates.sort(key=lambda v: -(v.get("score") or 0))
    pick = candidates[0]
    # Build additional_materials: feedback + the picked proof + best-so-far
    addl = out_dir / "rework_additional_materials.txt"
    parts: list[str] = []
    parts.append("[Grader 3 — Citation Verification Report (most-flagged proof)]\n")
    fb = Path(pick.get("feedback_path", ""))
    if fb.exists():
        parts.append(fb.read_text(encoding="utf-8"))
    parts.append(f"\n\n[Proof under review — stage {pick['stage']} solver {pick['solver_index']}]\n")
    for s in state["all_solutions"]:
        if (s.get("stage") == pick["stage"]
                and s.get("solver_index") == pick["solver_index"]
                and s.get("stage_type") == "parent"):
            parts.append(s["output"])
            break
    addl.write_text("\n".join(parts), encoding="utf-8")

    # Find the problem file path. The run's README or state may not record it;
    # the caller can pass --rework-problem-file to override. For now, abort
    # if we can't infer it.
    # Heuristic: look for state['problem'] (first ~200 chars) in problems/.
    problem_text = state.get("problem", "")
    problems_dir = ROOT / "problems"
    matched = None
    if problem_text:
        head = problem_text[:120].strip()
        for pf in problems_dir.glob("*.txt"):
            try:
                if head in pf.read_text(encoding="utf-8"):
                    matched = pf
                    break
            except Exception:
                pass
    if matched is None:
        return {"launched": False,
                "reason": "could not infer problem file from state; pass --rework-problem-file"}

    rework_run_label = f"grader3-rework-of-{run_id}"
    cmd = [
        sys.executable, "-m", "math_solver.main", "run", str(matched),
        "-W", "6", "-D", "6",
        "--no-search", "--no-child-spawn",
        "--total-budget", str(rework_budget),
        "--additional-materials", str(addl),
        "--label", rework_run_label,
    ]
    log_path = out_dir / "rework.log"
    log_fh = open(log_path, "wb")
    proc = subprocess.Popen(
        cmd, stdout=log_fh, stderr=subprocess.STDOUT,
        cwd=str(ROOT.parent / "math_solver"),  # main checkout's venv lives here
    )
    return {"launched": True, "pid": proc.pid, "log_path": str(log_path),
            "cmd": " ".join(cmd), "additional_materials": str(addl)}


# ─── Driver ───────────────────────────────────────────────────────────────

async def run_grader3(run_id: str, *, out_dir: Path | None, top_n: int,
                       concurrency: int, auto_rework: bool,
                       rework_budget: int,
                       critiques: dict | None = None) -> dict:
    """Top-K verification chain.

    `critiques` is an optional mapping (stage, solver_index) ->
    {"grader_a": str, "grader_b": str} carrying the two stripped
    grader critiques for each eligible proof. When supplied, each
    proof's critiques flow into its gap_report.txt for the librarian
    to use as critique-informed focus. CLI usage (laptop) passes None,
    falling back to the parent record's own grader_feedback /
    openai_feedback fields where present.
    """
    state = load_state(run_id)
    eligible = eligible_proofs(state, top_n)
    if not eligible:
        click.echo("[grader3] no eligible proofs")
        return {"verdicts": [], "n_eligible": 0}

    if out_dir is None:
        out_dir = SCRATCH_BASE / f"{datetime.now().strftime('%Y-%m-%d')}_grader3_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"[grader3] run_id={run_id}  eligible={len(eligible)}  out_dir={out_dir}")
    for p in eligible:
        click.echo(
            f"[grader3]   stage{p['stage']} solver{p['solver_index']} "
            f"score={p['effective_score']} bs_clean={p.get('bs_clean')}"
        )

    critiques = critiques or {}

    def _critiques_for(p: dict) -> tuple[str, str]:
        key = (p.get("stage"), p.get("solver_index"))
        from_caller = critiques.get(key, {})
        # Caller-supplied wins. Else fall back to fields on the parent record.
        a = from_caller.get("grader_a") or p.get("grader_feedback") or "(not provided)"
        b = from_caller.get("grader_b") or p.get("openai_feedback") or "(not provided)"
        return a, b

    # Run all per-proof pipelines in parallel.
    verdicts = await asyncio.gather(*[
        grade_one_proof(
            run_id, state, p, out_dir, concurrency,
            *_critiques_for(p),
        )
        for p in eligible
    ])

    # Persist artifacts
    best_path = write_best_so_far(verdicts, state, out_dir)
    report_path = write_aggregate_report(run_id, verdicts, out_dir)
    (out_dir / "verdicts.json").write_text(json.dumps(verdicts, indent=2),
                                            encoding="utf-8")

    n_pass = sum(1 for v in verdicts if v.get("verdict") == "PASS")
    click.echo(f"\n[grader3] DONE")
    click.echo(f"  best_so_far  -> {best_path}")
    click.echo(f"  report        -> {report_path}")
    click.echo(f"  verdicts:     PASS={n_pass}  REWRITE="
               f"{sum(1 for v in verdicts if v.get('verdict')=='REWRITE')}  "
               f"UNVERIFIABLE={sum(1 for v in verdicts if v.get('verdict')=='UNVERIFIABLE')}  "
               f"REWORK={sum(1 for v in verdicts if v.get('verdict')=='REWORK')}  "
               f"UNKNOWN={sum(1 for v in verdicts if v.get('verdict')=='UNKNOWN')}")

    result = {"verdicts": verdicts, "n_eligible": len(eligible),
              "n_pass": n_pass, "best_so_far": str(best_path),
              "report": str(report_path)}

    if auto_rework and n_pass < 2:
        click.echo(f"[grader3] fewer than 2 PASS — launching rework (budget={rework_budget})")
        rework_info = launch_rework(run_id, state, verdicts, out_dir, rework_budget)
        (out_dir / "rework_launch.json").write_text(
            json.dumps(rework_info, indent=2), encoding="utf-8")
        result["rework"] = rework_info
        if rework_info.get("launched"):
            click.echo(f"[grader3]   rework PID={rework_info['pid']}  log={rework_info['log_path']}")
        else:
            click.echo(f"[grader3]   rework NOT launched: {rework_info['reason']}")
    elif auto_rework:
        click.echo(f"[grader3] >=2 PASS — not launching rework")

    return result


# ─── CLI ─────────────────────────────────────────────────────────────────

@click.group()
def cli():
    pass


@cli.command("run")
@click.option("--run-id", required=True, help="Pipeline run id (runs/<id>/run.db).")
@click.option("--out-dir", default=None, type=click.Path(path_type=Path),
              help="Output directory. Default: scratch/<date>_grader3_<run_id>/")
@click.option("--top-n", default=DEFAULT_TOP_N, type=int, show_default=True,
              help="Maximum number of eligible proofs to grade.")
@click.option("--concurrency", default=4, type=int, show_default=True,
              help="Max parallel LLM calls per verify pipeline.")
@click.option("--auto-rework", is_flag=True, default=False,
              help="If fewer than 2 PASS, launch a W=6 D=6 rework run "
                   "in the background. NOT default per Sanjeev 2026-05-26.")
@click.option("--rework-budget", default=80, type=int, show_default=True,
              help="--total-budget for the rework run.")
def run_cmd(run_id: str, out_dir: Path | None, top_n: int, concurrency: int,
            auto_rework: bool, rework_budget: int) -> None:
    asyncio.run(run_grader3(
        run_id=run_id, out_dir=out_dir, top_n=top_n,
        concurrency=concurrency, auto_rework=auto_rework,
        rework_budget=rework_budget,
    ))


if __name__ == "__main__":
    cli()
