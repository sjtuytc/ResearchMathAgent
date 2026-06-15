"""Multi-agent GitHub-style issue tracker.

Each question (q1..q10) can have many issues. Each issue has a thread of
comments posted by humans or named agents. Agents can open issues, propose
plans, respond to each other, and mark issues resolved — enabling async
multi-agent coordination over a shared problem.

Storage layout:
  webapp/issues/{problem_id}/{issue_id}.json

Issue JSON schema:
  {
    "id": "q1-1",
    "problem_id": "q1",
    "title": "...",
    "status": "open" | "in_progress" | "resolved",
    "labels": ["plan", "blocker", ...],
    "created_at": "ISO",
    "created_by": "human" | "<agent name>",
    "comments": [
      {"id": "c1", "author": "human"|"<agent>", "role": "human"|"agent",
       "body": "...", "created_at": "ISO"}
    ]
  }
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

_TITLE_RE = re.compile(r"\\title\{([^}]*)\}")
_AUTHOR_RE = re.compile(r"\\author\{([^}]*)\}")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _issues_dir(repo_root: Path, problem_id: str) -> Path:
    d = repo_root / "webapp" / "issues" / problem_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _short_id(problem_id: str, existing: list[dict]) -> str:
    nums = [int(re.search(r"\d+$", i["id"]).group()) for i in existing if re.search(r"\d+$", i["id"])]
    n = max(nums, default=0) + 1
    return f"{problem_id}-{n}"


# ── list / get ──────────────────────────────────────────────────────────────

def list_issues(repo_root: Path, problem_id: str) -> list[dict]:
    d = _issues_dir(repo_root, problem_id)
    issues = []
    for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            issues.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    # Seed a default issue if none exist (write directly, no recursion)
    if not issues:
        issue = _seed_issue_direct(repo_root, problem_id)
        issues.append(issue)
    return issues


def get_issue(repo_root: Path, problem_id: str, issue_id: str) -> dict | None:
    path = _issues_dir(repo_root, problem_id) / f"{issue_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── create / update ─────────────────────────────────────────────────────────

def create_issue(repo_root: Path, problem_id: str, title: str,
                 body: str = "", author: str = "human",
                 labels: list[str] | None = None) -> dict:
    d = _issues_dir(repo_root, problem_id)
    existing = [json.loads(f.read_text()) for f in d.glob("*.json") if f.is_file()]
    issue_id = _short_id(problem_id, existing)
    now = _now()
    issue = {
        "id": issue_id,
        "problem_id": problem_id,
        "title": title,
        "status": "open",
        "labels": labels or [],
        "created_at": now,
        "created_by": author,
        "comments": [],
    }
    if body.strip():
        issue["comments"].append({
            "id": f"c{uuid.uuid4().hex[:8]}",
            "author": author,
            "role": "agent" if author != "human" else "human",
            "body": body.strip(),
            "created_at": now,
        })
    _save(repo_root, problem_id, issue)
    return issue


def add_comment(repo_root: Path, problem_id: str, issue_id: str,
                author: str, body: str) -> dict | None:
    issue = get_issue(repo_root, problem_id, issue_id)
    if issue is None:
        return None
    now = _now()
    issue["comments"].append({
        "id": f"c{uuid.uuid4().hex[:8]}",
        "author": author,
        "role": "agent" if author != "human" else "human",
        "body": body.strip(),
        "created_at": now,
    })
    _save(repo_root, problem_id, issue)
    return issue


def update_issue(repo_root: Path, problem_id: str, issue_id: str,
                 **kwargs) -> dict | None:
    issue = get_issue(repo_root, problem_id, issue_id)
    if issue is None:
        return None
    for k in ("title", "status", "labels"):
        if k in kwargs:
            issue[k] = kwargs[k]
    _save(repo_root, problem_id, issue)
    return issue


# ── legacy: agent run log ───────────────────────────────────────────────────

def append_activity(repo_root: Path, problem_id: str, entry: str,
                    agent: str = "solver-agent") -> None:
    """Log a solver run as a comment on the first open issue (or create one)."""
    issues = list_issues(repo_root, problem_id)
    open_issues = [i for i in issues if i.get("status") != "resolved"]
    target = open_issues[0] if open_issues else issues[0]
    add_comment(repo_root, problem_id, target["id"], agent, entry)


# ── internal ────────────────────────────────────────────────────────────────

def _save(repo_root: Path, problem_id: str, issue: dict) -> None:
    path = _issues_dir(repo_root, problem_id) / f"{issue['id']}.json"
    path.write_text(json.dumps(issue, indent=2, ensure_ascii=False), encoding="utf-8")


def _seed_issue_direct(repo_root: Path, problem_id: str) -> dict:
    """Create and save the default seed issue without calling list_issues."""
    tex_path = repo_root / "problems" / f"{problem_id}.tex"
    title, author, area = "(untitled)", "(unknown)", "(unspecified)"
    if tex_path.is_file():
        text = tex_path.read_text(encoding="utf-8", errors="replace")
        m = _TITLE_RE.search(text)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
        m = _AUTHOR_RE.search(text)
        if m:
            author = re.sub(r"\s+", " ", m.group(1)).strip()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("%") and "—" in line:
                area = line.lstrip("% ").split("—", 1)[1].strip()
                break
    issue_id = f"{problem_id}-1"
    now = _now()
    body = (
        f"Produce a correct, rigorous, self-contained proof for `{problem_id}`.\n\n"
        f"**Area:** {area}  \n**Problem author:** {author}\n\n"
        "Agents should post sub-lemma proposals, proof sketches, or blockers as "
        "comments. When a complete proof is agreed upon, mark this issue resolved."
    )
    issue = {
        "id": issue_id,
        "problem_id": problem_id,
        "title": f"Proof of {problem_id}: {title}",
        "status": "open",
        "labels": ["proof-task"],
        "created_at": now,
        "created_by": "system",
        "comments": [{
            "id": f"c{uuid.uuid4().hex[:8]}",
            "author": "system",
            "role": "agent",
            "body": body,
            "created_at": now,
        }],
    }
    _save(repo_root, problem_id, issue)
    return issue


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
