"""Documents store for the Research Math Agent web app.

Holds the daily reports written by the autonomous daily worker (and any other
markdown documents). The web UI surfaces these under a Documents tab. Reports
live in the repo-level ``documents/`` directory.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+\.(md|tex)$")


def documents_dir(repo_root: Path) -> Path:
    d = repo_root / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_documents(repo_root: Path) -> list[dict]:
    """Return all .md files under documents/, recursively, with folder metadata."""
    d = documents_dir(repo_root)
    items = []
    for path in sorted(d.rglob("*")):
        if path.suffix not in (".md", ".tex"):
            continue
        rel = path.relative_to(d)
        parts = rel.parts
        folder = "/".join(parts[:-1]) if len(parts) > 1 else ""
        text = path.read_text(encoding="utf-8", errors="replace")
        items.append({
            "name": path.name,
            "path": str(rel),      # relative path from documents/ root
            "folder": folder,       # "" for root-level files
            "title": _title(text, path.stem),
            "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "size": path.stat().st_size,
        })
    # Sort: newest first within each folder (date-prefixed names sort lexically)
    items.sort(key=lambda it: (it["folder"], it["name"]), reverse=True)
    return items


def read_document(repo_root: Path, rel_path: str) -> str | None:
    if not _NAME_RE.match(rel_path):
        return None
    path = documents_dir(repo_root) / rel_path
    # Prevent path traversal
    try:
        path.resolve().relative_to(documents_dir(repo_root).resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def report_path(repo_root: Path, date_str: str) -> Path:
    return documents_dir(repo_root) / f"{date_str}.md"


def write_or_append_report(repo_root: Path, date_str: str, section: str) -> Path:
    """Create today's report, or append a new timestamped section if it exists."""
    path = report_path(repo_root, date_str)
    if path.is_file():
        body = path.read_text(encoding="utf-8", errors="replace").rstrip()
        body += "\n\n---\n\n" + section.strip() + "\n"
    else:
        body = f"# Daily Report — {date_str}\n\n" + section.strip() + "\n"
    path.write_text(body, encoding="utf-8")
    return path


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return fallback
