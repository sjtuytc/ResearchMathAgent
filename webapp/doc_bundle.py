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

    def _inline(s: str) -> str:
        """Apply inline conversions: bold, italic, code — but not inside math."""
        # Split on $...$ to protect math
        parts = re.split(r"(\$[^$]*\$|\\\[[^\]]*\\\])", s)
        result = []
        for p in parts:
            if p.startswith("$") or p.startswith(r"\["):
                result.append(p)
            else:
                # Bold **text**
                p = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", p)
                # Italic *text*
                p = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", p)
                # Bold __text__
                p = re.sub(r"__([^_]+)__", r"\\textbf{\1}", p)
                # Italic _text_ (only when surrounded by spaces or start/end)
                p = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\\textit{\1}", p)
                # Inline code `text`
                p = re.sub(r"`([^`]+)`", r"\\texttt{\1}", p)
                result.append(p)
        return "".join(result)

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

        # Markdown table: detect | separator lines and rows
        if "|" in raw and raw.strip().startswith("|"):
            # Collect all table lines
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

        # Blockquote
        if raw.startswith("> "):
            _flush_list()
            content = _inline(raw[2:])
            out.append(r"\begin{quote}")
            out.append(content)
            out.append(r"\end{quote}")
            i += 1
            continue

        # Numbered list item
        m_num = re.match(r"^(\d+)\.\s+(.*)", raw)
        if m_num:
            if in_itemize:
                out.append(r"\end{itemize}")
                in_itemize = False
            if not in_enumerate:
                out.append(r"\begin{enumerate}")
                in_enumerate = True
            out.append(r"\item " + _inline(m_num.group(2)))
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
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return []
    ncols = max(len(r) for r in rows)
    spec = "l" * ncols
    result = [r"\begin{center}", f"\\begin{{tabular}}{{{spec}}}"]
    result.append(r"\hline")
    for k, row in enumerate(rows):
        # pad
        while len(row) < ncols:
            row.append("")
        cells_tex = " & ".join(row)
        result.append(cells_tex + r" \\")
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
        _add_q_docs(docs_root / "questions" / qid, qid.upper())
        # Recent daily reports
        for p in sorted(docs_root.glob("*.tex"), reverse=True)[:5]:
            files.append((p.stem, p))
        for p in sorted(docs_root.glob("*.md"), reverse=True)[:5]:
            if not (docs_root / (p.stem + ".tex")).exists():
                files.append((p.stem, p))
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
