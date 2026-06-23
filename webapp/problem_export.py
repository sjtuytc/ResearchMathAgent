"""Dataset-wide problem export for the solvability filter system.

Three pieces work together:

1. ``build_all_problems_pdf``   — a single compact PDF listing every problem
   across all datasets, each tagged with a stable export key ``dataset/id``.
   Hand this to Claude together with the instructions PDF.

2. ``build_eval_instructions_pdf`` — tells the model how to score each problem's
   AI-solvability (0-100) and exactly what JSON to return, keyed by ``dataset/id``.

3. ``ingest_evaluations`` — takes the JSON the model returns and writes the
   normalised (0-1) scores into each dataset's ``solvability_cache.json`` plus a
   full per-problem eval record, so the existing sidebar filter immediately works.

Statements are rendered as plain (escaped) text — LaTeX math is kept as source,
which Claude reads natively and which never breaks on malformed scraped LaTeX.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

# user-local reportlab (same path the supplementary build script uses)
_user_site = "/u/zzhao18/.local/lib/python3.12/site-packages"
if _user_site not in sys.path:
    sys.path.insert(0, _user_site)

from . import dataset_store as ds

REPO_ROOT = Path(__file__).resolve().parents[1]
_EXPORT_DIR = REPO_ROOT / "documents" / "exports"

_FONT_REGULAR = "/usr/share/fonts/truetype/DejaVuSans.ttf"
_FONT_BOLD = "/usr/share/fonts/truetype/DejaVuSans-Bold.ttf"
_FONT_MONO = "/usr/share/fonts/truetype/DejaVuSansMono.ttf"

_STATEMENT_CAP = 1400  # chars per statement in the export


# ── Fonts ──────────────────────────────────────────────────────────────────────

def _register_fonts() -> tuple[str, str, str]:
    """Register DejaVu (unicode-safe) fonts; fall back to built-ins."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", _FONT_REGULAR))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", _FONT_BOLD))
        pdfmetrics.registerFont(TTFont("DejaVu-Mono", _FONT_MONO))
        return "DejaVu", "DejaVu-Bold", "DejaVu-Mono"
    except Exception:
        return "Helvetica", "Helvetica-Bold", "Courier"


def _safe(text: str) -> str:
    """Escape for reportlab Paragraph markup (keeps LaTeX source readable)."""
    if not text:
        return ""
    return _xml_escape(str(text)).replace("\n", " ").strip()


# ── Cached / background build (large exports exceed the tunnel response timeout) ─

_BUILD_LOCK = threading.Lock()
_BUILDING: set[str] = set()


def _cache_sig(datasets, max_per_dataset, offset) -> str:
    key = json.dumps([sorted(datasets) if datasets else "all", max_per_dataset, offset])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _cache_path(sig: str) -> Path:
    return _EXPORT_DIR / f"problems_{sig}.pdf"


def get_or_build_catalogue(datasets, max_per_dataset, offset):
    """Return ("ready", path) when the PDF is cached, else ("building", None).

    The first call starts a background build to a cached file so the HTTP
    request returns immediately (the full 22k export takes ~20s — longer than
    the tunnel's response timeout).
    """
    sig = _cache_sig(datasets, max_per_dataset, offset)
    path = _cache_path(sig)
    if path.is_file() and path.stat().st_size > 0:
        return "ready", path

    with _BUILD_LOCK:
        if sig in _BUILDING:
            return "building", None
        _BUILDING.add(sig)

    def _worker():
        try:
            pdf = build_all_problems_pdf(datasets=datasets, max_per_dataset=max_per_dataset, offset=offset)
            _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".pdf.tmp")
            tmp.write_bytes(pdf)
            tmp.replace(path)
        except Exception:
            pass
        finally:
            with _BUILD_LOCK:
                _BUILDING.discard(sig)

    threading.Thread(target=_worker, daemon=True).start()
    return "building", None


# ── Problem catalogue PDF ───────────────────────────────────────────────────────

def build_all_problems_pdf(
    datasets: list[str] | None = None,
    max_per_dataset: int = 0,
    offset: int = 0,
) -> bytes:
    """Build a compact PDF of all problems across datasets.

    ``max_per_dataset=0`` means no cap (every problem). ``offset`` skips the
    first N problems within each dataset (for batched exports of huge datasets).
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor, black
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    )

    reg, bold, mono = _register_fonts()
    BLUE = HexColor("#1a237e")
    GRAY = HexColor("#546e7a")

    H_TITLE = ParagraphStyle("t", fontName=bold, fontSize=15, leading=19,
                             textColor=BLUE, spaceAfter=4, alignment=TA_LEFT)
    H_SUB = ParagraphStyle("s", fontName=reg, fontSize=9, leading=12,
                           textColor=GRAY, spaceAfter=6)
    H_DS = ParagraphStyle("ds", fontName=bold, fontSize=12, leading=15,
                          textColor=BLUE, spaceBefore=12, spaceAfter=4)
    KEY = ParagraphStyle("k", fontName=mono, fontSize=8, leading=10,
                         textColor=HexColor("#b34700"), spaceBefore=6, spaceAfter=0)
    TITLE = ParagraphStyle("pt", fontName=bold, fontSize=9.5, leading=12,
                           textColor=black, spaceAfter=1)
    BODY = ParagraphStyle("b", fontName=reg, fontSize=8.5, leading=11,
                          textColor=HexColor("#222222"), spaceAfter=2)
    META = ParagraphStyle("m", fontName=reg, fontSize=7.5, leading=9,
                          textColor=GRAY, spaceAfter=2)

    all_meta = {d["slug"]: d for d in ds.list_datasets()}
    slugs = datasets or [d["slug"] for d in ds.list_datasets()]

    story: list = []
    story.append(Paragraph("ResearchMathAgent — Problem Catalogue for Solvability Evaluation", H_TITLE))
    total = 0
    counts: dict[str, int] = {}
    for slug in slugs:
        plist = ds.list_problems(dataset=slug)
        if offset:
            plist = plist[offset:]
        if max_per_dataset and max_per_dataset > 0:
            plist = plist[:max_per_dataset]
        counts[slug] = len(plist)
        total += len(plist)
    story.append(Paragraph(
        f"{total} problems across {len(slugs)} datasets. Each problem is tagged with a"
        " <b>key</b> (dataset/id) shown in orange -- use that exact key when"
        " returning your evaluation. See the companion <i>Evaluation Instructions</i> PDF.", H_SUB))
    story.append(HRFlowable(width="100%", thickness=0.6, color=GRAY, spaceAfter=4))

    for slug in slugs:
        meta = all_meta.get(slug, {"name": slug})
        plist = ds.list_problems(dataset=slug)
        if offset:
            plist = plist[offset:]
        if max_per_dataset and max_per_dataset > 0:
            plist = plist[:max_per_dataset]
        if not plist:
            continue
        story.append(Paragraph(
            f"{_safe(meta.get('name', slug))} "
            f"<font size=8 color='#546e7a'>({slug}) — {counts[slug]} problems</font>",
            H_DS))
        for p in plist:
            pid = p.get("id", "")
            key = f"{slug}/{pid}"
            story.append(Paragraph(_safe(key), KEY))
            title = p.get("title") or pid
            story.append(Paragraph(_safe(title), TITLE))
            stmt = (p.get("statement") or "").strip()
            if stmt:
                if len(stmt) > _STATEMENT_CAP:
                    stmt = stmt[:_STATEMENT_CAP].rstrip() + " …[truncated]"
                story.append(Paragraph(_safe(stmt), BODY))
            bits = []
            if p.get("tags"):
                bits.append("tags: " + ", ".join(str(t) for t in p["tags"][:8]))
            if p.get("difficulty") is not None:
                bits.append(f"difficulty: {p['difficulty']}")
            if p.get("year"):
                bits.append(f"year: {p['year']}")
            if bits:
                story.append(Paragraph(_safe(" · ".join(bits)), META))

    import io
    bio = io.BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=letter,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        title="RMA Problem Catalogue", author="ResearchMathAgent",
    )
    doc.build(story)
    return bio.getvalue()


# ── Evaluation instructions PDF ─────────────────────────────────────────────────

def build_eval_instructions_pdf() -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor, black
    from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Preformatted,
    )

    reg, bold, mono = _register_fonts()
    BLUE = HexColor("#1a237e")
    GREEN = HexColor("#1b5e20")
    GRAY = HexColor("#546e7a")
    CODEBG = HexColor("#f5f5f5")

    TITLE = ParagraphStyle("t", fontName=bold, fontSize=15, leading=19,
                           textColor=BLUE, spaceAfter=6, alignment=TA_LEFT)
    SEC = ParagraphStyle("sec", fontName=bold, fontSize=12, leading=15,
                         textColor=BLUE, spaceBefore=14, spaceAfter=4)
    SEC2 = ParagraphStyle("sec2", fontName=bold, fontSize=12, leading=15,
                          textColor=GREEN, spaceBefore=14, spaceAfter=4)
    BODY = ParagraphStyle("b", fontName=reg, fontSize=10, leading=14,
                          textColor=black, spaceAfter=5, alignment=TA_JUSTIFY)
    BULLET = ParagraphStyle("bl", fontName=reg, fontSize=10, leading=13,
                            textColor=black, leftIndent=16, spaceAfter=2)
    CODE = ParagraphStyle("c", fontName=mono, fontSize=8.5, leading=11,
                          textColor=black, backColor=CODEBG, borderPad=5,
                          leftIndent=6, spaceBefore=4, spaceAfter=6)

    story: list = []
    story.append(Paragraph("Problem Evaluation Instructions — Solvability &amp; Mathematical Value", TITLE))
    story.append(Paragraph(
        "You are a world-class mathematician and AI-capabilities researcher. "
        "Read the companion <b>Problem Catalogue</b> PDF and assign <b>two independent "
        "scores</b> to every problem: <b>solvability</b> (can an AI solve it?) and "
        "<b>mathematical value</b> (how important is the result?). Both are integers 0–100. "
        "Together they determine which problems RMA should prioritise — the sweet spot is "
        "high value <i>and</i> high solvability.", BODY))
    story.append(HRFlowable(width="100%", thickness=0.6, color=GRAY, spaceAfter=4))

    # ── Solvability ──────────────────────────────────────────────────────────────
    story.append(Paragraph("Dimension 1 — Solvability (0–100)", SEC))
    story.append(Paragraph(
        "How likely is a state-of-the-art AI research agent (Claude Opus with code "
        "execution, literature search, and formal reasoning) to produce a mathematically "
        "<b>correct and complete</b> proof within a few hours of compute?", BODY))
    for band in [
        "<b>0–10</b>: Requires a fundamental mathematical breakthrough; impossible for AI today.",
        "<b>10–25</b>: Extremely hard; deep novelty required; very unlikely.",
        "<b>25–40</b>: Very hard; multiple non-trivial insights; AI might get partial progress only.",
        "<b>40–55</b>: Hard but structured; AI could solve with significant effort and the right tools.",
        "<b>55–70</b>: Moderately difficult; AI has a real chance if it finds the right approach.",
        "<b>70–85</b>: Within reach; techniques are known; AI needs to execute carefully.",
        "<b>85–100</b>: Straightforward for a well-equipped AI; mostly technical execution.",
    ]:
        story.append(Paragraph("• " + band, BULLET))
    story.append(Paragraph("Key solvability questions:", BODY))
    for c in [
        "Is the required mathematics within the training distribution of modern LLMs?",
        "Are the key techniques (tools, lemmas, arguments) well-documented in the literature?",
        "How much genuine novelty or creativity is required beyond known methods?",
        "Is the problem verifiable step-by-step, or does it hinge on a single flash of insight?",
        "How long and complex is a complete proof likely to be?",
    ]:
        story.append(Paragraph("• " + c, BULLET))

    # ── Mathematical Value ───────────────────────────────────────────────────────
    story.append(Paragraph("Dimension 2 — Mathematical Value (0–100)", SEC2))
    story.append(Paragraph(
        "How significant would a correct solution be to mathematics? Consider the "
        "problem's centrality to its field, the breadth of impact across related areas, "
        "whether it is a recognised open problem, and how much a solution would advance "
        "human understanding — not just the technical difficulty.", BODY))
    for band in [
        "<b>0–10</b>: Minimal significance; technical exercise with limited broader relevance.",
        "<b>10–25</b>: Niche interest; meaningful only to narrow specialists.",
        "<b>25–40</b>: Moderate value; interesting result, limited impact outside the sub-field.",
        "<b>40–55</b>: Notable contribution; recognised open problem; useful to its community.",
        "<b>55–70</b>: Important result; would be published in a top journal; broader impact.",
        "<b>70–85</b>: Major open problem; landmark result; opens new research directions.",
        "<b>85–100</b>: Fundamental breakthrough; Millennium/Fields-medal-adjacent significance.",
    ]:
        story.append(Paragraph("• " + band, BULLET))
    story.append(Paragraph("Key value questions:", BODY))
    for c in [
        "Is this a well-known open problem cited in surveys or problem lists?",
        "Would a solution directly unblock other open problems?",
        "How widely cited is the problem area? Would a solution appear in Annals, JAMS, etc.?",
        "Does the problem connect multiple fields (e.g., number theory + probability)?",
        "Has a prize or prestige been attached to this problem?",
    ]:
        story.append(Paragraph("• " + c, BULLET))

    # ── Output format ────────────────────────────────────────────────────────────
    story.append(Paragraph("Required output format", SEC))
    story.append(Paragraph(
        "Return <b>one JSON array</b> and nothing else — no markdown, no prose. "
        'One object per problem; use the exact <b>key</b> (orange, "dataset/id") from the catalogue. '
        "Include both <b>score</b> (solvability) and <b>value</b> (mathematical value):", BODY))
    story.append(Preformatted(
        '[\n'
        '  {\n'
        '    "key": "first_proof_1/q3",\n'
        '    "score": 35,\n'
        '    "value": 72,\n'
        '    "confidence": "medium",\n'
        '    "reasoning": "Needs novel Markov chain. High value: well-known Williams conjecture.",\n'
        '    "estimated_proof_length": "long"\n'
        '  },\n'
        '  {\n'
        '    "key": "erdos_problems/erdos_42",\n'
        '    "score": 8,\n'
        '    "value": 80,\n'
        '    "confidence": "high",\n'
        '    "reasoning": "Long-open Erdos conjecture; deep; $500 prize.",\n'
        '    "estimated_proof_length": "very_long"\n'
        '  }\n'
        ']', CODE))
    story.append(Paragraph(
        "<b>score</b>: integer 0–100 (solvability).  "
        "<b>value</b>: integer 0–100 (mathematical importance).  "
        '<b>confidence</b>: "high", "medium", or "low".  '
        '<b>estimated_proof_length</b>: "short", "medium", "long", or "very_long".  '
        "Cover every problem in the catalogue. If exported in batches, evaluate your batch "
        "and keep keys exact so results merge cleanly.", BODY))
    story.append(Paragraph(
        "Paste the returned JSON into the RMA <b>Export</b> tab (Ingest model evaluations). "
        "The <b>Design</b> tab will then display a priority report ranked by the geometric "
        "mean of solvability x value -- the problems to work on first.", BODY))

    import io
    bio = io.BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=letter,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        title="RMA Problem Evaluation Instructions", author="ResearchMathAgent",
    )
    doc.build(story)
    return bio.getvalue()


# ── Priority report PDF ─────────────────────────────────────────────────────────

def _priority(solv: float, val: float) -> float:
    """Geometric mean of solvability and value, both 0-1."""
    import math
    return math.sqrt(max(0.0, solv) * max(0.0, val))


def build_priority_report_pdf() -> bytes:
    """Build a priority report PDF showing problems ranked by solvability × value.

    If value scores are not yet ingested, falls back to showing solvability-only ranking
    with a note prompting the user to run the dual evaluation.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle,
    )
    import math, datetime

    reg, bold, mono = _register_fonts()
    BLUE = HexColor("#1a237e")
    GREEN = HexColor("#1b5e20")
    ORANGE = HexColor("#e65100")
    GRAY = HexColor("#546e7a")
    LGRAY = HexColor("#eceff1")
    RED = HexColor("#b71c1c")

    TITLE = ParagraphStyle("t", fontName=bold, fontSize=16, leading=20,
                           textColor=BLUE, spaceAfter=4)
    SUB = ParagraphStyle("sub", fontName=reg, fontSize=10, leading=13,
                         textColor=GRAY, spaceAfter=8)
    SEC = ParagraphStyle("sec", fontName=bold, fontSize=11, leading=14,
                         textColor=BLUE, spaceBefore=14, spaceAfter=4)
    BODY = ParagraphStyle("b", fontName=reg, fontSize=9.5, leading=13,
                          textColor=black, spaceAfter=4, alignment=TA_JUSTIFY)
    NOTE = ParagraphStyle("n", fontName=reg, fontSize=9, leading=12,
                          textColor=ORANGE, spaceAfter=6)
    CELL = ParagraphStyle("c", fontName=reg, fontSize=8, leading=10, textColor=black)
    CELLB = ParagraphStyle("cb", fontName=bold, fontSize=8, leading=10, textColor=black)

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story: list = []
    story.append(Paragraph("RMA — Problem Priority Report", TITLE))
    story.append(Paragraph(
        f"Solvability × Mathematical Value analysis  ·  Generated {now}", SUB))
    story.append(HRFlowable(width="100%", thickness=0.8, color=BLUE, spaceAfter=6))

    # Load all eval data
    all_rows: list[dict] = []
    has_value = False
    for dataset_meta in ds.list_datasets():
        slug = dataset_meta["slug"]
        eval_data = ds._load_eval_store(slug)
        if not eval_data:
            continue
        for pid, ev in eval_data.items():
            solv_norm = ev.get("score_norm", ev.get("score", 0) / 100.0)
            val_score = ev.get("value")
            val_norm = (val_score / 100.0) if val_score is not None else None
            if val_norm is not None:
                has_value = True
            priority = _priority(solv_norm, val_norm if val_norm is not None else solv_norm)
            all_rows.append({
                "dataset": slug,
                "pid": pid,
                "key": f"{slug}/{pid}",
                "solv": round(solv_norm * 100),
                "val": round(val_norm * 100) if val_norm is not None else None,
                "priority": round(priority * 100),
                "confidence": ev.get("confidence", ""),
                "reasoning": (ev.get("reasoning") or "")[:120],
                "proof_len": ev.get("estimated_proof_length", ""),
                "tier": ev.get("tier", ""),
            })

    total_problems = len(all_rows)
    datasets_with_data = len({r["dataset"] for r in all_rows})

    if not all_rows:
        story.append(Paragraph(
            "No evaluation data found. Download the Problem Catalogue PDF and Evaluation "
            "Instructions from the Export tab, send both to Claude, then paste the returned "
            "JSON into the Ingest box. The Design tab will render this report automatically.", NOTE))
        import io; bio = io.BytesIO()
        doc = SimpleDocTemplate(bio, pagesize=letter,
                                leftMargin=0.7*inch, rightMargin=0.7*inch,
                                topMargin=0.7*inch, bottomMargin=0.7*inch)
        doc.build(story)
        return bio.getvalue()

    if not has_value:
        story.append(Paragraph(
            f"NOTE: Only solvability scores found ({total_problems} problems, "
            f"{datasets_with_data} datasets). Priority currently equals solvability. "
            "Re-run evaluation with the updated instructions to add mathematical value "
            "scores — the priority ranking will then use the geometric mean of both.", NOTE))
    else:
        val_count = sum(1 for r in all_rows if r["val"] is not None)
        story.append(Paragraph(
            f"{total_problems} problems evaluated across {datasets_with_data} datasets. "
            f"{val_count} have both solvability and value scores. "
            f"Priority = geometric mean of solvability × value (0–100).", BODY))

    # ── Global top-30 ────────────────────────────────────────────────────────────
    story.append(Paragraph("Top 30 Priority Targets (all datasets)", SEC))
    top30 = sorted(all_rows, key=lambda r: -r["priority"])[:30]
    tdata = [[
        Paragraph("Rank", CELLB), Paragraph("Key", CELLB),
        Paragraph("Solv", CELLB), Paragraph("Val", CELLB),
        Paragraph("Priority", CELLB), Paragraph("Reasoning", CELLB),
    ]]
    for i, r in enumerate(top30, 1):
        val_str = str(r["val"]) if r["val"] is not None else "—"
        tdata.append([
            Paragraph(str(i), CELL),
            Paragraph(_safe(r["key"]), CELL),
            Paragraph(str(r["solv"]), CELL),
            Paragraph(val_str, CELL),
            Paragraph(str(r["priority"]), CELL),
            Paragraph(_safe(r["reasoning"]), CELL),
        ])
    col_w = [0.35*inch, 1.7*inch, 0.42*inch, 0.38*inch, 0.55*inch, 3.1*inch]
    t = Table(tdata, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LGRAY]),
        ("GRID", (0, 0), (-1, -1), 0.3, GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    # ── Per-dataset breakdown (top 50 per dataset to keep PDF compact) ──────────
    _DS_SHOW = 50
    datasets_order = sorted({r["dataset"] for r in all_rows})
    for slug in datasets_order:
        rows_all = sorted([r for r in all_rows if r["dataset"] == slug],
                          key=lambda r: -r["priority"])
        if not rows_all:
            continue
        rows = rows_all[:_DS_SHOW]
        story.append(Paragraph(f"Dataset: {slug} ({len(rows_all)} problems)", SEC))

        # Summary stats
        avg_solv = sum(r["solv"] for r in rows_all) / len(rows_all)
        val_rows = [r for r in rows_all if r["val"] is not None]
        avg_val_str = f"{sum(r['val'] for r in val_rows)/len(val_rows):.0f}" if val_rows else "n/a"
        avg_pri = sum(r["priority"] for r in rows_all) / len(rows_all)
        shown_note = f"  |  Showing top {len(rows)} of {len(rows_all)}" if len(rows_all) > _DS_SHOW else ""
        story.append(Paragraph(
            f"Avg solvability: {avg_solv:.0f}  |  Avg value: {avg_val_str}  |  "
            f"Avg priority: {avg_pri:.0f}{shown_note}",
            BODY))

        tdata2 = [[
            Paragraph("ID", CELLB), Paragraph("Solv", CELLB),
            Paragraph("Val", CELLB), Paragraph("Pri", CELLB),
            Paragraph("Len", CELLB), Paragraph("Reasoning", CELLB),
        ]]
        for r in rows:
            val_str = str(r["val"]) if r["val"] is not None else "—"
            tdata2.append([
                Paragraph(_safe(r["pid"]), CELL),
                Paragraph(str(r["solv"]), CELL),
                Paragraph(val_str, CELL),
                Paragraph(str(r["priority"]), CELL),
                Paragraph(_safe(r["proof_len"][:6]), CELL),
                Paragraph(_safe(r["reasoning"]), CELL),
            ])
        col_w2 = [0.85*inch, 0.42*inch, 0.38*inch, 0.38*inch, 0.48*inch, 3.99*inch]
        t2 = Table(tdata2, colWidths=col_w2, repeatRows=1)
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#37474f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LGRAY]),
            ("GRID", (0, 0), (-1, -1), 0.3, GRAY),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t2)

    # ── Legend ───────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.4, color=GRAY))
    story.append(Paragraph(
        "Priority = √(solvability × value), both 0–100. When value scores are missing, "
        "priority equals solvability. Regenerate this report after ingesting new evaluations "
        "via the Export tab. Solv = AI solvability; Val = mathematical value/importance; "
        "Pri = combined priority; Len = estimated proof length.", SUB))

    import io
    bio = io.BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=letter,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        title="RMA Problem Priority Report", author="ResearchMathAgent",
    )
    doc.build(story)
    return bio.getvalue()


# ── Ingest model evaluations ────────────────────────────────────────────────────

def ingest_evaluations(payload) -> dict:
    """Write model solvability evaluations into each dataset's cache + eval store.

    Accepts a list of objects, or a dict with an ``evaluations``/``results`` list,
    each carrying ``key`` (``dataset/id``) and ``score`` (0-100). For each dataset:

      * ``solvability_cache.json`` — ``{pid: score_norm}`` (0-1), read by the filter
      * ``solvability_eval.json``  — ``{pid: {score, tier, confidence, reasoning,
        estimated_proof_length}}`` for the detail view and category facet
    """
    if isinstance(payload, dict):
        items = payload.get("evaluations") or payload.get("results") or payload.get("scores") or []
    else:
        items = payload or []
    if not isinstance(items, list):
        return {"error": "expected a JSON array of {key, score} objects", "ingested": 0}

    cache_updates: dict[str, dict[str, float]] = {}
    eval_updates: dict[str, dict[str, dict]] = {}
    skipped = 0

    for it in items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        key = it.get("key") or it.get("id") or ""
        if "/" not in key:
            skipped += 1
            continue
        slug, pid = key.split("/", 1)
        try:
            ds._validate_slug(slug)
            ds._validate_id(pid)
        except Exception:
            skipped += 1
            continue
        try:
            score = float(it.get("score"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        score = max(0.0, min(100.0, score))
        norm = round(score / 100.0, 4)
        cache_updates.setdefault(slug, {})[pid] = norm
        entry: dict = {
            "score": int(round(score)),
            "score_norm": norm,
            "tier": ds.solvability_tier(norm),
            "confidence": it.get("confidence", ""),
            "reasoning": it.get("reasoning", ""),
            "estimated_proof_length": it.get("estimated_proof_length", ""),
        }
        # Optional mathematical value score (0-100); stored alongside solvability
        raw_val = it.get("value")
        if raw_val is not None:
            try:
                val = max(0.0, min(100.0, float(raw_val)))
                entry["value"] = int(round(val))
                entry["value_norm"] = round(val / 100.0, 4)
            except (TypeError, ValueError):
                pass
        eval_updates.setdefault(slug, {})[pid] = entry

    written = 0
    for slug, scores in cache_updates.items():
        cache_path = ds._solvability_cache_path(slug)
        if not cache_path.parent.is_dir():
            continue  # unknown dataset
        existing = ds._load_solvability_cache(slug)
        existing.update(scores)
        cache_path.write_text(json.dumps(existing), encoding="utf-8")

        eval_path = ds._eval_store_path(slug)
        existing_eval = ds._load_eval_store(slug)
        existing_eval.update(eval_updates.get(slug, {}))
        eval_path.write_text(json.dumps(existing_eval, ensure_ascii=False), encoding="utf-8")
        written += len(scores)

    return {
        "ingested": written,
        "skipped": skipped,
        "datasets_updated": sorted(cache_updates.keys()),
    }
