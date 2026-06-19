"""Global daily push-forward across all benchmark problems.

Runs once per day (gated by date stamp, overridable with force=True):
  1. For every active problem: discover new proof gaps (critic agent)
  2. Resolve up to N open issues per problem (solver agent)
  3. Create a meeting room with field-appropriate mathematician personas
  4. Run multiple rounds of discussion (each participant responds to the others)
  5. Synthesize the discussion into a concrete action plan
  6. Save meeting notes to documents/questions/{pid}/meets/{room_id}-notes.md

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
_METRICS_FILE = "push_forward_metrics.json"

# job_id → progress dict (lives in memory for the server lifetime)
_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


# ── State persistence ─────────────────────────────────────────────────────────

def _state_path(repo_root: Path) -> Path:
    return repo_root / "webapp" / _STATE_FILE


# ── Metrics persistence (survives restarts, stored in data/) ──────────────────

def _metrics_path(repo_root: Path) -> Path:
    return repo_root / "data" / _METRICS_FILE


def load_metrics(repo_root: Path) -> dict:
    p = _metrics_path(repo_root)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"snapshots": []}


def _save_metrics(repo_root: Path, metrics: dict) -> None:
    p = _metrics_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def snapshot_metrics(repo_root: Path, job_id: str, problems: list[str]) -> dict:
    """Compute document-size and issue-resolve metrics for a set of problems."""
    doc_root = repo_root / "documents" / "questions"
    issues_root = repo_root / "webapp" / "issues" / "first_proof_1"

    _DOC_EXTS = {".tex", ".md", ".txt"}

    total_bytes = 0
    per_problem_bytes: dict[str, int] = {}
    total_issues = 0
    resolved_issues = 0
    per_problem_issues: dict[str, dict] = {}

    for pid in problems:
        # Document size: all .tex/.md/.txt under documents/questions/<pid>/
        size = 0
        pid_doc = doc_root / pid
        if pid_doc.is_dir():
            for f in pid_doc.rglob("*"):
                if f.is_file() and f.suffix in _DOC_EXTS:
                    try:
                        size += f.stat().st_size
                    except OSError:
                        pass
        per_problem_bytes[pid] = size
        total_bytes += size

        # Issue counts
        open_c = resolved_c = 0
        pid_issues = issues_root / pid
        if pid_issues.is_dir():
            for f in pid_issues.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    if d.get("status") == "resolved":
                        resolved_c += 1
                    else:
                        open_c += 1
                except Exception:
                    pass
        per_problem_issues[pid] = {"open": open_c, "resolved": resolved_c}
        total_issues += open_c + resolved_c
        resolved_issues += resolved_c

    n = len(problems)
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "job_id": job_id,
        "total_doc_bytes": total_bytes,
        "avg_doc_bytes": total_bytes // n if n else 0,
        "total_issues": total_issues,
        "resolved_issues": resolved_issues,
        "open_issues": total_issues - resolved_issues,
        "solve_rate": round(resolved_issues / total_issues, 4) if total_issues else 0.0,
        "per_problem_doc_bytes": per_problem_bytes,
        "per_problem_issues": per_problem_issues,
    }


def append_metrics_snapshot(repo_root: Path, snap: dict) -> None:
    metrics = load_metrics(repo_root)
    snapshots = metrics.setdefault("snapshots", [])
    snap["round"] = len(snapshots) + 1
    snapshots.append(snap)
    _save_metrics(repo_root, metrics)


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


# ── Meeting documentation ─────────────────────────────────────────────────────

def _save_meeting_notes(repo_root: Path, pid: str, room_id: str) -> Path | None:
    """Write a markdown notes file for a completed meeting room.

    Saved to documents/questions/{pid}/meets/{room_id}-notes.md so it is
    surfaced in the Documents tab and survives server restarts.
    """
    from .meet import get_room, transcript_text
    room = get_room(repo_root, pid, room_id)
    if not room:
        return None

    lines: list[str] = [
        f"# Meeting Notes: {room.get('topic', room_id)}",
        f"**Goal:** {room.get('goal', '')}",
        f"**Date:** {room.get('created_at', '')[:10]}",
        f"**Participants:** {', '.join(room.get('participants', []))}",
        "",
        "## Discussion Transcript",
        "",
        transcript_text(room),
    ]

    plan = room.get("plan")
    if plan:
        lines += ["", "## Action Plan", "", plan.get("summary", "")]
        for i, step in enumerate(plan.get("steps", []), 1):
            title = step.get("title", f"Step {i}")
            body = step.get("body", step.get("description", ""))
            agent = step.get("agent", "")
            lines.append(f"\n### {i}. {title}" + (f" *(agent: {agent})*" if agent else ""))
            if body:
                lines.append(body)

    doc_dir = repo_root / "documents" / "questions" / pid / "meets"
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_path = doc_dir / f"{room_id}-notes.md"
    doc_path.write_text("\n".join(lines), encoding="utf-8")
    return doc_path


# ── Main runner ───────────────────────────────────────────────────────────────

_DEFAULT_MEETING_ROUNDS = 3


def run_push_forward(
    repo_root: Path,
    job_id: str,
    problems: list[str] | None = None,
    max_resolve: int = 2,
    n_meeting_rounds: int = _DEFAULT_MEETING_ROUNDS,
) -> None:
    """Execute the global push-forward. Blocking — call from a daemon thread.

    For each problem:
      1. Run a full issue cycle (discover + resolve)
      2. Create a meeting room with field-appropriate mathematician personas
      3. Run n_meeting_rounds of interleaved discussion
      4. Synthesize the discussion into a concrete action plan
      5. Save meeting notes to documents/questions/{pid}/meets/{room_id}-notes.md
    """
    from .issue_agents import run_issue_cycle
    from .meet import create_room, get_personas_for_problem
    from .meet_agents import run_round_offline, run_synthesis

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
        from .issues import list_issues as _list_issues

        for pid in active:
            with _LOCK:
                job = _JOBS.get(job_id, {})
                job["current"] = pid

            # Snapshot issue counts before cycle
            try:
                _before = _list_issues(repo_root, pid, "first_proof_1")
                open_before = sum(1 for i in _before if i.get("status") in ("open", "in_progress"))
                total_before = len(_before)
            except Exception:
                open_before = total_before = 0

            _log(f"{pid}: starting issue cycle (discover + resolve up to {max_resolve})")
            cycle_error = None
            try:
                cycle_log = run_issue_cycle(repo_root, pid, max_resolve=max_resolve)
                _log(f"{pid}: issue cycle done ({len(cycle_log)} log lines)")
            except Exception as exc:
                cycle_log = []
                cycle_error = str(exc)
                _log(f"{pid}: issue cycle error: {exc}")

            # Snapshot after cycle to measure what changed
            try:
                _after = _list_issues(repo_root, pid, "first_proof_1")
                open_after = sum(1 for i in _after if i.get("status") in ("open", "in_progress"))
                total_after = len(_after)
                issues_discovered = max(0, total_after - total_before)
                issues_resolved = max(0, open_before - open_after)
            except Exception:
                open_after = total_after = issues_discovered = issues_resolved = 0

            # Full meeting: multi-round discussion → synthesis → documented notes
            room_id = None
            notes_path = None
            meeting_participants: list[str] = []
            try:
                personas = get_personas_for_problem(pid)
                if personas:
                    meeting_participants = ["coordinator"] + [p["id"] for p in personas[:3]]
                    topic = f"Push-forward {today} — {pid} proof review"
                    goal = (
                        f"Review today's issue discovery and resolution results for {pid}. "
                        "Agree on the highest-priority remaining gaps and produce a concrete action plan."
                    )
                    room = create_room(repo_root, pid, topic=topic, goal=goal,
                                      participants=meeting_participants)
                    room_id = room["id"]
                    _log(f"{pid}: created meeting room {room_id} ({len(meeting_participants)} participants, "
                         f"{n_meeting_rounds} rounds planned)")

                    # Multi-round interleaved discussion
                    run_round_offline(
                        repo_root, pid, room_id,
                        f"{job_id}-{pid}-meet",
                        n_rounds=n_meeting_rounds,
                    )
                    _log(f"{pid}: {n_meeting_rounds} discussion rounds complete")

                    # Synthesis: coordinator reads transcript and produces an action plan
                    try:
                        for _ in run_synthesis(repo_root, pid, room_id):
                            pass
                        _log(f"{pid}: action plan synthesized")
                    except Exception as exc:
                        _log(f"{pid}: synthesis error: {exc}")

                    # Persist meeting notes to disk
                    try:
                        notes_path = _save_meeting_notes(repo_root, pid, room_id)
                        if notes_path:
                            _log(f"{pid}: meeting notes saved → {notes_path.name}")
                    except Exception as exc:
                        _log(f"{pid}: notes save error: {exc}")

            except Exception as exc:
                _log(f"{pid}: meeting error: {exc}")

            with _LOCK:
                job = _JOBS.get(job_id, {})
                job["done"] = job.get("done", 0) + 1
                job["results"].append({
                    "problem": pid,
                    "issues_open_before": open_before,
                    "issues_open_after": open_after,
                    "issues_discovered": issues_discovered,
                    "issues_resolved": issues_resolved,
                    "room_id": room_id,
                    "meeting_participants": meeting_participants,
                    "notes_path": str(notes_path) if notes_path else None,
                    "error": cycle_error,
                })

        # Persist run record
        state = load_state(repo_root)
        state["last_run_date"] = today
        with _LOCK:
            saved_results = list(_JOBS.get(job_id, {}).get("results", []))
        state.setdefault("runs", []).append({
            "date": today,
            "job_id": job_id,
            "problems": active,
            "n_meeting_rounds": n_meeting_rounds,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "results": saved_results,
        })
        # Keep at most 30 run records to avoid unbounded growth
        state["runs"] = state["runs"][-30:]
        _save_state(repo_root, state)

        # Snapshot metrics into data/push_forward_metrics.json
        try:
            snap = snapshot_metrics(repo_root, job_id, active)
            append_metrics_snapshot(repo_root, snap)
            _log(f"metrics snapshot round {snap['round']} saved")
        except Exception as me:
            log.warning("metrics snapshot failed: %s", me)

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
