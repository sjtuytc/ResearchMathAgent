"""Generate substantive meeting and issue content for first_proof_2 problems.

For each prob-01 through prob-10:
  1. Adds a critic review and verifier assessment to the existing issue thread
  2. Creates a meeting room with mathematician personas and runs 2 rounds of discussion
  3. Synthesizes an action plan

Uses vertex_llm.complete() directly (200-attempt retry, global endpoint).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)
DATASET = "first_proof_2"
PROBLEMS = [f"prob-{i:02d}" for i in range(1, 11)]
SOLUTION_DIR = REPO_ROOT / "output_solutions" / "fp2_vertex_opus_simple"

CRITIC_SYSTEM = (
    "You are a rigorous mathematical critic reviewing a proof attempt. "
    "Identify specific logical gaps, missing steps, unjustified claims, and potential errors. "
    "Be precise: quote exact lines or steps, explain why they are incomplete or incorrect. "
    "Also acknowledge what is done correctly. Structure your review with clear headings. "
    "Use LaTeX math notation where helpful. Target length: 400-600 words."
)

VERIFIER_SYSTEM = (
    "You are a mathematical verifier assessing a proof and the critique of it. "
    "Give an honest assessment: what is now solid, what still needs work, "
    "what is the overall completeness level (0-100%). "
    "Propose 2-3 concrete next steps to make the proof complete. "
    "Be concise: 200-350 words. Use LaTeX where helpful."
)

TURN_SLEEP = 5  # seconds between discussion turns (reduced from 30s)
ROUND_SLEEP = 15  # seconds between rounds (reduced from 90s)


def _read_solution(pid: str) -> str:
    sol_path = SOLUTION_DIR / pid / "solution.tex"
    if not sol_path.is_file():
        return ""
    text = sol_path.read_text(encoding="utf-8")
    # Truncate to avoid overly long prompts
    return text[:8000] if len(text) > 8000 else text


def _read_problem_statement(pid: str) -> str:
    """Read problem statement from the first comment of the seed issue."""
    issues_dir = REPO_ROOT / "webapp" / "issues" / DATASET / pid
    for f in sorted(issues_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            comments = d.get("comments", [])
            if comments:
                body = (comments[0].get("body") or "").strip()
                if body:
                    return body[:4000]
        except Exception:
            pass
    return ""


def _get_seed_issue_id(pid: str) -> str | None:
    """Get the ID of the first issue for this problem."""
    issues_dir = REPO_ROOT / "webapp" / "issues" / DATASET / pid
    for f in sorted(issues_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return d.get("id")
        except Exception:
            pass
    return None


def generate_critic_review(pid: str, problem_stmt: str, solution: str) -> str:
    from webapp.vertex_llm import complete
    prompt = f"""You are reviewing a proof attempt for the following mathematical problem.

## Problem Statement
{problem_stmt[:2000]}

## Proof Attempt (LaTeX)
```latex
{solution[:6000]}
```

Write a detailed mathematical critic review. Identify:
1. What is correctly argued
2. Specific gaps or missing steps
3. Any unjustified claims or logical errors
4. Whether the overall strategy is sound

Be mathematically precise. Use LaTeX notation where helpful."""

    log.info("%s: generating critic review", pid)
    text = complete(prompt, system=CRITIC_SYSTEM, max_tokens=2000)
    return (text or "").strip()


def generate_verifier_assessment(pid: str, problem_stmt: str, solution: str, critic_review: str) -> str:
    from webapp.vertex_llm import complete
    prompt = f"""You are verifying a proof attempt after reading a critic's review.

## Problem (brief)
{problem_stmt[:1000]}

## Critic Review
{critic_review[:2000]}

## Proof Attempt (excerpt)
```latex
{solution[:3000]}
```

Give your assessment:
- Overall completeness: X%
- What is solid
- What still needs work
- Top 2-3 concrete next steps

Be concise and precise."""

    log.info("%s: generating verifier assessment", pid)
    text = complete(prompt, system=VERIFIER_SYSTEM, max_tokens=1000)
    return (text or "").strip()


def add_issue_comments(pid: str) -> bool:
    """Add critic review and verifier assessment to the seed issue."""
    from webapp.issues import add_comment, update_issue

    problem_stmt = _read_problem_statement(pid)
    solution = _read_solution(pid)
    if not problem_stmt or not solution:
        log.warning("%s: missing problem statement or solution, skipping issue comments", pid)
        return False

    issue_id = _get_seed_issue_id(pid)
    if not issue_id:
        log.warning("%s: no seed issue found", pid)
        return False

    # Generate critic review
    critic_text = generate_critic_review(pid, problem_stmt, solution)
    if not critic_text:
        log.warning("%s: empty critic review", pid)
        return False

    add_comment(
        REPO_ROOT, pid, issue_id,
        author="critic-agent",
        body=critic_text,
        role="agent",
        dataset=DATASET,
    )
    log.info("%s: added critic review (%d chars)", pid, len(critic_text))

    time.sleep(3)

    # Generate verifier assessment
    verifier_text = generate_verifier_assessment(pid, problem_stmt, solution, critic_text)
    if verifier_text:
        add_comment(
            REPO_ROOT, pid, issue_id,
            author="verifier-agent",
            body=verifier_text,
            role="agent",
            dataset=DATASET,
        )
        log.info("%s: added verifier assessment (%d chars)", pid, len(verifier_text))

    # Update issue status to in_progress (it has active discussion)
    update_issue(REPO_ROOT, pid, issue_id, dataset=DATASET, status="in_progress")
    return True


def run_meeting(pid: str, job_id: str, n_rounds: int = 2) -> str | None:
    """Create a meeting room and run n_rounds of discussion. Returns room_id or None."""
    from webapp.meet import create_room, get_personas_for_problem
    from webapp.meet_agents import run_discussion_turn, run_synthesis
    from webapp.push_forward import _save_meeting_notes

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    personas = get_personas_for_problem(pid)
    if not personas:
        log.warning("%s: no personas found", pid)
        return None

    participants = ["coordinator"] + [p["id"] for p in personas[:3]]
    topic = f"Proof review {today} — {pid}"
    goal = (
        f"Review the generated proof for {pid}. "
        "Identify the strongest remaining gaps and agree on a concrete verification strategy."
    )

    room = create_room(REPO_ROOT, pid, topic=topic, goal=goal, participants=participants)
    room_id = room["id"]
    log.info("%s: created meeting room %s with %d participants", pid, room_id, len(participants))

    non_coord = [p for p in participants if p != "coordinator"]
    for round_num in range(n_rounds):
        log.info("%s/%s: round %d/%d", pid, room_id, round_num + 1, n_rounds)
        for participant in non_coord:
            for ev in run_discussion_turn(REPO_ROOT, pid, room_id, participant):
                if ev.type == "error":
                    log.warning("%s/%s: turn error for %s: %s", pid, room_id, participant, ev.data)
            time.sleep(TURN_SLEEP)
        if round_num < n_rounds - 1:
            log.info("%s/%s: round %d done, pausing %ds", pid, room_id, round_num + 1, ROUND_SLEEP)
            time.sleep(ROUND_SLEEP)

    # Synthesis
    log.info("%s/%s: running synthesis", pid, room_id)
    for ev in run_synthesis(REPO_ROOT, pid, room_id):
        if ev.type == "error":
            log.warning("%s/%s: synthesis error: %s", pid, room_id, ev.data)

    # Save meeting notes to documents
    notes = _save_meeting_notes(REPO_ROOT, pid, room_id)
    if notes:
        log.info("%s/%s: saved meeting notes to %s", pid, room_id, notes)

    return room_id


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate fp2 meeting+issue content")
    parser.add_argument("--problems", nargs="*", default=PROBLEMS, help="Problems to process")
    parser.add_argument("--skip-issues", action="store_true", help="Skip issue comment generation")
    parser.add_argument("--skip-meetings", action="store_true", help="Skip meeting generation")
    parser.add_argument("--rounds", type=int, default=2, help="Discussion rounds per meeting")
    args = parser.parse_args()

    log.info("Processing %d problems: %s", len(args.problems), args.problems)

    for pid in args.problems:
        log.info("=== %s ===", pid)
        job_id = f"fp2content-{pid}-{uuid.uuid4().hex[:6]}"

        if not args.skip_issues:
            try:
                ok = add_issue_comments(pid)
                log.info("%s: issue comments %s", pid, "added" if ok else "skipped")
            except Exception as exc:
                log.exception("%s: issue comments failed: %s", pid, exc)

        if not args.skip_meetings:
            try:
                room_id = run_meeting(pid, job_id, n_rounds=args.rounds)
                log.info("%s: meeting %s", pid, room_id or "failed")
            except Exception as exc:
                log.exception("%s: meeting failed: %s", pid, exc)

        log.info("%s: done", pid)
        time.sleep(3)

    log.info("All done.")


if __name__ == "__main__":
    main()
