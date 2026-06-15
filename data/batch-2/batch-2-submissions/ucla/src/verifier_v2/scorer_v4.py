"""§v4: Combined citation-verification + main verifier in one web-search-enabled call.

No pre-checker. The model first audits all named citations via web search,
then performs the full proof verification. Single API call, no duplicate input.

API call wrapper is **injected by the caller** via ``run_response_fn`` —
this lets the harness funnel every v4 verification through its own
``run_response`` (unified cost log, unified queued-timeout, unified
[stage_name] log format) without forcing verifier_v2 to ``import`` the
harness module (which would trigger its module-level pipeline).
"""
from __future__ import annotations
import re, os

ACCEPT_THRESHOLD = int(os.getenv("VERIFY_ACCEPT_THRESHOLD", "9"))

VERIFY_PROMPT_V4 = """\
You are a rigorous mathematical referee with web search access. You will check the following proof in two steps.

# Original Problem
PROBLEM_PLACEHOLDER

# Claim Being Verified
CLAIM_PLACEHOLDER

# Solution
SOLUTION_PLACEHOLDER

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## Step 1 — Citation Audit (external paper citations only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Use web search to verify citations and named theorems:

**Type A/B (external paper citations)** — full web search:
  A — specific claim in a named paper ("by Lemma 3.2 in [Smith2020]")
  B — broad reference to a named paper ("by results of [Hairer2014]")
  For each: search for the paper, verify it contains the claim, verify hypotheses match.

**Type C (named standard theorems without paper citation)** — search Wikipedia or standard references:
  C — "by Fubini", "by Cauchy-Schwarz", "by the Fourier-Laplace uniqueness theorem"
  For each: search Wikipedia or a standard reference to confirm the exact theorem statement.
  Check: (1) does the standard statement match the form invoked? (2) are the hypotheses (domain, growth conditions, support) the same as in this proof?
  If the exact variant needed (e.g., a specific growth condition, a specific domain) is not in Wikipedia or standard references, note it as "not found in standard references."
  If the theorem is clearly standard and applies trivially (e.g., Fubini for L¹ functions on bounded domain), say so briefly — do not over-verify routine applications.

Do NOT include in this section:
  - Introductory phrases ("We begin with...", "Therefore...")
  - Internal cross-references (\\ref{...}, \\eqref{...})

If the proof contains no citations or named theorems, output (none) immediately.

Output citation findings in this section:
<CITATION_AUDIT>
- [Paper: Smith2020] VERIFIED — Lemma 3.2 exists and states exactly the claimed bound.
- [Paper: Jones2019] HALLUCINATED — Paper does not exist (search returned no results).
- [Paper: Brown2015] WRONG CLAIM — Theorem 4 states a weaker bound; hypotheses don't match.
- (none) if no Type A/B paper citations found.
</CITATION_AUDIT>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## Step 2 — Proof Verification (strict audit)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Audit the proof very strictly. Do not mark the proof correct unless every step needed for the stated theorem is either fully proved or reduced to a standard lemma whose hypotheses are explicitly verified.

**The primary decision rule for every gap:**
Ask: "Must this be fixed, or is the proof wrong as written?"
- YES → **MAJOR_GAP** (regardless of whether the same strategy could be repaired)
- NO, it is truly optional detail → **MINOR_GAP**

**Gap classification — use patch existence to distinguish major from minor:**
- **MAJOR_GAP**: the proof is wrong/incomplete at this step AND you cannot supply a concrete corrective argument. Requires a fundamentally new approach. No patch.
- **MINOR_GAP**: the proof is wrong/incomplete at this step BUT you CAN supply a complete concrete argument that fixes it without changing the overall strategy. Include the full patch in PATCHES_REQUIRED_FOR_CORRECTNESS.

**Critical rule:** If you can provide the specific missing mathematical argument (e.g., the exact construction, the exact lemma with proof, the exact tail estimate) → MINOR, even if the step is currently absent from the proof. A gap is MAJOR only if you cannot identify a concrete fix.

**Black-box theorem policy:**
An invoked theorem may be accepted only if the proof:
1. states the theorem precisely enough to identify it,
2. invokes a genuinely standard result or gives a reliable citation,
3. verifies the hypotheses needed in this specific setting, and
4. uses a conclusion that exactly matches what the argument requires.
If a theorem is nontrivial, central to the proof, and one of these four checks fails: decide MAJOR vs MINOR based on whether you can supply the missing proof or verification. If yes → MINOR with patch. If no → MAJOR.

**Missing-citation classification (refinement of the policy above for the specific case of an absent or unclear citation):**
When the proof invokes a named theorem or external result without an adequate citation, classify the gap by your *confidence in the underlying result being correct*, NOT just on whether the literal reference is missing. Use Step 1's CITATION_AUDIT labels as anchors:
- You can **confidently identify the invoked result as correct** — i.e. either (a) Step 1 marked the citation as **VERIFIED** in CITATION_AUDIT after web search, OR (b) it is a textbook-standard result (Cauchy-Schwarz, Hölder, Fubini, dominated convergence, …) whose hypotheses are obviously satisfied in this setting — and the only thing missing is the literal reference or attribution → **MINOR_GAP classified as EXPOSITION ONLY**. Fix is purely supplying the reference, no mathematical work. (Exception: for *genuinely routine* textbook applications that no working mathematician would bother to cite — e.g., Cauchy-Schwarz on two L² vectors, Fubini on a non-negative L¹ integrand on a bounded domain — do NOT flag this as a gap at all.)
- Step 1 was **unable to confirm** the citation (e.g. labelled **NOT FOUND**), OR Step 1 flagged it as **HALLUCINATED / WRONG CLAIM / HYPOTHESIS MISMATCH**, BUT you can supply an alternative known-correct argument or a substitute citation that fills the same role in the proof → **MINOR_GAP classified as ROUTINE PATCH REQUIRED**, with the substitute argument or alternative reference written out in PATCHES_REQUIRED_FOR_CORRECTNESS so the proof can be patched defensively.
- The citation is essential to the proof, Step 1 could not confirm it (or confirmed it is wrong/hallucinated), and you cannot supply a substitute → **MAJOR_GAP**.

**Proof-critical checks (apply to every proof):**

1. **Uniqueness theorems**: State the exact uniqueness lemma being used. Verify the object (measure, function, distribution) has the required growth condition. If the proof cites a theorem without verifying hypotheses: can you verify the hypotheses and write out the missing step? If yes → MINOR with patch. If no → MAJOR.

2. **Vague/weak convergence**: Identify exactly which test functions are used. If any non-compactly-supported test function is used without a cutoff argument: can you write out the cutoff/truncation argument and tail bound? If yes → MINOR with patch. If no → MAJOR.

3. **Nonzero limits**: Check that mass does not escape to infinity. If no cutoff argument is given: can you provide ψ ∈ C_c and the liminf lower bound? If yes → MINOR with patch. If no → MAJOR.

4. **Constants and quantifiers**: Compare the final constants and quantifiers to the original theorem. If constants are not fixed or the proof gives a weaker constant, weaker range, or weaker hypothesis, mark IS_RELAXATION: true.

**Proof-obligation audit:**
For every nontrivial statement — lemmas, estimates, named theorems (even standard ones), deferred claims — determine whether it is:
1. proved in the solution;
2. assumed without proof (flag if non-trivial);
3. cited from a valid external paper whose hypotheses match (verified in Step 1);
4. a named standard theorem (Type C: Fubini, Cauchy-Schwarz, etc.) — for these, verify:
   (a) the theorem's hypotheses are satisfied in this specific setting, and
   (b) the conclusion matches exactly what the argument uses.
   Even if the named theorem is undisputed, if hypotheses are not verified → flag as gap.
5. essentially equivalent to the Claim (circular — MAJOR_GAP);
6. insufficient to imply the step for which it is used.

**Named theorem policy (Type C):** Standard theorems (no paper citation) are NOT automatically accepted. The proof must show the required hypotheses hold in this setting. If the theorem is central and its hypotheses are not verified, this is a MAJOR_GAP. If peripheral and routine, MINOR_GAP.

### Quantitative-dependence audit
If the Claim contains explicit constants, rates, error bounds, asymptotics, or parameter regimes:
- Extract the exact quantitative conclusion claimed.
- Check that the final dependence follows algebraically from proved estimates.
- Flag as MAJOR gap if the proof only assumes the key estimate or proves a weaker/different dependence.

### PROBLEM_SOLVED
State only what the proof actually establishes after accounting for all gaps, unverified citations, and unproved assumptions. Do not merely restate the Claim.

### IS_RELAXATION
Compare the **Claim Being Verified** (what the solver attempted to prove) against the Original Problem — NOT PROBLEM_SOLVED.

IS_RELAXATION: true only if the solver deliberately weakened their claim relative to the Original Problem (different quantifiers, weaker conclusion, added hypotheses, smaller constant that provably doesn't satisfy the original).

IS_RELAXATION: false if the solver's Claim matches the Original Problem in all essential respects (same conclusion, same hypotheses, explicit constants that satisfy the original's implicit bound like R ~ 1/δ), even if the proof has major gaps.

Do NOT set IS_RELAXATION: true merely because the proof is incomplete and PROBLEM_SOLVED is conditional. A failed attempt at the full theorem is not a relaxation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## Output
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<CITATION_AUDIT>
...
</CITATION_AUDIT>
<MAJOR_GAPS>
- gap description (or empty if none)
</MAJOR_GAPS>
<MINOR_GAPS>
- gap description classified as EXPOSITION ONLY or ROUTINE PATCH REQUIRED
</MINOR_GAPS>
<PATCHES_REQUIRED_FOR_CORRECTNESS>
For each MAJOR_GAP or CORRECTNESS-RELEVANT gap, write the missing argument or lemma in enough detail that it could be inserted into the proof. Be specific about hypotheses and conclusions needed.
</PATCHES_REQUIRED_FOR_CORRECTNESS>
<SALVAGEABLE_WITH_SAME_STRATEGY>true or false</SALVAGEABLE_WITH_SAME_STRATEGY>
<FINAL_VERDICT>
Output EXACTLY one of these three strings (no other wording):
- Correct
- Correct after minor fixes
- Incorrect

Criteria (decide in this order):
1. **Incorrect** — choose iff there is at least one MAJOR_GAP. The proof has a fundamental issue that requires a new approach.
2. **Correct after minor fixes** — choose iff there are no MAJOR_GAPS, but there are MINOR_GAPS that require actual (though routine) mathematical work to close (e.g., a cutoff/truncation argument that must be written out, a missing tail estimate, a hypothesis check for a black-box theorem). These are gaps you classified above as "ROUTINE PATCH REQUIRED".
3. **Correct** — choose iff either: (a) there are no gaps at all, OR (b) the only MINOR_GAPS are purely cosmetic/expository (notation, organization, missing citation for a textbook fact) and do NOT affect the rigor of the proof. These are gaps you classified above as "EXPOSITION ONLY".

If you write "Correct" but list any MINOR_GAP as "ROUTINE PATCH REQUIRED", you are contradicting yourself — pick "Correct after minor fixes" instead.
</FINAL_VERDICT>
<PROBLEM_SOLVED>
fully self-contained statement of what the proof actually establishes
</PROBLEM_SOLVED>
<IS_RELAXATION>true or false or uncertain</IS_RELAXATION>
<FLAGGED_CITATIONS>
For each citation that is NOT VERIFIED, HALLUCINATED, WRONG CLAIM, or HYPOTHESIS MISMATCH, output one line:
  CRITICAL|<verbatim excerpt from the proof — 5-10 words that appear literally in the solution text>|<one-line reason>
For citations that are unverifiable (NOT FOUND) but not confirmed wrong, output:
  MINOR|<verbatim excerpt>|<one-line reason>
For verified citations, output nothing.
Example: CRITICAL|by the Lovász–Rado–Edmonds represented-subspace|citation too imprecise to verify
</FLAGGED_CITATIONS>
""".strip()


def run_verify_v4(
    solution: str,
    problem: str,
    claim: str | None = None,
    reasoning: str = "xhigh",
    *,
    run_response_fn,
    stage_name: str = "run_verify_v4",
    verbosity: str = "medium",
    max_output_tokens: int = 128_000,
):
    """Run the v4 combined citation+verification call.

    ``run_response_fn`` is a callable matching the harness's ``run_response``
    signature ``(prompt, stage_name, reasoning_effort, verbosity,
    max_output_tokens, web_search, model=None) -> (text, usage_dict)``.
    Injection (rather than importing from the harness module) keeps
    verifier_v2 a leaf subpackage with no cyclic dependency on harness
    module-level state.

    ``stage_name`` is the log prefix shown in `[stage_name] in_progress
    after Ns` lines — pass the per-task stage_label (e.g.
    ``"verify_writeup_r2_0daa8a_round_0"``) to make stuck calls
    distinguishable in the logs; defaults to ``"run_verify_v4"``.

    Returns: (correct, major_gaps, minor_gaps, citation_audit,
              flagged_issues, salvageable, patches_text, final_verdict,
              verdict_class, raw_output)

    ``correct`` is now derived from ``verdict_class`` (not from gap counts).
    ``verdict_class`` is one of: "correct", "correct_after_minor", "incorrect".
    """
    if claim is None:
        claim = problem

    prompt = (
        VERIFY_PROMPT_V4
        .replace("PROBLEM_PLACEHOLDER", problem)
        .replace("CLAIM_PLACEHOLDER", claim)
        .replace("SOLUTION_PLACEHOLDER", solution)
    )

    raw, _usage = run_response_fn(
        prompt,
        stage_name=stage_name,
        reasoning_effort=reasoning,
        verbosity=verbosity,
        max_output_tokens=max_output_tokens,
        web_search=True,
    )

    major_m      = re.search(r"<MAJOR_GAPS>(.*?)</MAJOR_GAPS>",   raw, re.DOTALL)
    minor_m      = re.search(r"<MINOR_GAPS>(.*?)</MINOR_GAPS>",   raw, re.DOTALL)
    audit_m      = re.search(r"<CITATION_AUDIT>(.*?)</CITATION_AUDIT>", raw, re.DOTALL)
    flagged_m    = re.search(r"<FLAGGED_CITATIONS>(.*?)</FLAGGED_CITATIONS>", raw, re.DOTALL)

    _EMPTY_MARKERS = {"empty", "none", "- ...", "(none)", "(empty)", "none.", "none found",
                      "no major gaps", "no minor gaps", "no gaps", "n/a", "-"}

    def _parse(text: str) -> list[str]:
        if not text:
            return []
        results = []
        for l in text.strip().splitlines():
            stripped = l.lstrip("- ").strip()
            if not stripped:
                continue
            if stripped.lower() in _EMPTY_MARKERS or l.strip().lower() in _EMPTY_MARKERS:
                continue
            results.append(stripped)
        return results

    # Parse flagged citations for inline annotation
    flagged_issues: list[dict] = []
    if flagged_m:
        for line in flagged_m.group(1).strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("For ") or line.startswith("Example"):
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                severity_tag, excerpt, reason = parts
                severity_tag = severity_tag.strip().upper()
                is_minor = severity_tag == "MINOR"
                flagged_issues.append({
                    "severity": "minor" if is_minor else "CRITICAL",
                    "ctype": "A",  # generic citation type for annotation
                    "excerpt": excerpt.strip(),
                    "claim": "",
                    "detail": reason.strip(),
                })

    major_gaps     = _parse(major_m.group(1)  if major_m  else "")
    minor_gaps     = _parse(minor_m.group(1)  if minor_m  else "")
    citation_audit = audit_m.group(1).strip() if audit_m else ""

    salvageable_m  = re.search(r"<SALVAGEABLE_WITH_SAME_STRATEGY>(.*?)</SALVAGEABLE_WITH_SAME_STRATEGY>",
                               raw, re.DOTALL)
    patches_m      = re.search(r"<PATCHES_REQUIRED_FOR_CORRECTNESS>(.*?)</PATCHES_REQUIRED_FOR_CORRECTNESS>",
                               raw, re.DOTALL)
    verdict_m      = re.search(r"<FINAL_VERDICT>(.*?)</FINAL_VERDICT>", raw, re.DOTALL)

    salvageable = (salvageable_m.group(1).strip().lower() == "true") if salvageable_m else None
    patches_text = patches_m.group(1).strip() if patches_m else ""
    final_verdict = verdict_m.group(1).strip() if verdict_m else ""

    # Normalize <FINAL_VERDICT> into a 3-class enum used by the harness.
    # Unknown / unparseable verdicts default to "incorrect" (safe side).
    verdict_norm = final_verdict.strip().lower()
    if "correct after minor" in verdict_norm:
        verdict_class = "correct_after_minor"
    elif verdict_norm.startswith("correct"):
        verdict_class = "correct"
    elif "incorrect" in verdict_norm:
        verdict_class = "incorrect"
    else:
        print(f"[scorer_v4] unrecognized <FINAL_VERDICT>: {final_verdict!r} — defaulting to 'incorrect'")
        verdict_class = "incorrect"

    # Cross-check: log warnings when verdict and gap counts disagree.
    # We trust the verdict (per design) but surface the inconsistency.
    if verdict_class != "incorrect" and major_gaps:
        print(f"[scorer_v4] WARN verdict={verdict_class!r} but {len(major_gaps)} MAJOR_GAPS listed — trusting verdict")
    if verdict_class == "incorrect" and not major_gaps:
        print(f"[scorer_v4] WARN verdict='incorrect' but no MAJOR_GAPS listed — trusting verdict")

    # `correct` (bool) is now derived from the verdict, not from gap counts.
    # True iff the verdict is one of the accepting classes.
    correct = verdict_class in ("correct", "correct_after_minor")

    return correct, major_gaps, minor_gaps, citation_audit, flagged_issues, salvageable, patches_text, final_verdict, verdict_class, raw


def is_accepted_v4(correct: bool) -> bool:
    return correct
