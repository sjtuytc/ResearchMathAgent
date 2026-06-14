"""Conjecture Extractor v3 — fires when pipeline stuck ≥2 rounds."""
from __future__ import annotations

import random
import re

from ..gemini import call_gemini, flash_tag_conjectures
from ..models import AgentCall, Conjecture, ConjectureExtractOutput

_PROMPT_TEMPLATE = """\
**Conjecture Extraction Prompt v3**

### **Inputs for this Task**

**1. The Problem:**
```
{problem}
```

**2. Candidate Solution or Solutions:**
```
{solver_subset}
```
**3. Current list of facts, or graders' reports**
```
{facts_and_grader_reports}
```

**4. Currently-active conjecture tuples (with their last implication proof), if any:**
```
{active_tuples}
```

### **Execution Protocol (MUST BE FOLLOWED METICULOUSLY)**

You will perform an iterative process where a council of experts critiques each proof, clearly articulating holes in the argument. The final result is a **single more rigorous proof** that borrows ideas from provided proofs. It fixes all discovered holes by relying on **clearly-stated conjectures.** If these conjectures were proven, this proof would be complete and correct. The key objective is to use **as few conjectures as possible.**

#### **Persona Descriptions**

*   **The Council of Graders:** A team of specialist personas.
    *   **The Formalist:** A master of logic and rigor. The Formalist's sole focus is on the line-by-line validity of the argument. The Formalist checks for logical fallacies, unstated assumptions, and gaps in reasoning.
    *   **The Strategist:** An expert in mathematical problem-solving approaches. The Strategist evaluates the overall architecture of the solution. Is the chosen strategy sound? Was there a logical hole, or did it miss a simpler path? What is the easiest conjecture that could fill the logical hole?
*   **Advocatus Diaboli:** Tries to give the best possible defense of what the others consider to be a logical hole.
*   **The Conjecture Auditor:** Scourge of lazy conjecturing, with these beliefs:
    (i) *Keep each conjecture minimal*: make each individual conjecture as weak as possible (universal → existential; equality → inequality; exact → range) while still letting the tuple jointly suffice to bridge the gap. A tuple may contain 1 to 3 conjectures.
    (ii) *Make it nontrivial*: it should not just imply *the problem* in a paragraph or two.
    (iii) *Not refutable on easy or small examples* (e.g., graphs on ≤ 5 vertices, the symmetric group, etc.). If a counterexample is found, weaken the conjecture until refutation fails.
    (iv) *Does not re-instantiate a documented dead end*: for each candidate, ask: if the pipeline pursued this conjecture, would it fail by the same mechanism already recorded under some IPT-N — even under different parameters, different framing, or cosmetic relabeling? If so, reject or reformulate. Log the IPT-N matched.
    (v) *Distinct from currently-active tuples*: if a candidate's technique family matches a currently-active tuple, reject — even under different parameters or surface form. Log the match.
    *The parent problem is carefully designed, so its hypotheses are almost certainly all necessary; a strengthening of the parent (e.g., "for all n" when only multiples of 4 are needed) is likely false.*
*   **The Chief Architect:** The final arbiter who oversees the process and synthesizes the final, refined solution along with clearly stated conjectures.

---
### **Instructions**
**Configuration:** `MAX_GRADING_ROUNDS: 3`

**<internal_monologue>**

*(You will perform the following stages silently. The final output will be assembled at the end.)*

**--- BEGIN GRADING FORUM ---**

1.  **Initial Analysis (Round 0):**
    *   The Formalist and the Strategist will independently read each provided solution and write an `Initial_Critique` (containing at most 2-3 bullet points) on its potential flaws and strengths from their perspective. The Chief Architect will combine these into a single report for each solution and will also create a single `Conjecture_list` that is initially empty.

2.  **Iterative Refinement (Rounds 1 to MAX_GRADING_ROUNDS):**
    *   Initialize `round_count = 1`.
    *   **BEGIN REFINEMENT LOOP:**
        *   a. **Cognitive Reset:** The Chief Architect writes a Haiku summarizing the current state of the proof to clear the context window of repetitive phrasing.
        *   b. **Council's Critique:** For each provided solution, the Chief Architect combines their initial findings and results of the previous round into a single, consolidated `Current_Critique` containing, for each proof, the gaps identified so far. This document should list all identified weaknesses.
        *   c. **The Defense:** The Advocatus Diaboli will read the `Current_Critique` and write a `Rebuttal`. For each weakness, this argues why it is either not a flaw, a minor issue, or a misunderstanding of the proof's intent.
        *   d. **Refinement and Judgment:** The Council reads the `Rebuttal`. They must now produce a `Refined_Critique`. They will decide which of their points stand, which should be dropped in light of the defense, and which need to be re-phrased to be more precise. For each point that stands, they must explicitly state why the `Rebuttal` was unconvincing. For each gap in the solution's logic, **The Strategist** must first attempt to bridge it using standard deduction. Only if this fails may they propose a conjecture. The conjecture must be phrased in a *clear and self-contained way* so that it can be understood without access to the rest of the proof. **The Conjecture Auditor** then applies its three beliefs in turn to each proposed conjecture. Each weakening attempt and each small-example refutation attempt is logged in the `Refined_Critique`. The version added to `Conjecture_list` is the one that survives the Auditor.
        *   e. **Consolidation of Conjectures:** The Council deliberates on ways to shorten the `Conjecture_list` via suitable rephrasing. They may choose to ignore proofs that are hopelessly broken and require too many fixes.
        *   f. **Halt Condition:** The loop will halt if the `Refined_Critique` is substantially unchanged from the `Current_Critique` of the same round, or if `round_count` reaches `MAX_GRADING_ROUNDS`.
        *   g. Increment `round_count` and repeat the loop, using the `Refined_Critique` as the starting point for the next round's `Current_Critique`.
    *   **END REFINEMENT LOOP.**
    *   The final `Refined_Critique`.

3.  **Final Verdict (The Chief Architect):**
    *   **Coroner's Report:** The Chief Architect will write a one-paragraph "Coroner's Report" on each proof and assign a grade out of 7. Major gaps in reasoning incur significant penalty, and a grade of 5 or higher implies a near-correct proof.
    *   **Synthesis:** The Chief Architect will now synthesize the `Final_Council_Report` and all preceding logs into a single final proof draft that combines the best ideas of all input proofs and, together with `Conjecture_list`, represents a candidate solution path.

    The new proof starts by stating new conjectures, phrased in a self-contained way (i.e., can be completely understood by somebody who has not seen *The Problem*). This is followed by a rigorous proof that is correct and complete if the conjectures are assumed. *No sloppiness is allowed in this proof* (e.g., asserting something holds for all N after checking for N = 1 to 3, or appealing to an unnamed "well-known result").

**--- END GRADING FORUM ---**

**</internal_monologue>**

---
### **Final Output Format**

Your final response must be structured in **exactly** the following two parts.

**Part 1: The Grading Log**

*(Render a structured summary of the grading process.)*

*   **Round 1 Haiku:** [Insert Haiku]
*   **Council's Critique:** (List of strengths/weaknesses)
*   **Advocatus Diaboli's Rebuttals:** (Point-by-point defense)
*   **Final Refined Critique:** (Final list of points for this round, with justifications against the rebuttal)

*(Repeat for subsequent rounds as necessary. Include the Haiku for each round.)*

**Part 2: Completed Proof with Conjectures**

1.  **Conjecture Tuple (1–3 conjectures, jointly sufficient):** Each must be a self-contained mathematical statement that can be completely understood by somebody who has not seen *The Problem*.
2.  **Negation of Each Conjecture:** List the *negation* of each conjecture appearing in (1). This negation must be true iff the conjecture is false.
3.  **Implication Proof:** A rigorous proof of *The Problem* assuming the conjecture tuple. (This is what gets gauntlet-verified downstream as "tuple ⇒ parent".)
"""


# ── Output parser ─────────────────────────────────────────────────────────────

def _extract_tag(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


async def _parse_tagged_conjectures(raw: str) -> tuple[list[Conjecture], str]:
    """Ask Flash to tag the conjecture/negation/proof sections, then extract by tag."""
    tagged = await flash_tag_conjectures(raw)

    proof_block = _extract_tag(tagged, "proof")

    conjectures: list[Conjecture] = []
    i = 1
    while True:
        stmt = _extract_tag(tagged, f"conjecture_{i}")
        if not stmt:
            break
        neg = _extract_tag(tagged, f"negation_{i}")
        conjectures.append(Conjecture(
            id=f"C{i}",
            statement=stmt,
            negation=neg,
            bisection_sufficient=True,
            needs_child_notebook=False,
        ))
        i += 1

    return conjectures, proof_block


# ── Public API ────────────────────────────────────────────────────────────────

async def run_conjecture_extractor(
    *,
    problem: str,
    notebook_level1: str,
    solver_calls: list[AgentCall],
    grader_reports: str = "",
    active_tuples: str = "(none — initial extraction)",
    notebook_id: str,
    run_id: str,
    store=None,
) -> ConjectureExtractOutput:
    """
    Select a random subset of 2-3 solver calls (not all K — avoids divergence
    from too-different proofs), then run the extractor.
    Input 3 combines notebook Level 1 facts with grader reports.
    """
    k = min(3, len(solver_calls))
    subset = random.sample(solver_calls, k) if len(solver_calls) > k else solver_calls
    solver_subset = "\n\n---\n\n".join(
        f"[Attempt {i + 1}]\n{s.output}" for i, s in enumerate(subset)
    )

    facts_and_grader_reports = notebook_level1
    if grader_reports:
        facts_and_grader_reports += f"\n\n---\n\n[Grader Reports]\n{grader_reports}"

    prompt = _PROMPT_TEMPLATE.format(
        problem=problem,
        solver_subset=solver_subset,
        facts_and_grader_reports=facts_and_grader_reports,
        active_tuples=active_tuples,
    )
    call = await call_gemini(
        prompt,
        run_id=run_id,
        notebook_id=notebook_id,
        agent="conjecture_extractor",
        inputs={"n_solvers": len(solver_calls), "subset_size": k},
        store=store,
    )

    conjectures, proof = await _parse_tagged_conjectures(call.output)
    # Strip the Part 1 "Grading Log" (Council deliberation summary) on
    # harvest so downstream consumers (cluster agent, notebook injection,
    # Mode A child run materials) never see internal monologue prose.
    # The full raw output is still preserved in run.db via call_gemini's
    # store hook; only the in-memory `.raw` field returned to callers is
    # the stripped Part 2 onward.
    stripped_raw = await _strip_part1(call.output)
    return ConjectureExtractOutput(
        conjectures=conjectures,
        synthesized_partial_proof=proof,
        raw=stripped_raw,
    )


async def _strip_part1(text: str) -> str:
    """Three-tier strip: marker -> Flash -> full text.

    Tier 1 (marker): String-search for "**Part 2", "## Part 2", etc.
    Cheap, deterministic. Caught 100% (15/15) of real extractor outputs
    in offline test 2026-05-28.

    Tier 2 (Flash): Calls flash_extract_part2 to recognize Part 2
    semantically when the marker is missing or non-standard. Sanity-
    checked: rejects if Flash returns >= 1.1x input length.

    Tier 3 (full text): Returns input unmodified. Same defensive
    fallback as today's behavior.
    """
    # Tier 1: marker
    for marker in ("**Part 2", "## Part 2", "Part 2:", "---\n\n**Part 2"):
        idx = text.find(marker)
        if idx >= 0:
            return text[idx:].strip()

    # Tier 2: Flash
    try:
        from ..gemini import flash_extract_part2
        flash_out = await flash_extract_part2(text)
        if flash_out and len(flash_out) < len(text) * 1.1:
            return flash_out
    except Exception:
        pass

    # Tier 3: full text safety net
    return text
