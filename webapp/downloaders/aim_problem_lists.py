"""Scrape AIM (American Institute of Mathematics) Problem Lists.

Source: http://aimpl.org/  (80+ curated workshop problem lists)
        https://aimath.org/pastworkshops/ (older PDF lists)
License: Academic / non-commercial (no explicit license; attribution required)
Format: HTML pages on aimpl.org — one page per problem section.

Scraping strategy:
  1. Fetch the main index from aimpl.org
  2. For each list, scrape individual section pages
  3. Parse problem title, statement, and remarks
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path


DATASET_SLUG = "aim_problem_lists"
INDEX_URL = "http://aimpl.org/"

METADATA = {
    "slug": DATASET_SLUG,
    "name": "AIM Problem Lists",
    "description": "Open problem lists from American Institute of Mathematics workshops. Covers 80+ topics in pure and applied mathematics including spectral theory, combinatorics, number theory, geometry, and more.",
    "source": "http://aimpl.org/",
    "license": "Academic/non-commercial (attribution required)",
    "version": "2025",
    "year": 2025,
    "tags": ["open-problems", "workshop", "AIM", "multi-area"],
}

# Manually curated list of known aimpl.org slugs (representative sample)
KNOWN_LISTS = [
    ("spectralhypergraph", "Spectral Hypergraph Theory"),
    ("hypergraphturan", "Hypergraph Turán Problems"),
    ("addcombapp", "Additive Combinatorics"),
    ("sarnakconjecture", "Sarnak's Conjecture"),
    ("kpzuniversality", "KPZ Universality"),
    ("markovmixing", "Markov Chain Mixing"),
    ("graphisomorphism", "Graph Isomorphism"),
    ("matroidtheory", "Matroid Theory"),
    ("ramsey", "Ramsey Theory"),
    ("discretegeometry", "Discrete Geometry"),
    ("finitefields", "Finite Fields"),
    ("algcombinatorics", "Algebraic Combinatorics"),
    ("lowdimtop", "Low-Dimensional Topology"),
    ("arithmeticgeometry", "Arithmetic Geometry"),
    ("randommatrices", "Random Matrices"),
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ResearchMathAgent/1.0; +https://github.com/sjtuytc/ResearchMathAgent)",
    "Accept": "text/html,application/xhtml+xml",
}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer"):
            self._skip = False
        if tag in ("p", "div", "h1", "h2", "h3", "li"):
            self.text.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)

    def get_text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.text)).strip()


def _fetch(url: str, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                print(f"  [aim] Failed to fetch {url}: {e}")
                return None


def _scrape_list(slug: str, list_name: str, problems_dir: Path, start_idx: int) -> int:
    count = 0
    section = 1
    while section <= 50:
        url = f"http://aimpl.org/{slug}/{section}/"
        html = _fetch(url)
        if html is None or "Page not found" in html or "404" in html:
            break

        parser = _TextExtractor()
        parser.feed(html)
        text = parser.get_text()

        # Extract problem title from h2/h3
        title_m = re.search(r"Problem \d+\.?\d*[.:]\s*(.+)", text)
        title = title_m.group(1).strip() if title_m else f"{list_name} §{section}"
        # Clean up title (first line only)
        title = title.split("\n")[0].strip()[:200]

        # Extract statement (text between title and "Remarks" or end)
        statement = text
        if len(statement) > 4000:
            statement = statement[:4000] + "…"

        pid = f"aim_{slug}_{section:03d}"
        record = {
            "id": pid,
            "dataset": DATASET_SLUG,
            "title": title,
            "statement": statement,
            "tex": "",
            "tags": ["AIM", "workshop", "open-problem"],
            "difficulty": None,
            "solvability_score": None,
            "source_url": url,
            "year": 2025,
            "aim_list": slug,
            "aim_list_name": list_name,
            "section": section,
        }
        (problems_dir / f"{pid}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        count += 1
        section += 1
        time.sleep(0.3)  # polite crawl

    return count


def download(datasets_dir: Path, force: bool = False) -> int:
    out_dir = datasets_dir / DATASET_SLUG
    problems_dir = out_dir / "problems"

    if problems_dir.is_dir() and any(problems_dir.glob("*.json")) and not force:
        existing = sum(1 for _ in problems_dir.glob("*.json"))
        print(f"[aim_problem_lists] Already downloaded ({existing} problems). Use --force to re-download.")
        return existing

    problems_dir.mkdir(parents=True, exist_ok=True)

    # Try to discover lists from the index
    all_lists = _discover_lists() or KNOWN_LISTS

    total = 0
    for slug, list_name in all_lists:
        print(f"  [aim] Scraping: {slug} ({list_name})")
        n = _scrape_list(slug, list_name, problems_dir, total)
        print(f"  [aim]   → {n} sections scraped")
        total += n

    _write_metadata(out_dir, total)
    print(f"[aim_problem_lists] Total: {total} problem sections.")
    return total


def _discover_lists() -> list[tuple[str, str]] | None:
    """Try to scrape the aimpl.org index to find all list slugs."""
    html = _fetch(INDEX_URL)
    if not html:
        return None
    # Look for links like /slug/
    found = []
    for m in re.finditer(r'href=["\']/([\w-]+)/["\']', html):
        slug = m.group(1)
        if slug and slug not in ("about", "contact", "login", "search", "static"):
            found.append((slug, slug.replace("-", " ").title()))
    return found[:80] if found else None


def _write_metadata(out_dir: Path, count: int) -> None:
    meta = dict(METADATA)
    meta["problem_count"] = count
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
