"""Persistent per-question TODO items.

Auto-generated TODOs are computed dynamically by the frontend from the
question summary data. This module handles only user-created (persistent)
TODO items that survive page refreshes.

Storage: webapp/todos/{problem_id}.json
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _todos_path(repo_root: Path, problem_id: str) -> Path:
    d = repo_root / "webapp" / "todos"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{problem_id}.json"


def _load(repo_root: Path, problem_id: str) -> list[dict]:
    p = _todos_path(repo_root, problem_id)
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(repo_root: Path, problem_id: str, items: list[dict]) -> None:
    _todos_path(repo_root, problem_id).write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_todos(repo_root: Path, problem_id: str) -> list[dict]:
    return _load(repo_root, problem_id)


def create_todo(
    repo_root: Path,
    problem_id: str,
    title: str,
    priority: str = "medium",
    note: str = "",
    action_tab: str = "",
    action_target: str = "",
) -> dict:
    items = _load(repo_root, problem_id)
    todo: dict = {
        "id": f"t{uuid.uuid4().hex[:8]}",
        "problem_id": problem_id,
        "title": title,
        "priority": priority,
        "note": note,
        "status": "pending",
        "action_tab": action_tab,
        "action_target": action_target,
        "created_at": _now(),
        "done_at": None,
    }
    items.append(todo)
    _save(repo_root, problem_id, items)
    return todo


def update_todo(
    repo_root: Path,
    problem_id: str,
    todo_id: str,
    **kwargs: object,
) -> dict | None:
    items = _load(repo_root, problem_id)
    for item in items:
        if item["id"] == todo_id:
            for k in ("title", "priority", "note", "status", "action_tab", "action_target"):
                if k in kwargs:
                    item[k] = kwargs[k]
            if kwargs.get("status") == "done" and not item.get("done_at"):
                item["done_at"] = _now()
            elif kwargs.get("status") == "pending":
                item["done_at"] = None
            _save(repo_root, problem_id, items)
            return item
    return None


def delete_todo(repo_root: Path, problem_id: str, todo_id: str) -> bool:
    items = _load(repo_root, problem_id)
    new = [i for i in items if i["id"] != todo_id]
    if len(new) == len(items):
        return False
    _save(repo_root, problem_id, new)
    return True
