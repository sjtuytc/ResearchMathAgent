"""Typeset a solver proof into a self-contained, Overleaf-clean LaTeX document.

First Proof spec (Second Batch) requires the output to be a JSON file in which
each of the ten solutions is "a separate, properly compilable LaTeX document",
"document class article with no changes to margin and line spacing, and in 12
point font", up to 12 pages, and compiling "cleanly on Overleaf without
modification".

The solver pipeline emits proofs as *prose with Unicode math* (e.g. ``GL_{n+1}``,
``∫``, ``→``), not LaTeX. This module turns that prose into a complete
``\\documentclass[12pt]{article}`` document via an LLM typesetting pass, then
verifies it with a local ``pdflatex`` compile and an error-feedback repair loop.
If the document exceeds the page limit it runs a condense pass.

Design notes
------------
* The typesetter is a *formatting* agent. Its mandate is faithful transcription
  of the mathematics into LaTeX — it must not alter, strengthen, or "fix" the
  mathematical content. This mirrors the (now-removed) polisher's contract.
* Stdlib-only helpers (``compile_pdf``, ``extract_latex_document``,
  ``count_pages``) import nothing from the Gemini SDK, so they are testable in
  isolation. The LLM passes import ``call_gemini`` lazily.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Default repair / condense budgets. Each is one extra LLM call.
DEFAULT_MAX_REPAIRS = 3
DEFAULT_MAX_CONDENSE = 2
PAGE_LIMIT = 12

# ── pdflatex availability ─────────────────────────────────────────────────────


def pdflatex_available() -> bool:
    return shutil.which("pdflatex") is not None


# ── LaTeX text wrangling (no LLM, no SDK) ─────────────────────────────────────

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n|\n```$", re.MULTILINE)
_PAGES_RE = re.compile(r"Output written on .*?\((\d+)\s+pages?", re.IGNORECASE)
# pdflatex errors appear either as "! message" (default) or, with
# -file-line-error, as "./file.tex:LINE: message". Match both.
_TEX_ERROR_RE = re.compile(
    r"^(?:! .*|(?:\./)?[\w./-]+:\d+:.*)$", re.MULTILINE)


def extract_latex_document(text: str) -> str:
    """Pull a clean LaTeX document out of an LLM response.

    Strips Markdown code fences and, if a ``\\documentclass ... \\end{document}``
    span is present, returns exactly that span. Falls back to the de-fenced text.
    """
    stripped = _FENCE_RE.sub("", text).strip()
    start = stripped.find("\\documentclass")
    end = stripped.rfind("\\end{document}")
    if start != -1 and end != -1:
        return stripped[start : end + len("\\end{document}")].strip()
    return stripped


def count_pages(log: str) -> int | None:
    """Parse the page count out of a pdflatex log. None if not found."""
    matches = _PAGES_RE.findall(log)
    return int(matches[-1]) if matches else None


def tex_errors(log: str) -> list[str]:
    """Return the TeX error lines (``! ...``) from a pdflatex log."""
    return _TEX_ERROR_RE.findall(log)


def minimal_unsolved_document(message: str) -> str:
    """A guaranteed-compilable article-class doc reporting no solution.

    Used as a fallback when a run crashed or produced no proof to typeset, so the
    output JSON still contains a clean LaTeX document for every problem. It does
    NOT embed the problem statement (which is itself a full LaTeX document and
    would not nest), keeping the fallback trivially compilable.
    """
    safe = message.replace("\\", " ").replace("{", "(").replace("}", ")").replace("$", "")
    return (
        "\\documentclass[12pt]{article}\n"
        "\\usepackage{amsmath,amssymb,amsthm}\n"
        "\\title{Solution}\n\\author{}\n\\date{}\n"
        "\\begin{document}\n\\maketitle\n"
        "\\section*{Result}\n"
        f"The system was unable to produce a solution to this problem. {safe}\n"
        "\\end{document}\n"
    )


@dataclass
class CompileResult:
    ok: bool                    # pdf produced AND no TeX errors in the log
    pdf_produced: bool
    pages: int | None
    log: str                    # full pdflatex log (.log file contents)
    errors: list[str]           # extracted "! ..." lines


def compile_pdf(tex_source: str, *, workdir: Path | None = None,
                timeout: int = 180) -> CompileResult:
    """Compile ``tex_source`` with pdflatex (two passes for cross-refs).

    Uses ``-interaction=nonstopmode`` (not ``-halt-on-error``) so the whole log
    of errors is collected for the repair prompt while still producing a PDF
    when possible. Returns a CompileResult; never raises on a LaTeX error.
    """
    if not pdflatex_available():
        return CompileResult(ok=False, pdf_produced=False, pages=None,
                             log="pdflatex not installed", errors=["pdflatex not installed"])

    tmp_ctx = None
    if workdir is None:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="latexcheck_")
        workdir = Path(tmp_ctx.name)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    tex_path = workdir / "solution.tex"
    pdf_path = workdir / "solution.pdf"
    log_path = workdir / "solution.log"
    tex_path.write_text(tex_source, encoding="utf-8")

    log = ""
    try:
        for _ in range(2):  # second pass resolves \ref / \cite / page totals
            # nonstopmode (without -halt-on-error) keeps going past errors so the
            # full error list lands in the .log for the repair prompt.
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-file-line-error",
                 "solution.tex"],
                cwd=str(workdir), capture_output=True, timeout=timeout,
            )
    except subprocess.TimeoutExpired:
        return CompileResult(ok=False, pdf_produced=pdf_path.exists(), pages=None,
                             log="pdflatex timed out", errors=["pdflatex timed out"])
    finally:
        if log_path.exists():
            log = log_path.read_text(encoding="utf-8", errors="replace")

    errors = tex_errors(log)
    pdf_produced = pdf_path.exists() and pdf_path.stat().st_size > 0
    pages = count_pages(log)
    ok = pdf_produced and not errors
    result = CompileResult(ok=ok, pdf_produced=pdf_produced, pages=pages,
                           log=log, errors=errors)
    if tmp_ctx is not None:
        tmp_ctx.cleanup()
    return result


# ── LLM prompts ───────────────────────────────────────────────────────────────

_SYSTEM = """You are a meticulous LaTeX typesetter for a mathematics journal.

Your sole job is to transcribe a mathematical solution into a complete,
self-contained LaTeX document that compiles cleanly on Overleaf with pdflatex,
with no edits required.

ABSOLUTE RULES
1. Do NOT change the mathematics. Do not add steps, fix gaps, strengthen claims,
   or "improve" the argument. Transcribe faithfully, including any limitations
   or gaps the author stated. You are a typesetter, not a co-author.
2. Convert all Unicode math (∫, →, ×, ⊗, ≤, subscripts/superscripts written as
   _{...}/^{...}, Greek spelled out as words like "psi", etc.) into correct
   LaTeX math mode. All mathematics must be inside $...$, \\[...\\], or proper
   math environments (align, equation, gather, ...).
3. Output a SINGLE complete document and NOTHING else — no commentary, no
   Markdown fences. Start with \\documentclass and end with \\end{document}.

REQUIRED PREAMBLE (the spec is strict about format):
- \\documentclass[12pt]{article}
- Do NOT change margins or line spacing. Do NOT load geometry, fullpage,
  setspace, or any package that alters margins/spacing.
- You MAY load only standard, Overleaf-default packages:
  amsmath, amssymb, amsthm, mathtools, and (if genuinely needed) hyperref.
- Use \\title / \\author{} (leave author blank or "Anonymous") / \\date{} and
  \\maketitle.
- If the proof does not fit in 12 pages at this format, tighten the prose —
  never change margins, font size, or load any format-altering package.

STRUCTURE:
- A short statement of the problem (typeset from the LaTeX problem statement you
  are given).
- The solution / proof, faithfully typeset, using theorem/lemma/proof
  environments where natural.
- If the author reports the problem could NOT be solved, say so plainly in the
  document and present the partial progress honestly.

LENGTH: at most 12 pages in this format. Be complete but do not pad.
COMPILE-SAFETY: every \\begin has a matching \\end; every $ is balanced; no
undefined commands; no stray Unicode. The document must compile on the first try.
"""


def _typeset_prompt(problem_latex: str, proof_text: str, *,
                    solved: bool, score: float) -> str:
    status = (
        "The pipeline CONFIRMED this as a complete solution."
        if solved else
        "The pipeline did NOT confirm a complete solution; this is the best "
        "attempt. Typeset it faithfully and make clear in the document where the "
        "argument is partial or where gaps remain (do not paper over them)."
    )
    return (
        f"{status} (internal grader score: {score:.1f}/7)\n\n"
        "=== PROBLEM STATEMENT (already in LaTeX) ===\n"
        f"{problem_latex}\n\n"
        "=== SOLUTION TO TYPESET (prose with Unicode math) ===\n"
        f"{proof_text}\n\n"
        "Produce the complete LaTeX document now."
    )


def _repair_prompt(tex_source: str, errors: list[str], log_tail: str) -> str:
    err_block = "\n".join(errors[:40]) or "(no explicit '!' lines; PDF was not produced)"
    return (
        "The LaTeX document below FAILED to compile with pdflatex. Fix the "
        "compilation errors and return the COMPLETE corrected document. Change "
        "ONLY what is needed to compile — do not alter the mathematics, and keep "
        "\\documentclass[12pt]{article} with default margins/spacing.\n\n"
        f"=== pdflatex errors ===\n{err_block}\n\n"
        f"=== end of pdflatex log ===\n{log_tail[-2500:]}\n\n"
        "=== current document ===\n"
        f"{tex_source}\n\n"
        "Return ONLY the corrected complete document (\\documentclass ... "
        "\\end{document}), no commentary, no code fences."
    )


def _condense_prompt(tex_source: str, pages: int) -> str:
    return (
        f"This document compiles but is {pages} pages; the limit is {PAGE_LIMIT} "
        "pages in 12pt article format with default margins. Tighten the exposition "
        "so it fits in at most 12 pages WITHOUT removing any mathematical step or "
        "weakening the argument (condense prose, merge displays, remove redundancy "
        "only). Keep it compilable. DO NOT shrink margins, change font size, or "
        "load any package that affects page count (geometry, fullpage, setspace, "
        "savetrees, etc.) — those moves disqualify the submission. Return ONLY "
        "the complete document, no commentary, no code fences.\n\n"
        f"{tex_source}"
    )


# ── Orchestration ─────────────────────────────────────────────────────────────


@dataclass
class TypesetResult:
    latex: str
    compiles: bool
    pages: int | None
    repair_attempts: int
    condense_attempts: int
    note: str = ""


async def typeset_and_verify(
    problem_latex: str,
    proof_text: str,
    *,
    run_id: str,
    store,
    solved: bool,
    score: float,
    max_repairs: int = DEFAULT_MAX_REPAIRS,
    max_condense: int = DEFAULT_MAX_CONDENSE,
) -> TypesetResult:
    """Typeset a proof to LaTeX, then compile-check + repair + condense.

    Every LLM call is logged to ``store`` under agent name ``latex_export`` so
    its tokens (in/out/reasoning) roll up into the run's totals exactly like any
    other pipeline call. If pdflatex is unavailable, the first typeset output is
    returned as-is with ``compiles=False`` and a note (e.g. local dry runs).
    """
    from .gemini import call_gemini  # lazy: keeps stdlib helpers SDK-free

    # 1. Initial typeset pass.
    call = await call_gemini(
        _typeset_prompt(problem_latex, proof_text, solved=solved, score=score),
        run_id=run_id, notebook_id="ROOT", agent="latex_export",
        inputs={"stage": "typeset", "solved": solved}, system_instruction=_SYSTEM,
        store=store,
    )
    tex = extract_latex_document(call.output)

    if not pdflatex_available():
        return TypesetResult(latex=tex, compiles=False, pages=None,
                             repair_attempts=0, condense_attempts=0,
                             note="pdflatex unavailable — compile not verified")

    result = compile_pdf(tex)

    # 2. Repair loop on compile failure.
    repairs = 0
    while not result.ok and repairs < max_repairs:
        repairs += 1
        call = await call_gemini(
            _repair_prompt(tex, result.errors, result.log),
            run_id=run_id, notebook_id="ROOT", agent="latex_export",
            inputs={"stage": "repair", "attempt": repairs}, system_instruction=_SYSTEM,
            store=store,
        )
        tex = extract_latex_document(call.output)
        result = compile_pdf(tex)

    # 3. Condense loop if over the page limit (only if it compiles).
    condenses = 0
    while result.ok and result.pages and result.pages > PAGE_LIMIT \
            and condenses < max_condense:
        condenses += 1
        call = await call_gemini(
            _condense_prompt(tex, result.pages),
            run_id=run_id, notebook_id="ROOT", agent="latex_export",
            inputs={"stage": "condense", "attempt": condenses}, system_instruction=_SYSTEM,
            store=store,
        )
        new_tex = extract_latex_document(call.output)
        new_result = compile_pdf(new_tex)
        if new_result.ok:           # only accept a condense that still compiles
            tex, result = new_tex, new_result
        else:
            break

    note = ""
    if not result.ok:
        note = f"did not compile cleanly after {repairs} repair attempt(s)"
    elif result.pages and result.pages > PAGE_LIMIT:
        note = f"compiles but {result.pages} pages exceeds the {PAGE_LIMIT}-page limit"
    return TypesetResult(latex=tex, compiles=result.ok, pages=result.pages,
                         repair_attempts=repairs, condense_attempts=condenses, note=note)
