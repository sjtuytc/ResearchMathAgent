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


def _issues_dir(repo_root: Path, problem_id: str, dataset: str = "first_proof_1") -> Path:
    # New layout: webapp/issues/<dataset>/<problem_id>/
    # Legacy layout (dataset=first_proof_1): also check old path for back-compat
    new_path = repo_root / "webapp" / "issues" / dataset / problem_id
    if not new_path.exists() and dataset == "first_proof_1":
        old_path = repo_root / "webapp" / "issues" / problem_id
        if old_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
    new_path.mkdir(parents=True, exist_ok=True)
    return new_path


def _short_id(problem_id: str, existing: list[dict]) -> str:
    nums = [int(re.search(r"\d+$", i["id"]).group()) for i in existing if re.search(r"\d+$", i["id"])]
    n = max(nums, default=0) + 1
    return f"{problem_id}-{n}"


# ── list / get ──────────────────────────────────────────────────────────────

def list_issues(repo_root: Path, problem_id: str, dataset: str = "first_proof_1") -> list[dict]:
    d = _issues_dir(repo_root, problem_id, dataset)
    issues = []
    for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            issues.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    # Seed a default issue if none exist (write directly, no recursion)
    if not issues:
        issue = _seed_issue_direct(repo_root, problem_id, dataset)
        issues.append(issue)
    return issues


def get_issue(repo_root: Path, problem_id: str, issue_id: str, dataset: str = "first_proof_1") -> dict | None:
    path = _issues_dir(repo_root, problem_id, dataset) / f"{issue_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── event helpers ────────────────────────────────────────────────────────────

def _make_event(event_type: str, description: str, author: str = "system") -> dict:
    return {
        "id": f"ev{uuid.uuid4().hex[:8]}",
        "author": author,
        "role": "event",
        "event_type": event_type,
        "body": description,
        "created_at": _now(),
    }


# ── create / update ─────────────────────────────────────────────────────────

def create_issue(repo_root: Path, problem_id: str, title: str,
                 body: str = "", author: str = "human",
                 labels: list[str] | None = None,
                 dataset: str = "first_proof_1") -> dict:
    d = _issues_dir(repo_root, problem_id, dataset)
    existing = [json.loads(f.read_text()) for f in d.glob("*.json") if f.is_file()]
    issue_id = _short_id(problem_id, existing)
    now = _now()
    issue = {
        "id": issue_id,
        "problem_id": problem_id,
        "dataset": dataset,
        "title": title,
        "status": "open",
        "labels": labels or [],
        "created_at": now,
        "created_by": author,
        "comments": [_make_event("opened", f"Issue opened by **{author}**", author)],
    }
    if body.strip():
        issue["comments"].append({
            "id": f"c{uuid.uuid4().hex[:8]}",
            "author": author,
            "role": "agent" if author != "human" else "human",
            "body": body.strip(),
            "created_at": now,
        })
    _save(repo_root, problem_id, issue, dataset)
    return issue


def add_comment(repo_root: Path, problem_id: str, issue_id: str,
                author: str, body: str, dataset: str = "first_proof_1") -> dict | None:
    issue = get_issue(repo_root, problem_id, issue_id, dataset)
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
    _save(repo_root, problem_id, issue, dataset)
    return issue


def update_issue(repo_root: Path, problem_id: str, issue_id: str,
                 dataset: str = "first_proof_1", **kwargs) -> dict | None:
    issue = get_issue(repo_root, problem_id, issue_id, dataset)
    if issue is None:
        return None
    old_status = issue.get("status")
    for k in ("title", "status", "labels"):
        if k in kwargs:
            issue[k] = kwargs[k]
    if "status" in kwargs and kwargs["status"] != old_status:
        icon = {"open": "🔵", "in_progress": "🟡", "resolved": "✅"}.get(kwargs["status"], "⚪")
        issue["comments"].append(
            _make_event("status_changed", f"{icon} Status changed: **{old_status}** → **{kwargs['status']}**")
        )
    _save(repo_root, problem_id, issue, dataset)
    return issue


def log_event(
    repo_root: Path,
    problem_id: str,
    event_type: str,
    description: str,
    author: str = "system",
    dataset: str = "first_proof_1",
    issue_id: str | None = None,
) -> None:
    """Append a structured event to an issue's log. Uses first open issue if issue_id not given."""
    issues = list_issues(repo_root, problem_id, dataset)
    if issue_id:
        target = get_issue(repo_root, problem_id, issue_id, dataset)
        if target is None:
            target = issues[0] if issues else None
    else:
        open_issues = [i for i in issues if i.get("status") != "resolved"]
        target = open_issues[0] if open_issues else (issues[0] if issues else None)
    if target is None:
        return
    target.setdefault("comments", []).append(_make_event(event_type, description, author))
    _save(repo_root, problem_id, target, dataset)


def get_activity_log(
    repo_root: Path,
    problem_id: str,
    dataset: str = "first_proof_1",
    limit: int = 200,
) -> list[dict]:
    """Return all comments/events across all issues, sorted chronologically."""
    issues = list_issues(repo_root, problem_id, dataset)
    entries: list[dict] = []
    for iss in issues:
        for c in iss.get("comments", []):
            entries.append({**c, "issue_id": iss["id"], "issue_title": iss.get("title", "")})
    entries.sort(key=lambda e: e.get("created_at", ""))
    return entries[-limit:]


# ── legacy: agent run log ───────────────────────────────────────────────────

def append_activity(repo_root: Path, problem_id: str, entry: str,
                    agent: str = "solver-agent", dataset: str = "first_proof_1") -> None:
    """Log a solver run as a comment on the first open issue (or create one)."""
    issues = list_issues(repo_root, problem_id, dataset)
    open_issues = [i for i in issues if i.get("status") != "resolved"]
    target = open_issues[0] if open_issues else issues[0]
    add_comment(repo_root, problem_id, target["id"], agent, entry, dataset)


# ── internal ────────────────────────────────────────────────────────────────

def _save(repo_root: Path, problem_id: str, issue: dict, dataset: str = "first_proof_1") -> None:
    path = _issues_dir(repo_root, problem_id, dataset) / f"{issue['id']}.json"
    path.write_text(json.dumps(issue, indent=2, ensure_ascii=False), encoding="utf-8")


def _seed_issue_direct(repo_root: Path, problem_id: str, dataset: str = "first_proof_1") -> dict:
    """Create and save the default seed issue without calling list_issues."""
    title, author, area, statement = "(untitled)", "(unknown)", "(unspecified)", ""

    # Try dataset store first (works for all datasets)
    try:
        from .dataset_store import get_problem as _ds_get_problem
        rec = _ds_get_problem(dataset, problem_id)
        if rec:
            title = rec.get("title", problem_id) or problem_id
            statement = rec.get("statement", "") or ""
            tags = rec.get("tags", [])
            area = ", ".join(tags) if tags else area
    except Exception:
        pass

    # Fallback: read .tex for first_proof_1
    if not statement or dataset == "first_proof_1":
        tex_path = repo_root / "problems" / f"{problem_id}.tex"
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
            if not statement:
                statement = text.strip()

    issue_id = f"{problem_id}-1"
    now = _now()

    # Build body: include the actual problem statement
    stmt_block = f"\n\n**Problem statement:**\n{statement[:2000]}" if statement else ""
    body = (
        f"**Area:** {area}  \n**Problem author:** {author}{stmt_block}\n\n"
        "---\n"
        "Agents should post sub-lemma proposals, proof sketches, or blockers as "
        "comments. When a complete proof is agreed upon, mark this issue resolved."
    )
    issue = {
        "id": issue_id,
        "problem_id": problem_id,
        "title": f"Proof: {title}",
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
    _save(repo_root, problem_id, issue, dataset)
    return issue


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
