"""Standalone CLI runner for push-forward.

Run as: python -m webapp.push_forward_cli [--problems q1 q2] [--force] [--dataset first_proof_1]

This runs outside the uvicorn process so server --reload does not kill it.
Progress is printed to stdout and saved to webapp/push_forward_state.json.
"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run push-forward outside uvicorn")
    parser.add_argument("--problems", nargs="*", help="Problem IDs to run (default: all)")
    parser.add_argument("--force", action="store_true", help="Bypass once-per-day gate")
    parser.add_argument("--dataset", default="first_proof_1", help="Dataset to use")
    parser.add_argument("--rounds", type=int, default=2, help="Discussion rounds per meeting")
    args = parser.parse_args()

    repo = Path(__file__).parent.parent
    job_id = uuid.uuid4().hex

    from .push_forward import already_ran_today, run_push_forward

    if not args.force and already_ran_today(repo):
        log.info("Already ran today — use --force to override")
        return

    log.info("Starting push-forward job %s (dataset=%s, problems=%s, rounds=%d)",
             job_id[:8], args.dataset, args.problems or "all", args.rounds)

    run_push_forward(
        repo,
        job_id,
        problems=args.problems or None,
        n_meeting_rounds=args.rounds,
        dataset=args.dataset,
    )

    log.info("Push-forward job %s complete", job_id[:8])


if __name__ == "__main__":
    main()
