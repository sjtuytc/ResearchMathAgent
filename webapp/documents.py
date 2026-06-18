"""Documents store for the Research Math Agent web app.

Holds the daily reports written by the autonomous daily worker (and any other
documents). The web UI surfaces these under a Documents tab. Reports live in
the repo-level ``documents/`` directory. All new files are written as .tex;
legacy .md files are still readable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

# Allow .tex for new writes; still read .md for backwards compat
_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+\.(tex|md)$")


def documents_dir(repo_root: Path) -> Path:
    d = repo_root / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_documents(repo_root: Path) -> list[dict]:
    """Return all .tex and .md files under documents/, recursively.

    When both overview.tex and overview.md exist, only .tex is returned.
    """
    d = documents_dir(repo_root)
    items = []
    seen_stems: set[str] = set()  # (folder, stem) pairs already added as .tex

    # First pass: collect .tex files
    for path in sorted(d.rglob("*.tex")):
        rel = path.relative_to(d)
        parts = rel.parts
        folder = "/".join(parts[:-1]) if len(parts) > 1 else ""
        key = (folder, path.stem)
        seen_stems.add(key)
        text = path.read_text(encoding="utf-8", errors="replace")
        items.append({
            "name": path.name,
            "path": str(rel),
            "folder": folder,
            "title": _title(text, path.stem),
            "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "size": path.stat().st_size,
        })

    # Second pass: .md files only if no .tex counterpart exists
    for path in sorted(d.rglob("*.md")):
        rel = path.relative_to(d)
        parts = rel.parts
        folder = "/".join(parts[:-1]) if len(parts) > 1 else ""
        key = (folder, path.stem)
        if key in seen_stems:
            continue  # .tex version already listed
        text = path.read_text(encoding="utf-8", errors="replace")
        items.append({
            "name": path.name,
            "path": str(rel),
            "folder": folder,
            "title": _title(text, path.stem),
            "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "size": path.stat().st_size,
        })

    items.sort(key=lambda it: (it["folder"], it["name"]), reverse=True)
    return items


def read_document(repo_root: Path, rel_path: str) -> str | None:
    if not _NAME_RE.match(rel_path):
        return None
    path = documents_dir(repo_root) / rel_path
    try:
        path.resolve().relative_to(documents_dir(repo_root).resolve())
    except ValueError:
        return None
    if not path.is_file():
        # Try the other extension as fallback
        alt_ext = ".md" if rel_path.endswith(".tex") else ".tex"
        alt_path = documents_dir(repo_root) / (rel_path[:-len(rel_path.split(".")[-1])-1] + alt_ext)
        if alt_path.is_file():
            return alt_path.read_text(encoding="utf-8", errors="replace")
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def report_path(repo_root: Path, date_str: str) -> Path:
    return documents_dir(repo_root) / f"{date_str}.tex"


def write_or_append_report(repo_root: Path, date_str: str, section: str) -> Path:
    """Create or append to today's LaTeX report."""
    path = report_path(repo_root, date_str)
    # Also check if a legacy .md report exists
    md_path = documents_dir(repo_root) / f"{date_str}.md"

    if path.is_file():
        body = path.read_text(encoding="utf-8", errors="replace").rstrip()
        body += "\n\n\\clearpage\n\n" + _ensure_tex_section(section) + "\n"
    elif md_path.is_file():
        # Migrate legacy .md to .tex on first append
        from webapp.doc_bundle import _md_to_tex  # lazy to avoid circular
        old_content = _md_to_tex(md_path.read_text(encoding="utf-8", errors="replace"))
        body = old_content.rstrip() + "\n\n\\clearpage\n\n" + _ensure_tex_section(section) + "\n"
    else:
        body = (
            f"% Auto-generated daily report\n"
            f"\\section*{{Daily Report --- {date_str}}}\n\n"
            + _ensure_tex_section(section)
            + "\n"
        )
    path.write_text(body, encoding="utf-8")
    return path


def _ensure_tex_section(section: str) -> str:
    """If section looks like markdown, convert it; otherwise pass through."""
    if section.strip().startswith("#") or "**" in section or "---" in section[:200]:
        try:
            from webapp.doc_bundle import _md_to_tex
            return _md_to_tex(section)
        except Exception:
            pass
    return section


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        # LaTeX section titles
        m = re.match(r"\\(?:section|subsection|subsubsection)\*?\{(.+?)\}", line)
        if m:
            return m.group(1).strip()
        # Markdown titles (legacy)
        if line.startswith("# "):
            return line[2:].strip()
    return fallback
