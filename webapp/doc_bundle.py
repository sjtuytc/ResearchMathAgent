"""Generate a combined PDF context bundle from all documents using tectonic.

Falls back to fpdf2 when tectonic is unavailable.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure user-local fpdf2 is importable for fallback
_user_site = Path.home() / ".local/lib/python3.12/site-packages"
if str(_user_site) not in sys.path:
    sys.path.insert(0, str(_user_site))

_FONT_REGULAR = "/usr/share/fonts/truetype/DejaVuSans.ttf"
_FONT_BOLD    = "/usr/share/fonts/truetype/DejaVuSans-Bold.ttf"


# ── Markdown → LaTeX conversion ───────────────────────────────────────────────

_EMOJI_MAP = {
    "✅": r"\checkmark{}",       # ✅
    "❌": r"$\times$",           # ❌
    "\U0001f7e1": r"(\textasciitilde{})",  # 🟡
    "\U0001f534": r"(!)",            # 🔴
    "\U0001f7e0": r"(!)",            # 🟠
    "⚪": r"(\textopenbullet{})",# ⚪
    "⚠️": r"(!)",          # ⚠️
    "⚠": r"(!)",                # ⚠
    "\U0001f50d": r"",               # 🔍
    "\U0001f6ab": r"(!)",            # 🚫
    "★": r"$\star$",            # ★
    "▶": r"$\triangleright$",   # ▶
    "▼": r"$\triangledown$",    # ▼
    "◐": r"(\textopenbullet{})",# ◐
    "●": r"$\bullet$",          # ●
    "○": r"$\circ$",            # ○
    "\U0001f4dd": r"",               # 📝
    "\U0001f4c4": r"",               # 📄
    "\U0001f4d6": r"",               # 📖
    "\U0001f4a1": r"",               # 💡
    "\U0001f3af": r"",               # 🎯
    "\U0001f4c8": r"",               # 📈
    "\U0001f4ca": r"",               # 📊
    # Typography — these are <0xFF but render wrong under T1 font encoding.
    "·": r"\textperiodcentered{}",  # · middle dot
    "–": "--",                  # – en dash
    "—": "---",                 # — em dash
    "‘": "`",                   # ' left single quote
    "’": "'",                   # ' right single quote
    "“": "``",                  # " left double quote
    "”": "''",                  # " right double quote
    "…": r"\ldots{}",           # … ellipsis
    "→": r"$\rightarrow$",      # → arrow
    "←": r"$\leftarrow$",       # ← arrow
    "×": r"$\times$",           # × times
    "≤": r"$\leq$",             # ≤
    "≥": r"$\geq$",             # ≥
    "≠": r"$\neq$",             # ≠
}


def _strip_emojis(s: str) -> str:
    for em, rep in _EMOJI_MAP.items():
        s = s.replace(em, rep)
    # Remove any remaining non-Latin characters that LaTeX can't handle
    return re.sub(r"[^\x00-\xff]", "", s)


def _inline(s: str) -> str:
    """Convert inline markdown to LaTeX, preserving math regions."""
    # 1. Save all math segments as placeholders so bold/italic regexes can't cross them
    math_store: list[str] = []

    def _save(m: re.Match) -> str:
        math_store.append(m.group(0))
        return f"\x00M{len(math_store)-1}\x00"

    # Protect display math \[...\], $$...$$, \(...\) and inline $...$
    s = re.sub(r"\\\[.*?\\\]", _save, s, flags=re.DOTALL)
    s = re.sub(r"\$\$.*?\$\$", _save, s, flags=re.DOTALL)
    s = re.sub(r"\\\(.*?\\\)", _save, s, flags=re.DOTALL)
    s = re.sub(r"\$[^$\n]+?\$", _save, s)

    # 1b. Citations: no bibliography is compiled, so \cite{...} renders as "[?]".
    #     Convert to a plain bracketed key; drop dangling refs/labels.
    s = re.sub(r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\])?\{([^}]*)\}",
               lambda m: "[" + m.group(1).replace("_", " ") + "]", s)
    s = re.sub(r"\\(?:eqref|ref|autoref|cref|Cref)\{[^}]*\}", "", s)
    s = re.sub(r"\\label\{[^}]*\}", "", s)

    # 1c. Auto-wrap bare math tokens (q_1, q_m, c_{n}, x^2, H^{(i)}) so subscripts
    #     and superscripts render instead of being escaped to a literal "q_1".
    def _save_auto(mm):
        math_store.append("$" + mm.group(0) + "$")
        return f"\x00M{len(math_store)-1}\x00"
    _SUB = r"_(?:\{[^{}]*\}|[A-Za-z0-9]+)"
    _SUP = r"\^(?:\{[^{}]*\}|\([^)]*\)|[A-Za-z0-9]+)"
    s = re.sub(r"(?<![\\\w$\x00/])([A-Za-z]\w*(?:" + _SUB + r")+)", _save_auto, s)
    s = re.sub(r"(?<![\\\w$\x00/])([A-Za-z]\w*(?:" + _SUP + r")+)", _save_auto, s)

    # 2. Strip emojis
    s = _strip_emojis(s)

    # 3. Markdown links [text](url) → just the label
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)

    # 4. Bold **text** and __text__
    s = re.sub(r"\*\*([^*\n]+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"__([^_\n]+?)__", r"\\textbf{\1}", s)

    # 5. Italic *text* and _text_
    s = re.sub(r"\*([^*\n]+?)\*", r"\\textit{\1}", s)
    s = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"\\textit{\1}", s)

    # 6. Inline code `text`
    s = re.sub(r"`([^`]+)`", r"\\texttt{\1}", s)

    # 7. Escape stray LaTeX specials left in prose (math is protected above).
    #    Applied everywhere incl. inside generated \textbf/\textit/\texttt — all
    #    correct, since those commands contain none of these characters.
    s = _escape_specials(s)

    # 8. Restore math placeholders
    for idx, math in enumerate(math_store):
        s = s.replace(f"\x00M{idx}\x00", math)

    return s


def _escape_specials(s: str) -> str:
    """Escape LaTeX special characters that appear as literal text (not in math).
    Deliberately does NOT touch backslashes or braces, so generated commands
    like \\textbf{...} survive."""
    return (s.replace("&", r"\&")
             .replace("#", r"\#")
             .replace("%", r"\%")
             .replace("_", r"\_")
             .replace("~", r"\textasciitilde{}")
             .replace("^", r"\textasciicircum{}"))


def _md_to_tex(text: str) -> str:
    """Convert markdown structural markup to LaTeX. Preserves existing LaTeX math."""
    lines = text.splitlines()
    out: list[str] = []
    in_verbatim = False
    verbatim_buf: list[str] = []
    in_itemize = False
    in_enumerate = False

    def _flush_list():
        nonlocal in_itemize, in_enumerate
        if in_itemize:
            out.append(r"\end{itemize}")
            in_itemize = False
        if in_enumerate:
            out.append(r"\end{enumerate}")
            in_enumerate = False

    i = 0
    while i < len(lines):
        line = lines[i]
        raw = line.rstrip()

        # Code fence open/close
        if raw.startswith("```"):
            if not in_verbatim:
                _flush_list()
                in_verbatim = True
                verbatim_buf = []
            else:
                in_verbatim = False
                out.append(r"\begin{verbatim}")
                out.extend(verbatim_buf)
                out.append(r"\end{verbatim}")
            i += 1
            continue

        if in_verbatim:
            verbatim_buf.append(raw)
            i += 1
            continue

        # Markdown table
        if "|" in raw and raw.strip().startswith("|"):
            table_lines = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].rstrip())
                i += 1
            _flush_list()
            out.extend(_table_to_tex(table_lines))
            continue

        # Headings
        m = re.match(r"^(#{1,4})\s+(.*)", raw)
        if m:
            _flush_list()
            level = len(m.group(1))
            title = _inline(m.group(2))
            cmds = ["section*", "subsection*", "subsubsection*", "paragraph"]
            cmd = cmds[min(level - 1, 3)]
            out.append(f"\\{cmd}{{{title}}}")
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^---+\s*$", raw):
            _flush_list()
            out.append(r"\vspace{4pt}\noindent\rule{\linewidth}{0.4pt}\vspace{4pt}")
            i += 1
            continue

        # Blockquote — collect consecutive > lines
        if raw.startswith("> "):
            _flush_list()
            bq_lines = []
            while i < len(lines) and lines[i].rstrip().startswith("> "):
                bq_lines.append(_inline(lines[i].rstrip()[2:]))
                i += 1
            out.append(r"\begin{quote}")
            out.extend(bq_lines)
            out.append(r"\end{quote}")
            continue

        # Numbered list item
        m_num = re.match(r"^\d+\.\s+(.*)", raw)
        if m_num:
            if in_itemize:
                out.append(r"\end{itemize}")
                in_itemize = False
            if not in_enumerate:
                out.append(r"\begin{enumerate}")
                in_enumerate = True
            out.append(r"\item " + _inline(m_num.group(1)))
            i += 1
            continue

        # Bullet list item
        m_bull = re.match(r"^[-*]\s+(.*)", raw)
        if m_bull:
            if in_enumerate:
                out.append(r"\end{enumerate}")
                in_enumerate = False
            if not in_itemize:
                out.append(r"\begin{itemize}")
                in_itemize = True
            out.append(r"\item " + _inline(m_bull.group(1)))
            i += 1
            continue

        # Empty line
        if raw.strip() == "":
            _flush_list()
            out.append("")
            i += 1
            continue

        # Normal paragraph line
        _flush_list()
        out.append(_inline(raw))
        i += 1

    _flush_list()
    if in_verbatim:
        out.append(r"\begin{verbatim}")
        out.extend(verbatim_buf)
        out.append(r"\end{verbatim}")

    return "\n".join(out)


def _table_to_tex(lines: list[str]) -> list[str]:
    """Convert a markdown table to LaTeX tabular."""
    rows = []
    for line in lines:
        if re.match(r"^\s*\|[-| :]+\|\s*$", line):
            continue  # separator row
        cells = [_inline(c.strip()) for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return []
    ncols = max(len(r) for r in rows)
    spec = "l" * ncols
    result = [r"\begin{center}", f"\\begin{{tabular}}{{{spec}}}"]
    result.append(r"\hline")
    for k, row in enumerate(rows):
        while len(row) < ncols:
            row.append("")
        result.append(" & ".join(row) + r" \\")
        if k == 0:
            result.append(r"\hline")
    result.append(r"\hline")
    result.append(r"\end{tabular}")
    result.append(r"\end{center}")
    return result


def _tex_escape_title(s: str) -> str:
    """Escape LaTeX special chars in plain-text section titles."""
    for ch, rep in [("&", r"\&"), ("%", r"\%"), ("#", r"\#"), ("~", r"\textasciitilde{}"),
                    ("^", r"\textasciicircum{}"), ("<", r"$<$"), (">", r"$>$")]:
        s = s.replace(ch, rep)
    return s


# ── Bundle PDF generation ─────────────────────────────────────────────────────

def _bundle_cache_path(repo_root: Path) -> Path:
    d = repo_root / "documents" / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    return d / "bundle.pdf"


def prebuild_bundle_pdf(repo_root: Path) -> None:
    """Build the full document bundle offline and cache it to documents/pdf/bundle.pdf.

    Called as a background daemon thread at startup so the Documents tab
    never has to wait for compilation.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info("prebuild_bundle_pdf: building document bundle…")
    try:
        pdf_bytes = build_bundle_pdf(repo_root)
        dest = _bundle_cache_path(repo_root)
        dest.write_bytes(pdf_bytes)
        logger.info("prebuild_bundle_pdf: saved %d bytes to %s", len(pdf_bytes), dest)
    except Exception as exc:
        logger.warning("prebuild_bundle_pdf: failed — %s", exc)


def build_bundle_pdf(repo_root: Path, dataset: str | None = None, qid: str | None = None) -> bytes:
    """Build a combined PDF of all documents. Returns raw PDF bytes."""
    from .documents import documents_dir
    from .latex import latex_available

    docs_root = documents_dir(repo_root)
    preamble = repo_root / "problems" / "preamble.tex"
    tool = latex_available()

    # Collect (display_title, path) pairs
    files: list[tuple[str, Path]] = []

    def _add_q_docs(q_dir: Path, prefix: str) -> None:
        for stem in ["overview", "progress", "strategies", "timeline"]:
            for ext in [".tex", ".md"]:
                p = q_dir / (stem + ext)
                if p.is_file():
                    files.append((f"{prefix} — {stem.title()}", p))
                    break

    if qid:
        # Only include this question's own documents — no cross-problem daily reports
        _add_q_docs(docs_root / "questions" / qid, qid.upper())
        # Meeting notes for this question only (skip if content is trivially empty)
        meets_dir = docs_root / "questions" / qid / "meets"
        if meets_dir.is_dir():
            for p in sorted(meets_dir.glob("*.md")):
                txt = p.read_text(encoding="utf-8", errors="replace")
                # Only include notes that have substantive content beyond the opening line
                transcript_lines = [ln for ln in txt.splitlines()
                                    if ln.strip() and not ln.startswith("#") and
                                    "Meeting opened" not in ln and "Goal:" not in ln and
                                    "Date:" not in ln and "Participants:" not in ln]
                if len(transcript_lines) >= 3:
                    files.append((f"{qid.upper()} — Meeting: {p.stem}", p))
    else:
        for p in sorted(docs_root.glob("*.tex"), reverse=True):
            files.append((p.stem, p))
        for p in sorted(docs_root.glob("*.md"), reverse=True):
            if not (docs_root / (p.stem + ".tex")).exists():
                files.append((p.stem, p))
        q_base = docs_root / "questions"
        if q_base.is_dir():
            for q_dir in sorted(q_base.iterdir()):
                if q_dir.is_dir():
                    _add_q_docs(q_dir, q_dir.name.upper())

    if not files:
        return _fpdf2_fallback([])

    # Try tectonic compilation first
    if tool:
        pdf = _compile_with_tectonic(tool, preamble, files, qid, dataset)
        if pdf:
            return pdf

    # Fallback: fpdf2
    return _fpdf2_fallback(files)


def _compile_with_tectonic(
    tool: str,
    preamble: Path,
    files: list[tuple[str, Path]],
    qid: str | None,
    dataset: str | None,
) -> bytes | None:
    """Compile the bundle using tectonic. Returns PDF bytes or None on failure."""
    scope = _tex_escape_title(qid or dataset or "all")
    sections: list[str] = []

    for title, path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if path.suffix == ".md":
            content = _md_to_tex(content)
        title_tex = _tex_escape_title(title)
        sections.append(
            f"\\clearpage\n\\section*{{{title_tex}}}\n\n{content}\n"
        )

    preamble_block = "\\input{preamble}" if preamble.is_file() else (
        "\\usepackage{amsmath,amssymb,amsthm}"
    )

    master = (
        "\\documentclass[11pt,a4paper]{article}\n"
        f"{preamble_block}\n"
        "\\usepackage[margin=2.5cm]{geometry}\n"
        "\\usepackage{parskip}\n"
        "\\usepackage[hidelinks]{hyperref}\n"
        f"\\title{{Research Context Bundle\\\\\\large Scope: {scope}}}\n"
        "\\date{}\n"
        "\\begin{document}\n"
        "\\maketitle\n"
        "\\tableofcontents\n"
        + "".join(sections)
        + "\\end{document}\n"
    )

    with tempfile.TemporaryDirectory(prefix="rma_bundle_") as tmp:
        build = Path(tmp)
        if preamble.is_file():
            shutil.copyfile(preamble, build / "preamble.tex")
        (build / "main.tex").write_text(master, encoding="utf-8")
        try:
            proc = subprocess.run(
                [tool, "main.tex"],
                cwd=build,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        out = build / "main.pdf"
        if proc.returncode == 0 and out.is_file():
            return out.read_bytes()
    return None


def _fpdf2_fallback(files: list[tuple[str, Path]]) -> bytes:
    """Generate a simple PDF via fpdf2 when tectonic is unavailable."""
    try:
        from fpdf import FPDF
    except ImportError:
        return b"%PDF-1.3\n% fpdf2 not available\n"

    pdf = FPDF()
    pdf.set_margins(15, 15, 15)
    pdf.add_font("DejaVu", "",  _FONT_REGULAR)
    pdf.add_font("DejaVu", "B", _FONT_BOLD)

    pdf.add_page()
    pdf.set_font("DejaVu", "B", 16)
    pdf.set_text_color(80, 80, 220)
    pdf.cell(0, 14, "Research Context Bundle", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu", "", 9)
    for i, (title, _) in enumerate(files, 1):
        pdf.cell(0, 5, f"  {i}. {_safe(title)}", new_x="LMARGIN", new_y="NEXT")

    for title, path in files:
        pdf.add_page()
        pdf.set_font("DejaVu", "B", 13)
        pdf.set_fill_color(30, 30, 46)
        pdf.set_text_color(200, 200, 255)
        pdf.cell(0, 10, _safe(title), new_x="LMARGIN", new_y="NEXT", fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in content.splitlines():
            raw = line.rstrip()
            safe = _safe(_strip_tex(raw))
            if raw.startswith(r"\section") or raw.startswith("# "):
                pdf.set_font("DejaVu", "B", 12)
            elif raw.startswith(r"\subsection") or raw.startswith("## "):
                pdf.set_font("DejaVu", "B", 10)
            elif raw.strip() == "" or raw.startswith(r"\clearpage"):
                pdf.ln(3)
                continue
            else:
                pdf.set_font("DejaVu", "", 8)
            try:
                pdf.multi_cell(0, 5, safe, new_x="LMARGIN", new_y="NEXT")
            except Exception:
                pass

    return bytes(pdf.output())


def _strip_tex(s: str) -> str:
    """Remove LaTeX commands for plain-text fallback display."""
    s = re.sub(r"\\[a-zA-Z]+\*?\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+\*?", "", s)
    s = re.sub(r"[{}]", "", s)
    return s


def _safe(text: str) -> str:
    return (text
            .replace("’", "'").replace("‘", "'")
            .replace("“", '"').replace("”", '"')
            .replace("–", "-").replace("—", "--")
            .replace("…", "..."))
