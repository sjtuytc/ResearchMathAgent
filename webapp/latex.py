"""LaTeX compilation service for the Research Math Agent web app.

Compiles an agent's ``solution.tex`` (full document or a proof fragment) to PDF
so the UI can preview it. Uses the repo's shared ``problems/preamble.tex`` and
the system ``latexmk``/``pdflatex`` toolchain. Degrades gracefully (returns a
clear message) when no TeX toolchain is installed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_TIMEOUT = 240


def latex_available() -> str | None:
    return shutil.which("latexmk") or shutil.which("pdflatex")


def pdf_dir(repo_root: Path) -> Path:
    d = repo_root / "documents" / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_pdf_name(name: str) -> str:
    base = _NAME_RE.sub("_", name).strip("._-") or "solution"
    return base if base.endswith(".pdf") else base + ".pdf"


def build_main_tex(content: str, has_preamble_file: bool) -> str:
    """Wrap a proof fragment into a compilable document, or pass a full doc
    through unchanged."""
    has_begin = "\\begin{document}" in content
    has_docclass = "\\documentclass" in content
    has_input_pre = "\\input{preamble" in content

    if has_begin:
        return content  # already a full document (declares/inputs its own preamble)

    parts: list[str] = []
    if not has_docclass and not has_input_pre:
        if has_preamble_file:
            parts.append("\\input{preamble}")
        else:
            parts.append("\\documentclass[12pt]{article}\n\\usepackage{amsmath,amssymb,amsthm}")
    parts.append("\\begin{document}")
    parts.append(content)
    if "\\end{document}" not in content:
        parts.append("\\end{document}")
    return "\n".join(parts) + "\n"


def compile_tex(repo_root: Path, content: str, name: str) -> dict:
    """Compile ``content`` to ``documents/pdf/<name>.pdf``. Returns
    {ok, pdf, log}."""
    tool = latex_available()
    if not tool:
        return {"ok": False, "pdf": None,
                "log": "No LaTeX toolchain (latexmk/pdflatex) is installed on the server."}
    if not content.strip():
        return {"ok": False, "pdf": None, "log": "Empty document."}

    pdf_name = safe_pdf_name(name)
    preamble = repo_root / "problems" / "preamble.tex"
    has_preamble = preamble.is_file()

    with tempfile.TemporaryDirectory(prefix="rma_tex_") as tmp:
        build = Path(tmp)
        if has_preamble:
            shutil.copyfile(preamble, build / "preamble.tex")
        (build / "main.tex").write_text(build_main_tex(content, has_preamble), encoding="utf-8")

        if shutil.which("latexmk"):
            cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
        else:
            cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
        try:
            proc = subprocess.run(cmd, cwd=build, text=True, capture_output=True, timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "pdf": None, "log": "LaTeX compilation timed out."}

        out_pdf = build / "main.pdf"
        log_tail = (proc.stdout or "")[-4000:]
        if proc.returncode == 0 and out_pdf.is_file():
            dest = pdf_dir(repo_root) / pdf_name
            shutil.copyfile(out_pdf, dest)
            return {"ok": True, "pdf": pdf_name, "log": "BUILD OK"}
        return {"ok": False, "pdf": None, "log": f"BUILD FAILED (exit {proc.returncode})\n{log_tail}"}
