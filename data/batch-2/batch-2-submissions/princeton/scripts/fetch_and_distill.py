"""Librarian Package B — fetch PDFs + distill into compact .md summaries.

Consumes the citation list produced by Package A
(scripts/librarian.py → librarian_findings.md) and:

  1. Parses entries from the VERY RELATED / RELATED sections.
  2. For each entry, searches SerpAPI Google for a public PDF.
  3. Downloads candidates and verifies via pdftotext page-1 keyword match.
  4. Extracts text from verified PDFs with pdftotext (poppler) by
     default, falling back to pypdf if pdftotext is unavailable.
  5. Runs the literature_summarizer prompt (Quoter / Summarizer / Auditor)
     to produce a compact .md: verbatim labeled statements + length-graded
     proof summaries.

Output structure (under <problem-dir>):
  pdfs/<slug>.pdf
  summaries/<slug>.md
  fetch_and_distill_log.json

The summaries/ directory is ready to be concatenated and passed to a
future run via --additional-materials.

Requires:
  SERPAPI_API_KEY environment variable.
  pdftotext on PATH (poppler-utils; macOS: `brew install poppler`).
  pypdf (in the project venv).
  requests (in the project venv).

Usage:
  python scripts/fetch_and_distill.py run <problem-dir>
  python scripts/fetch_and_distill.py run <problem-dir> --buckets very,related
  python scripts/fetch_and_distill.py run <problem-dir> --dry-run

Cost: ~$0.05 SerpAPI per entry searched + ~$0.10-0.50 Gemini per
summary. Wall-clock dominated by download attempts (≤5 candidates per
entry × ~10s).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import click
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import pypdf  # type: ignore
except ImportError:
    pypdf = None  # type: ignore

from math_solver.gemini import call_gemini  # noqa: E402


# ─── Configuration ─────────────────────────────────────────────────────────

SERPAPI_KEY_ENV = "SERPAPI_API_KEY"
MAX_DOWNLOAD_ATTEMPTS_PER_QUERY = 5    # per SerpAPI query
DOWNLOAD_TIMEOUT_S = 60
SERPAPI_TIMEOUT_S = 30
PDFTOTEXT_TIMEOUT_S = 30
DEFAULT_BUCKETS = ("VERY RELATED", "RELATED")  # SOMEWHAT RELATED opt-in via --buckets


SUMMARIZER_SYSTEM_INSTRUCTION = """\
You are a mathematical-paper summarizer. Given the text of one paper,
return a compact list of its named statements and a short proof
summary for each. No filler.

Three personas operate in sequence:

- **Quoter.** Lists every named statement in the paper (Theorem N.M,
  Lemma N.M, Definition N.M, Proposition N.M, Corollary N.M). Copies
  each statement verbatim, with its label.
- **Summarizer.** For each statement with a proof in the paper:
  - if the proof is **≤ ~1 page**, one line summarizing the technique.
  - if the proof is **longer**, 2-3 lines naming the steps and the key
    tools used.
  Definitions get no summary. Statements with no proof in the paper
  get `(no proof in this paper)`.
- **Auditor.** Drops anything paraphrased. Anything kept must be a
  contiguous span from the source. Flags any statement whose label is
  missing from the source.

Disciplines:
- Verbatim statements. No paraphrase.
- No "Connection:" or "How to use:" fields. The reader decides.
- No equations transcribed beyond what appears in the statement.
- No section-by-section narrative.
- Skip introduction and related-work content. Only labeled mathematical
  statements.
- Terseness over completeness. If a corollary is a one-line consequence
  of the previous theorem, mark it `(immediate from <label>)` and skip
  the proof summary.

Output format:

```
# <Paper title and citation, one line>

## Definitions
- **<Label>.** <verbatim statement>

## Lemmas, Theorems, Propositions, Corollaries
- **<Label>.** <verbatim statement>
  *Proof:* <1 line for short; 2-3 lines for long; or "(no proof in this paper)"; or "(immediate from <label>)".
```
"""


SUMMARIZER_USER_TEMPLATE = """\
**Paper citation:**
{citation}

**Paper text:**
{paper_text}
"""


# ─── Findings parser ──────────────────────────────────────────────────────

# Matches a bullet entry of the form
#   - [type] Authors / Year — Title — Venue — IDs: arxiv:.../doi:.../isbn:... — (one-line connection)
# Forgiving: lets IDs section be "no ID", missing, or otherwise.
ENTRY_RE = re.compile(
    r"^-\s*\[(?P<type>[^\]]+)\]\s*"
    r"(?P<authors>[^/]+?)\s*/\s*(?P<year>[^—]+?)\s*—\s*"
    r"(?P<title>[^—]+?)\s*—\s*"
    r"(?P<venue>[^—]+?)\s*—\s*"
    r"(?P<rest>.+)$",
    re.MULTILINE,
)

ARXIV_RE = re.compile(r"arxiv[:\s]*([0-9]{4}\.[0-9]{4,5}|[a-z\-]+/\d{7})", re.IGNORECASE)
DOI_RE = re.compile(r"doi[:\s]*(10\.\d{4,9}/[\-._;()/:A-Z0-9]+)", re.IGNORECASE)
# Librarian-supplied web search query (v3 prompt onward).
# Format: `... — search: <query>` at the end of an entry line.
SEARCH_RE = re.compile(r"—\s*search:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _slugify(authors: str, title: str) -> str:
    surname = authors.split(",")[0].split(" and ")[0].split()[-1]
    title_part = re.sub(r"[^a-zA-Z0-9]+", "_", title.lower())[:50].strip("_")
    surname_part = re.sub(r"[^a-zA-Z0-9]+", "_", surname.lower()).strip("_")
    return f"{surname_part}__{title_part}"


def _verify_keywords(authors: str, title: str) -> list[str]:
    """Keywords required on PDF page 1 to consider it a match.

    Surname + 2-3 most-distinctive title words. Skip common stopwords."""
    surname = authors.split(",")[0].split(" and ")[0].split()[-1].lower()
    stop = {"the", "a", "an", "of", "for", "on", "in", "and", "to", "by",
            "with", "from", "at", "as"}
    title_words = [
        w.lower() for w in re.findall(r"[A-Za-z]+", title)
        if w.lower() not in stop and len(w) > 2
    ]
    # Take up to 3 longest words (proxy for distinctiveness)
    title_words.sort(key=lambda w: -len(w))
    return [surname] + title_words[:3]


def parse_findings(findings_md: str, buckets: tuple[str, ...]) -> list[dict]:
    """Extract entries from the named buckets in the aggregator section."""
    # Find the Stage 1 aggregator block (between '# Stage 1 — Gauntlet (aggregator output)' and the next '# Stage')
    agg_match = re.search(
        r"#\s*Stage\s*1\s*[—–-]\s*Gauntlet\s*\(aggregator output\)\s*\n(.*?)(?=^#\s*Stage|\Z)",
        findings_md, re.DOTALL | re.MULTILINE,
    )
    section = agg_match.group(1) if agg_match else findings_md
    entries: list[dict] = []
    seen: set[str] = set()
    for bucket in buckets:
        bm = re.search(
            rf"^##\s*{re.escape(bucket)}\s*\n(.*?)(?=^##\s|\Z)",
            section, re.MULTILINE | re.DOTALL,
        )
        if not bm:
            continue
        block = bm.group(1)
        for em in ENTRY_RE.finditer(block):
            entry = {
                "bucket": bucket,
                "type": em.group("type").strip().lower(),
                "authors": em.group("authors").strip(),
                "year": em.group("year").strip(),
                "title": em.group("title").strip(),
                "venue": em.group("venue").strip(),
                "rest": em.group("rest").strip(),
            }
            entry["slug"] = _slugify(entry["authors"], entry["title"])
            if entry["slug"] in seen:
                continue
            seen.add(entry["slug"])
            arxiv_m = ARXIV_RE.search(em.group("rest"))
            doi_m = DOI_RE.search(em.group("rest"))
            search_m = SEARCH_RE.search(em.group("rest"))
            entry["arxiv"] = arxiv_m.group(1) if arxiv_m else None
            entry["doi"] = doi_m.group(1).rstrip(".,);") if doi_m else None
            entry["search_query"] = search_m.group(1).strip() if search_m else None
            entry["verify_keywords"] = _verify_keywords(entry["authors"], entry["title"])
            entries.append(entry)
    return entries


# ─── PDF fetch ────────────────────────────────────────────────────────────

def _serp_web(query: str, num: int = 8) -> dict:
    api_key = os.environ.get(SERPAPI_KEY_ENV)
    if not api_key:
        raise click.UsageError(f"{SERPAPI_KEY_ENV} not set")
    r = requests.get(
        "https://serpapi.com/search",
        params={"engine": "google", "q": query, "api_key": api_key, "num": num},
        timeout=SERPAPI_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


# Hard cap on a single PDF download. Papers / open-excerpt chapters are well
# under this; a textbook (hundreds of MB) is rejected BEFORE it is buffered into
# memory, closing the OOM/crash vector. Streamed in chunks so RAM is bounded by
# the cap regardless of the file's true size. A "too-large" result returns an
# empty body, which both callers treat as a download miss (body[:4] != b"%PDF").
MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB

def _try_download(url: str) -> tuple[int, bytes, str]:
    with requests.get(
        url, headers={"User-Agent": "Mozilla/5.0 (math_solver/librarian)"},
        timeout=DOWNLOAD_TIMEOUT_S, allow_redirects=True, stream=True,
    ) as r:
        clen = r.headers.get("content-length")
        if clen and clen.isdigit() and int(clen) > MAX_PDF_BYTES:
            return r.status_code, b"", "too-large"
        buf = bytearray()
        for chunk in r.iter_content(chunk_size=65536):
            if not chunk:
                continue
            buf.extend(chunk)
            if len(buf) > MAX_PDF_BYTES:
                return r.status_code, b"", "too-large"
        return r.status_code, bytes(buf), r.headers.get("content-type", "")


def _first_page_text(pdf_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = f.name
    try:
        out = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "2", tmp, "-"],
            capture_output=True, text=True, timeout=PDFTOTEXT_TIMEOUT_S,
        )
        return out.stdout
    finally:
        Path(tmp).unlink(missing_ok=True)


# Tokens that, when leading page 1, mark the PDF as commentary on the work
# rather than the work itself (errata, corrigenda, reviews, syllabi). Earlier
# rev (2026-05-25 run 1) let through Bump's errata document, the 2012
# Jacquet correction, etc. — short-summary symptom downstream.
COMMENTARY_TOKENS = (
    "errata", "erratum", "corrigendum", "corrigenda", "correction",
    "corrections to", "review of", "book review", "review article",
    "notes on", "remarks on", "summary of", "syllabus", "course outline",
    "lecture summary", "reading guide", "bibliography",
)

MIN_PDF_BYTES = 80_000  # papers/books below this are usually errata / fragments
MIN_TITLE_WORD_MATCHES = 2  # require ≥2 distinctive title words, not 1


def _verify(body: bytes, keywords: list[str]) -> dict:
    if body[:4] != b"%PDF":
        return {"is_pdf": False, "matched": [], "missing": keywords,
                "verified": False, "reject_reason": "not_a_pdf"}
    if len(body) < MIN_PDF_BYTES:
        return {"is_pdf": True, "verified": False,
                "reject_reason": f"too_small ({len(body)} < {MIN_PDF_BYTES})",
                "matched": [], "missing": keywords}
    try:
        text = _first_page_text(body).lower()
    except Exception as e:
        return {"is_pdf": True, "pdftotext_error": str(e),
                "matched": [], "missing": keywords, "verified": False}
    head = " ".join(text.split()[:300])
    matched = [k for k in keywords if k in head]
    missing = [k for k in keywords if k not in head]
    surname_ok = bool(keywords) and keywords[0] in matched
    n_title_matches = sum(1 for k in keywords[1:] if k in matched)
    title_ok = n_title_matches >= min(MIN_TITLE_WORD_MATCHES, max(1, len(keywords) - 1))
    # Reject if page 1 leads with a commentary token (errata / review / etc).
    head_first_60_words = " ".join(head.split()[:60])
    commentary_hit = next(
        (t for t in COMMENTARY_TOKENS if t in head_first_60_words),
        None,
    )
    verified = surname_ok and title_ok and not commentary_hit
    reject_reason = None
    if not verified:
        reasons = []
        if not surname_ok:
            reasons.append("surname_missing")
        if not title_ok:
            reasons.append(f"only_{n_title_matches}_title_words")
        if commentary_hit:
            reasons.append(f"commentary_token: {commentary_hit!r}")
        reject_reason = "; ".join(reasons) or "unknown"
    return {
        "is_pdf": True, "matched": matched, "missing": missing,
        "head_excerpt": head[:240],
        "verified": verified,
        "reject_reason": reject_reason,
        "size_bytes": len(body),
        "n_title_matches": n_title_matches,
        "commentary_hit": commentary_hit,
    }


FLASH_URL_PICKER_PROMPT = """\
You are helping locate an open-access PDF of a specific academic work
(paper, book, monograph, lecture notes, or thesis). You are given a list
of Google search results and the expected work's authors / title / year /
type. Pick the ONE result link that is most likely the actual open-access
PDF of the expected work.

REJECT:
- Errata, corrigenda, corrections, review articles, book reviews
- Different works by the same author(s) (e.g., a different paper with
  overlapping keywords)
- Broken or generic landing pages where the linked file is unclear
- Partial extracts / single chapters when the work is a multi-chapter
  book or notes (unless that specific chapter is the cited target)
- Bibliographies, syllabi, course outlines that merely mention the work

PREFER:
- Direct PDF links (URL ending in .pdf)
- Author-homepage hosting (`/~surname/`, `people.math.<inst>.edu/...`,
  `<inst>.edu/...`)
- Diamond open-access journals (Documenta Math, arXiv, J. Eur. Math. Soc.)
- Institutional repositories (MSRI, IHÉS, Fields Institute, PCMI, TIFR,
  Bonn HIM)

If no result is clearly the right work, return "NONE".

Output a JSON object with two fields:
  url:    the chosen URL verbatim, or "NONE"
  reason: one short sentence explaining the choice
"""


async def _flash_pick_url(all_hits: list[dict], entry: dict) -> tuple[str | None, str]:
    """Ask Flash to pick the best URL from a deduplicated list of SerpAPI
    hits. Returns (url, reason). url is None if Flash sees no good match.

    Why this exists: regex-based URL pre-selection consistently picked
    near-misses (Bump errata for Bump book; Cogdell PCMI when Cogdell
    Fields was needed; etc.). Flash reading the snippets is faster
    end-to-end (no download-then-discard loop) and more accurate.
    """
    from math_solver.gemini import _get_client
    from math_solver.config import GEMINI_FLASH_MODEL
    from google.genai import types as gtypes
    import json as _json

    if not all_hits:
        return None, "no SerpAPI hits"
    hits_text = "\n".join(
        f"{i+1}. {h.get('title', '')[:150]}\n"
        f"   URL: {h.get('link', '')}\n"
        f"   Snippet: {h.get('snippet', '')[:300]}"
        for i, h in enumerate(all_hits[:20])
    )
    expected_block = (
        f"Expected work:\n"
        f"  Authors: {entry.get('authors', '?')}\n"
        f"  Title:   {entry.get('title', '?')}\n"
        f"  Year:    {entry.get('year', '?')}\n"
        f"  Type:    {entry.get('type', '?')}\n\n"
        f"Search results:\n{hits_text}"
    )
    prompt = FLASH_URL_PICKER_PROMPT + "\n\n" + expected_block

    client = _get_client()
    config = gtypes.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {"url": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["url", "reason"],
        },
        temperature=0.0,
        max_output_tokens=512,
    )
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_FLASH_MODEL,
                contents=prompt,
                config=config,
            ),
            timeout=60.0,
        )
        data = _json.loads(response.text or "{}")
        url = (data.get("url") or "").strip()
        reason = (data.get("reason") or "").strip()
        if not url or url.upper() == "NONE":
            return None, reason or "no match"
        return url, reason
    except Exception as e:
        return None, f"flash error: {e}"


async def fetch_pdf(entry: dict, pdfs_dir: Path) -> dict:
    """Try to find a public PDF for `entry`. On success writes
    pdfs_dir/<slug>.pdf and returns a dict with `path` set; on failure
    returns details for the log."""
    slug = entry["slug"]
    dest = pdfs_dir / f"{slug}.pdf"
    if dest.exists() and dest.stat().st_size > 1000:
        return {"slug": slug, "path": str(dest), "source": "cached", "queries": []}

    # If we have an arxiv ID, try the canonical URL first — bypass SerpAPI.
    if entry.get("arxiv"):
        arxiv_url = f"https://arxiv.org/pdf/{entry['arxiv']}"
        try:
            status, body, ct = _try_download(arxiv_url)
            if status == 200 and body[:4] == b"%PDF":
                v = _verify(body, entry["verify_keywords"])
                if v.get("verified"):
                    dest.write_bytes(body)
                    return {"slug": slug, "path": str(dest), "source": "arxiv",
                            "url": arxiv_url, "verify": v, "queries": []}
        except Exception as e:
            pass  # fall through to SerpAPI

    # SerpAPI Google web search.
    # PRIMARY: librarian-supplied human-natural query (added in librarian v3
    # for "Cogdell lecture notes pdf" type lookups that the constructed
    # quoted-title + filetype:pdf queries miss). FALLBACKS: the older
    # constructed forms, kept for safety if the librarian omitted the field.
    surname = entry["verify_keywords"][0]  # already lowercased
    queries: list[str] = []
    if entry.get("search_query"):
        queries.append(entry["search_query"])
    queries.extend([
        f'"{entry["title"]}" {surname} filetype:pdf',
        f'"{entry["title"]}" filetype:pdf',
    ])
    record = {"slug": slug, "queries": []}

    # Collect hits across all queries, then ask Flash to pre-pick.
    # Flash gets the union of hits and chooses the most plausible URL.
    all_hits: list[dict] = []
    seen_urls: set[str] = set()
    for q in queries:
        qrec = {"q": q, "hits": []}
        try:
            data = _serp_web(q)
        except Exception as e:
            qrec["error"] = str(e)
            record["queries"].append(qrec)
            continue
        for o in data.get("organic_results", []):
            link = o.get("link", "")
            if not link or link in seen_urls:
                continue
            seen_urls.add(link)
            all_hits.append({
                "title": o.get("title", ""),
                "link": link,
                "snippet": o.get("snippet", ""),
                "from_query": q,
            })
        record["queries"].append(qrec)

    # Flash pre-pick
    flash_url, flash_reason = await _flash_pick_url(all_hits, entry)
    record["flash_pick"] = {"url": flash_url, "reason": flash_reason,
                            "n_hits_seen": len(all_hits)}

    # Try Flash's pick first (if any), then fall back to per-query top-N.
    download_order: list[dict] = []
    if flash_url:
        flash_hit = next((h for h in all_hits if h["link"] == flash_url), None)
        if flash_hit is None:
            flash_hit = {"title": "(flash pick)", "link": flash_url,
                         "snippet": "", "from_query": "<flash>"}
        download_order.append(flash_hit)
    # Fallbacks: top MAX_DOWNLOAD_ATTEMPTS_PER_QUERY hits from each query,
    # in original order, skipping any already-tried URL.
    tried = {flash_url} if flash_url else set()
    per_query_count: dict[str, int] = {}
    for h in all_hits:
        if h["link"] in tried:
            continue
        c = per_query_count.get(h["from_query"], 0)
        if c >= MAX_DOWNLOAD_ATTEMPTS_PER_QUERY:
            continue
        per_query_count[h["from_query"]] = c + 1
        download_order.append(h)
        tried.add(h["link"])

    for h in download_order:
        # Attribute to the originating query record for logging.
        qrec = next((q for q in record["queries"] if q["q"] == h.get("from_query")),
                    None)
        if qrec is None:
            qrec = {"q": "<flash-only>", "hits": []}
            record["queries"].append(qrec)
        hit_log = {"link": h["link"], "hit_title": h.get("title", "")[:120],
                   "picked_by": "flash" if h is download_order[0] and flash_url else "rank"}
        try:
            status, body, ct = _try_download(h["link"])
            hit_log["status"] = status
            hit_log["bytes"] = len(body)
            if status == 200:
                v = _verify(body, entry["verify_keywords"])
                hit_log["verify"] = v
                if v.get("verified"):
                    dest.write_bytes(body)
                    record["path"] = str(dest)
                    record["source"] = "serpapi" if hit_log["picked_by"] == "rank" else "flash"
                    record["url"] = h["link"]
                    qrec["hits"].append(hit_log)
                    return record
        except Exception as e:
            hit_log["download_error"] = str(e)[:200]
        qrec["hits"].append(hit_log)
    return record  # path not set → failure


# ─── PDF text extraction + summarize ──────────────────────────────────────

MAX_SUMMARIZER_CHARS = 240_000  # cap text fed to Gemini per paper (~60K tokens)


def _extract_via_pdftotext(pdf_path: Path) -> str:
    """Primary path: pdftotext -layout via poppler-utils binary.

    Higher math fidelity than pypdf on the standard arXiv/Springer math-paper
    corpus — ligatures are normalized to ASCII (``fi``, not ``ﬁ``), no spurious
    word-internal spaces ("series" stays "series", not "seri es"), and layout
    is preserved for display equations and multi-column papers. pdftotext
    separates pages with the form-feed control character ``\\x0c``, which we
    split on to preserve the ``--- [page N] ---`` marker convention the prior
    pypdf-based implementation used.

    Raises ``subprocess.SubprocessError`` (or ``FileNotFoundError`` if the
    binary is missing entirely) so the caller can fall back to pypdf.
    """
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=120, check=True,
    )
    pages = out.stdout.split("\x0c")
    chunks = [f"--- [page {i+1}] ---\n{p}" for i, p in enumerate(pages) if p.strip()]
    if not chunks:
        # pdftotext returned exit 0 but with empty stdout — image-only PDF
        # without an OCR layer, or an embedded-font failure that pdftotext
        # doesn't flag as an error. Route this case to the pypdf fallback
        # rather than silently summarizing zero bytes.
        raise subprocess.SubprocessError(
            f"pdftotext produced empty output for {pdf_path.name}"
        )
    return "\n\n".join(chunks)


def _extract_via_pypdf(pdf_path: Path) -> str:
    """Fallback path: pure-Python pypdf extraction.

    Retained as defense-in-depth after tonight's two PDF-related deploy
    bugs (2026-05-28 evening):
      * ``ff9116e`` — poppler-utils was missing from the Dockerfile, making
        pdftotext unavailable; the primary path here would have raised
        FileNotFoundError.
      * ``09aad42`` — pypdf was missing from deploy/requirements.lock.txt,
        making this fallback path unavailable.
    Keeping both code paths means no single missing dep can take the chain
    down. Quality caveat: pypdf has measurable math-fidelity artifacts
    (preserves ``ﬁ`` ligature, misreads ``=`` as ``−`` in some sup/sub
    contexts, introduces spurious word-internal spaces) which the Flash
    summarizer downstream can sometimes paper over but not always. Prefer
    the pdftotext primary path whenever it's available.
    """
    if pypdf is None:
        raise click.UsageError(
            "Neither pdftotext nor pypdf is available — Grader 3 distill cannot run. "
            "Install poppler-utils for pdftotext (preferred) or pip install pypdf."
        )
    reader = pypdf.PdfReader(str(pdf_path))
    chunks = []
    for i, p in enumerate(reader.pages):
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        chunks.append(f"--- [page {i+1}] ---\n{t}")
    return "\n\n".join(chunks)


def extract_text(pdf_path: Path) -> str:
    """Extract full text from a PDF for the Flash summarizer.

    Primary: pdftotext -layout (poppler-utils binary). Fallback: pypdf.
    See _extract_via_pdftotext / _extract_via_pypdf for the rationale on
    why both code paths are retained.
    """
    try:
        return _extract_via_pdftotext(pdf_path)
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        click.echo(
            f"[fetch_and_distill] pdftotext extract failed for {pdf_path.name} "
            f"({type(exc).__name__}: {exc}); falling back to pypdf",
            err=True,
        )
        return _extract_via_pypdf(pdf_path)


async def distill(entry: dict, pdf_path: Path, summaries_dir: Path,
                  run_tag: str) -> dict:
    text = extract_text(pdf_path)
    if len(text) > MAX_SUMMARIZER_CHARS:
        text = text[:MAX_SUMMARIZER_CHARS] + "\n\n[...truncated to fit context...]"
    citation = (f"{entry['authors']} ({entry['year']}). "
                f"{entry['title']}. {entry['venue']}.")
    user = SUMMARIZER_USER_TEMPLATE.format(citation=citation, paper_text=text)
    full_prompt = SUMMARIZER_SYSTEM_INSTRUCTION + "\n\n---\n\n" + user
    call = await call_gemini(
        full_prompt,
        run_id=run_tag, notebook_id=f"summarize_{entry['slug']}",
        agent="literature_summarizer_v1",
        inputs={"slug": entry["slug"], "pdf_bytes": pdf_path.stat().st_size,
                "text_chars": len(text)},
        store=None,
    )
    header = (
        f"<!-- Generated {datetime.now().isoformat(timespec='seconds')} -->\n"
        f"<!-- Source PDF: {pdf_path.name} ({pdf_path.stat().st_size} bytes) -->\n"
        f"<!-- Citation: {citation} -->\n\n"
    )
    out_path = summaries_dir / f"{entry['slug']}.md"
    out_path.write_text(header + call.output, encoding="utf-8")
    return {
        "slug": entry["slug"], "summary_path": str(out_path),
        "text_chars": len(text), "summary_chars": len(call.output),
    }


# ─── Driver ───────────────────────────────────────────────────────────────

async def _run(problem_dir: Path, buckets: tuple[str, ...],
               dry_run: bool, run_tag: str) -> None:
    findings_path = problem_dir / "librarian_findings.md"
    if not findings_path.exists():
        raise click.UsageError(f"Missing {findings_path} — run Package A first.")
    findings_md = findings_path.read_text(encoding="utf-8")
    entries = parse_findings(findings_md, buckets)
    click.echo(f"[fetch_and_distill] parsed {len(entries)} entries from buckets {buckets}")
    for e in entries:
        click.echo(f"  - [{e['bucket']}] [{e['type']}] {e['authors']} / {e['year']} — "
                   f"{e['title'][:70]}  (arxiv={e['arxiv']}, doi={e['doi']})")

    if dry_run:
        click.echo("[fetch_and_distill] --dry-run set; not fetching. Exiting.")
        return

    if not os.environ.get(SERPAPI_KEY_ENV):
        raise click.UsageError(f"{SERPAPI_KEY_ENV} not set in environment")

    pdfs_dir = problem_dir / "pdfs"
    summaries_dir = problem_dir / "summaries"
    pdfs_dir.mkdir(exist_ok=True)
    summaries_dir.mkdir(exist_ok=True)

    # Fetch all PDFs sequentially — SerpAPI / downloads are I/O-bound but
    # parallelism risks rate-limiting and complicates error reporting.
    click.echo(f"[fetch_and_distill] fetching PDFs ({len(entries)} entries)…")
    fetch_records: list[dict] = []
    for e in entries:
        click.echo(f"  fetch: {e['slug']}…")
        rec = await fetch_pdf(e, pdfs_dir)
        fetch_records.append({**e, **rec})
        status = "OK" if rec.get("path") else "FAIL"
        click.echo(f"    -> {status}{' ('+rec.get('source','')+')' if rec.get('path') else ''}")

    # Distill verified PDFs in parallel (Gemini calls).
    to_distill = [r for r in fetch_records if r.get("path")]
    click.echo(f"[fetch_and_distill] distilling {len(to_distill)} verified PDFs…")
    distill_records: list[dict] = []
    if to_distill:
        results = await asyncio.gather(*(
            distill(e, Path(e["path"]), summaries_dir, run_tag) for e in to_distill
        ), return_exceptions=True)
        for e, res in zip(to_distill, results):
            if isinstance(res, Exception):
                distill_records.append({"slug": e["slug"], "error": str(res)[:300]})
                click.echo(f"    distill FAIL: {e['slug']} — {res}")
            else:
                distill_records.append(res)
                click.echo(f"    distill OK: {res['slug']} -> "
                           f"{res['summary_chars']} chars")

    # Persist log
    log = {
        "run_tag": run_tag,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "buckets": list(buckets),
        "entries_parsed": len(entries),
        "pdfs_fetched": sum(1 for r in fetch_records if r.get("path")),
        "summaries_written": sum(1 for r in distill_records if r.get("summary_path")),
        "fetch_records": fetch_records,
        "distill_records": distill_records,
    }
    log_path = problem_dir / "fetch_and_distill_log.json"
    log_path.write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")
    click.echo(f"[fetch_and_distill] wrote {log_path}")
    click.echo(f"[fetch_and_distill] summary: parsed={len(entries)} "
               f"fetched={log['pdfs_fetched']} distilled={log['summaries_written']}")


@click.group()
def cli() -> None:
    """Librarian Package B — fetch PDFs + distill summaries."""


@cli.command("run")
@click.argument("problem_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--buckets", default="very,related",
              help="Comma-separated buckets to pull from the librarian findings. "
                   "Options: very, related, somewhat. Default: very,related.")
@click.option("--dry-run", is_flag=True,
              help="Parse and print entries, then exit without fetching.")
@click.option("--tag", default=None, help="Run tag for telemetry.")
def run_cmd(problem_dir: Path, buckets: str, dry_run: bool, tag: str | None) -> None:
    """Fetch PDFs + distill for entries in PROBLEM_DIR/librarian_findings.md.

    Writes PDFs to PROBLEM_DIR/pdfs/, summaries to PROBLEM_DIR/summaries/,
    and a fetch_and_distill_log.json with everything that was tried.
    """
    bucket_map = {"very": "VERY RELATED", "related": "RELATED",
                  "somewhat": "SOMEWHAT RELATED", "not": "NOT MUCH"}
    parsed = []
    for tok in buckets.split(","):
        key = tok.strip().lower()
        if key not in bucket_map:
            raise click.UsageError(
                f"Unknown bucket {key!r}. Allowed: {', '.join(bucket_map)}"
            )
        parsed.append(bucket_map[key])
    if tag is None:
        tag = f"fetch_distill_{problem_dir.name}_{datetime.now().strftime('%Y%m%d')}"
    asyncio.run(_run(problem_dir, tuple(parsed), dry_run, tag))


if __name__ == "__main__":
    cli()
