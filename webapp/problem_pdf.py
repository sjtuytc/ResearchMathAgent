"""Compile a problem statement to PDF — the renderer behind the PDF-only
Question tab.

Works for every dataset: benchmark problems are LaTeX (.tex using custom macros
not always present in the shared preamble), while curated RM14k / erdos / unsolved
problems are markdown/plain text (sometimes with literal ``\\n`` escapes). Both are
normalised onto the robust ``issue_pdf`` preamble (plus ``\\providecommand``
fallbacks for common custom macros) and compiled with tectonic using
``continue-on-errors`` so an undefined macro never hard-fails the build.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .issue_pdf import _PREAMBLE, _TECTONIC, md_to_latex

# Fallback defs for custom macros used by benchmark problem sources. Uses
# \providecommand so it never clashes with a real definition in the body.
_MACROS = r"""
\providecommand{\bR}{\mathbb{R}}
\providecommand{\bC}{\mathbb{C}}
\providecommand{\bZ}{\mathbb{Z}}
\providecommand{\bN}{\mathbb{N}}
\providecommand{\bQ}{\mathbb{Q}}
\providecommand{\bE}{\mathbb{E}}
\providecommand{\bP}{\mathbb{P}}
\providecommand{\bF}{\mathbb{F}}
\providecommand{\bH}{\mathbb{H}}
\providecommand{\roots}{\operatorname{roots}}
\providecommand{\score}{\operatorname{score}}
\providecommand{\Tr}{\operatorname{Tr}}
\providecommand{\rank}{\operatorname{rank}}
\providecommand{\supp}{\operatorname{supp}}
\providecommand{\Var}{\operatorname{Var}}
\providecommand{\Cov}{\operatorname{Cov}}
\providecommand{\sgn}{\operatorname{sgn}}
"""

_STRIP_RE = re.compile(
    r"^\s*\\(input\{[^}]*\}|documentclass\b.*|usepackage\b.*|RequirePackage\b.*|"
    r"title\{.*|author\{.*|date\{.*|maketitle|begin\{document\}|end\{document\})\s*$"
)


def _looks_latex(s: str) -> bool:
    return bool(re.search(
        r"\\input\{preamble\}|\\documentclass|\\begin\{document\}|\\\[|"
        r"\\begin\{(align|equation|theorem|lemma|definition|proof)", s))


def _normalise(s: str) -> str:
    # Some sources store literal "\n"/"\t" escapes instead of real whitespace.
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n").replace("\\t", "\t")
    return s


def _clean_latex_body(s: str) -> str:
    return "\n".join(ln for ln in s.splitlines() if not _STRIP_RE.match(ln))


def _build_tex(title: str, statement: str) -> str:
    statement = _normalise(statement or "")
    body = _clean_latex_body(statement) if _looks_latex(statement) else md_to_latex(statement)
    head = _PREAMBLE + _MACROS + "\\begin{document}\n"
    if title:
        head += "{\\Large\\bfseries " + md_to_latex(title).strip() + "}\\par\\medskip\n"
    return head + body + "\n\\end{document}\n"


def _build_verbatim_tex(title: str, statement: str) -> str:
    """Always-compilable fallback: render the raw statement as verbatim text.

    Used when the smart build produces no PDF (broken/fragmentary LaTeX in the
    source), so the PDF-only Question tab always shows *something* readable.
    """
    statement = _normalise(statement or "")
    # verbatim cannot contain its own end marker; neutralise it.
    safe = statement.replace("\\end{verbatim}", "\\end {verbatim}")
    head = _PREAMBLE + "\\begin{document}\n"
    if title:
        head += "{\\Large\\bfseries " + md_to_latex(title).strip() + "}\\par\\medskip\n"
    head += ("{\\small\\itshape The statement below is shown as plain source because it "
             "could not be typeset.}\\par\\medskip\n")
    return head + "\\begin{verbatim}\n" + safe + "\n\\end{verbatim}\n\\end{document}\n"


def _cache_paths(repo_root: Path, key: str) -> tuple[Path, Path]:
    d = repo_root / "documents" / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.pdf", d / f"{key}.hash"


def compile_problem_statement_pdf(repo_root: Path, dataset: str, problem_id: str,
                                  title: str, statement: str, force: bool = False) -> dict:
    """Compile a problem's statement to PDF. Returns {ok, pdf_url, log}."""
    if not (statement or "").strip():
        return {"ok": False, "pdf_url": None, "log": "no statement source"}

    key = re.sub(r"[^A-Za-z0-9_-]", "_", f"problem_{dataset}_{problem_id}")
    dest, hash_file = _cache_paths(repo_root, key)
    cur_hash = hashlib.md5((statement + "||" + (title or "")).encode("utf-8")).hexdigest()[:12]
    if not force and dest.is_file() and hash_file.is_file() and hash_file.read_text().strip() == cur_hash:
        return {"ok": True, "pdf_url": f"/api/pdf/{key}.pdf", "log": "cached"}

    tect = _TECTONIC if os.path.isfile(_TECTONIC) and os.access(_TECTONIC, os.X_OK) \
        else shutil.which("tectonic") or shutil.which("pdflatex")
    if not tect:
        return {"ok": False, "pdf_url": None, "log": "No LaTeX toolchain available"}

    tex = _build_tex(title, statement)
    with tempfile.TemporaryDirectory(prefix="rma_prob_") as tmp:
        build = Path(tmp)
        (build / "main.tex").write_text(tex, encoding="utf-8")

        def run(cmd: list[str]) -> tuple[int, str]:
            try:
                p = subprocess.run(cmd, cwd=build, capture_output=True, timeout=180)
                return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")
            except subprocess.TimeoutExpired:
                return 1, "compilation timed out"

        if "tectonic" in tect:
            rc, log = run([tect, "main.tex"])
            if rc != 0:
                rc, log = run([tect, "-Z", "continue-on-errors", "main.tex"])
        else:
            rc, log = run([tect, "-interaction=nonstopmode", "main.tex"])

        note = "OK"
        # Fallback: if the smart build produced no PDF (broken/fragmentary LaTeX),
        # render the raw statement verbatim so the PDF-only tab always shows it.
        if not (build / "main.pdf").is_file():
            (build / "main.tex").write_text(_build_verbatim_tex(title, statement), encoding="utf-8")
            if "tectonic" in tect:
                run([tect, "-Z", "continue-on-errors", "main.tex"])
            else:
                run([tect, "-interaction=nonstopmode", "main.tex"])
            note = "OK (verbatim fallback)"

        if (build / "main.pdf").is_file():
            shutil.copyfile(build / "main.pdf", dest)
            hash_file.write_text(cur_hash)
            return {"ok": True, "pdf_url": f"/api/pdf/{key}.pdf", "log": note}
        return {"ok": False, "pdf_url": None, "log": f"build failed\n{log[-1500:]}"}
