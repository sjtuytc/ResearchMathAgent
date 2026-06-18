"""Per-question prefix entries — ordered context blocks injected into every agent prompt."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

_TYPES = {"theorem", "paper", "background", "definition", "strategy", "note"}


def _prefix_path(repo_root: Path, problem_id: str) -> Path:
    d = repo_root / "webapp" / "prefix"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{problem_id}.json"


def load_prefix(repo_root: Path, problem_id: str) -> list[dict]:
    p = _prefix_path(repo_root, problem_id)
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("entries", [])
    except Exception:
        return []


def save_prefix(repo_root: Path, problem_id: str, entries: list[dict]) -> None:
    _prefix_path(repo_root, problem_id).write_text(
        json.dumps({"entries": entries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_entry(
    repo_root: Path,
    problem_id: str,
    *,
    type: str = "background",
    title: str,
    content: str,
    enabled: bool = True,
) -> dict:
    entries = load_prefix(repo_root, problem_id)
    entry = {
        "id": f"{problem_id}-pfx-{uuid.uuid4().hex[:8]}",
        "type": type if type in _TYPES else "background",
        "title": title.strip(),
        "content": content.strip(),
        "enabled": bool(enabled),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    entries.append(entry)
    save_prefix(repo_root, problem_id, entries)
    return entry


def update_entry(
    repo_root: Path,
    problem_id: str,
    entry_id: str,
    patch: dict,
) -> dict | None:
    entries = load_prefix(repo_root, problem_id)
    for e in entries:
        if e["id"] == entry_id:
            if "type" in patch and patch["type"] in _TYPES:
                e["type"] = patch["type"]
            if "title" in patch:
                e["title"] = str(patch["title"]).strip()
            if "content" in patch:
                e["content"] = str(patch["content"]).strip()
            if "enabled" in patch:
                e["enabled"] = bool(patch["enabled"])
            if "order" in patch:
                # move to position
                entries.remove(e)
                pos = max(0, min(int(patch["order"]), len(entries)))
                entries.insert(pos, e)
            save_prefix(repo_root, problem_id, entries)
            return e
    return None


def delete_entry(repo_root: Path, problem_id: str, entry_id: str) -> bool:
    entries = load_prefix(repo_root, problem_id)
    new = [e for e in entries if e["id"] != entry_id]
    if len(new) == len(entries):
        return False
    save_prefix(repo_root, problem_id, new)
    return True


def reorder_entries(repo_root: Path, problem_id: str, ordered_ids: list[str]) -> list[dict]:
    entries = load_prefix(repo_root, problem_id)
    by_id = {e["id"]: e for e in entries}
    reordered = [by_id[i] for i in ordered_ids if i in by_id]
    # append any that weren't in the ordered_ids list (shouldn't happen but safe)
    seen = set(ordered_ids)
    reordered += [e for e in entries if e["id"] not in seen]
    save_prefix(repo_root, problem_id, reordered)
    return reordered


def build_prefix_md(repo_root: Path, problem_id: str) -> str:
    """Render all enabled entries as a markdown document for agent injection."""
    entries = [e for e in load_prefix(repo_root, problem_id) if e.get("enabled", True)]
    if not entries:
        return ""
    lines = [f"# Context Prefix for {problem_id.upper()}\n"]
    lines.append("The following background context has been curated for this problem.\n")
    for e in entries:
        label = e.get("type", "note").capitalize()
        lines.append(f"## [{label}] {e['title']}\n")
        lines.append(e.get("content", "").strip())
        lines.append("")
    return "\n".join(lines)
