"""finalize.py — two-track final-output stage that replaces Stage 2.9 + Stage 5.

Mirrors the chat-interface pattern that empirically closed `writeup_r6_6ca6f7`-
style problems (where the in-loop verifier accepted a writeup that turned out
to need a relaxation pass to be fully rigorous):

    1. POLISH       — make the candidate proof / report end-to-end and rigorous.
                       Permission to relax quantitative bounds slightly (Track A
                       only). No jargon for jargon's sake. Every step justified.

    2. TYPESET      — convert the polished output to a complete LaTeX document.
                       Re-checks for gaps during the conversion.

Both calls run on the strongest model at xhigh reasoning and 128k output cap;
the typeset stage is no longer routed through the small TYPESET_MODEL.

Routing decision (made by the harness at finalize entry):

    Track A: any task_output with is_relaxation=False exists
        → finalize_full_proof(seed=that output)

    Track B: no such output (only relaxations / partials, or nothing verified)
        → finalize_progress_report(verified_partials, kb)

The verifier's verdict (if_final_true=true|false) is *informational*, not a
gate — Track A fires whenever some attempt was filed as a full-problem proof,
regardless of whether the verifier accepted it. This is by design: the chat-
interface success was on a writeup the verifier had flagged as having gaps.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


# ─── Polish prompt (Track A) ─────────────────────────────────────────────────
# Wording intentionally mirrors the chat-interface message that worked.

POLISH_PROMPT_TEMPLATE = """\
You are revising a candidate proof of a mathematical problem.

# Original Problem
{problem}

# Candidate Proof (on the right track, may have gaps or unnecessary jargon)
{seed_solution}
{references_block}
# Instructions

This approach seems to be quite promising. Can you make this approach work to solve \
the original problem (even if the quantitative bounds are slightly worse)? I want \
you to be able to get an end-to-end solution without using unnecessary jargon and/or \
any gaps. No need to optimize constants. The proof should be correct.

Output the complete polished proof, including proper citations, in markdown with inline LaTeX math, ready to be \
turned into a self-contained LaTeX document.
""".strip()


# ─── Report prompt (Track B) ─────────────────────────────────────────────────

REPORT_PROMPT_TEMPLATE = """\
You are writing a research progress report. The effort below did NOT solve the \
original problem; your job is to honestly document what was learned.

# Original Problem
{problem}

# Verified Partial Results (each with its proof)
{partials_block}

# Approaches That Were Tried (and why they ran into difficulty)
{failed_attempts_block}

# Bottlenecks Identified
{bottlenecks_block}

# Strategic Notes From Each Round (for additional context)
{strategic_notes_block}

# Instructions

I failed to solve the original problem. But here is a full detailed report of what I \
learned about the problem: the partial results that were proven, the approaches that \
were tried and why this seemed difficult, the bottleneck for the full theorem, and \
what a researcher picking up this effort should know.

Be honest — do not claim more than was actually proved. Be useful — write clearly \
enough that a researcher reading the report could pick up where this effort left off.

Output the complete report in markdown with inline LaTeX math, ready to be turned \
into a self-contained LaTeX document.
""".strip()


# ─── Typeset prompt (both tracks) ────────────────────────────────────────────

TYPESET_PROMPT_TEMPLATE = """\
Convert the document below into a complete, self-contained LaTeX file.

# Original Problem (for reference; restate as the headline theorem)
{problem}
{claim_block}
# Source Document
{source_text}

# Instructions

Make sure there are no gaps or mistakes or unexplained steps in the proof. It should \
be fully rigorous. If during the conversion you find a step that cannot be made \
rigorous as written, fill it in with a correct argument; if that is not possible, \
state explicitly what is missing.

# Document structure: two layers (additive, not substitutive)

The document should have two layers, both present:

  (a) A short Overview / Strategy section (1-2 paragraphs in plain English) near \
      the top, which names the main proof moves at a high level and points to \
      where each one is carried out in the body. This helps a reader navigate.

  (b) The full formal development: definitions, lemmas, propositions, theorems, \
      all with complete proofs in standard environments.

The overview is **additive**. It MUST NOT serve as a substitute for any formal \
proof. Every lemma, proposition, and theorem in the body has a complete \
\\begin{{proof}}...\\end{{proof}} with no omission, abbreviation, or "see overview" \
hand-waving — even for steps that look routine. If a step would normally be left \
to the reader, write it out anyway.

Style: prefer the simplest formulation that carries the math. Brief motivating \
remarks between sections (one or two sentences) are welcome where they help a \
reader navigate, but never in place of a derivation.

# LaTeX requirements (strict — competition grading requires clean Overleaf compilation)

- Document class: `\\documentclass[12pt]{{article}}` — use this exact form. Do NOT use \
`amsart`, `amsbook`, `report`, `book`, or any other class. The 12pt option is mandatory.
- The ONLY package permitted for changing margins or line spacing is \
`\\usepackage{{fullpage}}`. Do NOT use `geometry`, `\\setlength{{\\textwidth}}{{...}}`, \
`\\renewcommand{{\\baselinestretch}}{{...}}`, `\\linespread{{...}}`, \
`\\setlength{{\\parskip}}{{...}}`, or any other margin / spacing modifier — these are \
explicitly disallowed by the submission specification.
- Standard content packages are encouraged: `amsmath`, `amssymb`, `amsthm`, `hyperref`, \
`mathtools`. Use `amsthm` to define theorem / lemma / proof environments (the `article` \
class does not provide them by default).
- **The complete document MUST fit in at most 12 pages** in this `article` 12pt + \
`fullpage` layout. If a faithful proof would exceed 12 pages, compress the exposition \
(shorter Overview / Strategy section, tighter prose, fewer motivating remarks, briefer \
inter-section commentary) WITHOUT removing non-trivial proof steps or weakening any \
claim. When even a compressed exposition would exceed 12 pages, you MAY abbreviate \
genuinely routine textbook steps (with a one-clause justification or citation, e.g. \
"by dominated convergence"), but never abbreviate a step that carries the mathematical \
content of the proof. The 12-page hard cap overrides the "write every step out" rule \
in the document-structure section above when (and only when) the two are in genuine \
conflict.
- Include proper citations wherever citations are needed, and list all cited sources in \
a References section at the end of the document.
- The document must compile cleanly on Overleaf (and with `pdflatex`) without any \
external dependencies, custom fonts, missing .bib files, or non-CTAN packages. If you \
use BibTeX-style citations, embed the bibliography directly using \
`\\begin{{thebibliography}}` rather than an external .bib file.
- Preserve all mathematical content exactly — do not silently drop or rephrase claims.
- Use the original problem as the document title and as the headline theorem the \
solution targets.
- If a "Claim Established" block is present below and differs from the original problem, \
render the established claim prominently as its own theorem so the reader can see what \
was actually proved versus what was originally asked.
- Output ONLY the complete .tex file content, starting with `\\documentclass` and ending \
with `\\end{{document}}`.
- Do not wrap the output in markdown code fences.
""".strip()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _build_claim_block(original_problem: str, problem_solved: str) -> str:
    if not problem_solved or _norm(problem_solved) == _norm(original_problem):
        return "\n"
    return (
        "\n# Claim Established (what the solution actually proves — may be a "
        "relaxation or paraphrase of the original)\n"
        f"{problem_solved}\n"
    )


def _build_references_block(references: list[tuple[str, str]] | None) -> str:
    if not references:
        return ""
    lines = ["\n# Other Verified Partial Results From the Same Effort (use as needed)"]
    for label, text in references:
        lines.append(f"\n## {label}\n{text}")
    lines.append("")
    return "\n".join(lines)


def _build_partials_block(partials: list[tuple[str, str]]) -> str:
    if not partials:
        return "(none)"
    parts = []
    for label, text in partials:
        parts.append(f"## {label}\n\n{text}")
    return "\n\n".join(parts)


def _build_failed_attempts_block(items: list[dict]) -> str:
    if not items:
        return "(none recorded)"
    lines = []
    for it in items:
        approach = (it.get("approach") or "").strip()
        reason = (it.get("reason") or "").strip()
        if approach:
            line = f"- **{approach}** — {reason}" if reason else f"- **{approach}**"
            lines.append(line)
    return "\n".join(lines) if lines else "(none recorded)"


def _build_bottlenecks_block(items: list) -> str:
    if not items:
        return "(none recorded)"
    return "\n".join(f"- {b}" for b in items if b)


def _build_strategic_notes_block(notes: list[dict]) -> str:
    if not notes:
        return "(none recorded)"
    lines = []
    for n in notes:
        rnd = n.get("round")
        note = (n.get("note") or "").strip()
        if not note:
            continue
        lines.append(f"### Round {rnd}\n{note}")
    return "\n\n".join(lines) if lines else "(none recorded)"


# ─── Track A: full-proof finalize ────────────────────────────────────────────

def finalize_full_proof(
    *,
    problem: str,
    seed_solution: str,
    seed_problem_solved: str | None,
    references: list[tuple[str, str]] | None,
    run_response,
    polish_reasoning: str = "xhigh",
    polish_max_tokens: int = 128_000,
    typeset_reasoning: str = "xhigh",
    typeset_max_tokens: int = 128_000,
    log_conversation=None,
):
    """Two-call finalize: polish (with relaxation permission) → LaTeX typeset.

    Returns ``(polished_text, latex_text, polish_usage, typeset_usage)``.
    """
    # ── Call 1: polish ──────────────────────────────────────────────────────
    polish_prompt = POLISH_PROMPT_TEMPLATE.format(
        problem=problem,
        seed_solution=seed_solution,
        references_block=_build_references_block(references),
    )
    print(f"\n{'='*80}\n[finalize / Track A] polishing seed proof "
          f"(seed_chars={len(seed_solution)})\n{'='*80}")
    polished_text, polish_usage = run_response(
        polish_prompt,
        stage_name="finalize_polish",
        reasoning_effort=polish_reasoning,
        verbosity="high",
        max_output_tokens=polish_max_tokens,
        web_search=True,
    )
    print(f"[finalize / polish] done ({len(polished_text)} chars)")
    if log_conversation:
        log_conversation({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type":      "finalize_polish",
            "track":     "A",
            "prompt":    polish_prompt,
            "response":  polished_text,
            "usage":     polish_usage,
        })

    # ── Call 2: typeset ─────────────────────────────────────────────────────
    typeset_prompt = TYPESET_PROMPT_TEMPLATE.format(
        problem=problem,
        claim_block=_build_claim_block(problem, seed_problem_solved or problem),
        source_text=polished_text,
    )
    print(f"\n{'='*80}\n[finalize / Track A] typesetting polished proof\n{'='*80}")
    latex_text, typeset_usage = run_response(
        typeset_prompt,
        stage_name="finalize_typeset",
        reasoning_effort=typeset_reasoning,
        verbosity="high",
        max_output_tokens=typeset_max_tokens,
        web_search=False,
    )
    print(f"[finalize / typeset] done ({len(latex_text)} chars)")
    if log_conversation:
        log_conversation({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type":      "finalize_typeset",
            "track":     "A",
            "prompt":    typeset_prompt,
            "response":  latex_text,
            "usage":     typeset_usage,
        })

    return polished_text, latex_text, polish_usage, typeset_usage


# ─── Track B: progress-report finalize ───────────────────────────────────────

def finalize_progress_report(
    *,
    problem: str,
    verified_partials: list[tuple[str, str]],
    failed_attempts: list[dict],
    bottlenecks: list,
    strategic_notes: list[dict],
    run_response,
    report_reasoning: str = "xhigh",
    report_max_tokens: int = 128_000,
    typeset_reasoning: str = "xhigh",
    typeset_max_tokens: int = 128_000,
    log_conversation=None,
):
    """Two-call finalize: progress report → LaTeX typeset."""
    # ── Call 1: report ──────────────────────────────────────────────────────
    report_prompt = REPORT_PROMPT_TEMPLATE.format(
        problem                = problem,
        partials_block         = _build_partials_block(verified_partials),
        failed_attempts_block  = _build_failed_attempts_block(failed_attempts),
        bottlenecks_block      = _build_bottlenecks_block(bottlenecks),
        strategic_notes_block  = _build_strategic_notes_block(strategic_notes),
    )
    print(f"\n{'='*80}\n[finalize / Track B] compiling progress report "
          f"(partials={len(verified_partials)}, failed={len(failed_attempts)})"
          f"\n{'='*80}")
    report_text, report_usage = run_response(
        report_prompt,
        stage_name="finalize_report",
        reasoning_effort=report_reasoning,
        verbosity="high",
        max_output_tokens=report_max_tokens,
        web_search=True,
    )
    print(f"[finalize / report] done ({len(report_text)} chars)")
    if log_conversation:
        log_conversation({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type":      "finalize_report",
            "track":     "B",
            "prompt":    report_prompt,
            "response":  report_text,
            "usage":     report_usage,
        })

    # ── Call 2: typeset ─────────────────────────────────────────────────────
    typeset_prompt = TYPESET_PROMPT_TEMPLATE.format(
        problem=problem,
        claim_block="\n# Note: this document is a research progress report, NOT a "
                    "claimed proof of the original problem.\n",
        source_text=report_text,
    )
    print(f"\n{'='*80}\n[finalize / Track B] typesetting report\n{'='*80}")
    latex_text, typeset_usage = run_response(
        typeset_prompt,
        stage_name="finalize_typeset_report",
        reasoning_effort=typeset_reasoning,
        verbosity="high",
        max_output_tokens=typeset_max_tokens,
        web_search=False,
    )
    print(f"[finalize / typeset] done ({len(latex_text)} chars)")
    if log_conversation:
        log_conversation({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type":      "finalize_typeset_report",
            "track":     "B",
            "prompt":    typeset_prompt,
            "response":  latex_text,
            "usage":     typeset_usage,
        })

    return report_text, latex_text, report_usage, typeset_usage


# ─── Seed selection helpers (used by the harness) ────────────────────────────

def find_full_proof_seed(memory):
    """Pick the best `is_relaxation=False` proof to feed to Track A.

    Preference order:
      1. final_solutions row with is_relaxation=False AND if_final_true="true"
         (verifier accepted as-is). Earliest round wins for determinism.
         seed_priority = "verified_full_proof".
      2. final_solutions row with is_relaxation=False AND if_final_true="nearly true"
         (verifier accepted only minor gaps remain after refine ran out of budget).
         Earliest round wins. seed_priority = "nearly_verified_full_proof".
         For this tier the seed text is the REFINED `Final_Solution`, not the
         pre-refine task_output, because refine has already absorbed several
         rounds of patches.
      3. Any task_output with is_relaxation=False (totally unverified or
         rejected). Latest round wins (most informed by prior advisor decisions).
         seed_priority = "unverified_full_proof".

    Returns ``(seed_entry_dict, seed_priority)`` or ``(None, None)``.
    """
    final_solutions = memory.all_final_solutions()

    # Tier 1: verified clean ───────────────────────────────────────────────
    candidates_verified = []
    for tid, fe in final_solutions.items():
        if fe.get("is_relaxation"): continue
        if (fe.get("if_final_true") or "").lower() != "true": continue
        task_entry = memory.get_task_output(tid) or {}
        rnd = task_entry.get("round", 10**9)
        candidates_verified.append((rnd, tid, task_entry))
    if candidates_verified:
        candidates_verified.sort(key=lambda x: (x[0], x[1]))
        return candidates_verified[0][2], "verified_full_proof"

    # Tier 2: nearly verified (verdict=Correct after minor fixes, refine
    # exhausted but no major gaps) ─────────────────────────────────────────
    candidates_nearly = []
    for tid, fe in final_solutions.items():
        if fe.get("is_relaxation"): continue
        if (fe.get("if_final_true") or "").lower() != "nearly true": continue
        task_entry = memory.get_task_output(tid) or {}
        rnd = task_entry.get("round", 10**9)
        candidates_nearly.append((rnd, tid, task_entry, fe))
    if candidates_nearly:
        candidates_nearly.sort(key=lambda x: (x[0], x[1]))
        _, _, task_entry, fe = candidates_nearly[0]
        # The refined Final_Solution lives in final_solutions; the task_output
        # still holds the pre-refine draft. Wrap so seed_text picks up the
        # refined text (the harness reads ``solution`` or ``full_text``).
        seed = dict(task_entry)
        refined = fe.get("Final_Solution") or ""
        if refined:
            seed["solution"] = refined
            seed["full_text"] = refined
        seed["problem_solved"] = fe.get("problem_solved") or seed.get("problem_solved")
        return seed, "nearly_verified_full_proof"

    # Tier 3: anything else (unverified or rejected) ───────────────────────
    candidates_unverified = []
    for tid, te in memory.all_task_outputs().items():
        if te.get("is_relaxation"): continue
        if not te.get("solution"):  continue
        rnd = te.get("round", 0)
        candidates_unverified.append((rnd, tid, te))
    if candidates_unverified:
        candidates_unverified.sort(key=lambda x: (-x[0], x[1]))  # latest round wins
        return candidates_unverified[0][2], "unverified_full_proof"
    return None, None


def collect_verified_partials(memory) -> list[tuple[str, str]]:
    """Collect (label, full_text) pairs for every verified-relaxation writeup."""
    out = []
    for tid, fe in memory.all_final_solutions().items():
        if (fe.get("if_final_true") or "").lower() != "true": continue
        if not fe.get("is_relaxation"): continue
        te = memory.get_task_output(tid) or {}
        text = te.get("full_text") or fe.get("Final_Solution") or ""
        ps = te.get("problem_solved") or fe.get("problem_solved") or ""
        if not text:
            continue
        label = f"{tid}: {ps}" if ps else tid
        out.append((label, text))
    return out
