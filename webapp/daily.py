"""Autonomous daily worker for the Research Math Agent.

Runs the agent on its own, once a day, with no human in the loop, using the
local ``claude`` CLI (your Pro/Max subscription — no API credits). Each day it
works one or more benchmark problems, writes a dated report into ``documents/``
(surfaced by the web UI's Documents tab), and logs the run to each problem's
issue.

Run it in a shell on the server:

    python -m webapp.daily              # daemon: run every day at $RMA_DAILY_AT (default 09:00)
    python -m webapp.daily --now        # run once immediately, then keep the daily schedule
    python -m webapp.daily --once       # run once and exit (use this from cron)

Configuration via env vars:
    RMA_DAILY_AT        target local time "HH:MM" (default "09:00")
    RMA_DAILY_PROBLEMS  comma list, e.g. "q6" or "q1,q2" (default: one rotating problem/day)
    RMA_DAILY_MODEL     claude model alias (default "sonnet")
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .agent import AgentConfig
from .documents import write_or_append_report
from .issues import append_activity
from .runs import REGISTRY, RunHandle

REPO_ROOT = Path(__file__).resolve().parents[1]
_ALL_PROBLEMS = [f"q{i}" for i in range(1, 11)]
_stop = False
_current: RunHandle | None = None


def _log(msg: str) -> None:
    print(f"[daily {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def chosen_problems(repo_root: Path) -> list[str]:
    env = os.environ.get("RMA_DAILY_PROBLEMS", "").strip()
    if env:
        return [p.strip() for p in env.split(",") if p.strip()]
    # Default: rotate one problem per day so cost/time stay bounded.
    avail = [p for p in _ALL_PROBLEMS if (repo_root / "problems" / f"{p}.tex").is_file()]
    if not avail:
        return []
    return [avail[datetime.now().toordinal() % len(avail)]]


def run_daily_job(repo_root: Path = REPO_ROOT, *, model: str | None = None,
                  problems: list[str] | None = None, runner=None) -> Path | None:
    """Work today's problem(s) and write a report. Returns the report path."""
    global _current
    from .claude_code import run_claude_code_agent  # lazy import (avoids cycle at module load)
    runner = runner or run_claude_code_agent
    model = model or os.environ.get("RMA_DAILY_MODEL", "sonnet")
    problems = problems or chosen_problems(repo_root)
    if not problems:
        _log("no problems found; nothing to do")
        return None

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    started = datetime.now(timezone.utc).strftime("%H:%M UTC")
    _log(f"starting daily run for {problems} (model={model})")
    report_path = None

    for pid in problems:
        if _stop:
            break
        handle = REGISTRY.register(f"daily-{pid}-{int(time.time())}",
                                   {"problem": pid, "provider": "claude-code", "model": model, "kind": "daily"})
        _current = handle
        cfg = AgentConfig(problem_id=pid, problem_text="", model=model,
                          repo_root=repo_root, provider="claude-code")
        transcript: list[str] = []
        artifact = None
        usage = {}
        reason = "end_turn"
        try:
            for ev in runner(cfg, handle):
                if ev.type == "text_delta":
                    transcript.append(ev.data.get("text", ""))
                elif ev.type == "artifact":
                    artifact = ev.data
                elif ev.type == "usage":
                    usage = ev.data
                elif ev.type == "error":
                    transcript.append(f"\n[error] {ev.data.get('message','')}")
                elif ev.type == "done":
                    reason = ev.data.get("reason", "end_turn")
        finally:
            REGISTRY.unregister(handle.run_id)
            _current = None

        section = _build_section(pid, started, "".join(transcript), artifact, usage, reason)
        report_path = write_or_append_report(repo_root, date_str, section)
        try:
            append_activity(repo_root, pid,
                            f"Autonomous daily run (model {model}, {reason}). See documents/{date_str}.md.")
        except Exception:  # noqa: BLE001
            pass
        _log(f"  {pid}: {reason}; report -> documents/{date_str}.md")

    _log("daily run complete")
    return report_path


def _build_section(pid: str, started: str, transcript: str, artifact, usage: dict, reason: str) -> str:
    summary = transcript.strip()[-1800:] or "_(no text output)_"
    lines = [f"## {pid} — autonomous run ({started})", "", "**Outcome summary:**", "", summary, ""]
    bits = []
    if usage.get("cost_usd") is not None:
        bits.append(f"est. cost ${float(usage['cost_usd']):.4f}")
    if usage.get("num_turns") is not None:
        bits.append(f"turns {usage['num_turns']}")
    bits.append(f"tokens in {usage.get('input_tokens', 0)} / out {usage.get('output_tokens', 0)}")
    bits.append(f"stop: {reason}")
    lines.append("**Run:** " + " · ".join(bits))
    if artifact and artifact.get("content"):
        content = artifact["content"]
        lines += ["", "<details><summary>solution.tex (%d chars)</summary>" % len(content), "",
                  "```latex", content[:8000], "```", "", "</details>"]
    return "\n".join(lines)


def _seconds_until(hhmm: str) -> float:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        h, m = 9, 0
    now = datetime.now()
    nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def _install_signals() -> None:
    def handler(signum, frame):  # noqa: ARG001
        global _stop
        _stop = True
        _log(f"signal {signum} received; cancelling current run and exiting…")
        if _current is not None:
            _current.request_cancel()
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _sleep_until(target: str) -> None:
    """Sleep until the target time, in short chunks so signals are responsive."""
    remaining = _seconds_until(target)
    _log(f"next run at {target} (in {remaining/3600:.1f}h)")
    while remaining > 0 and not _stop:
        time.sleep(min(30.0, remaining))
        remaining = _seconds_until(target) if remaining > 60 else remaining - 30


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Autonomous daily Research Math Agent worker.")
    parser.add_argument("--once", action="store_true", help="run once now and exit (for cron)")
    parser.add_argument("--now", action="store_true", help="run once immediately, then keep the daily schedule")
    parser.add_argument("--at", default=os.environ.get("RMA_DAILY_AT", "09:00"), help="daily run time HH:MM")
    args = parser.parse_args(argv)

    _install_signals()

    if args.once:
        run_daily_job()
        return 0

    if args.now:
        run_daily_job()

    _log(f"daemon started; scheduled daily at {args.at}. Ctrl-C to stop.")
    while not _stop:
        _sleep_until(args.at)
        if _stop:
            break
        run_daily_job()
    _log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
