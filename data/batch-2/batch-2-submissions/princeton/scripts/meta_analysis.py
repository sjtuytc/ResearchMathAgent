"""Meta-analyze multiple AI-vs-gold comparison reports for the same problem.

Companion to scripts/compare_ai_to_gold.py.  When you run the
comparator on multiple AI proofs (e.g. top_1 and top_2 from the same
run), pass the comparison reports here for cross-checking,
common-feature extraction, and reclassification of any standalone-
comparator findings that depended on pipeline context the comparator
lacked (e.g. `SNT-N` is this pipeline's notebook namespace, not a
fabricated acronym).

Usage:
    python -m scripts.meta_analysis \\
        --problem problems/q5.txt \\
        --comparisons scratch/<date>_<problem>_gold/comparison_top1.txt \\
                      scratch/<date>_<problem>_gold/comparison_top2.txt \\
        --out scratch/<date>_<problem>_gold/meta_analysis.txt

Options:
    --pipeline-context S  one-line note about pipeline-internal
                          conventions the meta-analyst should know
                          (default: the math_solver SNT-N namespace
                          rule).  Useful if a different pipeline.
    --technical-question  string identifying a specific technical
                          divergence the meta-analyst should treat as
                          a standalone expert question (with literature
                          citations).  Optional but often the most
                          valuable output.

See memory/project_gold_comparison_protocol.md for protocol details.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from math_solver.gemini import call_gemini  # noqa: E402


_DEFAULT_PIPELINE_NOTE = (
    "In this system, labels of the form `SNT-N` (Settled Named Theorem), "
    "`VF-N`, `OC-N`, `PS-N`, `RH-N`, `IPT-N` refer to entries in the AI "
    "run's shared internal notebook (a documentation convention).  They "
    "are not external citations and not fabricated acronyms.  Any "
    "comparator complaint that frames `SNT-N` as 'hallucinated' is itself "
    "an artifact of the comparator lacking the notebook in scope; you "
    "should reclassify such complaints."
)


def _prompt(*, problem: str, comparisons: list[tuple[str, str]],
            pipeline_note: str, technical_question: str) -> str:
    blocks = []
    for tag, text in comparisons:
        blocks.append(f"## Comparison report: {tag} (AI proof) vs GOLD\n\n{text}")
    comp_section = "\n\n---\n\n".join(blocks)

    tq_section = ""
    if technical_question.strip():
        tq_section = f"""

### D. Technical query

{technical_question.strip()}

Treat this as a standalone expert technical question, drawing on the
literature you know.  Answer sub-questions D.1, D.2, ... that you
identify as relevant; cite specific sources where you can.  This is
the most valuable section if the comparator reports surface a
substantive mathematical divergence between AI and GOLD.
"""

    return f"""\
You are a senior research mathematician auditing AI-generated proofs.
Multiple AI proofs for the same problem have been compared, by
separate AI comparator runs, against a human-written GOLD proof.
Your job is meta-analysis of those comparison reports.

A pipeline-context note: {pipeline_note}

---

## The Problem

{problem}

---

{comp_section}

---

## Your Meta-Analysis

Produce a structured report in the following format.

### A. Agreement between the comparisons
What do the comparison reports independently agree on?  Cite specific
findings present in two or more reports.  This is the most reliable
signal because it surfaces despite stochastic comparator variation.

### B. Disagreement between the comparisons
Where do the reports diverge — either in what they flag, or in how
they classify the same item (e.g., LEGITIMATE ALTERNATIVE vs
SUSPECT)?  For each disagreement, propose which is more likely
correct and why.

### C. Features common to ALL AI proofs (vs GOLD)
If two or more AI solutions exhibit the same divergence from GOLD,
the divergence is pipeline-wide (likely sourced in a shared notebook
entry), not solver-specific.  List each such common feature and
classify as one of:
  - SHARED LEGITIMATE ALTERNATIVE — pipeline found a different valid
    path that all solvers used
  - SHARED METHODOLOGICAL CHOICE — pipeline made a definition or
    convention choice that all solvers inherited
  - SHARED SUSPECT — pipeline-wide pattern that may indicate a
    systematic error or a misreading of the problem
{tq_section}
### E. Items the standalone comparators may have misclassified
Given the pipeline-context note above, and any other context you can
supply from your own expertise, identify any findings in the
comparison reports that you would now reclassify.  For each, name
the finding, its original classification, and your revised
classification with brief justification.

### F. Open Expert-Review Questions
List the questions that you think a domain expert (not an AI) must
adjudicate before we can be confident in the AI's solution.  Keep
the list short and prioritized.
"""


async def _run(args):
    problem = Path(args.problem).read_text()

    comparisons = []
    for path in args.comparisons:
        p = Path(path)
        tag = p.stem.replace("comparison_", "").replace("_", " ")
        comparisons.append((tag, p.read_text()))

    prompt = _prompt(
        problem=problem,
        comparisons=comparisons,
        pipeline_note=args.pipeline_context,
        technical_question=args.technical_question,
    )

    print(f"problem:     {len(problem)} chars")
    for tag, text in comparisons:
        print(f"comparison {tag}: {len(text)} chars")
    print(f"prompt:      {len(prompt)} chars")
    print()
    print("Calling Gemini for meta-analysis...")

    call = await call_gemini(
        prompt,
        run_id=args.run_id,
        notebook_id=args.notebook_id,
        agent="ai_vs_gold_meta_analyst",
        inputs={"n_comparisons": len(comparisons)},
        store=None,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(call.output)
    print(f"meta-analysis: {len(call.output)} chars -> {out_path}")
    print(f"tokens: in={call.tokens_in} out={call.tokens_out}")

    # Surface section F (open expert questions) as the actionable headline.
    m = re.search(r"### F\..*", call.output, re.DOTALL)
    if m:
        print(f"\n=== F (OPEN EXPERT QUESTIONS) ===\n{m.group(0).strip()[:1200]}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--problem", required=True, help="path to problem statement")
    p.add_argument("--comparisons", nargs="+", required=True,
                   help="paths to comparison reports from scripts.compare_ai_to_gold")
    p.add_argument("--out", required=True, help="output path for meta-analysis")
    p.add_argument("--pipeline-context", default=_DEFAULT_PIPELINE_NOTE,
                   help="one-line pipeline-internal convention note "
                        "(default: math_solver SNT-N namespace rule)")
    p.add_argument("--technical-question", default="",
                   help="a specific technical divergence the meta-analyst "
                        "should treat as a standalone expert question; "
                        "include worked numeric examples and literature "
                        "hints where helpful")
    p.add_argument("--run-id", default="gold_meta_analysis",
                   help="identifier passed to call_gemini (cosmetic)")
    p.add_argument("--notebook-id", default="GOLD_META",
                   help="identifier passed to call_gemini (cosmetic)")
    args = p.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
