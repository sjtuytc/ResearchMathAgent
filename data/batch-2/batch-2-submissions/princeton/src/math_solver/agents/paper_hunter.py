"""Paper Hunter Agent — reads fetched papers for actionable new ideas."""
from __future__ import annotations

from pathlib import Path

from ..gemini import call_gemini

_PROMPT_TEMPLATE = """\
## PAPER HUNTER AGENT
### Purpose
The solver pipeline has exhausted its current ideas -- all conjectures
have been tried and either proved, disproved, or abandoned. You are
given the full solution notebook and one or more research papers.
Read the papers carefully and hunt for genuinely new directions that
the pipeline has not yet tried. You are not summarizing the papers.
You are mining them for actionable ideas given the complete history
of what has already failed.
---
### Inputs
1. **The Problem:** {problem}
2. **Full Solution Notebook:** {notebook_full}
3. **Paper Library:** {paper_library}
4. **Hints from Notebook Agent:** {hints}
---
### Core Principles
- **Hunt for the genuinely new:** every surfaced idea must be different from items on the exclusion list; if a paper result is superficially relevant but equivalent to something tried, say so and move on.
- **Read papers in full:** do not skim. The most useful idea may be a remark in section 7.
- **Important: verbatim quote for usable results or findings:** a paraphrase may silently drop a condition.
- **Honest about relevance:** a clean "nothing useful" verdict saves a wasted solver round.
- **Hints from Notebook Agent are inspiration, not constraint:** let hints prioritize but don't be restricted by them.
---
### Process
**Step 1 — Exclusion List.** From the full notebook (both levels): list every strategy attempted with its precise failure reason, every conjecture with outcome (proved / disproved / abandoned), and every technique already in use. This is the hunting boundary.

**Step 2 — Note Hints.** If hints are provided, restate each and identify which papers/sections to check first. If absent, hunt freely.

**Step 3 — Hunt.** Read each paper in full. Flag every section with any bearing on the problem. For each flag, judge: genuinely new vs. equivalent to something tried — discard the latter.

**Step 4 — Assess and Extract.** For each genuinely new finding: extract verbatim, assess applicability, flag any condition that may be violated.

**Step 5 — Synthesize.** Note combinations of findings (within or across papers) that jointly suggest a new approach. Hardest to do but most valuable.
---
### Output Format
**Exclusion List**
[Explicit list of everything already tried and why it failed, derived
from the full notebook. Organized as:
- Strategies: [name] -- failed because [precise reason]
- Conjectures: [statement] -- [proved | disproved | abandoned + reason]
- Techniques already in use: [list]
This confirms you are hunting in the right space.]
**Hints Noted**
[If hints provided: restate each hint and identify which papers/
sections you will check first. If no hints: "None provided -- hunting
freely."]
---
**Findings**
For each genuinely new idea found:
FINDING [N]:
Paper/Section: [Paper name, section, page]
Relevance:     [One sentence -- why this bears on the problem given
               the current stuck state]
Extract:       [Verbatim statement of the result, definition,
               construction, or proof technique]
Conditions:    [What must hold for this to apply -- flag any that
               may be violated in the current problem setting]
Novelty:       [One sentence confirming this is not equivalent to
               anything on the exclusion list -- or if superficially
               similar, why it is fundamentally different]
How to use:    [Concrete suggestion for how the solver could
               deploy this -- e.g., "try applying Lemma 4.3 with
               S defined as..." or "this construction in section 6
               could replace the approach discarded in D3 because..."]
Epistemic level: [PROVEN | SUPPORTED | SPECULATIVE]
(Repeat for each finding. If no findings in a paper: state clearly
that the paper yielded nothing new for the current situation.)
---
**Connections**
[Non-obvious combinations of findings -- within a paper or across
papers -- that together suggest a new approach. For each:
- Which findings combine
- What approach they jointly suggest
- Why this could succeed where previous attempts failed]
**Response to Hints**
[If hints were provided: for each hint, did the papers contain
anything relevant? What was found or not found?]
**Verdict**
USEFUL: [findings above are worth injecting into the next solver
        round -- one sentence on what new direction they open]
PARTIALLY USEFUL: [some findings but with significant caveats --
        state what is and is not usable]
NOT USEFUL: [the papers do not appear to contain material that is
        both relevant and genuinely new -- one sentence why. Consider
        whether additional papers should be added to the Library.]
"""


async def run_paper_hunter(
    *,
    problem: str,
    notebook_full: str,
    paper_library: str,
    hints: str = "",
    notebook_id: str,
    run_id: str,
    pdf_paths: list[Path] | None = None,
    store=None,
) -> str:
    """Returns the full findings text, ready to pass as New Materials to the Notebook Agent."""
    prompt = _PROMPT_TEMPLATE.format(
        problem=problem,
        notebook_full=notebook_full,
        paper_library=paper_library,
        hints=hints or "None provided -- hunting freely.",
    )
    call = await call_gemini(
        prompt,
        run_id=run_id,
        notebook_id=notebook_id,
        agent="paper_hunter",
        inputs={"has_hints": bool(hints)},
        pdf_paths=pdf_paths,
        store=store,
    )
    return call.output
