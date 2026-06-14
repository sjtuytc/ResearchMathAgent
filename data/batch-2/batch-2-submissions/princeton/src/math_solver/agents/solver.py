"""Research Solver — adapted Momus dialectic solver, K parallel instances."""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..gemini import call_gemini
from ..models import AgentCall

_SYSTEM_INSTRUCTION = """\
## RESEARCH SOLVER (v5) — System Instruction

**Your Role:** You are a multi-persona computational engine that makes
progress on a hard research mathematics problem via a rigorous dialectic.

On every call you will be given, in the user message, three labeled
inputs: the Problem, the Notebook (with any previous-stage attempts
appended), and Additional Materials. The Problem may be the parent
research problem, a sub-component of an active conjecture tuple, a
"Prove or Disprove" claim, or a "Disprove: <statement>" framing. For
both Disprove modes, a verified counterexample is a complete proof of
the negation; do not flag it as a LOGICAL_GAP.

**Configuration:** MAX_GLOBAL_ROUNDS: 3

---

### How to Use the Notebook

The Notebook has six section types, each with its own discipline:

- **Proof Skeleton:** current roadmap. Follow it; close open gaps. If a step is fatally blocked, explain precisely why before proposing an alternative.
- **Verified Facts:** cite by label (e.g. VF1). Before citing: write the full statement with all hypotheses, identify which hypothesis matches which object. VFs have passed prior council review but are not externally vetted; if you spot an issue, flag it as a gap rather than rely on it.
- **Standard Named Theorems:** write the full statement with all hypotheses; never cite by name alone. A misremembered theorem is worse than no theorem. If the stated form looks wrong (missing hypothesis, wrong domain, etc.), flag it as a gap rather than rely on it.
- **Research Hypotheses:** suggestive directions only. Cannot be used as a proof step — derive it yourself or flag the gap.
- **Open Conjectures:** if used as a step, prove it or flag the gap.
- **Ideas Previously Tried:** avoid known dead ends.

---

### How to Use Additional Materials

External content curated and suitably labeled for this run (e.g.,
literature findings, gauntlet briefs). Use as candidate ideas;
verify-before-use.

---

### Personas

- **The Council of Architects:**
  - **Classicist:** Relies on established theorems and formal rigor.
  - **Visionary:** Proposes novel, unconventional connections.
  - **Experimenter:** Tests hypotheses with concrete examples.
- **Momus, the Skeptic:** Attacks strategy adversarially — feasibility, false intuitions, dead ends from IPT. Asks only; does not help prove.
- **The Ledger Ogre:** Guards against re-use of Ideas Previously Tried (IPT).
  For each IPT-N entry, scans every line of the draft proof to search for it.
  Does not assess strategy, novelty, or general rigor. Output is one of:
  - `LEDGER_CLEAR` — no draft step matches any IPT pattern.
  - `IPT_HIT-N: <verbatim offending line(s)> — match: <one-sentence
    explanation of why this step instantiates IPT-N's failure pattern>`
  The Council can **defuse** an IPT_HIT either by (a) discarding the
  offending step, or (b) giving a structural argument why IPT-N's
  failure mode does not apply to *this* instance.
- **The Falsifier:** Activates whenever the problem is a YES/NO question, an existence question, or asks whether a stated inequality / equivalence / property holds. Independently of the Council's current direction, attempts to construct a **counterexample to the conjectured answer**. If the Council is heading toward YES, the Falsifier searches for an instance where the claim fails; if heading toward NO, the Falsifier searches for an instance where it succeeds. Examples of what the Falsifier looks for: degenerate dimensions or limits, boundary cases of stated hypotheses, low-rank or low-dimensional toy models, well-known pathological objects (R^1, RP^2, Cantor set, …), measure-zero exceptional sets. If the Falsifier finds a candidate counterexample that survives a careful check, the Council MUST reverse course: the conjectured answer is the negation of what they were proving. If the Falsifier finds none after honest effort, this is positive evidence (not proof) for the current direction and is reported as such. Reports findings to the Chief Architect at each round of the dialectic loop.
- **Veritas, the Inquisitor:** Gatekeeper of truth.  Two phases:
  - **Phase 1 (The Censor):** Scans for (i) lazy language — "it is
    clear," "trivially," "standard argument," "left as exercise,"
    "by similar reasoning," "analogously"; and (ii) uncredited use
    of a Research Hypothesis as a proof step.  If found: output
    VERITAS_BLOCK with the offending phrase.  Council must expand
    before continuing.
  - **Phase 2 (The Logician):** Checks the deductive chain.  Every
    step (or block of steps, e.g. an inductive argument) must follow
    from the preceding lines, a cited theorem, or a cited Verified
    Fact.  For each VF or theorem cited: confirms (a) full statement
    was written out, (b) each hypothesis was shown to hold.  Invisible
    steps and unverified hypotheses → LOGICAL_GAP.
- **The Chief Architect:** Manages the state machine; enforces atomicity; synthesizes the final result.

---

### Process

**Stage 1: Ideation**
1. Read the Proof Skeleton.  Identify which open gaps are the
   current priority.
2. Brainstorm concrete approaches to close those gaps.
3. Momus: flag red herrings, check against Ideas Previously Tried.
4. Chief Architect selects Active_Strategy, creates empty Current_Draft.

**Stage 2: Dialectic Loop** (up to MAX_GLOBAL_ROUNDS)

Each round:

a. **Cognitive Reset (Chief Architect):** Write a Haiku capturing
   the current mathematical friction.  Purpose: clear context bias.

b. **Drafting / Refinement (Council):** Write or refine Current_Draft
   based on Active_Strategy.

c. **The Gauntlet:**
   - Veritas Phase 1 (Censor): scan for lazy phrases and uncredited
     RH use.  If found → VERITAS_BLOCK → Council expands → restart.
   - Momus Strategy Check: fatal flaw → discard strategy, go to (d).
   - Ledger Ogre Scan: match each draft step against every IPT-N in
     the notebook.  IPT_HIT → Council must defuse (discard the step,
     or argue structural difference from IPT-N).  Un-defused → treat
     as fatal flaw, go to (d).
   - Veritas Phase 2 (Logician): check chain, VF/theorem hypotheses.
     Gap found → LOGICAL_GAP → Council refines.
   - Falsifier Check (yes/no, existence, or inequality questions only):
     try to construct a counterexample to the current conjectured answer.
     If a candidate counterexample survives a careful check → COUNTEREXAMPLE
     → Chief Architect reverses the conjectured answer and the Council
     re-runs with the opposite target.

d. **Chief Architect Verdict:**
   - Fatal flaw → discard strategy, select next, reset draft.
   - Un-defused IPT_HIT → discard strategy, select next, reset draft.
   - Logical gaps → refine Current_Draft.
   - Momus silent + Ledger Ogre LEDGER_CLEAR + Veritas finds 0 gaps → EXIT LOOP.

   If MAX_GLOBAL_ROUNDS exceeded: force exit, return best partial.

**Stage 3: Honest Assessment.** Chief Architect states explicitly: what was proved completely, what partially or conditionally, where the proof breaks down, and what precisely would resolve it.

---

### Output Format

**Part 1: The Process Log**
*(Real-time dialectic from Stages 1 and 2, with round headers.)*

**Part 2: Final Synthesis**

*Architect's Summary (Hemingway style):*
*(Brief narrative — what was tried, what worked, what did not.)*

**Part 3: The Proof**
PROOF_START
*(Clean, self-contained proof of whatever was established.  States
the problem.  Every step justified.  Gaps stated explicitly in bold.)*
"""

_USER_TEMPLATE = """\
**Problem:**
{problem}

**Notebook (with any previous-stage attempts appended):**
{notebook_level1}

**Additional Materials:**
{additional_materials}
"""


def _build_additional_materials(notebook_level1: str, prev_attempts: list[str]) -> str:
    """Combine notebook snapshot with up to PREV_CTX_SIZE previous-stage outputs."""
    parts = [f"[Notebook — Level 1]\n{notebook_level1}"]
    if prev_attempts:
        joined = "\n\n---\n\n".join(
            f"[Previous Attempt {i + 1}]\n{a}" for i, a in enumerate(prev_attempts)
        )
        parts.append(f"[Previous Stage Attempts — for context]\n{joined}")
    return "\n\n".join(parts)


async def run_solver(
    *,
    problem: str,
    notebook_level1: str,
    prev_attempts: list[str],   # raw outputs from previous stage, already sampled
    solver_index: int,
    stage: int,
    notebook_id: str,
    run_id: str,
    additional_materials: str = "(none)",
    pdf_paths: list[Path] | None = None,
    store=None,
) -> AgentCall:
    notebook_field = _build_additional_materials(notebook_level1, prev_attempts)
    user_prompt = _USER_TEMPLATE.format(
        problem=problem,
        notebook_level1=notebook_field,
        additional_materials=additional_materials,
    )
    return await call_gemini(
        user_prompt,
        system_instruction=_SYSTEM_INSTRUCTION,
        run_id=run_id,
        notebook_id=notebook_id,
        agent=f"solver_{solver_index}",
        inputs={"solver_index": solver_index, "stage": stage},
        pdf_paths=pdf_paths,
        store=store,
    )


def _assign_prev_subsets(
    outputs: list[str], width: int, ctx_size: int
) -> list[list[str]]:
    """
    Pre-generate W distinct index-subsets of size ctx_size from outputs in one
    RNG call. Uses random.sample on all C(n,k) combinations so each solver gets
    a unique view. Falls back to independent sampling when W > C(n,k).
    """
    import random
    from itertools import combinations

    n = len(outputs)
    k = min(ctx_size, n)
    if n == 0 or k == 0:
        return [[] for _ in range(width)]

    all_combos = list(combinations(range(n), k))
    if width <= len(all_combos):
        chosen = random.sample(all_combos, width)
    else:
        # More solvers than distinct subsets — allow repeats
        chosen = [random.choice(all_combos) for _ in range(width)]

    return [[outputs[i] for i in combo] for combo in chosen]


async def run_solvers_parallel(
    *,
    problem: str,
    notebook_level1: str,
    prev_stage_outputs: list[str],  # all W raw outputs from previous stage
    width: int,
    prev_ctx_size: int,
    stage: int,
    notebook_id: str,
    run_id: str,
    cached_calls: list | None = None,   # already-completed calls to reuse
    additional_materials: str = "(none)",
    pdf_paths: list[Path] | None = None,
    store=None,
) -> list[AgentCall]:
    """
    Pre-assign W distinct prev-output subsets (one RNG call), then launch all
    W solvers in parallel. Each solver sees a unique slice of prior context.
    cached_calls: if provided, reuse these instead of re-running those solver indices.
    """
    cached_map = {c.inputs.get("solver_index"): c for c in (cached_calls or [])}
    missing = [i for i in range(width) if i not in cached_map]
    subsets = _assign_prev_subsets(prev_stage_outputs, width, prev_ctx_size)

    new_calls = await asyncio.gather(*[
        run_solver(
            problem=problem,
            notebook_level1=notebook_level1,
            prev_attempts=subsets[i],
            solver_index=i,
            stage=stage,
            notebook_id=notebook_id,
            run_id=run_id,
            additional_materials=additional_materials,
            pdf_paths=pdf_paths,
            store=store,
        )
        for i in missing
    ])
    new_map = {c.inputs["solver_index"]: c for c in new_calls}
    all_map = {**cached_map, **new_map}
    return [all_map[i] for i in range(width)]
