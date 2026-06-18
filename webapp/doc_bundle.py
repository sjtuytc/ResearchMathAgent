"""Generate a combined PDF context bundle from all documents."""
from __future__ import annotations

import re
import sys
from pathlib import Path

_FONT_REGULAR = "/usr/share/fonts/truetype/DejaVuSans.ttf"
_FONT_BOLD    = "/usr/share/fonts/truetype/DejaVuSans-Bold.ttf"
_FONT_MONO    = "/usr/share/fonts/truetype/DejaVuSansMono.ttf"

# Add user-local site-packages so fpdf2 is importable when the server starts
_user_site = Path.home() / ".local/lib/python3.12/site-packages"
if str(_user_site) not in sys.path:
    sys.path.insert(0, str(_user_site))


def _strip_markdown(text: str) -> str:
    """Very light strip: remove link syntax, bold/italic markers, code fences."""
    # Code fences → keep content, drop backtick lines
    text = re.sub(r"^```[^\n]*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```\s*$", "", text, flags=re.MULTILINE)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Links [label](url)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Bold/italic
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    return text


def _safe(text: str) -> str:
    """Replace characters that DejaVuSans cannot encode."""
    # These are commonly problematic fancy quotes / dashes
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "--")
    text = text.replace("…", "...")
    return text


def _render_doc(pdf, title: str, content: str) -> None:
    """Render one document (title + markdown content) into the FPDF object."""
    lines = content.splitlines()

    # Document title page (separator)
    pdf.add_page()
    pdf.set_font("DejaVu", "B", 16)
    pdf.set_fill_color(30, 30, 46)
    pdf.set_text_color(200, 200, 255)
    pdf.cell(0, 12, _safe(title), new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    for line in lines:
        raw = line.rstrip()
        stripped = _strip_markdown(raw)
        safe = _safe(stripped)

        # Headings
        if raw.startswith("# "):
            pdf.set_font("DejaVu", "B", 14)
            pdf.set_fill_color(245, 245, 250)
            pdf.multi_cell(0, 8, safe[2:], fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif raw.startswith("## "):
            pdf.set_font("DejaVu", "B", 12)
            pdf.multi_cell(0, 7, safe[3:], new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif raw.startswith("### "):
            pdf.set_font("DejaVu", "B", 10)
            pdf.multi_cell(0, 6, safe[4:], new_x="LMARGIN", new_y="NEXT")
        elif raw.startswith("---"):
            pdf.set_draw_color(180, 180, 180)
            pdf.set_line_width(0.3)
            pdf.line(pdf.get_x(), pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
            pdf.ln(5)
        elif raw.startswith("- ") or raw.startswith("* "):
            pdf.set_font("DejaVu", "", 9)
            pdf.multi_cell(0, 5, "  • " + safe[2:], new_x="LMARGIN", new_y="NEXT")
        elif raw.strip() == "":
            pdf.ln(3)
        else:
            pdf.set_font("DejaVu", "", 9)
            pdf.multi_cell(0, 5, safe, new_x="LMARGIN", new_y="NEXT")


def build_bundle_pdf(repo_root: Path, dataset: str | None = None, qid: str | None = None) -> bytes:
    """Build a combined PDF from documents. Returns raw PDF bytes."""
    from fpdf import FPDF
    from .documents import documents_dir

    docs_root = documents_dir(repo_root)

    # Collect (display_title, path) pairs in logical order
    files: list[tuple[str, Path]] = []

    if qid:
        # Question-focused bundle: problem statement + per-question docs
        ds = dataset or "first_proof_1"
        q_dir = docs_root / "questions" / qid
        for fname in ["overview.md", "progress.md", "strategies.md", "timeline.md"]:
            p = q_dir / fname
            if p.is_file():
                files.append((f"{qid.upper()} — {fname.replace('.md','').title()}", p))
        # Also add daily reports (most recent 5)
        daily = sorted(docs_root.glob("*.md"), reverse=True)[:5]
        for p in daily:
            files.append((f"Daily Report — {p.stem}", p))
    else:
        # Full bundle: all non-folder markdown files first, then per-question docs
        root_mds = sorted(docs_root.glob("*.md"), reverse=True)
        for p in root_mds:
            files.append((p.stem, p))
        # Per-question docs
        q_base = docs_root / "questions"
        if q_base.is_dir():
            for q_dir in sorted(q_base.iterdir()):
                if not q_dir.is_dir():
                    continue
                for fname in ["overview.md", "progress.md", "strategies.md", "timeline.md"]:
                    p = q_dir / fname
                    if p.is_file():
                        files.append((f"{q_dir.name.upper()} — {fname.replace('.md','').title()}", p))

    if not files:
        # Return a one-page "no documents" PDF
        from fpdf import FPDF as _F
        pdf2 = _F()
        pdf2.add_font("DejaVu", "", _FONT_REGULAR)
        pdf2.add_page()
        pdf2.set_font("DejaVu", size=12)
        pdf2.cell(0, 10, "No documents found.", new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf2.output())

    pdf = FPDF()
    pdf.set_margins(15, 15, 15)
    pdf.add_font("DejaVu", "",  _FONT_REGULAR)
    pdf.add_font("DejaVu", "B", _FONT_BOLD)

    # Cover page with table of contents
    pdf.add_page()
    pdf.set_font("DejaVu", "B", 18)
    pdf.set_text_color(80, 80, 220)
    pdf.cell(0, 14, "Research Context Bundle", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu", "", 10)
    pdf.cell(0, 6, f"Scope: {qid or dataset or 'all'}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(0, 7, "Contents", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 9)
    for i, (title, _) in enumerate(files, 1):
        pdf.cell(0, 5, f"  {i}. {_safe(title)}", new_x="LMARGIN", new_y="NEXT")

    # Render each document
    for title, path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = "(unreadable)"
        _render_doc(pdf, title, content)

    return bytes(pdf.output())
