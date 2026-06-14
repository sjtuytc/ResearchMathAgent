"""arxiv API client — no API key required (export.arxiv.org/api/query)."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Literal

import feedparser
import httpx

from ..models import Paper

ARXIV_API = "https://export.arxiv.org/api/query"
MATH_CATS = ["math.AG", "math.NT", "math.RT", "math.GR", "math.CO",
             "math.LO", "math.CA", "math.AP", "math.DS", "math.PR",
             "math.FA", "math.MG", "math.DG", "math.AT", "math.GT",
             "math.CV", "math.OA", "math.RA", "math.CT", "math.KT",
             "cs.LO", "cs.CC", "hep-th"]  # broad math coverage


async def search_arxiv(
    query: str,
    *,
    max_results: int = 20,
    recency: Literal["recent", "any", "unknown"] = "any",
    recent_months: int = 18,
    max_date: datetime | None = None,
    sort_by: Literal["relevance", "submittedDate"] = "relevance",
) -> list[Paper]:
    """
    Query arxiv and return Paper objects (no PDF download).
    If recency=="recent", filters to papers submitted in the last recent_months.
    If max_date is set, drops papers submitted on or after that date.
    Default sort is relevance — date-sort returns recent papers that happen to
    match keywords rather than the canonical references for the query, which
    is the opposite of what research-math literature search needs.
    """
    params: dict[str, str | int] = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    import asyncio as _asyncio
    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(4):
            try:
                resp = await client.get(ARXIV_API, params=params)
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.NetworkError):
                if attempt < 3:
                    await _asyncio.sleep(15 * (attempt + 1))
                    continue
                return []
            if resp.status_code == 429:
                await _asyncio.sleep(15 * (attempt + 1))
                continue
            resp.raise_for_status()
            break

    feed = feedparser.parse(resp.text)
    papers: list[Paper] = []

    cutoff: datetime | None = None
    if recency == "recent":
        cutoff = datetime.utcnow() - timedelta(days=recent_months * 30)

    for entry in feed.entries:
        arxiv_id = _extract_id(entry.get("id", ""))
        if not arxiv_id:
            continue

        pub_date = _parse_date(entry.get("published", ""))
        if cutoff and pub_date and pub_date < cutoff:
            continue
        if max_date and pub_date and pub_date >= max_date:
            continue

        authors = [a.get("name", "") for a in entry.get("authors", [])]
        primary_cat = entry.get("arxiv_primary_category", {}).get("term", "")

        paper = Paper(
            arxiv_id=arxiv_id,
            title=_clean(entry.get("title", "")),
            authors=authors,
            date=pub_date.strftime("%Y-%m-%d") if pub_date else "unknown",
            abstract=_clean(entry.get("summary", "")),
            primary_category=primary_cat,
        )
        papers.append(paper)

    return papers


async def download_pdf(arxiv_id: str, dest_path) -> bool:
    """Download the PDF for arxiv_id to dest_path. Returns True on success."""
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        from pathlib import Path
        path = Path(dest_path)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(resp.content)
        tmp.replace(path)
        return True
    except Exception:
        return False


def build_arxiv_query(terms: str, categories: list[str] | None = None) -> str:
    """Wrap a query with optional category filter.

    Multi-word bare-keyword queries are AND-joined per-term so arxiv's parser
    applies the `all:` field to every word (arxiv ignores additional words
    after the first within a single field clause). If the caller already
    supplied a structured query (containing AND/OR/ANDNOT, quotes, or parens),
    pass it through unchanged.
    """
    structured = any(tok in terms for tok in (" AND ", " OR ", " ANDNOT ", '"', "(", ")"))
    if structured:
        q = f"all:{terms}" if not terms.lstrip().startswith(("all:", "ti:", "abs:", "au:")) else terms
    else:
        words = terms.split()
        q = " AND ".join(f"all:{w}" for w in words) if words else f"all:{terms}"
    if categories:
        cat_filter = " OR ".join(f"cat:{c}" for c in categories)
        q = f"({q}) AND ({cat_filter})"
    return q


def _extract_id(url: str) -> str:
    m = re.search(r"arxiv\.org/abs/([^\s]+)", url)
    return m.group(1) if m else url.split("/")[-1]


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
