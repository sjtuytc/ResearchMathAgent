"""Consensus verifier: 3 parallel models + judge adjudication.

Usage (from harness):
    from verifier_v2.consensus import run_consensus_verify

    correct_text, major_gaps_text, minor_gaps_text, usage, output_text, \
        problem_solved_text, is_relaxation_bool = run_consensus_verify(
            solution=solution,
            original_problem=original_problem,
            claim=claim,
            precheck_report=precheck_report,
            stage_label=stage_label,
        )
"""
from __future__ import annotations
import os, re
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Judge prompt ───────────────────────────────────────────────────────────────
JUDGE_PROMPT_TEMPLATE = """\
You are a meta-verifier adjudicating three independent mathematical verification reports.

# Original Problem
{original_problem}

# Claim Being Verified
{claim}

# Solution
{solution}

# Pre-checker Report
{precheck_report}

# Verifier 1 Report
CORRECT: {v1_correct}
MAJOR_GAPS:
{v1_major_gaps}
MINOR_GAPS:
{v1_minor_gaps}
PROBLEM_SOLVED: {v1_problem_solved}
IS_RELAXATION: {v1_is_relaxation}

# Verifier 2 Report
CORRECT: {v2_correct}
MAJOR_GAPS:
{v2_major_gaps}
MINOR_GAPS:
{v2_minor_gaps}
PROBLEM_SOLVED: {v2_problem_solved}
IS_RELAXATION: {v2_is_relaxation}

# Verifier 3 Report
CORRECT: {v3_correct}
MAJOR_GAPS:
{v3_major_gaps}
MINOR_GAPS:
{v3_minor_gaps}
PROBLEM_SOLVED: {v3_problem_solved}
IS_RELAXATION: {v3_is_relaxation}

# Instructions

Three independent verifiers checked this solution. Your job is to produce a single authoritative verdict.

First, form your own independent assessment of the proof by reading the Problem, Claim, Solution, and Pre-checker Report directly. Do this before evaluating what the verifiers said.

Then read the three verifier reports as expert opinions. Use them as additional evidence, not as votes:
- A gap flagged by only one verifier may be the most important finding if the argument is correct.
- A gap flagged by all three verifiers may still be wrong or trivial if the argument is flawed.
- Judge each claimed gap on its mathematical merits. The number of verifiers who flagged it is irrelevant to your classification.

Definitions:
- MAJOR gap: cannot be patched without fundamentally changing the proof strategy. If present, CORRECT must be false.
- MINOR gap: fixable within the same proof approach (missing citation, routine step unjustified, repairable error).

Additional requirements:
- Quantitative audit: verify that all claimed bounds, exponents, and asymptotic dependencies follow algebraically from what was proved, not just asserted. Flag any mismatch as a MAJOR gap.
- PROBLEM_SOLVED: state only what the proof actually establishes after accounting for all gaps you accept as real. Do not merely restate the Claim.
- IS_RELAXATION: compare your PROBLEM_SOLVED against the Original Problem directly.
- CORRECT: true if and only if MAJOR_GAPS is empty.
- CONSENSUS_NOTES: for each gap where verifiers disagreed, explain your mathematical reasoning for accepting or rejecting it.

Output format:
<CORRECT>true or false</CORRECT>
<MAJOR_GAPS>
- gap description (or leave empty)
</MAJOR_GAPS>
<MINOR_GAPS>
- gap description (or leave empty)
</MINOR_GAPS>
<PROBLEM_SOLVED>
fully self-contained statement of what the proof actually establishes
</PROBLEM_SOLVED>
<IS_RELAXATION>true or false</IS_RELAXATION>
<CONSENSUS_NOTES>
conflicts between verifiers and your resolution of each
</CONSENSUS_NOTES>""".strip()


def _parse_verifier_output(output_text: str) -> dict:
    """Parse CORRECT/MAJOR_GAPS/MINOR_GAPS/PROBLEM_SOLVED/IS_RELAXATION from verifier output."""
    def _get(tag: str) -> str:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", output_text, re.DOTALL)
        return m.group(1).strip() if m else ""

    return {
        "correct":       _get("CORRECT") or "?",
        "major_gaps":    _get("MAJOR_GAPS"),
        "minor_gaps":    _get("MINOR_GAPS"),
        "problem_solved": _get("PROBLEM_SOLVED"),
        "is_relaxation": _get("IS_RELAXATION"),
        "raw":           output_text,
    }


def _run_single_verifier(
    solution: str,
    original_problem: str,
    claim: str,
    precheck_report: str,
    model: str,
    backend: str,
    stage: str,
    verify_prompt_template: str,
) -> dict:
    """Run one verifier instance. Returns parsed output dict + cost."""
    prompt = verify_prompt_template.format(
        original_problem=original_problem,
        claim=claim,
        solution=solution,
    )

    if backend == "openai":
        from verifier_v2._api import call_api
        raw = call_api(prompt, stage, reasoning="xhigh", max_tokens=128_000)
        cost = 0.0  # tracked in _api._COST_LOG
    elif backend == "openrouter":
        from verifier_v2.openrouter import call_openrouter
        raw = call_openrouter(prompt, stage, model=model, reasoning="xhigh", max_tokens=32_000)
        cost = 0.0  # tracked in openrouter._COST_LOG
    else:
        raise ValueError(f"Unknown backend: {backend!r}")

    result = _parse_verifier_output(raw)
    result["model"] = model
    result["backend"] = backend
    result["cost"] = cost
    return result


def _run_judge(
    solution: str,
    original_problem: str,
    claim: str,
    precheck_report: str,
    v1: dict,
    v2: dict,
    v3: dict,
    stage: str,
) -> dict:
    """Run the judge on 3 verifier outputs. Returns parsed output dict."""
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        original_problem=original_problem,
        claim=claim,
        solution=solution,
        precheck_report=precheck_report,
        v1_correct=v1.get("correct", "?"),
        v1_major_gaps=v1.get("major_gaps", "(not available)"),
        v1_minor_gaps=v1.get("minor_gaps", "(not available)"),
        v1_problem_solved=v1.get("problem_solved", "(not available)")[:500],
        v1_is_relaxation=v1.get("is_relaxation", "?"),
        v2_correct=v2.get("correct", "?"),
        v2_major_gaps=v2.get("major_gaps", "(not available)"),
        v2_minor_gaps=v2.get("minor_gaps", "(not available)"),
        v2_problem_solved=v2.get("problem_solved", "(not available)")[:500],
        v2_is_relaxation=v2.get("is_relaxation", "?"),
        v3_correct=v3.get("correct", "?"),
        v3_major_gaps=v3.get("major_gaps", "(not available)"),
        v3_minor_gaps=v3.get("minor_gaps", "(not available)"),
        v3_problem_solved=v3.get("problem_solved", "(not available)")[:500],
        v3_is_relaxation=v3.get("is_relaxation", "?"),
    )

    from verifier_v2._api import call_api
    raw = call_api(prompt, stage, reasoning="xhigh", max_tokens=128_000)

    result = _parse_verifier_output(raw)
    m = re.search(r"<CONSENSUS_NOTES>(.*?)</CONSENSUS_NOTES>", raw, re.DOTALL)
    result["consensus_notes"] = m.group(1).strip() if m else ""
    result["raw"] = raw
    return result


def run_consensus_verify(
    solution: str,
    original_problem: str,
    claim: str,
    precheck_report: str,
    stage_label: str,
    verify_prompt_template: str,
) -> tuple:
    """Run 3 parallel verifiers + judge. Returns same 7-tuple as Run_Verify in harness_v3.

    Returns:
        (correct_text, major_gaps_text, minor_gaps_text, usage_dict,
         raw_output_text, problem_solved_text, is_relaxation_bool)
    """
    # Verifier model config
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

    print(f"[consensus] launching {len(verifiers)} parallel verifiers for {stage_label}", flush=True)

    results: list[dict | None] = [None, None, None]

    with ThreadPoolExecutor(max_workers=len(verifiers)) as ex:
        future_to_idx = {
            ex.submit(
                _run_single_verifier,
                solution, original_problem, claim, precheck_report,
                v["model"], v["backend"], v["stage"], verify_prompt_template,
            ): i
            for i, v in enumerate(verifiers)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
                print(f"[consensus] verifier {idx+1} done: CORRECT={results[idx]['correct']}", flush=True)
            except Exception as e:
                print(f"[consensus] verifier {idx+1} failed: {e}", flush=True)
                results[idx] = {
                    "correct": "?", "major_gaps": f"(verifier {idx+1} failed: {e})",
                    "minor_gaps": "", "problem_solved": "", "is_relaxation": "?",
                    "raw": "", "model": verifiers[idx]["model"], "backend": verifiers[idx]["backend"],
                }

    v1, v2, v3 = results

    # Run judge
    print(f"[consensus] running judge for {stage_label}", flush=True)
    judge = _run_judge(
        solution, original_problem, claim, precheck_report,
        v1, v2, v3,
        stage=f"{stage_label}_judge",
    )
    print(f"[consensus] judge done: CORRECT={judge['correct']}", flush=True)
    if judge.get("consensus_notes"):
        print(f"[consensus] CONSENSUS_NOTES: {judge['consensus_notes'][:300]}", flush=True)

    correct_text     = judge["correct"]
    major_gaps_text  = judge["major_gaps"]
    minor_gaps_text  = judge["minor_gaps"]
    problem_solved   = judge["problem_solved"]
    is_relaxation_s  = judge["is_relaxation"]
    is_relaxation_b  = is_relaxation_s.lower() == "true"
    raw_output       = judge["raw"]

    usage = {
        "model": "consensus_v1",
        "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
        "reasoning_tokens": 0, "total_tokens": 0, "elapsed_seconds": 0,
        "stage": stage_label, "response_id": "consensus",
    }

    return (correct_text, major_gaps_text, minor_gaps_text, usage,
            raw_output, problem_solved, is_relaxation_b)
