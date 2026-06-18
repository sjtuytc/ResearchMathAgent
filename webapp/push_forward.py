"""Global daily push-forward across all benchmark problems.

Runs once per day (gated by date stamp, overridable with force=True):
  1. For every active problem: discover new proof gaps (critic agent)
  2. Resolve up to N open issues per problem (solver agent)
  3. Create a new meeting room with expert mathematician personas
  4. Run one round of AI discussion in each new room

All agents use Vertex AI (AnthropicVertex via ADC).
State is persisted in webapp/push_forward_state.json.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_STATE_FILE = "push_forward_state.json"

# job_id → progress dict (lives in memory for the server lifetime)
_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


# ── State persistence ─────────────────────────────────────────────────────────

def _state_path(repo_root: Path) -> Path:
    return repo_root / "webapp" / _STATE_FILE


def load_state(repo_root: Path) -> dict:
    p = _state_path(repo_root)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_run_date": None, "runs": []}


def _save_state(repo_root: Path, state: dict) -> None:
    _state_path(repo_root).write_text(json.dumps(state, indent=2), encoding="utf-8")


def already_ran_today(repo_root: Path) -> bool:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return load_state(repo_root).get("last_run_date") == today


# ── Job tracking ──────────────────────────────────────────────────────────────

def get_job(job_id: str) -> dict | None:
    return _JOBS.get(job_id)


def list_jobs() -> list[dict]:
    with _LOCK:
        return [{"job_id": jid, **info} for jid, info in _JOBS.items()]


def running_job() -> dict | None:
    with _LOCK:
        for jid, info in _JOBS.items():
            if info.get("status") == "running":
                return {"job_id": jid, **info}
    return None


# ── Main runner ───────────────────────────────────────────────────────────────

def run_push_forward(
    repo_root: Path,
    job_id: str,
    problems: list[str] | None = None,
    max_resolve: int = 2,
) -> None:
    """Execute the global push-forward. Blocking — call from a daemon thread."""
    from .issue_agents import run_issue_cycle
    from .meet import create_room, get_personas_for_problem
    from .meet_agents import run_round_offline

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    default_problems = [f"q{i}" for i in range(1, 11)]
    candidate = problems or default_problems
    active = [p for p in candidate if (repo_root / "problems" / f"{p}.tex").is_file()]

    with _LOCK:
        _JOBS[job_id] = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "total": len(active),
            "done": 0,
            "current": None,
            "log": [],
            "results": [],
        }

    def _log(msg: str) -> None:
        log.info("[push-forward %s] %s", job_id[:8], msg)
        with _LOCK:
            job = _JOBS.get(job_id)
            if job is not None:
                job["log"].append(msg)

    try:
        for pid in active:
            with _LOCK:
                job = _JOBS.get(job_id, {})
                job["current"] = pid

            _log(f"{pid}: starting issue cycle (discover + resolve up to {max_resolve})")
            issue_lines = 0
            try:
                cycle_log = run_issue_cycle(repo_root, pid, max_resolve=max_resolve)
                issue_lines = len(cycle_log)
                _log(f"{pid}: issue cycle done ({issue_lines} log lines)")
            except Exception as exc:
                _log(f"{pid}: issue cycle error: {exc}")

            # Create a meeting room with field-appropriate mathematician personas
            room_id = None
            try:
                personas = get_personas_for_problem(pid)
                if personas:
                    participants = ["coordinator"] + [p["id"] for p in personas[:3]]
                    topic = f"Push-forward {today} — {pid} proof review"
                    goal = (
                        f"Review today's issue discovery and resolution results for {pid}. "
                        "Agree on the highest-priority remaining gaps and a concrete next step."
                    )
                    room = create_room(repo_root, pid, topic=topic, goal=goal,
                                      participants=participants)
                    room_id = room["id"]
                    _log(f"{pid}: created meeting room {room_id} (participants: {participants})")

                    # One round of discussion (each non-human participant posts one turn)
                    try:
                        run_round_offline(repo_root, pid, room_id,
                                          f"{job_id}-{pid}-meet", n_rounds=1)
                        _log(f"{pid}: meeting discussion round complete")
                    except Exception as exc:
                        _log(f"{pid}: meeting discussion error: {exc}")
            except Exception as exc:
                _log(f"{pid}: meeting creation error: {exc}")

            with _LOCK:
                job = _JOBS.get(job_id, {})
                job["done"] = job.get("done", 0) + 1
                job["results"].append({
                    "problem": pid,
                    "issue_log_lines": issue_lines,
                    "room_id": room_id,
                })

        # Persist run record
        state = load_state(repo_root)
        state["last_run_date"] = today
        state.setdefault("runs", []).append({
            "date": today,
            "job_id": job_id,
            "problems": active,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        _save_state(repo_root, state)

        with _LOCK:
            job = _JOBS.get(job_id, {})
            if job:
                job.update({
                    "status": "done",
                    "current": None,
                    "done_at": datetime.now(timezone.utc).isoformat(),
                })
        _log("push-forward complete")

    except Exception as exc:
        log.exception("push-forward job %s failed", job_id)
        with _LOCK:
            job = _JOBS.get(job_id, {})
            if job:
                job.update({"status": "error", "error": str(exc), "current": None})
