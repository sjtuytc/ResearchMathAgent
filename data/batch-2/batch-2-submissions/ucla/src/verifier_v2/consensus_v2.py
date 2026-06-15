"""Consensus v2: 3 parallel v4 verifiers (citation web-search + proof audit) + judge.

No pre-checker. Each verifier uses v4's combined citation-audit + verification prompt
in one web-search-enabled call. No duplicate proof transmission.

Usage:
    from verifier_v2.consensus_v2 import run_consensus_v2

    correct_text, major_gaps_text, minor_gaps_text, usage, output_text, \
        problem_solved_text, is_relaxation_bool = run_consensus_v2(
            solution=solution,
            original_problem=original_problem,
            claim=claim,
            stage_label=stage_label,
        )
"""
from __future__ import annotations
import os, re
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Judge prompt ───────────────────────────────────────────────────────────────
JUDGE_PROMPT_TEMPLATE = """\
You are a meta-verifier adjudicating three independent mathematical verification reports.
Each verifier independently audited all citations via web search and verified the proof.

# Original Problem
{original_problem}

# Claim Being Verified
{claim}

# Solution
{solution}

# Verifier 1 Report
CORRECT: {v1_correct}
CITATION_AUDIT:
{v1_citation_audit}
MAJOR_GAPS:
{v1_major_gaps}
MINOR_GAPS:
{v1_minor_gaps}
PROBLEM_SOLVED: {v1_problem_solved}
IS_RELAXATION: {v1_is_relaxation}

# Verifier 2 Report
CORRECT: {v2_correct}
CITATION_AUDIT:
{v2_citation_audit}
MAJOR_GAPS:
{v2_major_gaps}
MINOR_GAPS:
{v2_minor_gaps}
PROBLEM_SOLVED: {v2_problem_solved}
IS_RELAXATION: {v2_is_relaxation}

# Verifier 3 Report
CORRECT: {v3_correct}
CITATION_AUDIT:
{v3_citation_audit}
MAJOR_GAPS:
{v3_major_gaps}
MINOR_GAPS:
{v3_minor_gaps}
PROBLEM_SOLVED: {v3_problem_solved}
IS_RELAXATION: {v3_is_relaxation}

# Instructions

Three independent verifiers each audited all named citations via web search and verified the proof.
Your job is to produce a single authoritative verdict.

First, form your own independent assessment by reading the Problem, Claim, and Solution directly.

Then read the three reports as expert opinions. Use them as additional evidence, not votes:
- A gap or citation issue flagged by only one verifier may be the most important finding if the argument is correct.
- A gap flagged by all three may still be wrong if the argument is flawed.
- Judge each claimed gap and citation finding on its mathematical merits.

For citation issues: if multiple verifiers independently web-searched and found the same hallucination or wrong claim, that is strong evidence. If only one flagged it, investigate independently.

A gap is MAJOR if it cannot be patched without fundamentally changing the proof strategy.
A gap is MINOR if fixable within the same approach.
The proof is accepted if and only if MAJOR_GAPS is empty.

PROBLEM_SOLVED: state only what the proof actually establishes after accounting for all accepted gaps and citation failures.
IS_RELAXATION: compare PROBLEM_SOLVED against the Original Problem directly.
CONSENSUS_NOTES: explain any conflicts and how you resolved them.

<MAJOR_GAPS>
- gap (or empty if none)
</MAJOR_GAPS>
<MINOR_GAPS>
- gap (or empty if none)
</MINOR_GAPS>
<PROBLEM_SOLVED>
fully self-contained statement
</PROBLEM_SOLVED>
<IS_RELAXATION>true or false</IS_RELAXATION>
<CONSENSUS_NOTES>
conflicts and resolutions
</CONSENSUS_NOTES>""".strip()


def _parse_output(output_text: str) -> dict:
    def _get(tag: str) -> str:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", output_text, re.DOTALL)
        return m.group(1).strip() if m else ""

    audit_m = re.search(r"<CITATION_AUDIT>(.*?)</CITATION_AUDIT>", output_text, re.DOTALL)
    major_gaps = _get("MAJOR_GAPS")
    # CORRECT is derived: accepted iff major_gaps is empty
    _EMPTY = {"empty", "none", "- ...", "(none)", "(empty)", "none.", "none found",
              "no major gaps", "no gaps", "n/a", "-"}
    def _has_gaps(text):
        lines = [l.lstrip("- ").strip() for l in text.splitlines() if l.strip()]
        return any(l.lower() not in _EMPTY for l in lines)
    correct = "false" if _has_gaps(major_gaps) else "true"
    return {
        "correct":        correct,
        "major_gaps":     major_gaps,
        "minor_gaps":     _get("MINOR_GAPS"),
        "problem_solved": _get("PROBLEM_SOLVED"),
        "is_relaxation":  _get("IS_RELAXATION"),
        "citation_audit": audit_m.group(1).strip() if audit_m else "",
        "raw":            output_text,
    }


def _run_single_v4_verifier(
    solution: str,
    original_problem: str,
    claim: str,
    model: str,
    backend: str,
    stage: str,
) -> dict:
    """Run one v4 verifier instance (citation web-search + proof audit). Returns parsed dict."""
    from verifier_v2.scorer_v4 import VERIFY_PROMPT_V4
    prompt = (
        VERIFY_PROMPT_V4
        .replace("PROBLEM_PLACEHOLDER", original_problem)
        .replace("CLAIM_PLACEHOLDER", claim)
        .replace("SOLUTION_PLACEHOLDER", solution)
    )

    if backend == "openai":
        from verifier_v2._api import call_api
        raw = call_api(prompt, stage, reasoning="xhigh", max_tokens=128_000, web_search=True)
    elif backend == "openrouter":
        from verifier_v2.openrouter import call_openrouter
        raw = call_openrouter(prompt, stage, model=model, reasoning="xhigh", max_tokens=32_000)
    else:
        raise ValueError(f"Unknown backend: {backend!r}")

    result = _parse_output(raw)
    result["model"]   = model
    result["backend"] = backend
    return result


def _run_judge(
    solution: str,
    original_problem: str,
    claim: str,
    v1: dict, v2: dict, v3: dict,
    stage: str,
) -> dict:
    """Run judge on 3 v4 verifier outputs."""
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        original_problem=original_problem,
        claim=claim,
        solution=solution,
        v1_correct=v1.get("correct", "?"),
        v1_citation_audit=v1.get("citation_audit", "(not available)")[:600],
        v1_major_gaps=v1.get("major_gaps", "(not available)"),
        v1_minor_gaps=v1.get("minor_gaps", "(not available)"),
        v1_problem_solved=v1.get("problem_solved", "(not available)")[:500],
        v1_is_relaxation=v1.get("is_relaxation", "?"),
        v2_correct=v2.get("correct", "?"),
        v2_citation_audit=v2.get("citation_audit", "(not available)")[:600],
        v2_major_gaps=v2.get("major_gaps", "(not available)"),
        v2_minor_gaps=v2.get("minor_gaps", "(not available)"),
        v2_problem_solved=v2.get("problem_solved", "(not available)")[:500],
        v2_is_relaxation=v2.get("is_relaxation", "?"),
        v3_correct=v3.get("correct", "?"),
        v3_citation_audit=v3.get("citation_audit", "(not available)")[:600],
        v3_major_gaps=v3.get("major_gaps", "(not available)"),
        v3_minor_gaps=v3.get("minor_gaps", "(not available)"),
        v3_problem_solved=v3.get("problem_solved", "(not available)")[:500],
        v3_is_relaxation=v3.get("is_relaxation", "?"),
    )

    from verifier_v2._api import call_api
    raw = call_api(prompt, stage, reasoning="xhigh", max_tokens=128_000)
    result = _parse_output(raw)
    m = re.search(r"<CONSENSUS_NOTES>(.*?)</CONSENSUS_NOTES>", raw, re.DOTALL)
    result["consensus_notes"] = m.group(1).strip() if m else ""
    return result


def run_consensus_v2(
    solution: str,
    original_problem: str,
    claim: str,
    stage_label: str,
) -> tuple:
    """Run 3 parallel v4 verifiers + judge. Returns same 7-tuple as Run_Verify.

    No pre-checker. Each verifier uses v4 prompt (citation web-search + proof audit).
    """
    verifiers = [
        {
            "model":   os.getenv("CONSENSUS_MODEL_1", "gpt-5.5-pro"),
            "backend": "openai",
            "stage":   f"{stage_label}_v1",
        },
        {
            "model":   os.getenv("CONSENSUS_MODEL_2", "google/gemini-2.5-pro"),
            "backend": "openrouter",
            "stage":   f"{stage_label}_v2",
        },
        {
            "model":   os.getenv("CONSENSUS_MODEL_3", "anthropic/claude-opus-4-7"),
            "backend": "openrouter",
            "stage":   f"{stage_label}_v3",
        },
    ]

    print(f"[consensus_v2] launching {len(verifiers)} parallel v4 verifiers for {stage_label}", flush=True)

    results: list[dict | None] = [None, None, None]

    with ThreadPoolExecutor(max_workers=len(verifiers)) as ex:
        future_to_idx = {
            ex.submit(
                _run_single_v4_verifier,
                solution, original_problem, claim,
                v["model"], v["backend"], v["stage"],
            ): i
            for i, v in enumerate(verifiers)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
                print(f"[consensus_v2] verifier {idx+1} done: CORRECT={results[idx]['correct']}", flush=True)
            except Exception as e:
                print(f"[consensus_v2] verifier {idx+1} failed: {e}", flush=True)
                results[idx] = {
                    "correct": "?", "major_gaps": f"(verifier {idx+1} failed: {e})",
                    "minor_gaps": "", "problem_solved": "", "is_relaxation": "?",
                    "citation_audit": "", "raw": "",
                }

    v1, v2, v3 = results

    print(f"[consensus_v2] running judge for {stage_label}", flush=True)
    judge = _run_judge(solution, original_problem, claim, v1, v2, v3,
                       stage=f"{stage_label}_judge")
    print(f"[consensus_v2] judge done: CORRECT={judge['correct']}", flush=True)
    if judge.get("consensus_notes"):
        print(f"[consensus_v2] CONSENSUS_NOTES: {judge['consensus_notes'][:300]}", flush=True)

    correct_text    = judge["correct"]
    major_gaps_text = judge["major_gaps"]
    minor_gaps_text = judge["minor_gaps"]
    problem_solved  = judge["problem_solved"]
    is_relaxation_s = judge["is_relaxation"]
    is_relaxation_b = is_relaxation_s.lower() == "true"
    raw_output      = judge["raw"]

    usage = {
        "model": "consensus_v2", "cost_usd": 0.0, "input_tokens": 0,
        "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0,
        "elapsed_seconds": 0, "stage": stage_label, "response_id": "consensus_v2",
    }

    return (correct_text, major_gaps_text, minor_gaps_text, usage,
            raw_output, problem_solved, is_relaxation_b)
