#!/usr/bin/env python3
"""Push meeting-round discussion turns for q1–q10 on the Claude subscription.

For each problem (default: q1–q10):
  1. Creates a mathematician meeting room if none exists yet.
  2. Runs one discussion round — each mathematician contributes once.
  3. Saves directly to webapp/meets/{pid}/{room_id}.json on disk.

Uses llm.complete() so no user interaction is needed.
Run this from cron, a daily loop, or manually.

Usage:
    python3 scripts/push_meet_rounds.py [--problems q1 q2 ...] [--rounds N] [--dry-run]

Options:
    --problems   Subset of problems to process (default: q1 q2 q3 q4 q5 q6 q7 q8 q9 q10)
    --rounds N   Number of full rounds per room (default: 1)
    --dry-run    Print what would happen without calling the model
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("push_meet")

_ALL_PROBLEMS = ["q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9", "q10"]
_SLEEP_BETWEEN_TURNS = 3   # seconds between Vertex calls (quota friendliness)


# ── problem context ────────────────────────────────────────────────────────────

def _problem_tex(problem_id: str) -> str:
    """Return problem statement text (tex or md)."""
    p = REPO_ROOT / "problems" / f"{problem_id}.tex"
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    for ext in ("md", "txt"):
        p2 = REPO_ROOT / "problems" / f"{problem_id}.{ext}"
        if p2.is_file():
            return p2.read_text(encoding="utf-8", errors="replace")
    return f"Problem {problem_id} (statement not found on disk)"


def _problem_topic(problem_id: str) -> str:
    topics = {
        "q1": "Equivalence of Φ⁴₃ measures under shift — Hairer",
        "q2": "Whittaker functions and Rankin–Selberg integrals — Nelson",
        "q3": "Macdonald stationary distribution via Markov chain — Williams",
        "q4": "Subharmonicity of 1/Φₙ under finite free convolution — Srivastava",
        "q5": "Slice filtration for N∞ operads — Blumberg",
        "q6": "ε-light subsets in spectral graph theory — Spielman",
        "q7": "Uniform lattices in Lie groups with 2-torsion — Weinberger",
        "q8": "Lagrangian smoothings of legendrian knots — Abouzaid",
        "q9": "Algebraic relations on determinantal tensors — Kileel",
        "q10": "Preconditioned CG for RKHS-CP decomposition — Kolda/Ward",
    }
    return topics.get(problem_id, f"Problem {problem_id}")


# ── room management ────────────────────────────────────────────────────────────

def _ensure_room(problem_id: str, dry_run: bool) -> dict:
    """Return the most recent meeting room, creating one if none exists."""
    from webapp.meet import list_rooms, create_room, PROBLEM_PERSONAS, MATHEMATICIAN_PERSONAS

    rooms = list_rooms(REPO_ROOT, problem_id)
    # Pick the most recent open room, or any room
    open_rooms = [r for r in rooms if r.get("status") != "closed"]
    if open_rooms:
        room = open_rooms[-1]
        log.info("  [%s] using existing room: %s (%d messages)",
                 problem_id, room["id"], len(room.get("messages", [])))
        return room

    # Create a new room with the problem's mathematician personas
    persona_ids = PROBLEM_PERSONAS.get(problem_id, ["dan-spielman", "nikhil-srivastava"])
    participants = [p for p in persona_ids if p in MATHEMATICIAN_PERSONAS]
    if not participants:
        participants = list(MATHEMATICIAN_PERSONAS.keys())[:3]

    topic = _problem_topic(problem_id)
    goal = (
        f"Identify the key mathematical obstacles and agree on a concrete strategy "
        f"to prove or make progress on: {topic}."
    )

    if dry_run:
        log.info("  [%s] DRY-RUN would create room with participants: %s", problem_id, participants)
        return {
            "id": f"{problem_id}-meet-1",
            "problem_id": problem_id,
            "topic": topic,
            "goal": goal,
            "participants": participants,
            "messages": [{"role": "event", "body": f"Meeting opened: **{topic}**",
                          "author": "coordinator", "created_at": ""}],
        }

    room = create_room(REPO_ROOT, problem_id, topic=topic, goal=goal, participants=participants)
    log.info("  [%s] created room: %s with %d participants", problem_id, room["id"], len(participants))
    return room


# ── participant prompt ─────────────────────────────────────────────────────────

def _build_turn_prompt(participant: str, room: dict, problem_tex: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for one discussion turn."""
    from webapp.meet import MATHEMATICIAN_PERSONAS, PERSONAS, transcript_text

    transcript = transcript_text(room)
    problem_id = room["problem_id"]

    if participant in MATHEMATICIAN_PERSONAS:
        mp = MATHEMATICIAN_PERSONAS[participant]
        system = (
            f"{mp['character']}\n\n"
            f"You are in a virtual research meeting about problem {problem_id}. "
            f"Stay completely in character as {mp['display']}. "
            "Speak in first person. Use your characteristic mathematical style. "
            "Be concise but substantive: 4–10 sentences or a focused list of mathematical points. "
            "Use LaTeX notation where helpful. "
            "Respond with ONLY your discussion contribution — no preamble, no meta-commentary."
        )
        opening = mp.get("opening_move", "")
        user = (
            f"The meeting discussion so far:\n\n{transcript}\n\n"
            f"--- The problem statement ---\n{problem_tex[:3000]}\n\n"
            f"Your characteristic first move when starting: \"{opening}\"\n\n"
            "Add your substantive mathematical contribution to this discussion. "
            "Engage with what was already said. Be direct and mathematically precise."
        )
    else:
        p = PERSONAS.get(participant, PERSONAS["coordinator"])
        system = (
            f"You are {participant} in a research meeting about math problem {problem_id}. "
            f"Role: {p['role']} {p['style']}\n"
            "Be concise and mathematical. Use LaTeX where helpful. "
            "Respond with ONLY your contribution — no meta-commentary."
        )
        user = (
            f"The meeting discussion so far:\n\n{transcript}\n\n"
            f"Problem statement:\n{problem_tex[:3000]}\n\n"
            "Add your concise mathematical contribution."
        )

    return system, user


# ── one round ─────────────────────────────────────────────────────────────────

def run_one_round(problem_id: str, room: dict, dry_run: bool) -> int:
    """Run one discussion round for all participants. Returns number of turns done."""
    from webapp.meet import post_message

    participants = [p for p in room.get("participants", []) if p != "human"]
    problem_tex = _problem_tex(problem_id)
    turns_done = 0

    for participant in participants:
        log.info("  [%s/%s] turn: %s …", problem_id, room["id"], participant)
        system, user = _build_turn_prompt(participant, room, problem_tex)

        if dry_run:
            log.info("    DRY-RUN: would call llm.complete() for %s", participant)
            turns_done += 1
            continue

        try:
            from webapp.llm import complete
            response = complete(user, system=system, max_tokens=1024)
        except Exception as exc:
            log.warning("    Vertex call failed for %s: %s", participant, exc)
            continue

        if not response:
            log.warning("    Empty response for %s — skipping", participant)
            continue

        # Save directly to disk
        updated = post_message(REPO_ROOT, problem_id, room["id"], participant, response)
        if updated is None:
            log.warning("    post_message returned None for %s/%s", problem_id, room["id"])
        else:
            room = updated  # keep transcript up-to-date for subsequent speakers
            log.info("    posted %d chars", len(response))
        turns_done += 1

        time.sleep(_SLEEP_BETWEEN_TURNS)

    return turns_done


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--problems", nargs="+", default=_ALL_PROBLEMS, metavar="PID",
                        help="Problems to process (default: q1–q10)")
    parser.add_argument("--rounds", type=int, default=1, metavar="N",
                        help="Discussion rounds per room (default: 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without calling the model")
    args = parser.parse_args()

    total_turns = 0
    for problem_id in args.problems:
        log.info("[%s] processing …", problem_id)
        try:
            room = _ensure_room(problem_id, args.dry_run)
        except Exception as exc:
            log.error("  [%s] failed to get/create room: %s", problem_id, exc)
            continue

        for round_n in range(1, args.rounds + 1):
            log.info("  [%s] round %d/%d …", problem_id, round_n, args.rounds)
            try:
                n = run_one_round(problem_id, room, args.dry_run)
                total_turns += n
                log.info("  [%s] round %d done — %d turns", problem_id, round_n, n)
            except Exception as exc:
                log.error("  [%s] round %d failed: %s", problem_id, round_n, exc)

        # Refresh room from disk for next round
        if not args.dry_run:
            from webapp.meet import list_rooms
            rooms = list_rooms(REPO_ROOT, problem_id)
            if rooms:
                room = rooms[-1]

    log.info("Done. Total turns posted: %d", total_turns)


if __name__ == "__main__":
    main()
