"""Compare an AI-generated proof to a human-written gold proof.

This is the durable artifact of the 2026-05-19 Q5 gold-grader work.
See memory/project_gold_comparison_protocol.md for the full protocol.

We ask a single Gemini agent to read both proofs, identify load-bearing
steps in each, list similarities/dissimilarities, and surface gaps in
the AI proof while explicitly accepting that human proofs contain
non-serious elisions too.  No BS-detector or grader pre-loading; this
is comparison, not gauntlet grading.

Usage:
    python -m scripts.compare_ai_to_gold \\
        --problem problems/q5.txt \\
        --gold ~/claudecode/gold/q5/gold_q5_prose.md \\
        --ai runs/<run_id>/top_solution_1.txt \\
        --out scratch/<date>_<problem>_gold/comparison_top1.txt

Options:
    --strip-lines N   strip first N lines of the AI file (default 2,
                      drops the "Rank N - Stage X, Solver Y, Score Z/7"
                      header that `top_solution_*.txt` files carry).
                      Pass --strip-lines 0 if your AI file is bare.
    --gold-context S  one-line description of the gold source (e.g.
                      "Excerpt from Smith-Jones paper, deliberately
                      terse"). Optional; useful when the gold is
                      excerpted and the comparator should not mistake
                      length-induced terseness for AI-style elision.

Quarantine: the gold file MUST live outside `math_solver/`. See
~/claudecode/gold/README.md.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

# Make `python -m scripts.<name>` work from the math_solver root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from math_solver.gemini import call_gemini  # noqa: E402


def _prompt(*, problem: str, gold: str, ai: str, gold_context: str) -> str:
    return f"""\
You are a senior research mathematician comparing two solutions to the
same problem.  One is human-written (the GOLD, by the problem's
author).  The other is AI-generated (the AI).

Your task:
  1. Analyze whether the AI proof is similar to or different from GOLD.
  2. List points of similarity and dissimilarity in lemmas and proof
     steps.
  3. Use that analysis to identify potential chinks or gaps in the AI
     proof.

Important calibration: human proofs always contain gaps the author
considers non-serious — elisions, citations to earlier work, "by the
same argument as ...", "by standard machinery", and so on.  Do not
penalize the AI for gaps that mirror similar elisions in the GOLD;
those are within the bar set by the gold standard.  Penalize only
gaps where the AI elides something that the GOLD spells out, or
invokes machinery the GOLD does not use, or substitutes a step in a
way that does not follow from any identifiable mathematical
mechanism.

---

## The Problem

{problem}

---

## GOLD (human-written expert solution)

({gold_context})

{gold}

---

## AI (AI-generated solution)

{ai}

---

## Your Comparison Report

Produce a structured report in the following format.  Quote claims
verbatim when contrasting them; do not paraphrase load-bearing
statements.

### 1. Load-Bearing Steps in GOLD
List the main definitions, lemmas, and proof steps that carry the
weight of GOLD's argument.  For each, give it a short name and quote
its key claim.  Aim for the spine of the argument, not every
proposition.

### 2. Load-Bearing Steps in AI
Same exercise for the AI proof.  List the spine of the AI's argument
with short names and quoted key claims.

### 3. Similarities
Match steps that appear in BOTH proofs in substantively the same
form.  For each match, name the step on both sides.  If the content
is equivalent but the formulation differs, mark it
EQUIVALENT-REFORMULATION and explain how the two phrasings reduce to
each other.

### 4. Dissimilarities
- AI-ONLY: steps in the AI proof with no counterpart in GOLD.
  Classify each as:
    (a) LEGITIMATE ALTERNATIVE — a valid different path to the same
        conclusion
    (b) UNNECESSARY ELABORATION — extra machinery not strictly needed
    (c) SUSPECT — invokes a result outside its domain, or appears to
        fabricate a step that GOLD's structure shows is not needed
  Quote and explain each.
- GOLD-ONLY: steps in GOLD with no counterpart in the AI proof.  For
  each, note whether the AI appears to have a valid substitute or to
  have skipped the step entirely.

### 5. Contradictions
Any claim in the AI that contradicts a statement in GOLD?  Quote both
sides for each contradiction.  Pay special attention to: definitions
of objects shared by both proofs, the role of any characteristic-
function-like construction, and the precise form of the main
characterization theorem.

### 6. Gaps in the AI Proof
List gaps and elisions in the AI proof.  For each, classify:
  - MIRRORS GOLD — GOLD has an equivalent elision; this is within
    the human-acceptable standard.
  - NEW GAP — GOLD spells the step out, or its structure avoids
    needing it, but the AI elides.  This is a substantive concern.
  - HALLUCINATED — the AI asserts a step that does not follow from
    any identifiable mathematical mechanism, GOLD or otherwise.

### 7. Final Assessment
One paragraph.  Is the AI proof substantively similar to GOLD?
Where it differs, has it found a legitimate alternative or has it a
real hole?  Cite specific evidence from sections 1-6.  Avoid
pass/fail framing; the question is similarity and gap inventory.
"""


async def _run(args):
    problem = Path(args.problem).read_text()
    gold = Path(args.gold).read_text()
    ai_lines = Path(args.ai).read_text().splitlines()
    ai = "\n".join(ai_lines[args.strip_lines:])

    prompt = _prompt(
        problem=problem,
        gold=gold,
        ai=ai,
        gold_context=args.gold_context,
    )

    print(f"problem: {len(problem)} chars")
    print(f"gold:    {len(gold)} chars")
    print(f"ai:      {len(ai)} chars  (stripped first {args.strip_lines} lines)")
    print(f"prompt:  {len(prompt)} chars")
    print()
    print("Calling Gemini for comparison...")

    call = await call_gemini(
        prompt,
        run_id=args.run_id,
        notebook_id=args.notebook_id,
        agent="ai_vs_gold_comparator",
        inputs={"ai_path": str(args.ai), "gold_path": str(args.gold)},
        store=None,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(call.output)
    print(f"comparison: {len(call.output)} chars -> {out_path}")
    print(f"tokens: in={call.tokens_in} out={call.tokens_out}")

    m = re.search(r"### 7\. Final Assessment\s*\n+(.+?)(?=\n###|\Z)",
                  call.output, re.DOTALL)
    if m:
        print(f"\n=== FINAL ASSESSMENT ===\n{m.group(1).strip()[:600]}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--problem", required=True, help="path to problem statement")
    p.add_argument("--gold",    required=True, help="path to gold proof (markdown/text)")
    p.add_argument("--ai",      required=True, help="path to AI proof")
    p.add_argument("--out",     required=True, help="output path for comparison report")
    p.add_argument("--strip-lines", type=int, default=2,
                   help="strip first N lines of the AI file (default 2, "
                        "for Rank/Stage/Solver/Score header)")
    p.add_argument("--gold-context", default="Human-written reference solution.",
                   help="one-line description of the gold source; "
                        "useful when gold is an excerpt that is deliberately terse")
    p.add_argument("--run-id", default="gold_compare",
                   help="identifier passed to call_gemini (cosmetic)")
    p.add_argument("--notebook-id", default="GOLD_COMPARE",
                   help="identifier passed to call_gemini (cosmetic)")
    args = p.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
