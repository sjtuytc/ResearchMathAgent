"""§2: Run_Verify with 1-10 scoring and major/minor gap classification."""
from __future__ import annotations
import re
from ._api import call_api

ACCEPT_THRESHOLD = int(__import__("os").getenv("VERIFY_ACCEPT_THRESHOLD", "9"))

VERIFY_PROMPT = """\
You are a rigorous mathematical referee. Check the following solution carefully.

# Problem
PROBLEM_PLACEHOLDER

# Pre-Verification Report
PRECHECK_PLACEHOLDER

# Solution
SOLUTION_PLACEHOLDER

# Instructions
The Pre-Verification Report above flags issues found by symbolic tools and citation analysis.
Pay extra attention to CRITICAL and ERROR items.

Score the proof 1-10:
- 10: fully rigorous, every step proved, all citations present
- 9:  near-complete, only trivial/cosmetic issues
- 8:  one minor fixable gap
- 6-7: one significant gap or multiple minor
- 4-5: key lemma missing or major step unjustified
- 1-3: fundamental flaw or proof sketch only

Classify gaps:
- MAJOR: gaps that invalidate the proof strategy (missing key lemma, circular, wrong theorem)
- MINOR: gaps fixable without changing approach (missing citation, routine step unjustified)

Standard graduate-level analysis closure steps (Borel regularity, L² density, L²-contraction,
Urysohn, dominated convergence, Fubini) are NOT gaps — they are routine and should not be listed.

Output:
<SCORE>integer 1-10</SCORE>
<MAJOR_GAPS>
- gap (or empty)
</MAJOR_GAPS>
<MINOR_GAPS>
- gap (or empty)
</MINOR_GAPS>
"""


def run_verify(
    solution: str,
    problem: str,
    precheck_report: str,
    reasoning: str = "high",
) -> tuple[int, list[str], list[str], str]:
    """
    Run the main verifier with scoring.

    Returns: (score, major_gaps, minor_gaps, raw_output)
    - score: 1-10
    - major_gaps: list of major gap descriptions
    - minor_gaps: list of minor gap descriptions
    - raw_output: full model response
    """
    prompt = (
        VERIFY_PROMPT
        .replace("PROBLEM_PLACEHOLDER", problem)
        .replace("PRECHECK_PLACEHOLDER", precheck_report)
        .replace("SOLUTION_PLACEHOLDER", solution)
    )
    raw = call_api(prompt, "run_verify", reasoning=reasoning, max_tokens=32_000)

    score_m = re.search(r"<SCORE>\s*(\d+)\s*</SCORE>", raw)
    major_m = re.search(r"<MAJOR_GAPS>(.*?)</MAJOR_GAPS>", raw, re.DOTALL)
    minor_m = re.search(r"<MINOR_GAPS>(.*?)</MINOR_GAPS>", raw, re.DOTALL)

    score = int(score_m.group(1)) if score_m else 0

    def parse_gaps(text: str) -> list[str]:
        if not text:
            return []
        return [line.lstrip("- ").strip() for line in text.strip().splitlines()
                if line.strip() and not line.strip().startswith("#")]

    major_gaps = parse_gaps(major_m.group(1)) if major_m else []
    minor_gaps = parse_gaps(minor_m.group(1)) if minor_m else []

    # Filter out empty or placeholder entries
    major_gaps = [g for g in major_gaps if g and g.lower() not in ("empty", "none", "or empty")]
    minor_gaps = [g for g in minor_gaps if g and g.lower() not in ("empty", "none", "or empty")]

    return score, major_gaps, minor_gaps, raw


def is_accepted(score: int) -> bool:
    return score >= ACCEPT_THRESHOLD
