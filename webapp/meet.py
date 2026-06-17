"""Virtual meeting rooms for multi-agent mathematical discussions.

Each meeting room has a topic, a set of participants, a threaded message log,
a synthesized plan (created by the coordinator), and an execution log.

Storage layout:
  webapp/meets/{problem_id}/{room_id}.json
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ── Participant definitions ──────────────────────────────────────────────────

PERSONAS: dict[str, dict] = {
    "coordinator": {
        "color": "#f78166",
        "icon": "🎯",
        "role": "Meeting facilitator and plan synthesizer.",
        "style": "You keep the discussion focused, identify convergence, and produce clear action plans.",
    },
    "solver-agent": {
        "color": "#3fb950",
        "icon": "🔧",
        "role": "Mathematical proof strategist.",
        "style": "You propose concrete proof constructions, identify the right theorems to invoke, and sketch key steps.",
    },
    "critic-agent": {
        "color": "#ffa657",
        "icon": "🔍",
        "role": "Mathematical critic and devil's advocate.",
        "style": "You challenge assumptions, spot logical gaps, ask hard 'what if' questions, and force precision.",
    },
    "verifier-agent": {
        "color": "#d2a8ff",
        "icon": "✓",
        "role": "Mathematical verifier and correctness checker.",
        "style": "You check each claimed step rigorously, identify missing hypotheses, and flag circular reasoning.",
    },
    "human": {
        "color": "#58a6ff",
        "icon": "👤",
        "role": "Human researcher.",
        "style": "",
    },
}

DEFAULT_PARTICIPANTS = ["coordinator", "solver-agent", "critic-agent", "verifier-agent"]


# ── Storage helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meets_dir(repo_root: Path, problem_id: str) -> Path:
    d = repo_root / "webapp" / "meets" / problem_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(repo_root: Path, problem_id: str, room: dict) -> None:
    path = _meets_dir(repo_root, problem_id) / f"{room['id']}.json"
    path.write_text(json.dumps(room, indent=2, ensure_ascii=False), encoding="utf-8")


def _short_id(problem_id: str, existing: list[dict]) -> str:
    nums = []
    for r in existing:
        parts = r["id"].split("-")
        try:
            nums.append(int(parts[-1]))
        except (ValueError, IndexError):
            pass
    n = max(nums, default=0) + 1
    return f"{problem_id}-meet-{n}"


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_room(
    repo_root: Path,
    problem_id: str,
    topic: str,
    goal: str = "",
    participants: list[str] | None = None,
) -> dict:
    d = _meets_dir(repo_root, problem_id)
    existing = []
    for f in d.glob("*.json"):
        try:
            existing.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    room_id = _short_id(problem_id, existing)
    parts = participants or DEFAULT_PARTICIPANTS
    now = _now()
    room = {
        "id": room_id,
        "problem_id": problem_id,
        "topic": topic,
        "goal": goal or f"Agree on a concrete proof strategy for {problem_id}.",
        "participants": parts,
        "status": "open",
        "created_at": now,
        "messages": [{
            "id": f"m{uuid.uuid4().hex[:8]}",
            "author": "coordinator",
            "role": "event",
            "body": f"Meeting opened: **{topic}**",
            "created_at": now,
        }],
        "plan": None,
        "execution_log": [],
    }
    _save(repo_root, problem_id, room)
    return room


def get_room(repo_root: Path, problem_id: str, room_id: str) -> dict | None:
    path = _meets_dir(repo_root, problem_id) / f"{room_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_rooms(repo_root: Path, problem_id: str) -> list[dict]:
    d = _meets_dir(repo_root, problem_id)
    rooms = []
    for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            rooms.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return rooms


def post_message(
    repo_root: Path,
    problem_id: str,
    room_id: str,
    author: str,
    body: str,
    role: str | None = None,
    event_type: str | None = None,
) -> dict | None:
    room = get_room(repo_root, problem_id, room_id)
    if room is None:
        return None
    effective_role = role or ("human" if author == "human" else "agent")
    msg: dict = {
        "id": f"m{uuid.uuid4().hex[:8]}",
        "author": author,
        "role": effective_role,
        "body": body.strip(),
        "created_at": _now(),
    }
    if event_type:
        msg["event_type"] = event_type
    room["messages"].append(msg)
    _save(repo_root, problem_id, room)
    return room


def set_plan(
    repo_root: Path,
    problem_id: str,
    room_id: str,
    steps: list[dict],
    summary: str = "",
) -> dict | None:
    room = get_room(repo_root, problem_id, room_id)
    if room is None:
        return None
    room["plan"] = {
        "summary": summary,
        "steps": steps,
        "synthesized_at": _now(),
        "status": "pending",
        "executed_steps": [],
    }
    room["status"] = "planned"
    room["messages"].append({
        "id": f"m{uuid.uuid4().hex[:8]}",
        "author": "coordinator",
        "role": "event",
        "event_type": "plan_ready",
        "body": f"📋 **Plan synthesized** — {len(steps)} steps ready for execution.",
        "created_at": _now(),
    })
    _save(repo_root, problem_id, room)
    return room


def mark_step_done(
    repo_root: Path,
    problem_id: str,
    room_id: str,
    step_idx: int,
    outcome: str,
    notes: str = "",
) -> dict | None:
    room = get_room(repo_root, problem_id, room_id)
    if room is None or not room.get("plan"):
        return None
    plan = room["plan"]
    exec_entry = {"step": step_idx, "outcome": outcome, "notes": notes, "done_at": _now()}
    plan.setdefault("executed_steps", []).append(exec_entry)
    steps = plan.get("steps", [])
    all_done = len(plan["executed_steps"]) >= len(steps)
    if all_done:
        plan["status"] = "done"
        room["status"] = "done"
    icon = "✅" if outcome == "success" else "⚠️"
    title = steps[step_idx].get("title", f"Step {step_idx + 1}") if step_idx < len(steps) else f"Step {step_idx + 1}"
    room["messages"].append({
        "id": f"m{uuid.uuid4().hex[:8]}",
        "author": "coordinator",
        "role": "event",
        "event_type": "step_done",
        "body": f"{icon} **Step {step_idx + 1} done** ({title}): {outcome}",
        "created_at": _now(),
    })
    _save(repo_root, problem_id, room)
    return room


def transcript_text(room: dict) -> str:
    """Plain-text conversation transcript for use in prompts."""
    lines = [f"# Meeting: {room['topic']}", f"Goal: {room['goal']}", ""]
    for m in room.get("messages", []):
        if m.get("role") == "event":
            lines.append(f"[{m['author']}] {m['body']}")
        else:
            ts = m.get("created_at", "")[:16].replace("T", " ")
            lines.append(f"\n[{ts}] {m['author'].upper()}:")
            lines.append(m.get("body", ""))
    return "\n".join(lines)
