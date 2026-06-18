"""Compile an issue thread to PDF via tectonic.

Issues are written in markdown with embedded LaTeX math ($...$, $$...$$).
We convert the markdown structure to LaTeX and compile with tectonic.
Results are cached in documents/pdf/ and invalidated when the issue mtime changes.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_TECTONIC = "/projects/bhov/zzhao18/software/bin/tectonic"

_PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage{amsmath,amssymb,amsthm,mathtools}
\usepackage[margin=0.85in,top=0.75in]{geometry}
\usepackage{microtype,parskip,xcolor,hyperref}
\usepackage{mdframed}
\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}

\newtheorem{theorem}{Theorem}
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{proposition}[theorem]{Proposition}
\newtheorem{corollary}[theorem]{Corollary}
\newtheorem{claim}[theorem]{Claim}
\newtheorem{conjecture}[theorem]{Conjecture}
\theoremstyle{definition}
\newtheorem{definition}[theorem]{Definition}
\newtheorem{example}[theorem]{Example}
\theoremstyle{remark}
\newtheorem{remark}[theorem]{Remark}

\definecolor{agentbg}{rgb}{0.10,0.13,0.18}
\definecolor{agentborder}{rgb}{0.18,0.25,0.38}
\definecolor{authorcol}{rgb}{0.35,0.65,1.0}
\definecolor{agenttext}{rgb}{0.90,0.93,0.95}

\setlength{\parindent}{0pt}
"""

_MATH_PLACEHOLDER = "\x00MATH\x00"


def _protect_math(text: str) -> tuple[str, list[str]]:
    """Extract all math spans, replace with numbered placeholders."""
    stores: list[str] = []

    def _store(m: re.Match) -> str:
        stores.append(m.group(0))
        return f"\x00M{len(stores)-1}\x00"

    # display math first ($$...$$  or  \[...\])
    text = re.sub(r"\$\$[\s\S]*?\$\$", _store, text)
    text = re.sub(r"\\\[[\s\S]*?\\\]", _store, text)
    # inline math ($...$), single dollar, non-greedy
    text = re.sub(r"\$(?!\$)[^\$\n]+?\$", _store, text)
    # \(...\)
    text = re.sub(r"\\\([\s\S]*?\\\)", _store, text)
    return text, stores


def _restore_math(text: str, stores: list[str]) -> str:
    def _sub(m: re.Match) -> str:
        i = int(m.group(1))
        return stores[i] if i < len(stores) else m.group(0)
    return re.sub(r"\x00M(\d+)\x00", _sub, text)


def _escape_latex(s: str) -> str:
    """Escape LaTeX special chars (skip math zones — caller has already protected them)."""
    # Only escape chars that aren't part of LaTeX commands
    s = s.replace("&", r"\&")
    s = s.replace("%", r"\%")
    s = s.replace("#", r"\#")
    s = s.replace("^", r"\^{}")
    s = s.replace("~", r"\textasciitilde{}")
    # < > only in text mode
    s = re.sub(r"<(?![^>]*>)", r"\\textless{}", s)
    s = re.sub(r"(?<![<\w])>", r"\\textgreater{}", s)
    return s


def _inline_md(s: str) -> str:
    """Convert inline markdown (bold, italic, code, links) — math already protected."""
    # bold-italic
    s = re.sub(r"\*\*\*(.+?)\*\*\*", r"\\textbf{\\textit{\1}}", s)
    # bold
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"__(.+?)__", r"\\textbf{\1}", s)
    # italic
    s = re.sub(r"\*([^*\n]+?)\*", r"\\textit{\1}", s)
    s = re.sub(r"_([^_\n]+?)_", r"\\textit{\1}", s)
    # inline code  `...`
    s = re.sub(r"`([^`]+)`", lambda m: r"\texttt{" + m.group(1).replace("_", r"\_") + "}", s)
    # markdown links [text](url)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\\href{\2}{\1}", s)
    # bare urls
    s = re.sub(r"(?<![{(])(https?://\S+)", r"\\url{\1}", s)
    return s


def md_to_latex(md: str) -> str:
    """Convert a markdown+LaTeX-math string to a LaTeX document body (no preamble/begin/end)."""
    # Protect math from markdown processing
    text, stores = _protect_math(md)

    lines = text.splitlines()
    out: list[str] = []
    i = 0
    in_itemize = False
    in_enumerate = False
    in_code_block = False

    def close_lists():
        nonlocal in_itemize, in_enumerate
        if in_itemize:
            out.append(r"\end{itemize}"); in_itemize = False
        if in_enumerate:
            out.append(r"\end{enumerate}"); in_enumerate = False

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        # ── Fenced code block ──────────────────────────────────────────────────
        if line.startswith("```") or line.startswith("~~~"):
            close_lists()
            if not in_code_block:
                out.append(r"\begin{verbatim}")
                in_code_block = True
            else:
                out.append(r"\end{verbatim}")
                in_code_block = False
            i += 1; continue
        if in_code_block:
            out.append(raw)
            i += 1; continue

        # ── Pass-through LaTeX environments ───────────────────────────────────
        if re.match(r"\\(begin|end)\{", line):
            close_lists()
            out.append(line)
            i += 1; continue

        # ── ATX headings ──────────────────────────────────────────────────────
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            close_lists()
            depth = len(m.group(1))
            title = _inline_md(_restore_math(m.group(2), stores))
            cmds = {1: r"\section*", 2: r"\subsection*", 3: r"\subsubsection*", 4: r"\paragraph*"}
            out.append(f"{cmds.get(depth, r'\\paragraph*')}{{{title}}}")
            i += 1; continue

        # ── Horizontal rule ────────────────────────────────────────────────────
        if re.match(r"^[-*_]{3,}\s*$", line):
            close_lists()
            out.append(r"\medskip\hrule\medskip")
            i += 1; continue

        # ── Unordered list ─────────────────────────────────────────────────────
        m = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if m:
            if in_enumerate: out.append(r"\end{enumerate}"); in_enumerate = False
            if not in_itemize: out.append(r"\begin{itemize}"); in_itemize = True
            content = _inline_md(_restore_math(m.group(2), stores))
            out.append(r"\item " + content)
            i += 1; continue

        # ── Ordered list ───────────────────────────────────────────────────────
        m = re.match(r"^(\s*)\d+[.)]\s+(.*)", line)
        if m:
            if in_itemize: out.append(r"\end{itemize}"); in_itemize = False
            if not in_enumerate: out.append(r"\begin{enumerate}"); in_enumerate = True
            content = _inline_md(_restore_math(m.group(2), stores))
            out.append(r"\item " + content)
            i += 1; continue

        # ── Blank line ─────────────────────────────────────────────────────────
        if not line.strip():
            close_lists()
            out.append("")
            i += 1; continue

        # ── Blockquote ─────────────────────────────────────────────────────────
        if line.startswith("> "):
            close_lists()
            content = _inline_md(_restore_math(line[2:], stores))
            out.append(r"\begin{quote}" + content + r"\end{quote}")
            i += 1; continue

        # ── Normal paragraph line ──────────────────────────────────────────────
        # Close lists if we hit normal text
        close_lists()
        restored = _restore_math(line, stores)
        # Don't double-escape lines that look like LaTeX commands
        if re.match(r"\s*\\[A-Za-z]", restored):
            out.append(restored)
        else:
            out.append(_inline_md(restored))
        i += 1

    close_lists()
    if in_code_block:
        out.append(r"\end{verbatim}")

    return "\n".join(out)


def _build_issue_tex(issue: dict) -> str:
    """Assemble a full LaTeX document from an issue thread."""
    title = issue.get("title", "Issue")
    status = issue.get("status", "open")
    pid = issue.get("problem_id", "")
    issue_id = issue.get("id", "")

    parts = [_PREAMBLE]
    parts.append(r"\begin{document}")
    # Title block
    safe_title = title.replace("_", r"\_").replace("&", r"\&").replace("#", r"\#").replace("%", r"\%")
    parts.append(rf"""\begin{{center}}
{{\Large\bfseries {safe_title}}}\\[4pt]
{{\small\color{{gray}} {pid} / {issue_id} \quad|\quad status: {status}}}
\end{{center}}
\medskip\hrule\bigskip""")

    # Body (if present)
    body = (issue.get("body") or "").strip()
    if body:
        parts.append(md_to_latex(body))
        parts.append(r"\bigskip")

    # Comments
    comments = issue.get("comments", [])
    for c in comments:
        cbody = (c.get("body") or "").strip()
        if not cbody:
            continue
        author = c.get("author", "")
        role = c.get("role", "")
        created = (c.get("created_at") or "")[:16].replace("T", " ")
        safe_author = author.replace("_", r"\_")
        role_label = f"[{role}]" if role else ""

        parts.append(rf"""\begin{{mdframed}}[backgroundcolor=white,linecolor=black!25,linewidth=0.8pt,innerleftmargin=8pt,innerrightmargin=8pt,innertopmargin=6pt,innerbottommargin=6pt]
{{\small\bfseries\color{{black!70}} {safe_author} {role_label}}} \hfill {{\small\color{{black!50}} {created}}}
\medskip

""")
        parts.append(md_to_latex(cbody))
        parts.append(r"\end{mdframed}" + "\n")

    parts.append(r"\end{document}")
    return "\n".join(parts)


def _pdf_cache_path(repo_root: Path, problem_id: str, issue_id: str) -> Path:
    d = repo_root / "documents" / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"issue_{problem_id}_{issue_id}.pdf"


def _issue_hash(issue: dict) -> str:
    s = json.dumps(issue, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(s.encode()).hexdigest()[:12]


def _hash_file(repo_root: Path, problem_id: str, issue_id: str) -> Path:
    return repo_root / "documents" / "pdf" / f"issue_{problem_id}_{issue_id}.hash"


def compile_issue_pdf(repo_root: Path, issue: dict, force: bool = False) -> dict:
    """Compile issue thread to PDF. Returns {ok, pdf_url, log}."""
    problem_id = issue.get("problem_id", "")
    issue_id = issue.get("id", "")
    if not problem_id or not issue_id:
        return {"ok": False, "pdf_url": None, "log": "Missing problem_id or issue id"}

    dest = _pdf_cache_path(repo_root, problem_id, issue_id)
    hash_file = _hash_file(repo_root, problem_id, issue_id)
    cur_hash = _issue_hash(issue)

    # Serve from cache if hash matches
    if not force and dest.is_file() and hash_file.is_file():
        if hash_file.read_text().strip() == cur_hash:
            return {"ok": True, "pdf_url": f"/api/pdf/issue_{problem_id}_{issue_id}.pdf", "log": "cached"}

    import os
    tectonic = _TECTONIC if os.path.isfile(_TECTONIC) and os.access(_TECTONIC, os.X_OK) else shutil.which("tectonic") or shutil.which("pdflatex")
    if not tectonic:
        return {"ok": False, "pdf_url": None, "log": "No LaTeX toolchain available"}

    tex = _build_issue_tex(issue)

    with tempfile.TemporaryDirectory(prefix="rma_issue_") as tmp:
        build = Path(tmp)
        (build / "main.tex").write_text(tex, encoding="utf-8")
        cmd = [tectonic, "main.tex"] if "tectonic" in tectonic else ["pdflatex", "-interaction=nonstopmode", "main.tex"]
        try:
            proc = subprocess.run(cmd, cwd=build, text=True, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            return {"ok": False, "pdf_url": None, "log": "Compilation timed out"}

        out_pdf = build / "main.pdf"
        if proc.returncode == 0 and out_pdf.is_file():
            shutil.copyfile(out_pdf, dest)
            hash_file.write_text(cur_hash)
            return {"ok": True, "pdf_url": f"/api/pdf/issue_{problem_id}_{issue_id}.pdf", "log": "OK"}
        log = (proc.stdout or "") + (proc.stderr or "")
        return {"ok": False, "pdf_url": None, "log": f"Build failed (exit {proc.returncode})\n{log[-3000:]}"}
