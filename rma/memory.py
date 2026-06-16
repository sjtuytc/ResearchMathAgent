"""Strategy memory for ResearchMathAgent.

Appends one JSONL record per proof attempt and surfaces relevant history
as a formatted string for injection into model prompts. Inspired by the
experiment-memory idea from Karpathy's autoresearch.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

MEMORY_FILE_NAME = "strategy_memory.jsonl"
_DEFAULT_LIMIT = 8


def record_attempt(
    documents_dir: Path,
    problem_id: str,
    problem_area: str,
    strategy_summary: str,
    outcome: str,  # "success" | "partial" | "fail" | "screened_out"
    issue_count: int,
    model: str = "",
    notes: str = "",
) -> None:
    documents_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "problem_id": problem_id,
        "problem_area": problem_area,
        "strategy": strategy_summary[:400],
        "outcome": outcome,
        "issue_count": issue_count,
        "model": model,
        "notes": notes[:200],
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    memory_file = documents_dir / MEMORY_FILE_NAME
    with memory_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def query_memory(
    documents_dir: Path,
    problem_id: str | None = None,
    problem_area: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[dict]:
    memory_file = documents_dir / MEMORY_FILE_NAME
    if not memory_file.is_file():
        return []
    entries: list[dict] = []
    for line in memory_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if problem_id and entry.get("problem_id") != problem_id:
            continue
        if problem_area and problem_area.lower() not in entry.get("problem_area", "").lower():
            continue
        entries.append(entry)
    # most recent first
    return list(reversed(entries[-limit:]))


def format_memory_context(entries: list[dict]) -> str:
    if not entries:
        return ""
    lines = ["### Past proof attempts for this problem (most recent first)", ""]
    for e in entries:
        tag = f"[{e['outcome'].upper()}]"
        lines.append(f"- {tag} {e['date']} | strategy: {e['strategy']}")
        if e.get("issue_count"):
            lines.append(f"  verifier issues: {e['issue_count']}")
        if e.get("notes"):
            lines.append(f"  notes: {e['notes']}")
    lines += [
        "",
        "Avoid repeating strategies that have consistently failed. "
        "Build on approaches that produced fewer issues.",
        "",
    ]
    return "\n".join(lines)
