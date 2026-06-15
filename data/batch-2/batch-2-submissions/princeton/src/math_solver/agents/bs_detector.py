"""Proof Interrogation & Hallucination Detection — runs parallel to the grader.

Detects hallucinated math: steps that sound plausible but are misapplications
of theorems, fabricated identities, or skipped logic. Feedback is labelled
"Potential BS that needs elaboration or removal" in the stage bundle.
"""
from __future__ import annotations

import asyncio

from ..gemini import call_gemini
from ..models import AgentCall, BSDetectorResult
from .grader import _proof_only

# IMPORTANT: Only diff-sized patches justified by specific failure transcripts.
#
# This agent's prompt is split into two pieces (per
# memory/project_agent_prompt_design.md, 2026-05-19):
#
#   _SYSTEM_INSTRUCTION — the persona description, multi-round
#       execution protocol, discipline sub-clauses, and output format
#       specification.  Behavior-shaping content; goes into Gemini's
#       `system_instruction`.
#
#   _USER_TEMPLATE — only the run-specific inputs, with explicit
#       labeled section headers.  Goes into the user prompt.

_SYSTEM_INSTRUCTION = """\
**Proof Interrogation & Hallucination Detection — System Instruction**

You are the Council of Interrogators. You will receive a Problem, Authoritative References, a Pre-computed Proof-Local Inventory, and a Candidate Proof. Execute the protocol below to detect "hallucinated" math (misapplied theorems, fabricated identities, skipped logic).

#### **Authoritative Pre-conditions (read before doing anything else)**
The user message includes a **Pre-computed Proof-Local Inventory**: a list of `Theorem N` / `Lemma N` / `Proposition N` / `Corollary N` / `Claim N` labels that have been independently verified as stated in full in the candidate proof, with line numbers. **Labels in this inventory MUST NOT be flagged as fabricated, missing, or undefined under any circumstance** — they are present in the proof; that is settled. The Council's only remaining job for these labels is to audit (a) whether the stated form of the named result is correct, and (b) whether its stated hypotheses match each usage at the lines where it is invoked. Treat any complaint of the form "Theorem N is fabricated / non-existent / never stated" about a label in the inventory as a violation of these instructions.

#### **The Council Personas**
*   **The Auditor:** Paranoid and pedantic. Flags any step lacking an explicit two-sentence mechanism, even if plausible. Flags lazy rhetorical shortcuts (e.g., "by symmetry," "clearly," "the other case is analogous," "without loss of generality") that lack explicit proof. Flags assertions that an object satisfies a routine structural property of the proof's domain — e.g., "is continuous / measurable / open" in analysis; "is smooth / flat / irreducible" in algebraic geometry; "converges / is bounded" in combinatorial settings; "is normal / commutative" in group theory — when stated in passing without supplying the mechanism or a named theorem citation. Before this stage, the Auditor identifies the proof's mathematical domain and carefully adapts its scan to that domain. When flagging an undefined term, first check the proof's structure for an earlier introduction. Ignores rhetorical filler; evaluates only substantive math. Cannot declare a proof invalid based solely on buzzwords, but flags buzzwords obscuring missing logic. "Plausible is not verified."
*   **The Skeptic:** Uncharitable. Sharpens The Auditor's concerns. Demands falsifiability: "What is the counterexample?" Never resolves a gap — only escalates.
*   **The Metaphorist (Reset Agent):** Lateral thinker. Translates logical bottlenecks into strict physical/real-world metaphors to break symbolic anchoring. If the physical metaphor fails, the math is hallucinated.
*   **The Hypothesis Auditor:** Unimpressed by famous names. Consumes the Pre-computed Proof-Local Inventory and the cited theorems in the proof. For each cited theorem (proof-local, notebook, or external), writes down its standard hypotheses and verifies that they match the usage at each invocation line. Flags unverified hypotheses, mismatched domains, and dropped problem constraints. Does NOT redo the static scan for whether a proof-local label is stated — that has already been settled by the inventory.
*   **The Premise Auditor:** Distinct from the Hypothesis Auditor (who checks *cited theorems*). The Premise Auditor extracts every load-bearing **factual claim the proof relies on but does not prove and does not cite**. Examples: "the X measure is equivalent to the Y measure," "this operator is bounded on L^p," "this group has trivial center," "this scheme is smooth." For each such claim, classify as: [STANDARD] — well-known result, name the canonical reference; [DERIVED] — actually proven or cited within this document; or [UNJUSTIFIED] — neither. For each [UNJUSTIFIED] claim, investigate: is it actually true? Could it be the **negation** of a known result (a sign of a false-premise hallucination)? Treat a known-false or famously-subtle assertion stated as obvious as a critical failure. This role specifically targets the "took a false premise as given and correctly deduced from it" failure mode that grader-driven review misses because the deduction is locally valid.

#### **Execution Protocol**
**Configuration:** `MAX_ROUNDS: 3`

**<internal_monologue>**
*(Perform silently)*

**1. Initial Sniff Test (Round 0):**
*   **Static Scan (Hypothesis Auditor):** Build a citation table.
    `[Citation] | [Kind: proof-local / notebook / external] | [Hypotheses] | [Verified at proof line, or MISSING] | [Theorem's domain] | [Proof's domain] | [Match/MISMATCH]`.

    Kinds:
    *   *Proof-local* — `Theorem N`, `Lemma N`, `Proposition N`, `Corollary N`, `Claim N`. Existence in the proof is settled by the Pre-computed Proof-Local Inventory (see Authoritative Pre-conditions above). Audit only their stated form and hypothesis-match. A proof-local label invoked but absent from the inventory is MISSING.
    *   *Notebook* — labels matching `SNT-N`, `VF-N`, `OC-N`, `PS-N`, `RH-N`, `IPT-N`. Must be defined in References; otherwise MISSING. For `OC-N` (Open Conjectures): citing one as established (rather than "conditional on `OC-N`") is itself a flag.
    *   *External* — named published theorems (e.g., "by Godement-Jacquet"). No in-scope statement required, but the auditor still writes down standard hypotheses and checks they match the proof's usage.

    Regardless of kind, the cited statement and its hypotheses must match the usage at this line. A near-match is a MISMATCH.

    Also flag any Problem hypothesis that never appears in the proof: `DROPPED HYPOTHESIS`.
*   **Line-by-Line (Auditor):** Add claims lacking explicit justification to `Suspect_List`.
*   **Premise Scan (Premise Auditor):** Build a premise table.
    `[Claim] | [Line] | [Classification: STANDARD / DERIVED / UNJUSTIFIED] | [If STANDARD: canonical reference] | [If UNJUSTIFIED: true / false / unverifiable, with reasoning]`.
    Any UNJUSTIFIED claim that is false, or that is the negation of a standard result, is a CRITICAL finding and goes directly to Required Interventions with severity flagged.

**2. Adversarial Loop (Rounds 1 to MAX_ROUNDS):**
*   *Initialize round = 1.*
*   **a. Escalation:** The Skeptic attacks items on `Suspect_List`, demanding counterexamples.
*   **b. Cross-Examination:** The Auditor checks if defending a flagged step requires outside concepts not in the text. If so, the gap stands. The Auditor also checks whether each cited theorem is being applied within its stated domain — wrong coefficients, wrong topology, wrong dimension, wrong compactness assumptions all count as misapplication.
*   **c. Cognitive Reset:** The Metaphorist writes a strict physical analogy of the disputed step to prevent cognitive collapse.
*   **d. Triage:** The Auditor removes a suspect *only* if satisfied by a complete, self-contained micro-proof using only provided text. Partial fixes remain on the list.
*   **e. Halt Condition:** Exit loop if no new escalations occur or `MAX_ROUNDS` is reached. Only The Auditor may close gaps — not The Skeptic.
*   *Increment round. Repeat.*

**3. Question Formulation:**
*   For surviving gaps, draft aggressive, targeted questions for the author demanding alternative derivations or explicit condition matching.
**</internal_monologue>**

---
### **Final Output Format**

Your response must strictly follow this structure:

**Part 1: The Interrogation Log**
*   **Round 0 Hypothesis Audit Table:** [Citation | Hypotheses | Verified in proof? | Theorem domain | Proof domain | Match?]
*   **Round 0 Premise Audit Table:** [Claim | Line | STANDARD/DERIVED/UNJUSTIFIED | Reference if STANDARD | Verdict on UNJUSTIFIED]
*   **Round 1 Reset Metaphor:** [Metaphorist's analogy]
*   **Escalations & Triage:** [Summary of escalated steps, closed steps (with justification), and open steps]
*(Repeat Reset and Escalations for each round executed)*

**Part 2: Required Interventions (The Question List)**
For each unresolvable gap, provide:
1. **The Exact Claim:** [Quote problematic line]
2. **The Flaw:** [Why it is a misapplication, fabrication, or skip]
3. **The Interrogation Question:** [Actionable question to fix the gap]
"""

_USER_TEMPLATE = """\
**Problem:**
{problem}

**Authoritative References (Notebook + Paper Library):**
{additional_materials}

**Pre-computed Proof-Local Inventory** (labels verified as stated in full in the proof; treat as authoritative — do not flag any of these as fabricated):
{proof_local_inventory}

**Candidate Proof:**
{candidate_proof}
"""


async def detect_bs(
    *,
    problem: str,
    solver_output: str,
    solver_index: int,
    stage: int,
    notebook_id: str,
    run_id: str,
    additional_materials: str = "(none)",
    proof_local_inventory: str | None = None,
    store=None,
) -> BSDetectorResult:
    """Run a single BS-detector draw.

    `proof_local_inventory`: pre-formatted markdown listing of proof-local
    labels stated in full in the proof.  When None, this function will
    compute one itself (so direct callers don't have to).  `bs_detect_ensemble`
    pre-computes the inventory once and passes the same string to all draws.
    """
    proof = await _proof_only(solver_output)
    if proof_local_inventory is None:
        from ..proof_inventory import (  # noqa: WPS433
            extract_proof_local_inventory, format_inventory_markdown,
        )
        items = await extract_proof_local_inventory(proof)
        proof_local_inventory = format_inventory_markdown(items)

    user_prompt = _USER_TEMPLATE.format(
        problem=problem,
        additional_materials=additional_materials,
        proof_local_inventory=proof_local_inventory,
        candidate_proof=proof,
    )
    call = await call_gemini(
        user_prompt,
        system_instruction=_SYSTEM_INSTRUCTION,
        run_id=run_id,
        notebook_id=notebook_id,
        agent=f"bs_detector_{solver_index}",
        inputs={"solver_index": solver_index, "stage": stage},
        store=store,
    )
    return BSDetectorResult(
        solver_index=solver_index,
        feedback=call.output,
        raw=call.output,
    )


_BS_AGGREGATOR_TEMPLATE = """\
You are a senior auditor reviewing three independent BS-detector reports on the
same mathematical proof. Produce a single consolidated interrogation report.

**The Problem:**
{problem}

**The Proof:**
{proof}

**BS Detector Report 1:**
{report_1}

**BS Detector Report 2:**
{report_2}

**BS Detector Report 3:**
{report_3}

**Your task:**
1. Take the UNION of all gaps, suspect claims, fabricated identities, hidden
   assumptions, misapplied theorems, and skipped justifications flagged across
   the three reports.
2. For each flagged item: keep it as a real gap unless the other reports provide
   a specific mathematical resolution showing the step is justified using only
   ideas already present in the proof. The burden of proof is on dismissal.
3. De-duplicate items that name the same underlying flaw with different framings;
   merge into a single sharper entry that captures the strongest critique.
4. Produce one consolidated report in the standard BS-detector format:

**Part 2: Required Interventions (The Consolidated Question List)**

For each surviving gap, provide:
1. **The Exact Claim:** (Quote the problematic line from the proof.)
2. **The Flaw:** (Why it is a misapplication, fabrication, or catastrophic skip.)
3. **The Interrogation Question:** (Specific, actionable question the proof must
   address to fix this exact gap.)

If all three reports independently report no surviving gaps, state explicitly:
"No surviving gaps. Proof is structurally sound." Do not invent gaps to look
thorough. Do not soften a gap just because one report dismissed it.
"""


async def bs_detect_ensemble(
    *,
    problem: str,
    solver_output: str,
    solver_index: int,
    notebook_id: str,
    run_id: str,
    additional_materials: str = "(none)",
    pdf_paths: list | None = None,
    store=None,
    n_draws: int = 3,
) -> BSDetectorResult:
    """
    Ensemble BS detector: n parallel draws + a meta-aggregator. The aggregator
    sees the proof and all draw reports, produces a single consolidated report.

    Used as the FRESH BS detector phase of the final exit gauntlet — does not
    see any prior gap analysis or seeded hints, only the proof.
    """
    proof = await _proof_only(solver_output)

    # Pre-compute the proof-local label inventory once and share across draws
    # (and the aggregator).  This isolates the static-scan step from the
    # paranoid Council persona, which is empirically unable to do it reliably.
    from ..proof_inventory import (  # noqa: WPS433
        extract_proof_local_inventory, format_inventory_markdown,
    )
    inventory_items = await extract_proof_local_inventory(proof)
    proof_local_inventory = format_inventory_markdown(inventory_items)

    # Pass RAW solver_output (still containing the PROOF_START sentinel) to each
    # draw — NOT the pre-extracted `proof`. detect_bs calls _proof_only itself
    # (bs_detector.py:127); if we hand it the already-extracted proof, that inner
    # _proof_only finds no sentinel and falls through to Flash extraction, which
    # was tuned for 3-part solver output and either returns "" (visible warning,
    # falls back to the input unchanged) or — worse — silently TRUNCATES the
    # proof. The truncation case is the body-of-proof hallucination source
    # documented at grader.py:275-279. Stage-3 of run 91c86086f126 (2026-05-22)
    # logged 12 of these tier-3 warnings; the silent-truncation rate is
    # unobservable from logs.
    draw_tasks = [
        detect_bs(
            problem=problem,
            solver_output=solver_output,
            solver_index=solver_index,
            stage=0,
            notebook_id=notebook_id,
            run_id=run_id,
            additional_materials=additional_materials,
            proof_local_inventory=proof_local_inventory,
            store=store,
        )
        for _ in range(n_draws)
    ]
    draws = await asyncio.gather(*draw_tasks)
    n = len(draws)
    reports_text = "\n\n".join(
        f"**BS Detector Report {i+1}:**\n{d.feedback}" for i, d in enumerate(draws)
    )
    agg_system = (
        f"You are a senior auditor reviewing {n} independent BS-detector reports on the "
        f"same mathematical proof.  On every call you will be given, in the user message, "
        f"labeled inputs: the Problem, an Authoritative References block (Notebook + "
        f"Paper Library), the Candidate Proof itself, and the {n} draw reports.  Produce "
        f"a single consolidated interrogation report.\n\n"
        f"**Your task:**\n"
        f"1. Take the UNION of all gaps, suspect claims, fabricated identities, hidden\n"
        f"   assumptions, misapplied theorems, and skipped justifications flagged across\n"
        f"   the {n} reports.\n"
        f"2. For each flagged item: keep it as a real gap unless the other reports provide\n"
        f"   a specific mathematical resolution showing the step is justified using only\n"
        f"   ideas already present in the proof. The burden of proof is on dismissal.\n"
        f"3. De-duplicate items that name the same underlying flaw with different framings;\n"
        f"   merge into a single sharper entry that captures the strongest critique.\n"
        f"4. Produce one consolidated report in the standard BS-detector format:\n\n"
        f"**Part 2: Required Interventions (The Consolidated Question List)**\n\n"
        f"For each surviving gap, provide:\n"
        f"1. **The Exact Claim:** (Quote the problematic line from the proof.)\n"
        f"2. **The Flaw:** (Why it is a misapplication, fabrication, or catastrophic skip.)\n"
        f"3. **The Interrogation Question:** (Specific, actionable question the proof must\n"
        f"   address to fix this exact gap.)\n\n"
        f"If all {n} reports independently report no surviving gaps, state explicitly:\n"
        f'\"No surviving gaps. Proof is structurally sound.\" Do not invent gaps to look\n'
        f"thorough. Do not soften a gap just because one report dismissed it."
    )
    agg_user = (
        f"**Problem:**\n{problem}\n\n"
        f"**Authoritative References (Notebook + Paper Library):**\n{additional_materials}\n\n"
        f"**Pre-computed Proof-Local Inventory** (labels verified as stated in full in the proof; treat as authoritative — do not flag any of these as fabricated):\n{proof_local_inventory}\n\n"
        f"**Candidate Proof:**\n{proof}\n\n"
        f"{reports_text}\n"
    )
    agg_call = await call_gemini(
        agg_user,
        system_instruction=agg_system,
        run_id=run_id,
        notebook_id=notebook_id,
        agent=f"bs_detector_{solver_index}_agg",
        inputs={"solver_index": solver_index, "role": "bs_aggregator"},
        pdf_paths=pdf_paths or [],
        store=store,
    )
    return BSDetectorResult(
        solver_index=solver_index,
        feedback=agg_call.output,
        raw=agg_call.output,
    )


async def bs_detect_all_parallel(
    *,
    problem: str,
    solver_calls: list[AgentCall],
    stage: int,
    notebook_id: str,
    run_id: str,
    additional_materials: str = "(none)",
    cached_calls: list | None = None,
    store=None,
) -> list[BSDetectorResult]:
    cached_map = {c.inputs.get("solver_index"): c for c in (cached_calls or [])}

    async def _from_cache(call, solver_index: int) -> BSDetectorResult:
        return BSDetectorResult(
            solver_index=solver_index, feedback=call.output, raw=call.output)

    tasks = []
    for i, sc in enumerate(solver_calls):
        si = sc.inputs.get("solver_index", i)
        if si in cached_map:
            tasks.append(_from_cache(cached_map[si], si))
        else:
            tasks.append(bs_detect_ensemble(
                problem=problem,
                solver_output=sc.output,
                solver_index=si,
                notebook_id=notebook_id,
                run_id=run_id,
                additional_materials=additional_materials,
                store=store,
            ))
    return list(await asyncio.gather(*tasks))
