"""deep_read.py — Stage 1.5 literature deep-read.

Standalone module. Toggled by DEEP_READ_ENABLED in the parent harness.

Pipeline:
  A. Triage   — pick ≤N papers from advisor_directions[].relevant_techniques.
  B. Extract  — for each pick, fetch full paper text (PDF→text, cached on disk)
                and call a high-reasoning extractor that emits ≤K lemmas per
                paper as {label, statement, proof_sketch}.
  C. Apply    — each lemma is appended to the shared KB as a `proven_result_add`
                event with source_plan="literature_<arxiv_id>".

The KB schema is unchanged: imported lemmas live alongside solver-proven ones,
distinguished only by their source_plan tag and a "[arXiv:<id> Label]" prefix
on the statement so solvers see provenance at a glance.

This module never decides "what to avoid" — failed_attempts are the advisor's
job, downstream of solver feedback. Deep-read is pure extraction.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse


# ─── Cache helpers ────────────────────────────────────────────────────────────

# Match both modern-style IDs (YYMM.NNNNN) and old-style category-prefixed
# IDs (math/0508519, cs/9701102, etc.). Capture the full ID minus the .pdf suffix.
_ARXIV_NEW_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,6})", re.I)
_ARXIV_OLD_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([a-z\-]+(?:\.[A-Z]{2})?/[0-9]{7})", re.I)


def _arxiv_id_from_url(url: str) -> str | None:
    if not url:
        return None
    m = _ARXIV_NEW_RE.search(url)
    if m:
        return m.group(1)
    m = _ARXIV_OLD_RE.search(url)
    if m:
        return m.group(1)
    return None


def _sanitize_id(url: str) -> str:
    """Stable, filesystem-safe ID from a URL. Prefers arXiv ID.

    Old-style arXiv IDs contain slashes (e.g., ``math/0508519``); we replace
    them with underscores so the ID is safe to use as a filename.
    """
    aid = _arxiv_id_from_url(url)
    if aid:
        return "arxiv_" + aid.replace("/", "_")
    h = hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:12]
    netloc = re.sub(r"[^a-z0-9]+", "_", urlparse(url or "").netloc.lower()) or "url"
    return f"{netloc}_{h}"


_DOWNLOAD_BACKOFFS = (5, 15, 45)  # seconds between attempts 1→2, 2→3, 3→4


def _download(url: str, dest: Path, timeout: int = 60) -> bool:
    """Download ``url`` to ``dest`` with up to 4 attempts + exponential backoff.

    Backoff schedule is 5 s / 15 s / 45 s between successive failures.
    Returns True on the first successful response, False after all attempts
    exhausted. All exceptions (timeout, 4xx/5xx, DNS, SSL, …) are caught and
    counted as one failed attempt.
    """
    last_err = None
    n_attempts = len(_DOWNLOAD_BACKOFFS) + 1
    for attempt in range(1, n_attempts + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; deep-read/0.1)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                dest.write_bytes(resp.read())
            if attempt > 1:
                print(f"[deep_read] download succeeded on attempt {attempt}/{n_attempts} for {url}")
            return True
        except Exception as e:
            last_err = e
            print(f"[deep_read] download attempt {attempt}/{n_attempts} failed for {url}: {e}")
            if attempt < n_attempts:
                wait = _DOWNLOAD_BACKOFFS[attempt - 1]
                print(f"[deep_read] retrying in {wait}s...")
                time.sleep(wait)
    print(f"[deep_read] download permanently failed for {url} "
          f"after {n_attempts} attempts: {last_err}")
    return False


def _extract_pdf_url_from_html(html_path: Path, base_url: str) -> str | None:
    """Parse a downloaded HTML landing page for a direct PDF link.

    Heuristics in priority order:
      1. ``<meta name="citation_pdf_url" content="...">`` — the academic
         publishing standard (Highwire, Atypon, Springer, Elsevier all set it).
      2. ``<link rel="alternate" type="application/pdf" href="...">``.
      3. Loose fallback: any ``<a href="*.pdf">`` in the page.

    Relative URLs are resolved against ``base_url``. Returns the absolute
    URL of a PDF candidate, or None when nothing was found.
    """
    try:
        text = html_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    for pat in (
        # name=... content=...
        r'<meta[^>]*\bname=["\']citation_pdf_url["\'][^>]*\bcontent=["\']([^"\']+)["\']',
        # content=... name=...  (some publishers reverse the attribute order)
        r'<meta[^>]*\bcontent=["\']([^"\']+)["\'][^>]*\bname=["\']citation_pdf_url["\']',
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return urljoin(base_url, m.group(1).strip())

    for pat in (
        r'<link[^>]*\btype=["\']application/pdf["\'][^>]*\bhref=["\']([^"\']+)["\']',
        r'<link[^>]*\bhref=["\']([^"\']+)["\'][^>]*\btype=["\']application/pdf["\']',
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return urljoin(base_url, m.group(1).strip())

    m = re.search(
        r'<a[^>]*\bhref=["\']([^"\']+?\.pdf(?:[?#][^"\']*)?)["\']',
        text, re.IGNORECASE,
    )
    if m:
        return urljoin(base_url, m.group(1).strip())

    return None


def _pdf_to_text(pdf_path: Path) -> str | None:
    """Try pymupdf, then pdftotext shell. Return extracted text or None."""
    try:
        import pymupdf  # type: ignore
        doc = pymupdf.open(pdf_path)
        try:
            return "\n\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    except ImportError:
        pass
    except Exception as e:
        print(f"[deep_read] pymupdf parse failed: {e}")

    import subprocess
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        print(f"[deep_read] pdftotext exited {r.returncode}: {r.stderr[:200]}")
    except FileNotFoundError:
        print("[deep_read] neither pymupdf nor pdftotext available; "
              "install one of: pip install pymupdf  OR  brew install poppler")
    except Exception as e:
        print(f"[deep_read] pdftotext error: {e}")
    return None


def _is_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5).startswith(b"%PDF-")
    except Exception:
        return False


def _fetch_paper_text(url: str, cache_dir: Path) -> tuple[str | None, bool]:
    """Return (text, was_cached). None means unfetchable (caller skips).

    Fetch order:
      1. txt cache hit  → return immediately (no extraction needed).
      2. pdf cache hit  → re-extract text (e.g., when a prior run downloaded
                          the PDF but had no PDF parser installed).
      3. arXiv URL      → download from arxiv.org/pdf/<id>.pdf.
      4. Generic URL    → download as-is; accept iff response is a real PDF
                          (magic bytes %PDF-). Handles direct-PDF links from
                          non-arXiv hosts; HTML landing pages are rejected.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    sid = _sanitize_id(url)
    txt_path = cache_dir / f"{sid}.txt"
    pdf_path = cache_dir / f"{sid}.pdf"

    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8"), True

    if pdf_path.exists() and _is_pdf(pdf_path):
        cached = True
    else:
        aid = _arxiv_id_from_url(url)
        pdf_url = f"https://arxiv.org/pdf/{aid}.pdf" if aid else url
        if not _download(pdf_url, pdf_path):
            return None, False
        if not _is_pdf(pdf_path):
            # Likely an HTML landing page (publisher abstract page, paywall
            # stub). Try to find a direct PDF link in the markup, then re-
            # download. Academic platforms expose this via the standard
            # citation_pdf_url meta tag.
            direct = _extract_pdf_url_from_html(pdf_path, base_url=pdf_url)
            try:
                pdf_path.unlink()
            except Exception:
                pass

            if not direct or direct == pdf_url:
                print(f"[deep_read] {pdf_url} is not a PDF and no direct "
                      f"PDF link found in the page; skipping {url}")
                return None, False

            print(f"[deep_read] {pdf_url} is HTML landing page; "
                  f"extracted direct PDF link → {direct}")
            if not _download(direct, pdf_path):
                return None, False
            if not _is_pdf(pdf_path):
                print(f"[deep_read] direct link from landing page still "
                      f"not a PDF ({direct}); skipping {url}")
                try:
                    pdf_path.unlink()
                except Exception:
                    pass
                return None, False
        cached = False

    text = _pdf_to_text(pdf_path)
    if not text or len(text.strip()) < 1000:
        print(f"[deep_read] paper text empty/too short for {url} "
              f"({len(text or '')} chars)")
        return None, False

    txt_path.write_text(text, encoding="utf-8")
    return text, cached


# ─── Robust JSON extraction (handles ``` fences and surrounding prose) ────────

def _balanced_slice(text: str, open_c: str, close_c: str) -> str | None:
    start = text.find(open_c)
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == open_c:
                depth += 1
            elif c == close_c:
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def _try_json(text: str):
    for stripper in (lambda t: t,
                     lambda t: re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip())):
        try:
            return json.loads(stripper(text))
        except Exception:
            continue
    return None


def _extract_json_object(text: str) -> dict | None:
    obj_text = _balanced_slice(text, "{", "}")
    if obj_text is None:
        return None
    parsed = _try_json(obj_text)
    return parsed if isinstance(parsed, dict) else None


def _extract_json_array(text: str) -> list | None:
    arr_text = _balanced_slice(text, "[", "]")
    if arr_text is None:
        return None
    parsed = _try_json(arr_text)
    return parsed if isinstance(parsed, list) else None


# ─── Prompts ──────────────────────────────────────────────────────────────────

TRIAGE_PROMPT = """\
You are a research assistant. Below is a strategic briefing for a hard mathematics \
problem, with cited references. Pick the {n_papers} references most likely to contain \
theorem statements or proof techniques directly portable to the problem. Prefer papers \
whose proofs (not just topical summaries) are likely to be useful, and prefer arXiv \
URLs since their full text can be fetched.

# Problem
{problem}

# Strategic Briefing (the references live inside `directions[].relevant_techniques`)
{briefing}

# Output
Return ONLY a JSON array of exactly {n_papers} entries (or fewer if there aren't \
{n_papers} good candidates), each shaped:
[
  {{"url": "https://arxiv.org/abs/XXXX.XXXXX", "title": "...", "why_relevant": "1-2 sentences"}}
]
No prose before or after the array. No code fences.
""".strip()


EXTRACT_PROMPT = """\
You are extracting precise mathematical content from a research paper. The downstream \
consumer is a team of solvers attacking the problem below. What you write here is \
inserted into their shared knowledge base verbatim — quality matters.

# Original Problem
{problem}

# Why this paper was picked
{why_relevant}

# Full text of the paper (may be long)
{paper_text}

# Your task
Identify up to {n_lemmas} statements (theorems, lemmas, propositions) from THIS paper \
that are most directly useful for the original problem. For each, return:

1. **statement** — a precise, self-contained statement of the result. Paraphrasing \
   is allowed and often necessary, since the paper may use notation, conventions, or \
   definitions established earlier in the text; expand or rename them so the \
   statement stands alone. Every hypothesis, quantifier, and constant must be \
   preserved — silent changes to hypotheses can cause cascading errors downstream. \
   No length cap: if the statement is intricate, write it out fully.

2. **proof_sketch** — a high-quality outline of the proof that identifies *all of \
   the non-trivial ideas and steps* in the argument: every key construction, every \
   inequality or identity that does real work, every place a hypothesis is used, and \
   every clever choice or non-obvious move. Make the sketch detailed enough that a \
   mathematician could reconstruct or port the argument from it. You MAY also include:
     • implicit ideas the paper hints at but does not fully prove (e.g., "the paper \
       notes the same technique would apply to setting X if Y were replaced by Z");
     • one-line pointers to alternate proofs in works the paper cites (do NOT auto-fetch).
   Hard cap: 4000 characters. Use the full budget when the proof is intricate; do not \
   pad when it is short.

# Output (single JSON object, no code fences, no prose around it)
{{
  "arxiv_id": "{arxiv_id}",
  "title": "...",
  "lemmas": [
    {{
      "label": "Theorem N or Lemma N.M",
      "statement": "self-contained statement, paraphrase allowed, no length cap",
      "proof_sketch": "≤4000 chars"
    }}
  ]
}}

Constraints:
- Up to {n_lemmas} lemmas. Fewer is fine; if the paper has nothing directly useful, \
  return "lemmas": [].
- Do NOT extract failed_attempts or "what to avoid" — only proven, citable content.
- Do NOT translate the statement into the problem's setting; leave it in the paper's \
  own language. The translation may live inside `proof_sketch`.
""".strip()


# ─── Parsers ──────────────────────────────────────────────────────────────────

def _parse_triage(text: str, n_papers: int) -> list[dict]:
    arr = _extract_json_array(text) or []
    out: list[dict] = []
    for entry in arr[:n_papers]:
        if not isinstance(entry, dict):
            continue
        url = (entry.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        out.append({
            "url": url,
            "title": (entry.get("title") or "").strip(),
            "why_relevant": (entry.get("why_relevant") or "").strip(),
        })
    return out


def _parse_extraction(text: str, arxiv_id: str, n_lemmas: int) -> dict:
    obj = _extract_json_object(text) or {}
    obj.setdefault("arxiv_id", arxiv_id)
    obj.setdefault("title", "")
    raw = obj.get("lemmas") or []
    cleaned: list[dict] = []
    for lem in raw[:n_lemmas]:
        if not isinstance(lem, dict):
            continue
        stmt = (lem.get("statement") or "").strip()
        if not stmt:
            continue
        cleaned.append({
            "label":         (lem.get("label") or "").strip(),
            "statement":     stmt,
            "proof_sketch":  (lem.get("proof_sketch") or "").strip(),
        })
    obj["lemmas"] = cleaned
    return obj


# ─── Public entrypoint ────────────────────────────────────────────────────────

def run_deep_read(
    *,
    directions: dict,
    problem: str,
    run_response,                   # harness's run_response(...)
    apply_kb_updates,               # harness's _apply_advisor_kb_updates(kb_updates, source=...)
    output_file: Path,              # OUTPUT_DIR / "imported_papers.json"
    cache_dir: Path,                # PROBLEM_DATA_DIR / "papers"
    n_papers: int = 5,
    n_lemmas_per_paper: int = 3,
    triage_reasoning: str = "medium",
    triage_max_tokens: int = 16000,
    extract_reasoning: str = "xhigh",
    extract_max_tokens: int = 16000,
    max_parallel: int = 5,
    max_paper_chars: int = 250_000,
) -> dict:
    """Run Stage 1.5. Resume-friendly via `output_file`."""
    if output_file.exists():
        print(f"[deep_read] [RESUME] {output_file.name} exists — skipping deep-read")
        try:
            return json.loads(output_file.read_text(encoding="utf-8"))
        except Exception:
            pass  # fall through and re-run

    # ── A. Triage ────────────────────────────────────────────────────────────
    briefing_text = json.dumps(
        {k: v for k, v in directions.items() if k != "_usage"},
        ensure_ascii=False, indent=2,
    )
    triage_prompt = TRIAGE_PROMPT.format(
        problem=problem, briefing=briefing_text, n_papers=n_papers,
    )
    print(f"\n{'='*80}\n[Stage 1.5] deep-read triage (≤{n_papers} papers)\n{'='*80}")
    triage_text, _ = run_response(
        triage_prompt,
        stage_name="deepread_triage",
        reasoning_effort=triage_reasoning,
        verbosity="medium",
        max_output_tokens=triage_max_tokens,
        web_search=False,
    )
    picks = _parse_triage(triage_text, n_papers)
    if not picks:
        print("[deep_read] triage returned no picks; nothing to do.")
        summary = {"papers": [], "n_added_to_kb": 0, "skipped": True}
        output_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    print(f"[deep_read] triaged {len(picks)} paper(s):")
    for p in picks:
        print(f"  • {p['title'] or '?'} — {p['url']}")

    # ── B. Extract (parallel) ────────────────────────────────────────────────
    def _extract_one(pick: dict) -> dict:
        url = pick["url"]
        why = pick.get("why_relevant", "")
        text, cached = _fetch_paper_text(url, cache_dir)
        aid = _arxiv_id_from_url(url) or _sanitize_id(url)
        if not text:
            return {"url": url, "arxiv_id": aid, "title": pick.get("title", ""),
                    "why_relevant": why, "lemmas": [], "error": "fetch_failed"}
        if len(text) > max_paper_chars:
            print(f"[deep_read] truncating {url} from {len(text)} to {max_paper_chars} chars")
            text = text[:max_paper_chars]

        prompt = EXTRACT_PROMPT.format(
            problem=problem,
            why_relevant=why or "(no rationale provided)",
            paper_text=text,
            n_lemmas=n_lemmas_per_paper,
            arxiv_id=aid,
        )
        print(f"[deep_read] extracting from {url} "
              f"({'cached' if cached else 'fetched'}, paper={len(text)} chars)")
        try:
            txt, _ = run_response(
                prompt,
                stage_name=f"deepread_extract_{aid}",
                reasoning_effort=extract_reasoning,
                verbosity="high",
                max_output_tokens=extract_max_tokens,
                web_search=False,
            )
        except Exception as e:
            print(f"[deep_read] extraction error for {url}: {e}")
            return {"url": url, "arxiv_id": aid, "title": pick.get("title", ""),
                    "why_relevant": why, "lemmas": [], "error": str(e)[:300]}

        parsed = _parse_extraction(txt, aid, n_lemmas_per_paper)
        parsed["url"] = url
        parsed["why_relevant"] = why
        if not parsed.get("title"):
            parsed["title"] = pick.get("title", "")
        return parsed

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_parallel) as ex:
        futures = {ex.submit(_extract_one, p): p for p in picks}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"url": "?", "lemmas": [], "error": str(e)[:300]})

    # ── C. Apply to KB ───────────────────────────────────────────────────────
    n_added = 0
    for r in results:
        aid = r.get("arxiv_id") or _sanitize_id(r.get("url", ""))
        for lem in r.get("lemmas") or []:
            stmt = (lem.get("statement") or "").strip()
            if not stmt:
                continue
            label = (lem.get("label") or "").strip()
            sketch = (lem.get("proof_sketch") or "").strip()
            tag_prefix = f"[arXiv:{aid}{(' ' + label) if label else ''}] "
            tagged_stmt = tag_prefix + stmt
            apply_kb_updates(
                {
                    "new_proven_results": [
                        {"statement": tagged_stmt, "sketch": sketch},
                    ],
                },
                source=f"literature_{aid}",
            )
            n_added += 1

    print(f"[deep_read] added {n_added} imported lemma(s) to the KB "
          f"across {len(results)} paper(s).")

    summary = {
        "papers": [
            {
                "url":           r.get("url"),
                "arxiv_id":      r.get("arxiv_id"),
                "title":         r.get("title"),
                "why_relevant":  r.get("why_relevant"),
                "n_lemmas":      len(r.get("lemmas") or []),
                "error":         r.get("error"),
                "lemmas":        r.get("lemmas") or [],
            }
            for r in results
        ],
        "n_added_to_kb": n_added,
    }
    output_file.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"[deep_read] saved summary to {output_file.name}")
    return summary
