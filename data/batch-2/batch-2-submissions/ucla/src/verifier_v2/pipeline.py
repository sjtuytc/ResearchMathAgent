"""Main finalize pipeline — implements the v2_plan.md flowchart."""
from __future__ import annotations
import os
from .chunker import split_into_chunks, build_dependency_graph, get_accumulated_context
from .prechecker import run_prechecker
from .scorer import run_verify, is_accepted, ACCEPT_THRESHOLD
from .gap_classifier import record_major_gap, format_failed_approaches_block
from .patcher import patch_minor_gaps
from ._api import call_api

POLISH_PROMPT = """\
You are revising a candidate proof of a mathematical problem.

# Original Problem
PROBLEM_PLACEHOLDER

# Candidate Proof (on the right track, may have gaps)
PROOF_PLACEHOLDER

# Pre-Verification Report
PRECHECK_PLACEHOLDER

# Instructions
This approach is promising. Make it work end-to-end without gaps.
Every step must be proved or explicitly cited. No jargon without definition.
No need to optimize constants. The proof should be correct.

Output the complete polished proof in markdown with inline LaTeX math.
"""

TYPESET_PROMPT = """\
Convert the proof below into a complete, self-contained LaTeX file.

# Problem
PROBLEM_PLACEHOLDER

# Polished Proof
PROOF_PLACEHOLDER

# Instructions
Make sure there are no gaps or unexplained steps. Every lemma must be stated and proved.
Use amsart documentclass. Include amsmath, amssymb, amsthm. Output ONLY the .tex content.
"""


def _polish(proof: str, problem: str, precheck: str, reasoning: str) -> str:
    prompt = (
        POLISH_PROMPT
        .replace("PROBLEM_PLACEHOLDER", problem)
        .replace("PROOF_PLACEHOLDER", proof)
        .replace("PRECHECK_PLACEHOLDER", precheck)
    )
    return call_api(prompt, "polish", reasoning=reasoning, max_tokens=128_000)


def _typeset(proof: str, problem: str, reasoning: str) -> str:
    prompt = (
        TYPESET_PROMPT
        .replace("PROBLEM_PLACEHOLDER", problem)
        .replace("PROOF_PLACEHOLDER", proof)
    )
    return call_api(prompt, "typeset", reasoning=reasoning, max_tokens=128_000)


def finalize(
    candidate_proof: str,
    problem: str,
    reasoning: str = "high",
    kb_file: str = "failed_gaps.jsonl",
    split_chunks: bool = False,
) -> dict:
    """
    Main finalize pipeline (v2_plan.md flowchart).

    Args:
        candidate_proof: the solver's best proof attempt
        problem: the original problem statement
        reasoning: API reasoning effort
        kb_file: path to the failed-gap KB JSONL file
        split_chunks: whether to split into chunks (False = single chunk, recommended)

    Returns dict with:
        track: "A" (accepted) | "B" (progress report)
        solution_tex: LaTeX output (Track A) or None
        score: final score
        major_gaps: list of major gap descriptions
        minor_gaps: list of minor gap descriptions
        proof: final proof text
    """
    print("[pipeline] starting finalize v2")

    # §0: Generate chunks ONCE and reuse throughout
    chunks = split_into_chunks(candidate_proof, split=split_chunks)
    print(f"[pipeline] {len(chunks)} chunk(s)")
    dep_graph = build_dependency_graph(chunks)
    verified_status: dict[int, str] = {}

    # §1 (finalize): Full pre-check (numerical + citation)
    precheck_report = run_prechecker(candidate_proof, in_loop=False)
    print("[pipeline] pre-check complete")

    # §2: Score the candidate proof
    score, major_gaps, minor_gaps, _ = run_verify(
        candidate_proof, problem, precheck_report, reasoning=reasoning
    )
    print(f"[pipeline] candidate score: {score}/10, major: {len(major_gaps)}, minor: {len(minor_gaps)}")

    # §3: Major gap response
    if score <= 6:
        approach_summary = candidate_proof[:200]  # use first 200 chars as approach fingerprint
        for gap in major_gaps:
            record_major_gap(
                approach=approach_summary,
                gap_description=gap,
                lesson=f"Must prove: {gap}",
                kb_file=kb_file,
            )
        print("[pipeline] major gaps recorded to KB → Track B (do not restart solver from finalize)")
        return {
            "track": "B",
            "solution_tex": None,
            "score": score,
            "major_gaps": major_gaps,
            "minor_gaps": minor_gaps,
            "proof": candidate_proof,
            "note": "Major gaps detected. Downgrade to Track B (progress report). "
                    "KB updated — advisor should avoid this approach.",
        }

    # Score 7-8: targeted patch before polish
    current_proof = candidate_proof
    if score < ACCEPT_THRESHOLD and minor_gaps:
        acc_ctx = get_accumulated_context(chunks, verified_status, len(chunks))
        current_proof, escalated = patch_minor_gaps(
            current_proof, chunks, minor_gaps, acc_ctx, problem, reasoning
        )
        if escalated:
            print(f"[pipeline] {len(escalated)} gaps escalated after patching")
            for gap, _ in escalated:
                record_major_gap(
                    approach=candidate_proof[:200],
                    gap_description=gap,
                    lesson=f"Could not patch: {gap}",
                    kb_file=kb_file,
                )

    # Score ≥ 7 (after patching): proceed to finalize
    print("[pipeline] proceeding to Polish stage")
    pre2 = run_prechecker(current_proof, in_loop=False)
    polished = _polish(current_proof, problem, pre2, reasoning)
    if not polished.strip():
        polished = current_proof
    print("[pipeline] polish complete")

    # Verify polished proof
    score2, major2, minor2, _ = run_verify(
        polished, problem, pre2, reasoning=reasoning
    )
    print(f"[pipeline] polished score: {score2}/10")

    if score2 >= 9:
        # Accept immediately
        tex = _typeset(polished, problem, reasoning)
        return {
            "track": "A",
            "solution_tex": tex,
            "score": score2,
            "major_gaps": [],
            "minor_gaps": minor2,
            "proof": polished,
        }
    elif score2 >= 7:
        # One more targeted patch on polished
        acc_ctx2 = get_accumulated_context(chunks, verified_status, len(chunks))
        patched2, esc2 = patch_minor_gaps(
            polished, chunks, minor2, acc_ctx2, problem, reasoning
        )
        score3, _, _, _ = run_verify(patched2, problem, pre2, reasoning=reasoning)
        print(f"[pipeline] post-patch score: {score3}/10")
        if score3 >= 7:
            tex = _typeset(patched2, problem, reasoning)
            return {
                "track": "A",
                "solution_tex": tex,
                "score": score3,
                "major_gaps": [],
                "minor_gaps": [],
                "proof": patched2,
            }

    # ≤ 6 after polish → Track B (do NOT restart solver)
    print("[pipeline] polished proof still has major gaps → Track B")
    return {
        "track": "B",
        "solution_tex": None,
        "score": score2,
        "major_gaps": major2,
        "minor_gaps": minor2,
        "proof": polished,
        "note": "Post-polish major gaps. Track B only — do not restart solver.",
    }
