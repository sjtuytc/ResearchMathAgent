"""Per-question literature tracking: paper index + inline notes."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .agent import AgentEvent


def _lit_dir(repo_root: Path, qid: str) -> Path:
    d = repo_root / "documents" / "questions" / qid / "literature"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(repo_root: Path, qid: str) -> Path:
    return _lit_dir(repo_root, qid) / "index.json"


def load_index(repo_root: Path, qid: str) -> list[dict]:
    p = _index_path(repo_root, qid)
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_index(repo_root: Path, qid: str, papers: list[dict]) -> None:
    _index_path(repo_root, qid).write_text(
        json.dumps(papers, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _paper_id(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()[:10]


def add_paper(
    repo_root: Path,
    qid: str,
    *,
    url: str,
    title: str,
    authors: list[str] | None = None,
    year: int | None = None,
    abstract: str = "",
    tags: list[str] | None = None,
    relevance: str = "medium",
    notes: str = "",
    added_by: str = "human",
) -> dict:
    papers = load_index(repo_root, qid)
    pid = _paper_id(url)
    existing = next((p for p in papers if p["id"] == pid), None)
    if existing:
        return existing
    entry: dict = {
        "id": pid,
        "url": url,
        "title": title,
        "authors": authors or [],
        "year": year,
        "abstract": abstract,
        "tags": tags or [],
        "relevance": relevance,
        "notes": notes,
        "added_by": added_by,
        "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    papers.append(entry)
    _save_index(repo_root, qid, papers)
    return entry


def update_paper(repo_root: Path, qid: str, paper_id: str, **kwargs) -> dict | None:
    papers = load_index(repo_root, qid)
    for p in papers:
        if p["id"] == paper_id:
            allowed = {"title", "authors", "year", "abstract", "tags", "relevance", "notes", "url"}
            for k, v in kwargs.items():
                if k in allowed:
                    p[k] = v
            if "notes" in kwargs:
                p["notes_updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _save_index(repo_root, qid, papers)
            return p
    return None


def delete_paper(repo_root: Path, qid: str, paper_id: str) -> bool:
    papers = load_index(repo_root, qid)
    new = [p for p in papers if p["id"] != paper_id]
    if len(new) == len(papers):
        return False
    _save_index(repo_root, qid, new)
    return True


# ── Agent-driven discovery ──────────────────────────────────────────────────

_DISCOVER_SYSTEM = (
    "You are a mathematical literature researcher. Given a research-level math problem, "
    "identify the most important papers a researcher would need to read to tackle it. "
    "Focus on papers that contain key techniques, foundational results, or recent progress "
    "directly relevant to the specific mathematical objects in the problem. "
    "Be precise and mathematically informed."
)

_DISCOVER_PROMPT = """\
Problem ID: {qid}
Title: {title}

Problem statement (LaTeX):
{problem_tex}

Identify 6-10 papers essential for tackling this problem. Include: seminal foundational works, \
papers introducing key techniques used in the solution area, and any recent progress papers.

Return ONLY valid JSON — no markdown fences, no explanation outside the JSON array:
[
  {{
    "url": "https://arxiv.org/abs/XXXX.XXXXX",
    "title": "Full paper title",
    "authors": ["Surname, Firstname", "..."],
    "year": YYYY,
    "abstract": "2-3 sentence summary of what this paper proves/introduces",
    "tags": ["key technique", "foundational", "recent progress"],
    "relevance": "high",
    "notes": "2-3 sentences explaining exactly how this paper is useful for our specific problem — which lemma/technique/result we would borrow"
  }}
]
Relevance must be one of: high, medium, low. Order papers by relevance descending.
"""


def _call_claude_json(prompt: str, system: str, model: str = "claude-sonnet-4-6") -> str | None:
    binary = shutil.which("claude")
    if not binary:
        return None
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    cmd = [binary, "-p", prompt, "--output-format", "json", "--model", model,
           "--no-session-persistence", "--append-system-prompt", system]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
        if r.returncode != 0:
            return None
        obj = json.loads(r.stdout)
        return obj.get("result") or obj.get("text") or ""
    except Exception:
        return None


def ensure_all_lit(repo_root: Path, q_titles: dict | None = None) -> None:
    """Background: discover literature for any question missing a paper index."""
    for i in range(1, 11):
        qid = f"q{i}"
        if load_index(repo_root, qid):
            continue
        title = (q_titles or {}).get(qid, qid)
        for _ in discover_literature(repo_root, qid, title):
            pass


def discover_literature(repo_root: Path, qid: str, title: str) -> Iterator[AgentEvent]:
    """Call Claude to discover relevant papers, save them, yield AgentEvents."""
    problem_path = repo_root / "problems" / f"{qid}.tex"
    if not problem_path.is_file():
        yield AgentEvent("error", {"message": f"Problem file not found: {qid}.tex"})
        yield AgentEvent("done", {"reason": "error"})
        return

    yield AgentEvent("status", {"state": "running", "message": "Asking Claude to identify relevant literature…"})

    problem_tex = problem_path.read_text(encoding="utf-8", errors="replace")[:5000]
    prompt = _DISCOVER_PROMPT.format(qid=qid, title=title, problem_tex=problem_tex)
    raw = _call_claude_json(prompt, _DISCOVER_SYSTEM)

    if not raw:
        yield AgentEvent("error", {"message": "Claude returned no response."})
        yield AgentEvent("done", {"reason": "error"})
        return

    # Extract JSON array from response
    import re
    raw = raw.strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        raw = m.group(0)

    try:
        papers = json.loads(raw)
    except Exception:
        yield AgentEvent("error", {"message": f"Could not parse JSON response: {raw[:300]}"})
        yield AgentEvent("done", {"reason": "error"})
        return

    added = []
    for p in papers:
        if not isinstance(p, dict) or not p.get("url") or not p.get("title"):
            continue
        entry = add_paper(
            repo_root, qid,
            url=p.get("url", ""),
            title=p.get("title", ""),
            authors=p.get("authors", []),
            year=p.get("year"),
            abstract=p.get("abstract", ""),
            tags=p.get("tags", []),
            relevance=p.get("relevance", "medium"),
            notes=p.get("notes", ""),
            added_by="discovery-agent",
        )
        added.append(entry)
        yield AgentEvent("text_delta", {"text": f"+ {entry['title']} ({entry.get('year','')})\n"})

    yield AgentEvent("done", {"reason": "end_turn", "added": len(added), "papers": added})
