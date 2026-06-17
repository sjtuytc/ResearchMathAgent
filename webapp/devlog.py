"""Development log — append-only record of website changes."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_LOG_PATH_REL = "webapp/devlog.jsonl"


def _log_path(repo_root: Path) -> Path:
    return repo_root / _LOG_PATH_REL


def append_entry(
    repo_root: Path,
    *,
    title: str,
    description: str,
    files_changed: list[str] | None = None,
    signature: str = "background engineer",
) -> dict:
    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": title,
        "description": description,
        "files_changed": files_changed or [],
        "signature": signature,
    }
    path = _log_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_log(repo_root: Path) -> list[dict]:
    path = _log_path(repo_root)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(entries))  # newest first
