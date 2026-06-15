"""Per-question issue tracker, in the spirit of TheAgentCompany's task issues.

Each benchmark question (q1..q10) gets a markdown "issue" under webapp/issues/
that tracks its area, source, status, notes, and a log of agent runs. These are
*not* solutions — they are trackers — so they are safe to keep and edit. The web
UI shows each question's file alongside its issue.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

ISSUES_DIRNAME = "issues"
_TITLE_RE = re.compile(r"\\title\{([^}]*)\}")
_AUTHOR_RE = re.compile(r"\\author\{([^}]*)\}")


def issues_dir(repo_root: Path) -> Path:
    d = repo_root / "webapp" / ISSUES_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_issue(repo_root: Path, problem_id: str) -> str:
    path = issues_dir(repo_root) / f"{problem_id}.md"
    if not path.is_file():
        body = _seed(repo_root, problem_id)
        path.write_text(body, encoding="utf-8")
    return path.read_text(encoding="utf-8", errors="replace")


def save_issue(repo_root: Path, problem_id: str, markdown: str) -> None:
    path = issues_dir(repo_root) / f"{problem_id}.md"
    path.write_text(markdown, encoding="utf-8")


def append_activity(repo_root: Path, problem_id: str, entry: str) -> None:
    body = get_issue(repo_root, problem_id)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = body.rstrip() + f"\n\n### Run — {stamp}\n{entry.strip()}\n"
    save_issue(repo_root, problem_id, body)


def _seed(repo_root: Path, problem_id: str) -> str:
    tex_path = repo_root / "problems" / f"{problem_id}.tex"
    title, author, area = "(untitled)", "(unknown)", "(unspecified)"
    if tex_path.is_file():
        text = tex_path.read_text(encoding="utf-8", errors="replace")
        m = _TITLE_RE.search(text)
        if m:
            title = _clean(m.group(1))
        m = _AUTHOR_RE.search(text)
        if m:
            author = _clean(m.group(1))
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("%") and "—" in line:
                area = line.lstrip("% ").split("—", 1)[1].strip()
                break
    return f"""# Issue: {title}

- **Question:** {problem_id}
- **Area:** {area}
- **Author:** {author}
- **Status:** open
- **Difficulty:** research-level

## Task
Produce a correct, rigorous, self-contained proof or solution to question \
`{problem_id}`. See the Question tab for the full statement.

## Notes
_Track approaches, sub-lemmas, and blockers here._

## Activity
_Agent runs are logged below._
"""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
