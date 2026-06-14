"""Council of Graders — battle-tested, inquisitorial logic. Do not rewrite."""
from __future__ import annotations

import asyncio
import re

from rich.console import Console

from ..gemini import call_gemini, flash_extract_proof, flash_extract_score, flash_extract_critique
from ..models import AgentCall, GraderResult

_console = Console()

# IMPORTANT: Only diff-sized patches justified by specific failure transcripts.
_SYSTEM_INSTRUCTION = """\
### **Council of Graders (Inquisitorial Logic) — System Instruction**

You are a research-grade evaluation engine. Adopt a "Guilty until Proven Innocent" mindset to detect all logical flaws in the provided inputs: Problem, Solution, Additional Materials, and Prior Hallucination Flags (BS Detector).

*Crucial Constraint:* BS Detector flags are presumptively Fallacies. Rescuing *any* flagged step requires a complete micro-proof using *only* ideas already in the submitted text. If a defense introduces any external named theorem, construction, or technique, the rescue is automatically rejected.

#### **The Council Personas**
*   **The Inquisitor:** Pedantic line-by-line evaluator. Treats ambiguity as a fatal error. "If it is not written, it does not exist."
*   **The Architect:** Evaluates global structure. Flags "magic steps" that fail to logically bridge premise and conclusion.
*   **The Slip Hunter:** Searches specifically for implicit domain restrictions, unverified hypotheses, unconstructed existential claims, and notation that conceals a dimension or type mismatch. Scans the proof for EVERY mechanism or difficult calculation (involving integrals, matrices, and the like) asserted in a single clause, produces an enumerated candidate list of all such sites for the Council, and flags those lacking a full justification. Also flags assertions that an object satisfies a routine structural property of the proof's domain — e.g., "is continuous / measurable / open" in analysis; "is smooth / flat / irreducible" in algebraic geometry; "converges / is bounded" in combinatorial settings; "is normal / commutative" in group theory — when stated in passing without supplying the mechanism or a named theorem citation. Before this stage, the Slip Hunter identifies the proof's mathematical domain and carefully adapts its scan to that domain. Motto: "An unstated mechanism is a hidden conjecture."
*   **Advocatus Diaboli (The Defender):** Attempts to rescue flagged steps as minor "Slips" using *only* the student's existing text.
*   **The Chief Grader:** Arbitrator and scorer. Enforces strict bounds on rescues.

### **Execution Protocol**
**Configuration:** `MAX_ROUNDS: 3`.
**Brevity Protocol:** Dialectic log bullet points must be <30 words each.

**<internal_monologue>**
*(Perform silently)*

**1. Round 0: The Indictment**
*   The Inquisitor, Architect, and Slip Hunter read the Solution and BS Detector flags.
*   The Slip Hunter first emits its enumerated candidate list (every mechanism / difficult calculation asserted in a single clause). All three personas then ruthlessly list every gap, missing mechanism, unverified hypothesis, and unconstructed claim.

**2. Refinement Loop (Rounds 1 to MAX_ROUNDS):**
*   *Initialize round = 1.*
*   **a. Cognitive Reset (The Pre-Mortem):** The Chief Grader forces a perspective shift to prevent anchoring: *"Assume this proof looks correct but is actually wrong. What specific edge case (e.g., n=0, empty set) breaks it?"* Output a 1-sentence Hypothesis of Failure.
*   **b. The Defense:** Advocatus Diaboli attempts to rebut the Indictment and Pre-Mortem using *only* existing text.
*   **c. The Ruling:** The Council accepts or rejects the defense. Rejections are automatic if the defense relies on external math.
*   **d. Halt Check:** Always complete all `MAX_ROUNDS` rounds; do not halt early. Even an empty Round-0 list must run Rounds 1-3 with fresh Pre-Mortem hypotheses each round, executed by the Chief Grader from a different angle (e.g., Round 1: edge case; Round 2: notation/type mismatch; Round 3: a hidden hypothesis the proof assumes without stating).

**3. Final Severity Check (The Chief Grader):**
Classify remaining errors:
*   **Slip:** Minor gap verifiable from prior steps/setup. (-1 point).
*   **Fallacy:** Gap requiring external ideas, or an unconstructed existential claim. (Caps score at 3).
**</internal_monologue>**

---
### **Final Output Format**

Your response must strictly follow this structure:

**Part 1: The Grading Log**
*(Start directly with Round 0. Follow the Brevity Protocol strictly.)*
*   **Round 0 Indictment:** [List of gaps]
*   **Round 1 Pre-Mortem:** [1-sentence Hypothesis of Failure]
*   **Defense & Ruling:** [Summary of attempted rescues and Council verdicts]
*(Repeat Pre-Mortem and Defense/Ruling for each round executed)*

**Part 2: The Final Verdict**

**Coroner's Report:**
[One paragraph. Explicitly state "Cause of Death" if score is low, or "Clean Bill of Health" if high.]

**Chief Grader's Official Assessment:**

**Overall Strategy:**
[Neutral summary of the approach.]

**Strengths:**
*   [Numbered list]

**Areas for Improvement:**
*   [Numbered list. Explicitly classify each as a **Slip** or a **Fallacy**.]

**Scaffolding Questions:**
[3-5 self-contained questions building intuition for missing concepts. Do NOT refer to the student's work or notation.]

**Final Grade:**
*(Rubric: 7=Perfect. 6=Minor Slip only. 5=Significant but valid progress. 2-4=Fallacy or Incomplete. 0-1=Irrelevant.)*
SCORE: [N]/7
"""

_USER_TEMPLATE = """\
**Problem:**
{problem}

**Solution:**
{solver_output}

**Additional Materials:**
{additional_materials}

**Prior Hallucination Flags (BS Detector):**
{bs_flags}
"""


async def _proof_only(solver_output: str) -> str:
    """Three-tier Part 3 extraction — sentinel, Flash fallback, full output.

    Defense-in-depth hedge: if the input has no PROOF_START sentinel AND no
    "Part 1" / "Part 2" section headers, treat it as already-extracted (a
    proof-only string) and return it as-is. Without this guard, accidental
    double-extraction (e.g. passing the result of an earlier _proof_only call
    back through _proof_only) falls through to Flash, which was tuned for
    3-part solver output and may silently truncate a proof-only input. See
    grader.py:275-279 and the bs_detect_ensemble fix (bs_detector.py) for
    the original failure mode.
    """
    # Tier 1: machine-readable sentinel
    if "PROOF_START" in solver_output:
        return solver_output.split("PROOF_START", 1)[1].strip()
    # Tier 1.5 (idempotency hedge): no sentinel and no 3-part structure →
    # caller likely already extracted; do not let Flash truncate it.
    if "Part 1" not in solver_output and "Part 2" not in solver_output:
        return solver_output.strip()
    # Tier 2: Flash extraction
    proof = await flash_extract_proof(solver_output)
    if proof:
        return proof
    # Tier 3: full output — log warning so this is visible in traces
    _console.log("[yellow]_proof_only: Part 3 not isolated — grader will see full output[/yellow]")
    return solver_output


def _parse_score_primary(text: str) -> float | None:
    """Try to extract score from fixed SCORE: prefix line. Returns None if absent."""
    m = re.search(r"^SCORE:\s*(\d+(?:\.\d+)?)\s*/\s*7", text, re.MULTILINE)
    return float(m.group(1)) if m else None


def _parse_strategy_summary(text: str) -> str:
    """Extract the **Overall Strategy:** block from a grader report.

    Bounded by the next bold header (e.g. **Strengths:**). Returns the
    prose between, or empty string if absent (e.g. aggregator output,
    which doesn't produce this block).
    """
    m = re.search(
        r"\*\*Overall Strategy:\*\*\s*(.+?)(?=\n\s*\*\*[A-Z])",
        text,
        re.DOTALL,
    )
    return m.group(1).strip() if m else ""


async def _parse_grader_async(text: str, solver_index: int) -> GraderResult:
    """Extract score with Flash fallback; hard-fails rather than returning 0."""
    score = _parse_score_primary(text)
    if score is None:
        # Fallback: Gemini Flash with JSON structured output
        score = await flash_extract_score(text)
    is_complete = score >= 7.0
    # Strip on harvest: feedback piped downstream is "Areas for Improvement
    # + Scaffolding Questions" only — drop the Council deliberation, the
    # numerical grade prose, and Strengths/Coroner's-Report praise (which
    # otherwise reinforce wrong ideas in next-stage solvers). Score is
    # preserved separately in `.score`. Full raw stays in `.raw` for
    # debugging / persistence.
    stripped_feedback = await _extract_critique_only(text)
    return GraderResult(
        solver_index=solver_index,
        score=score,
        feedback=stripped_feedback,
        is_complete=is_complete,
        raw=text,
        summary=_parse_strategy_summary(text),
    )


async def _extract_critique_only(text: str) -> str:
    """Three-tier strip: regex -> Flash -> full text.

    Tier 1 (regex): Catches initial-grader format with explicit
    "**Areas for Improvement:**" / "**Scaffolding Questions:**" bold
    headers. ~87% of real Gemini grader outputs (measured 2026-05-28).

    Tier 2 (Flash): Catches aggregator format (numbered flaws +
    Summary + SCORE) and prompt-format drift. Uses Gemini Flash with
    JSON-structured output, temperature 0. Sanity-checked against
    length (rejects if Flash returns text >= 1.1x input size — likely
    hallucination).

    Tier 3 (full text): Defensive fallback. Returns input unmodified
    when both above paths fail. Same as pre-Flash leak behavior — no
    regression, no fabricated content.
    """
    # Tier 1: regex
    parts = []
    for section in ("Areas for Improvement", "Scaffolding Questions"):
        # Allow optional colon inside bold markers: graders emit
        # "**Areas for Improvement:**" more often than the bare form.
        m = re.search(
            rf"\*\*{section}:?\*\*(.*?)(?=\n\*\*[A-Z]|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            parts.append(f"**{section}**{m.group(1).rstrip()}")
    if parts:
        return "\n\n".join(parts)

    # Tier 2: Flash. Distinguish "Flash said no critique" (empty string,
    # trustworthy answer — the aggregator praised the proof; we want
    # empty downstream, not the praise prose) from "Flash errored after
    # retries" (None, fall through to Tier 3).
    try:
        flash_out = await flash_extract_critique(text)
        if flash_out is not None:
            if not flash_out:
                return ""  # trust Flash: this grader output has no critique
            if len(flash_out) < len(text) * 1.1:
                return flash_out
            # Oversized → likely hallucination; fall through
    except Exception:
        pass

    # Tier 3: full text safety net
    return text


async def grade_attempt(
    *,
    problem: str,
    solver_output: str,
    solver_index: int,
    stage: int,
    notebook_id: str,
    run_id: str,
    additional_materials: str = "(none)",
    bs_flags: str = "(BS detector not run)",
    pdf_paths: list | None = None,
    store=None,
) -> GraderResult:
    user_prompt = _USER_TEMPLATE.format(
        problem=problem,
        solver_output=solver_output,
        additional_materials=additional_materials,
        bs_flags=bs_flags,
    )
    call = await call_gemini(
        user_prompt,
        system_instruction=_SYSTEM_INSTRUCTION,
        run_id=run_id,
        notebook_id=notebook_id,
        agent=f"grader_{solver_index}",
        inputs={"solver_index": solver_index, "stage": stage},
        pdf_paths=pdf_paths or [],
        store=store,
    )
    return await _parse_grader_async(call.output, solver_index)


_AGGREGATOR_TEMPLATE = """\
You are a senior grader reviewing three independent grading reports on the same \
mathematical proof. Produce a single definitive assessment.

**The Problem:**
{problem}

**The Proof:**
{proof}

**Grading Report 1:**
{report_1}

**Grading Report 2:**
{report_2}

**Grading Report 3:**
{report_3}

**Your task:**
1. Identify the UNION of all errors, gaps, and ambiguities flagged across any \
of the three reports.
2. For each issue: if any report classified it as a Fallacy, treat it as a \
Fallacy unless the other reports provide a specific mathematical argument that \
it is fixable without new ideas (making it a Slip). The burden of proof is on \
dismissal, not discovery.
3. Assign a final grade based on the union of confirmed errors using the \
standard rubric below.

Produce output in the standard grader format:

**Coroner's Report:**
*(One paragraph. "Cause of Death" or "Clean Bill of Health".)*

**Areas for Improvement:**
*(Numbered list. Classify each as Slip or Fallacy. If none: \
state "None.")*

**Final Grade:**
*(Rubric: 7=Perfect. 6=Minor Slip only. 5=Significant but valid progress. \
2-4=Fallacy or Incomplete. 0-1=Irrelevant.)*
SCORE: [N]/7
"""


def _bs_is_clean(bs_feedback: str) -> bool:
    """Returns True if the BS aggregator found no surviving gaps.

    The BS aggregator prompt instructs it to state 'No surviving gaps.
    Proof is structurally sound.' when all draws agree the proof is clean.
    """
    return bool(re.search(r"no surviving gaps", bs_feedback, re.IGNORECASE))


async def verify_solution(
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
    always_aggregate: bool = False,
) -> tuple[bool, list["GraderResult"]]:
    """
    Ensemble exit-check: run n_draws independent grader calls in parallel,
    then an aggregator that sees the proof + all draw reports.

    Default (always_aggregate=False): all draws must score 7/7 to proceed to
    the aggregator (fast-fail otherwise). Used for the 7/7 stopping condition.

    With always_aggregate=True: aggregator always runs after n_draws draws,
    regardless of draw scores. Used for extended grading of ≥5 proofs.

    Returns (confirmed, [draw_results..., aggregator_result], bs_feedback).
    bs_feedback is the BS aggregator's raw output — callers can extract
    Required Interventions from it to pass to next-stage solvers.
    confirmed = True only if BOTH gates pass:
      - Gate 1 (grader): aggregator scores 7/7
      - Gate 2 (BS):     BS aggregator reports no surviving gaps

    Architecture (post 2026-05-17 upgrade):
      Phase A — Fresh BS-detector ensemble: n_draws parallel BS detector calls
                followed by a meta-aggregator that consolidates them into one
                report. This phase sees ONLY the proof; no seeded gap analysis,
                no prior grader feedback, no upstream BS reports.
      Phase B — Grader ensemble: n_draws grader draws grading the proof
                INDEPENDENTLY (no BS flags passed), followed by a
                grader-aggregator that produces the final verdict.
      Dual gate: confirmed = True only when grader aggregator scores 7/7 AND
                 BS aggregator reports no surviving gaps. The two ensembles
                 render independent verdicts; neither can rescue the other.
    """
    # Import here to avoid circular import (bs_detector imports _proof_only from grader)
    from .bs_detector import bs_detect_ensemble

    proof = await _proof_only(solver_output)

    # Phase A: fresh BS-detector ensemble (3 draws + aggregator), sees only the proof.
    # Pass RAW solver_output (still containing the PROOF_START sentinel) so the
    # BS detector's own _proof_only call hits Tier 1 (sentinel extraction). If we
    # pass the already-extracted `proof` here, the BS detector's _proof_only falls
    # through to Tier 2 (Flash extraction), which truncates a proof-only input
    # because Flash expects a 3-part output structure. That truncation is what
    # caused the body-of-proof hallucinations ("Theorem 1 is never stated…").
    bs_agg = await bs_detect_ensemble(
        problem=problem,
        solver_output=solver_output,
        solver_index=solver_index,
        notebook_id=notebook_id,
        run_id=run_id,
        additional_materials=additional_materials,
        pdf_paths=pdf_paths,
        store=store,
    )
    bs_clean = _bs_is_clean(bs_agg.feedback)
    _console.log(
        f"[{'green' if bs_clean else 'yellow'}]"
        f"BS gate (solver {solver_index}): {'CLEAN' if bs_clean else 'GAPS FOUND — gate open'}[/]"
    )

    # Phase B: n parallel grader draws, grading independently (no BS flags)
    draw_tasks = [
        grade_attempt(
            problem=problem,
            solver_output=proof,
            solver_index=solver_index,
            stage=0,  # ensemble draws are not stage-specific
            notebook_id=notebook_id,
            run_id=run_id,
            additional_materials=additional_materials,
            bs_flags="(grader ensemble is independent — BS detector ran separately)",
            pdf_paths=pdf_paths,
            store=store,
        )
        for _ in range(n_draws)
    ]
    draws = list(await asyncio.gather(*draw_tasks))

    # Fast-fail only when not always_aggregate
    if not always_aggregate and not all(d.is_complete for d in draws):
        return False, draws, bs_agg.feedback

    # Step 2: aggregator sees proof + critique-only from each draw (no process log, no praise, no grade)
    def _critique_only(text: str) -> str:
        import re
        parts = []
        for section in ("Areas for Improvement", "Scaffolding Questions"):
            m = re.search(
                rf"\*\*{section}\*\*(.*?)(?=\n\*\*[A-Z]|\Z)",
                text, re.DOTALL | re.IGNORECASE,
            )
            if m:
                parts.append(f"**{section}**{m.group(1).rstrip()}")
        return "\n\n".join(parts) if parts else text
    report_sections = "\n\n".join(
        f"**Grading Report {i+1}:**\n{_critique_only(d.feedback)}" for i, d in enumerate(draws)
    )
    n = len(draws)
    agg_system = (
        f"You are a senior grader reviewing {n} independent grading reports on the same "
        f"mathematical proof.  On every call you will be given, in the user message, "
        f"labeled inputs: the Problem, the Candidate Proof, and the {n} grading reports. "
        f"Produce a single definitive assessment.\n\n"
        f"**Your task:**\n"
        f"1. Identify the UNION of all errors, gaps, and ambiguities flagged across any "
        f"of the {n} reports.\n"
        f"2. For each issue: if any report classified it as a Fallacy, treat it as a "
        f"Fallacy unless the other reports provide a specific mathematical argument that "
        f"it is fixable without new ideas (making it a Slip). The burden of proof is on "
        f"dismissal, not discovery.\n"
        f"3. Assign a final grade based on the union of confirmed errors using the same "
        f"1-7 rubric. End with: SCORE: X/7"
    )
    agg_user = (
        f"**Problem:**\n{problem}\n\n"
        f"**Candidate Proof:**\n{proof}\n\n"
        f"{report_sections}\n"
    )
    agg_call = await call_gemini(
        agg_user,
        system_instruction=agg_system,
        run_id=run_id,
        notebook_id=notebook_id,
        agent=f"grader_{solver_index}_agg",
        inputs={"solver_index": solver_index, "role": "aggregator"},
        pdf_paths=pdf_paths or [],
        store=store,
    )
    agg_result = await _parse_grader_async(agg_call.output, solver_index)

    # Dual gate: both grader AND BS must pass
    confirmed = agg_result.is_complete and bs_clean
    if agg_result.is_complete and not bs_clean:
        _console.log(
            f"[yellow]Solver {solver_index}: grader 7/7 but BS gate open — "
            f"not confirmed, continuing to next stage.[/yellow]"
        )
    return confirmed, draws + [agg_result], bs_agg.feedback


async def grade_all_parallel(
    *,
    problem: str,
    solver_calls: list[AgentCall],
    stage: int,
    notebook_id: str,
    run_id: str,
    additional_materials: str = "(none)",
    bs_results=None,
    cached_calls: list | None = None,
    pdf_paths: list | None = None,
    store=None,
) -> list[GraderResult]:
    bs_map = {r.solver_index: r.feedback for r in (bs_results or [])}
    cached_map = {c.inputs.get("solver_index"): c for c in (cached_calls or [])}

    async def _from_cache(call, solver_index: int) -> GraderResult:
        return await _parse_grader_async(call.output, solver_index)

    proofs = await asyncio.gather(*[_proof_only(sc.output) for sc in solver_calls])
    tasks = []
    for i, (sc, proof) in enumerate(zip(solver_calls, proofs)):
        si = sc.inputs.get("solver_index", i)
        if si in cached_map:
            tasks.append(_from_cache(cached_map[si], si))
        else:
            tasks.append(grade_attempt(
                problem=problem,
                solver_output=proof,
                solver_index=si,
                stage=stage,
                notebook_id=notebook_id,
                run_id=run_id,
                additional_materials=additional_materials,
                bs_flags=bs_map.get(si, "(no flags)"),
                pdf_paths=pdf_paths,
                store=store,
            ))
    return list(await asyncio.gather(*tasks))
