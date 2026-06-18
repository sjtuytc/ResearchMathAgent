"""Proof version history — records each mutation of working_solution.tex.

Storage layout:
  webapp/proof_history/{problem_id}/
    history.jsonl   — append-only log of version metadata
    v0001.tex       — full content of each version

Each JSONL entry:
  {
    "version": 1,
    "timestamp": "ISO",
    "problem_id": "q6",
    "issue_id": "q6-3" | null,
    "issue_title": "..." | null,
    "agent": "solver-agent" | "hero" | "human" | null,
    "chars_before": 4200,
    "chars_after": 5800,
    "lines_before": 80,
    "lines_after": 120,
    "sha": "first 12 hex chars of sha256",
    "tex_file": "v0001.tex"
  }
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _history_dir(repo_root: Path, problem_id: str) -> Path:
    d = repo_root / "webapp" / "proof_history" / problem_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha(tex: str) -> str:
    return hashlib.sha256(tex.encode("utf-8")).hexdigest()[:12]


def _current_version(d: Path) -> int:
    hf = d / "history.jsonl"
    if not hf.is_file():
        return 0
    count = 0
    for line in hf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            count += 1
    return count


def record_proof_version(
    repo_root: Path,
    problem_id: str,
    new_tex: str,
    old_tex: str | None = None,
    issue_id: str | None = None,
    issue_title: str | None = None,
    agent: str | None = None,
) -> dict:
    """Append a new version to the history. Returns the version metadata dict."""
    d = _history_dir(repo_root, problem_id)
    version = _current_version(d) + 1
    sha = _sha(new_tex)

    # Don't record if content identical to previous
    if version > 1:
        prev_file = d / f"v{(version-1):04d}.tex"
        if prev_file.is_file():
            if _sha(prev_file.read_text(encoding="utf-8")) == sha:
                # Same content — skip
                prev_meta = list_proof_history(repo_root, problem_id)
                return prev_meta[-1] if prev_meta else {}

    tex_filename = f"v{version:04d}.tex"
    (d / tex_filename).write_text(new_tex, encoding="utf-8")

    old_chars = len(old_tex) if old_tex is not None else 0
    old_lines = old_tex.count("\n") if old_tex is not None else 0

    entry = {
        "version": version,
        "timestamp": _now(),
        "problem_id": problem_id,
        "issue_id": issue_id,
        "issue_title": issue_title,
        "agent": agent,
        "chars_before": old_chars,
        "chars_after": len(new_tex),
        "lines_before": old_lines,
        "lines_after": new_tex.count("\n"),
        "sha": sha,
        "tex_file": tex_filename,
    }

    hf = d / "history.jsonl"
    with hf.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def list_proof_history(repo_root: Path, problem_id: str) -> list[dict]:
    """Return all version entries, oldest first."""
    d = _history_dir(repo_root, problem_id)
    hf = d / "history.jsonl"
    if not hf.is_file():
        return []
    results = []
    for line in hf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                results.append(json.loads(line))
            except Exception:
                pass
    return results


def get_proof_version_tex(repo_root: Path, problem_id: str, version: int) -> str | None:
    d = _history_dir(repo_root, problem_id)
    tf = d / f"v{version:04d}.tex"
    if tf.is_file():
        return tf.read_text(encoding="utf-8", errors="replace")
    return None


def simple_diff_stats(old_tex: str, new_tex: str) -> dict:
    """Return a coarse line-level diff summary."""
    old_lines = set(old_tex.splitlines())
    new_lines = set(new_tex.splitlines())
    added = len(new_lines - old_lines)
    removed = len(old_lines - new_lines)
    return {"added": added, "removed": removed, "changed": added + removed}
