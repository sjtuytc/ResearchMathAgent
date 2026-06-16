"""GitHub Issues agentic API layer.

Wraps the GitHub REST API so that many AI agents can fully control issues
on the ResearchMathAgent repository.  All write operations require a
``GITHUB_TOKEN`` environment variable (classic or fine-grained PAT with
Issues read/write permission).  Read operations work unauthenticated but
are rate-limited to 60 req/hr; set the token to raise that to 5 000.

Convention: every issue that belongs to a benchmark problem is tagged with
the label ``problem:<pid>`` (e.g. ``problem:q1``).  The helpers create
these labels automatically if they are missing.
"""

from __future__ import annotations

import os
from typing import Any

import requests

REPO = "sjtuytc/ResearchMathAgent"
_BASE = "https://api.github.com"
_LABEL_COLOR = "0075ca"  # GitHub blue


# ── Auth / session ────────────────────────────────────────────────────────────

def _headers(token: str | None = None) -> dict[str, str]:
    tok = token or os.environ.get("GITHUB_TOKEN", "")
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _get(path: str, params: dict | None = None, token: str | None = None) -> Any:
    r = requests.get(f"{_BASE}{path}", headers=_headers(token), params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict, token: str | None = None) -> Any:
    r = requests.post(f"{_BASE}{path}", headers=_headers(token), json=body, timeout=20)
    r.raise_for_status()
    return r.json()


def _patch(path: str, body: dict, token: str | None = None) -> Any:
    r = requests.patch(f"{_BASE}{path}", headers=_headers(token), json=body, timeout=20)
    r.raise_for_status()
    return r.json()


# ── Label helpers ─────────────────────────────────────────────────────────────

def _problem_label(problem_id: str) -> str:
    return f"problem:{problem_id}"


def _ensure_label(problem_id: str, token: str | None = None) -> None:
    """Create the problem:<pid> label if it doesn't exist yet."""
    label = _problem_label(problem_id)
    try:
        _get(f"/repos/{REPO}/labels/{requests.utils.quote(label)}", token=token)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            try:
                _post(f"/repos/{REPO}/labels", {
                    "name": label,
                    "color": _LABEL_COLOR,
                    "description": f"Issues for benchmark problem {problem_id}",
                }, token=token)
            except Exception:
                pass  # label creation is best-effort


# ── Issue formatting ──────────────────────────────────────────────────────────

def _fmt_issue(raw: dict, comments: list[dict] | None = None) -> dict:
    """Convert a GitHub API issue object to our internal schema."""
    labels = [lb["name"] for lb in raw.get("labels", [])]
    problem_id = ""
    for lb in labels:
        if lb.startswith("problem:"):
            problem_id = lb[len("problem:"):]
            break
    non_problem_labels = [lb for lb in labels if not lb.startswith("problem:")]

    gh_state = raw.get("state", "open")
    if gh_state == "closed":
        status = "resolved"
    elif any(lb in non_problem_labels for lb in ("in-progress", "in_progress")):
        status = "in_progress"
    else:
        status = "open"

    fmt: dict = {
        "id": str(raw["number"]),
        "gh_number": raw["number"],
        "problem_id": problem_id,
        "title": raw.get("title", ""),
        "body": raw.get("body") or "",
        "status": status,
        "gh_state": gh_state,
        "labels": non_problem_labels,
        "created_at": raw.get("created_at", ""),
        "updated_at": raw.get("updated_at", ""),
        "created_by": (raw.get("user") or {}).get("login", ""),
        "html_url": raw.get("html_url", ""),
        "comments_count": raw.get("comments", 0),
    }
    if comments is not None:
        fmt["comments"] = [_fmt_comment(c) for c in comments]
    return fmt


def _fmt_comment(raw: dict) -> dict:
    return {
        "id": str(raw["id"]),
        "author": (raw.get("user") or {}).get("login", ""),
        "body": raw.get("body") or "",
        "created_at": raw.get("created_at", ""),
        "updated_at": raw.get("updated_at", ""),
        "html_url": raw.get("html_url", ""),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def list_issues(problem_id: str | None = None,
                state: str = "open",
                per_page: int = 50,
                page: int = 1,
                token: str | None = None) -> list[dict]:
    """List GitHub issues, optionally filtered by problem_id label."""
    params: dict = {"state": state, "per_page": per_page, "page": page}
    if problem_id:
        params["labels"] = _problem_label(problem_id)
    raw = _get(f"/repos/{REPO}/issues", params=params, token=token)
    return [_fmt_issue(r) for r in raw if "pull_request" not in r]


def get_issue(issue_number: int, include_comments: bool = True,
              token: str | None = None) -> dict:
    """Get a single issue, optionally with all comments."""
    raw = _get(f"/repos/{REPO}/issues/{issue_number}", token=token)
    comments = None
    if include_comments and raw.get("comments", 0) > 0:
        comments = _get(f"/repos/{REPO}/issues/{issue_number}/comments",
                        params={"per_page": 100}, token=token)
    return _fmt_issue(raw, comments)


def create_issue(problem_id: str, title: str, body: str = "",
                 labels: list[str] | None = None,
                 token: str | None = None) -> dict:
    """Create a new GitHub issue tagged with problem:<pid>."""
    _ensure_label(problem_id, token)
    all_labels = [_problem_label(problem_id)] + (labels or [])
    raw = _post(f"/repos/{REPO}/issues", {
        "title": title,
        "body": body,
        "labels": all_labels,
    }, token=token)
    return _fmt_issue(raw)


def add_comment(issue_number: int, body: str,
                token: str | None = None) -> dict:
    """Post a comment on an existing issue."""
    raw = _post(f"/repos/{REPO}/issues/{issue_number}/comments",
                {"body": body}, token=token)
    return _fmt_comment(raw)


def update_issue(issue_number: int,
                 title: str | None = None,
                 state: str | None = None,
                 labels: list[str] | None = None,
                 body: str | None = None,
                 token: str | None = None) -> dict:
    """Update issue title, state (open/closed), labels, or body."""
    payload: dict = {}
    if title is not None:
        payload["title"] = title
    if state is not None:
        payload["state"] = state  # "open" or "closed"
    if labels is not None:
        payload["labels"] = labels
    if body is not None:
        payload["body"] = body
    raw = _patch(f"/repos/{REPO}/issues/{issue_number}", payload, token=token)
    return _fmt_issue(raw)


def close_issue(issue_number: int, token: str | None = None) -> dict:
    """Close an issue (marks it resolved)."""
    return update_issue(issue_number, state="closed", token=token)


def reopen_issue(issue_number: int, token: str | None = None) -> dict:
    """Reopen a closed issue."""
    return update_issue(issue_number, state="open", token=token)


def search_issues(query: str, per_page: int = 30,
                  token: str | None = None) -> list[dict]:
    """Search issues using GitHub search syntax.

    Example query: ``q1 in:title label:problem:q1 repo:sjtuytc/ResearchMathAgent``
    """
    full_query = f"{query} repo:{REPO} is:issue"
    raw = _get("/search/issues", params={"q": full_query, "per_page": per_page},
               token=token)
    return [_fmt_issue(r) for r in raw.get("items", [])]


def token_available() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN"))
