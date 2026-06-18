"""Daily insight generation daemon.

Wakes up once a day (default 09:05, just after the daily job) and runs
run_all_insights() to regenerate system / dataset / question insights.

Env vars:
  RMA_INSIGHT_LOOP_DISABLED  Set to "1" to disable.
  RMA_INSIGHT_AT             HH:MM local time to run (default "09:05").
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_TIME = "09:05"
_INITIAL_DELAY_S = 120  # 2 min after server start before first run


def _seconds_until(target_hhmm: str) -> float:
    now = datetime.now()
    h, m = (int(x) for x in target_hhmm.split(":"))
    today_target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    delta = (today_target - now).total_seconds()
    if delta <= 0:
        delta += 86400  # already past today → wait until tomorrow
    return delta


def run_insight_loop(repo_root: Path) -> None:
    """Run forever: generate insights once per day at RMA_INSIGHT_AT."""
    if os.environ.get("RMA_INSIGHT_LOOP_DISABLED", "").strip() == "1":
        log.info("[insight-loop] disabled via RMA_INSIGHT_LOOP_DISABLED=1")
        return

    target_time = os.environ.get("RMA_INSIGHT_AT", _DEFAULT_TIME)
    log.info(f"[insight-loop] daemon started; will run daily at {target_time}")

    # On first startup, run once after a short delay so the server is fully up
    # and the issue daemon has had a chance to do its first pass.
    time.sleep(_INITIAL_DELAY_S)
    log.info("[insight-loop] running initial insight generation…")
    try:
        from .insight_agents import run_all_insights
        run_all_insights(repo_root)
    except Exception as exc:
        log.warning(f"[insight-loop] initial run failed: {exc}")

    while True:
        wait = _seconds_until(target_time)
        log.info(f"[insight-loop] next run in {wait/3600:.1f}h (at {target_time})")
        time.sleep(wait)
        log.info("[insight-loop] daily insight run starting…")
        try:
            from .insight_agents import run_all_insights
            run_all_insights(repo_root)
        except Exception as exc:
            log.warning(f"[insight-loop] daily run failed: {exc}")
        # Sleep a few seconds so we don't re-fire if we woke up a bit early
        time.sleep(10)
