"""Background daemon: continuously evolve open issues (discover → resolve).

Wakes up every RMA_ISSUE_LOOP_HOURS hours (default 6) and for every
(dataset, problem) pair that has at least one open issue, runs
run_issue_cycle which:
  1. Runs the critic/discovery agent to find new proof gaps.
  2. Runs the resolver agent on up to RMA_ISSUE_MAX_RESOLVE (default 2)
     open issues, writing fixes back to the working proof.

Skips any problem already being worked on by another active agent.

Manual one-shot trigger:  POST /api/evolve-issues
Background thread:        started automatically by server.py at import time.

Env vars:
  RMA_ISSUE_LOOP_HOURS      Hours between automatic passes (default 6).
  RMA_ISSUE_MAX_RESOLVE     Max issues to resolve per problem per pass (default 2).
  RMA_ISSUE_LOOP_DISABLED   Set to "1" to disable the background thread.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL_H = 6
_DEFAULT_MAX_RESOLVE = 2


def _iter_open_problems(repo_root: Path):
    """Yield (dataset, problem_id, n_open) for every problem with open issues."""
    from .issues import list_issues

    issues_root = repo_root / "webapp" / "issues"
    if not issues_root.is_dir():
        return

    for ds_dir in sorted(issues_root.iterdir()):
        if not ds_dir.is_dir():
            continue
        ds = ds_dir.name
        for prob_dir in sorted(ds_dir.iterdir()):
            if not prob_dir.is_dir():
                continue
            pid = prob_dir.name
            try:
                issues = list_issues(repo_root, pid, ds)
            except Exception:
                continue
            open_issues = [i for i in issues if i.get("status") in ("open", "in_progress")]
            if open_issues:
                yield ds, pid, len(open_issues)


def _is_active(pid: str) -> bool:
    """Return True if another agent is already running on this problem."""
    try:
        from .runs import REGISTRY
        for r in REGISTRY.active():
            if r.get("problem") == pid:
                return True
    except Exception:
        pass
    return False


def evolve_once(repo_root: Path, max_resolve: int | None = None) -> dict:
    """Run one full pass: discover + resolve for every open-issue problem.

    Returns a summary dict with per-problem results.
    """
    from .issue_agents import run_issue_cycle

    max_res = max_resolve if max_resolve is not None else int(
        os.environ.get("RMA_ISSUE_MAX_RESOLVE", _DEFAULT_MAX_RESOLVE)
    )
    results: list[dict] = []

    for ds, pid, n_open in _iter_open_problems(repo_root):
        if _is_active(pid):
            log.info(f"[issue-loop] {ds}/{pid}: agent already running — skipping")
            results.append({"dataset": ds, "problem": pid, "skipped": True, "reason": "active"})
            continue

        log.info(f"[issue-loop] {ds}/{pid}: {n_open} open issue(s) — running cycle")
        try:
            cycle_log = run_issue_cycle(repo_root, pid, max_resolve=max_res, dataset=ds)
            results.append({
                "dataset": ds,
                "problem": pid,
                "open": n_open,
                "ok": True,
                "log_lines": len(cycle_log),
            })
            log.info(f"[issue-loop] {ds}/{pid}: done ({len(cycle_log)} log lines)")
        except Exception as exc:
            log.warning(f"[issue-loop] {ds}/{pid}: error — {exc}")
            results.append({"dataset": ds, "problem": pid, "open": n_open, "ok": False, "error": str(exc)})

    ok = sum(1 for r in results if r.get("ok"))
    log.info(f"[issue-loop] pass complete: {len(results)} problem(s) — {ok} ok")
    return {"cycles": len(results), "ok": ok, "results": results}


def run_issue_loop(repo_root: Path) -> None:
    """Run forever in the background, calling evolve_once on schedule."""
    if os.environ.get("RMA_ISSUE_LOOP_DISABLED", "").strip() == "1":
        log.info("[issue-loop] disabled via RMA_ISSUE_LOOP_DISABLED=1")
        return

    interval_h = float(os.environ.get("RMA_ISSUE_LOOP_HOURS", _DEFAULT_INTERVAL_H))
    interval_s = interval_h * 3600

    log.info(f"[issue-loop] daemon started; interval={interval_h}h")
    # Initial delay: wait until server is fully up before first pass
    time.sleep(60)

    while True:
        try:
            evolve_once(repo_root)
        except Exception as exc:
            log.warning(f"[issue-loop] unhandled error: {exc}")
        time.sleep(interval_s)
