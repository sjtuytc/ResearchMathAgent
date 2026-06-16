"""Download Erdős Problems dataset.

Source:
  Metadata YAML: https://raw.githubusercontent.com/teorth/erdosproblems/main/data/problems.yaml
  Problem statements: https://www.erdosproblems.com/{number}  (requires browser UA)

Maintainer: Terence Tao (github.com/teorth/erdosproblems)
License: Apache 2.0
Size: 1,179 problems; ~59% open, ~41% solved/disproved

The YAML contains rich metadata (prize, status, tags, OEIS references) but NOT the
full problem statement. We fetch statements from erdosproblems.com with a browser
User-Agent header.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


DATASET_SLUG = "erdos_problems"
YAML_URL = "https://raw.githubusercontent.com/teorth/erdosproblems/main/data/problems.yaml"
SITE_URL = "https://www.erdosproblems.com"

METADATA = {
    "slug": DATASET_SLUG,
    "name": "Erdős Problems",
    "description": "1,179 open problems posed by Paul Erdős, maintained by Terence Tao. Includes cash prizes, tags, OEIS references, and current status (open/solved/disproved).",
    "source": "https://github.com/teorth/erdosproblems",
    "license": "Apache-2.0",
    "version": "2025-08",
    "year": 2025,
    "tags": ["erdos", "open-problems", "combinatorics", "number-theory", "graph-theory"],
}

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class _StatementExtractor(HTMLParser):
    """Extract the problem statement from an erdosproblems.com page."""
    def __init__(self):
        super().__init__()
        self._in_main = False
        self._in_para = False
        self._depth = 0
        self.paragraphs: list[str] = []
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        cls = attr_dict.get("class", "")
        if tag == "main" or (tag == "div" and "problem" in cls):
            self._in_main = True
        if self._in_main and tag in ("p", "div"):
            self._in_para = True
            self._buf = []

    def handle_endtag(self, tag):
        if self._in_main and tag in ("p", "div"):
            text = "".join(self._buf).strip()
            if text and len(text) > 20:
                self.paragraphs.append(text)
            self._in_para = False
            self._buf = []

    def handle_data(self, data):
        if self._in_main and self._in_para:
            self._buf.append(data)

    def get_statement(self) -> str:
        return "\n\n".join(self.paragraphs[:5])


def _fetch(url: str, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                print(f"  [erdos] Could not fetch {url}: {e}")
                return None


def _parse_yaml(text: str) -> list[dict]:
    """Minimal YAML parser for the flat list format used in problems.yaml."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or []
    except ImportError:
        pass

    # Fallback: hand-parse the simple YAML structure
    problems = []
    current: dict = {}
    for line in text.splitlines():
        if line.startswith("- number:"):
            if current:
                problems.append(current)
            current = {"number": int(line.split(":")[-1].strip())}
        elif line.startswith("  ") and ":" in line:
            key, _, val = line.strip().partition(":")
            val = val.strip()
            if val:
                try:
                    current[key] = int(val)
                except ValueError:
                    current[key] = val
        elif line.startswith("    - "):
            val = line.strip("- \n")
            current.setdefault(key, [])
            if isinstance(current.get(key), list):
                current[key].append(val)
    if current:
        problems.append(current)
    return problems


def _fetch_statement(number: int) -> str:
    """Fetch problem statement from erdosproblems.com/{number}."""
    url = f"{SITE_URL}/{number}"
    html = _fetch(url)
    if not html:
        return ""
    parser = _StatementExtractor()
    parser.feed(html)
    stmt = parser.get_statement()
    # Also try a simple regex fallback
    if not stmt:
        m = re.search(r"<p[^>]*>(.*?)</p>", html, re.DOTALL)
        if m:
            stmt = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    return stmt[:3000]


def download(datasets_dir: Path, force: bool = False, fetch_statements: bool = True) -> int:
    out_dir = datasets_dir / DATASET_SLUG
    problems_dir = out_dir / "problems"

    if problems_dir.is_dir() and any(problems_dir.glob("*.json")) and not force:
        existing = sum(1 for _ in problems_dir.glob("*.json"))
        print(f"[erdos_problems] Already downloaded ({existing} problems). Use --force to re-download.")
        return existing

    problems_dir.mkdir(parents=True, exist_ok=True)
    if force and not fetch_statements:
        for old in problems_dir.glob("*.json"):
            old.unlink()

    # 1. Download metadata YAML
    print("[erdos_problems] Downloading metadata YAML...")
    yaml_text = _fetch(YAML_URL)
    if not yaml_text:
        print("[erdos_problems] ERROR: Could not fetch YAML metadata.")
        return 0

    rows = _parse_yaml(yaml_text)
    print(f"[erdos_problems] Parsed {len(rows)} records from YAML.")

    count = 0
    for row in rows:
        number = row.get("number", count + 1)
        try:
            number = int(number)
        except (TypeError, ValueError):
            number = count + 1
        pid = f"erdos_{number:04d}"

        # 2. Optionally fetch statement from website
        statement = ""
        if fetch_statements:
            existing_path = problems_dir / f"{pid}.json"
            # Reuse existing statement if it's a real statement (not a placeholder)
            if existing_path.is_file():
                try:
                    existing_rec = json.loads(existing_path.read_text())
                    existing_stmt = existing_rec.get("statement", "")
                    if existing_stmt and "(Statement not yet fetched" not in existing_stmt:
                        statement = existing_stmt
                except Exception:
                    pass
            if not statement:
                statement = _fetch_statement(number)
                time.sleep(0.4)  # polite

        tags = list(row.get("tags", [])) or ["erdos", "open-problem"]
        tags = [str(t) for t in tags]
        if "erdos" not in tags:
            tags.insert(0, "erdos")

        record = {
            "id": pid,
            "dataset": DATASET_SLUG,
            "title": f"Erdős Problem #{number}",
            "statement": statement or f"(Statement not yet fetched — visit {SITE_URL}/{number})",
            "tex": "",
            "tags": tags,
            "difficulty": None,
            "solvability_score": None,
            "source_url": f"{SITE_URL}/{number}",
            "year": None,
            "prize_usd": row.get("prize"),
            "status": str(row.get("status", "open")),
            "oeis": row.get("oeis", []),
            "formalized": row.get("formalized", False),
            "erdos_number": number,
        }
        (problems_dir / f"{pid}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        count += 1

        if count % 100 == 0:
            print(f"  [erdos] {count}/{len(rows)} done...")

    _write_metadata(out_dir, count)
    print(f"[erdos_problems] Downloaded {count} problems.")
    return count


def _write_metadata(out_dir: Path, count: int) -> None:
    meta = dict(METADATA)
    meta["problem_count"] = count
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
