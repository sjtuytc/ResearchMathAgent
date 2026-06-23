"""Agent runners for virtual meeting rooms.

Discussion turns use direct Vertex AI completions (no tool loop) and post
messages to the room JSON via Python. Synthesis produces a plan JSON and
persists it the same way. This avoids the curl-in-agent-workspace problem.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import textwrap
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

from .agent import AgentEvent
from .issue_agents import _run_agent, _seed_workspace
from .runs import RunHandle
from .meet import PERSONAS, MATHEMATICIAN_PERSONAS, get_room, post_message, set_plan, mark_step_done, transcript_text

_MAX_EXEC_TURNS = 30

# ── Knowledge file helper ─────────────────────────────────────────────────────

def _knowledge_text(repo_root: Path, participant: str) -> str:
    """Return the content of the mathematician's knowledge file, or ''."""
    kpath = repo_root / "webapp" / "mathematician_knowledge" / f"{participant}.md"
    if kpath.is_file():
        return kpath.read_text(encoding="utf-8")
    return ""


# ── Discussion turn (direct LLM, no tool loop) ───────────────────────────────

def run_discussion_turn(
    repo_root: Path,
    problem_id: str,
    room_id: str,
    participant: str,
    handle: RunHandle | None = None,
) -> Iterator[AgentEvent]:
    """Generate one discussion contribution and post it to the room."""
    from .vertex_llm import complete

    yield AgentEvent("status", {"state": "running", "label": f"{participant} thinking…"})
    _DISCUSS_MODEL = None  # use DEFAULT_MODEL (claude-opus-4-8), only model available on this project

    room = get_room(repo_root, problem_id, room_id)
    if room is None:
        yield AgentEvent("error", {"message": f"Room {room_id} not found"})
        yield AgentEvent("done", {"reason": "error"})
        return

    transcript = transcript_text(room)
    knowledge = _knowledge_text(repo_root, participant)

    # Read problem statement (searches problems/<pid>.tex then every dataset store)
    prob_text = ""
    try:
        from .dataset_store import find_problem_tex
        prob_text = (find_problem_tex(repo_root, problem_id) or "")[:4000]
    except Exception:
        pass

    # Build system prompt
    if participant in MATHEMATICIAN_PERSONAS:
        mp = MATHEMATICIAN_PERSONAS[participant]
        system = (
            f"{mp['character']}\n\n"
            f"You are in a virtual research meeting (room: {room_id}) about problem {problem_id}. "
            f"Stay completely in character as {mp['display']}. "
            "Speak in first person, reference your own past work specifically "
            "(theorem names, paper titles, techniques), and engage critically with what others said. "
            "Be concise but substantive: 5–12 sentences or a structured list of mathematical points. "
            "Use LaTeX where it helps clarity. "
            "Reply with ONLY your spoken contribution — no meta-commentary, no 'as a mathematician' framing."
        )
    else:
        p = PERSONAS.get(participant, PERSONAS.get("coordinator", {}))
        system = (
            f"You are {participant} ({p.get('role', 'researcher')}) in a research meeting about {problem_id}. "
            "Be concise and mathematical. Use LaTeX where helpful. "
            "Reply with ONLY your spoken contribution."
        )

    # Build user prompt
    knowledge_section = (
        f"\n\n## Your Key Works and Tools\n{knowledge}\n"
        if knowledge else ""
    )
    problem_section = (
        f"\n\n## Problem Statement\n```latex\n{prob_text}\n```"
        if prob_text else ""
    )
    transcript_section = (
        f"\n\n## Meeting Transcript So Far\n{transcript}"
        if transcript.strip() else "\n\n*(You are the first to speak. Set the mathematical direction.)*"
    )

    prompt = textwrap.dedent(f"""
        You are attending a research meeting on problem **{problem_id}** (room: {room_id}).
        {knowledge_section}{problem_section}{transcript_section}

        Now contribute your perspective. Engage specifically with what was said, or if you are first,
        open with your characteristic approach. Be mathematically precise and reference your own work.
        Write ONLY your spoken contribution (no meta-commentary).
    """).strip()

    text = complete(prompt, system=system, max_tokens=1200, model=_DISCUSS_MODEL)

    if not text or not text.strip():
        yield AgentEvent("error", {"message": f"{participant}: empty response from LLM"})
        yield AgentEvent("done", {"reason": "error"})
        return

    text = text.strip()
    yield AgentEvent("text_delta", {"text": text})

    # Post directly to room JSON via Python (no curl)
    try:
        post_message(repo_root, problem_id, room_id, author=participant, body=text)
        log.info("meet/%s/%s: posted turn for %s (%d chars)", problem_id, room_id, participant, len(text))
    except Exception as exc:
        log.warning("meet/%s/%s: failed to post for %s: %s", problem_id, room_id, participant, exc)
        yield AgentEvent("error", {"message": str(exc)})
        yield AgentEvent("done", {"reason": "error"})
        return

    yield AgentEvent("done", {"reason": "end_turn"})


# ── Plan synthesis (direct LLM) ───────────────────────────────────────────────

def run_synthesis(
    repo_root: Path,
    problem_id: str,
    room_id: str,
    handle: RunHandle | None = None,
) -> Iterator[AgentEvent]:
    """Coordinator synthesizes a numbered action plan from the discussion."""
    from .vertex_llm import complete
    _SYNTH_MODEL = None  # use DEFAULT_MODEL (claude-opus-4-8), only model available on this project

    yield AgentEvent("status", {"state": "running", "label": "synthesizing plan…"})

    room = get_room(repo_root, problem_id, room_id)
    if room is None:
        yield AgentEvent("error", {"message": f"Room {room_id} not found"})
        yield AgentEvent("done", {"reason": "error"})
        return

    transcript = transcript_text(room)
    if not transcript.strip():
        yield AgentEvent("done", {"reason": "no_transcript"})
        return

    system = (
        "You are a research coordinator synthesizing an action plan from a mathematical discussion. "
        "Output ONLY valid JSON — no markdown fences, no explanation, just the JSON object."
    )

    prompt = textwrap.dedent(f"""
        You are synthesizing an action plan for problem {problem_id} based on this discussion:

        {transcript}

        Produce a JSON action plan with this exact structure:
        {{
          "summary": "one-sentence description of the overall mathematical approach agreed upon",
          "steps": [
            {{
              "idx": 0,
              "title": "short title",
              "body": "detailed description of what must be done mathematically",
              "agent": "solver-agent",
              "depends_on": []
            }}
          ]
        }}

        Rules:
        - 4–8 steps, each concrete and independently executable
        - "agent" must be one of: solver-agent, verifier-agent, critic-agent, strategist-agent
        - steps must follow logically from the discussion
        - Output ONLY the JSON object, nothing else
    """).strip()

    raw = complete(prompt, system=system, max_tokens=10000, model=_SYNTH_MODEL, thinking_budget=8000)

    if not raw:
        yield AgentEvent("error", {"message": "empty response from LLM for synthesis"})
        yield AgentEvent("done", {"reason": "error"})
        return

    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw.strip(), flags=re.MULTILINE)
    raw = raw.strip()

    try:
        plan_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("meet synthesis JSON parse error: %s\nraw: %s", exc, raw[:300])
        # Try to extract JSON from the response
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            try:
                plan_data = json.loads(m.group())
            except Exception:
                yield AgentEvent("error", {"message": f"JSON parse error: {exc}"})
                yield AgentEvent("done", {"reason": "error"})
                return
        else:
            yield AgentEvent("error", {"message": f"JSON parse error: {exc}"})
            yield AgentEvent("done", {"reason": "error"})
            return

    summary = plan_data.get("summary", "")
    steps = plan_data.get("steps", [])

    # Ensure idx fields are present
    for i, step in enumerate(steps):
        if "idx" not in step:
            step["idx"] = i

    try:
        set_plan(repo_root, problem_id, room_id, steps=steps, summary=summary)
        log.info("meet/%s/%s: plan synthesized (%d steps)", problem_id, room_id, len(steps))
    except Exception as exc:
        log.warning("meet/%s/%s: failed to set plan: %s", problem_id, room_id, exc)
        yield AgentEvent("error", {"message": str(exc)})
        yield AgentEvent("done", {"reason": "error"})
        return

    # Post summary message
    try:
        post_message(
            repo_root, problem_id, room_id,
            author="coordinator",
            body=f"**Action plan synthesized** ({len(steps)} steps):\n\n{summary}",
        )
    except Exception:
        pass

    yield AgentEvent("text_delta", {"text": summary})
    yield AgentEvent("done", {"reason": "end_turn"})


# ── Offline full discussion round ─────────────────────────────────────────────

# job_id → {"status": "running"|"done"|"error", ...}
_PUSH_JOBS: dict[str, dict] = {}


def push_job_status(job_id: str) -> dict | None:
    return _PUSH_JOBS.get(job_id)


def run_round_offline(
    repo_root: Path,
    problem_id: str,
    room_id: str,
    job_id: str,
    n_rounds: int = 3,
) -> None:
    """Run n_rounds of discussion for all non-human participants (blocking).

    Each participant speaks once per round in order. Uses direct Vertex AI
    completions — no tool loop, no curl. Messages post to room JSON immediately.
    """
    from datetime import datetime, timezone
    import time

    _PUSH_JOBS[job_id] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}

    try:
        room = get_room(repo_root, problem_id, room_id)
        if room is None:
            _PUSH_JOBS[job_id] = {"status": "error", "error": "room not found"}
            return

        participants = [p for p in room.get("participants", []) if p != "human" and p != "coordinator"]
        if not participants:
            _PUSH_JOBS[job_id] = {"status": "done", "turns": 0}
            return

        turns_done = 0
        for round_num in range(n_rounds):
            log.info("meet/%s/%s: round %d/%d", problem_id, room_id, round_num + 1, n_rounds)
            for participant in participants:
                try:
                    for ev in run_discussion_turn(repo_root, problem_id, room_id, participant):
                        if ev.type == "error":
                            log.warning("meet turn error (%s): %s", participant, ev.data)
                    turns_done += 1
                except Exception as exc:
                    log.warning("meet turn exception (%s): %s", participant, exc)
                # Pause between turns — shared NAIRR quota, so space out calls.
                time.sleep(30)
            # Longer pause between rounds to let the per-minute quota window slide
            if round_num < n_rounds - 1:
                log.info("meet/%s/%s: round %d done, pausing 90s before next round", problem_id, room_id, round_num + 1)
                time.sleep(90)

        _PUSH_JOBS[job_id] = {
            "status": "done",
            "turns": turns_done,
            "done_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        log.exception("push-round job %s failed", job_id)
        _PUSH_JOBS[job_id] = {"status": "error", "error": str(exc)}


# ── Step execution (tool loop, unchanged) ────────────────────────────────────

def run_step_execution(
    repo_root: Path,
    problem_id: str,
    room_id: str,
    step_idx: int,
    handle: RunHandle | None = None,
) -> Iterator[AgentEvent]:
    """Execute one plan step via a targeted solver agent."""
    room = get_room(repo_root, problem_id, room_id)
    if room is None:
        yield AgentEvent("error", {"message": f"Room {room_id} not found"})
        yield AgentEvent("done", {"reason": "error"})
        return

    plan = room.get("plan")
    if not plan:
        yield AgentEvent("error", {"message": "No plan synthesized yet"})
        yield AgentEvent("done", {"reason": "error"})
        return

    steps = plan.get("steps", [])
    if step_idx >= len(steps):
        yield AgentEvent("error", {"message": f"Step {step_idx} out of range"})
        yield AgentEvent("done", {"reason": "error"})
        return

    step = steps[step_idx]
    ws = _seed_workspace(repo_root, problem_id, extra_files={
        "step.json": json.dumps(step, indent=2, ensure_ascii=False),
        "meet_context.md": transcript_text(room),
    })

    executor_system = (
        f"You are a math solver agent executing one step of a proof plan for {problem_id}. "
        "You have read_file, write_file, and run_python tools. "
        "Your workspace has problem.tex, solution.tex (current best proof), "
        "step.json (the step you must execute), and meet_context.md (meeting context). "
        "Be rigorous."
    )

    prompt = textwrap.dedent(f"""
        You are executing Step {step_idx + 1} of the proof plan for {problem_id}.

        **Step title:** {step.get('title', '')}
        **Step description:**
        {step.get('body', '')}

        Your workspace has:
        - problem.tex: the problem statement
        - solution.tex: the current best proof (if any)
        - step.json: this step's details
        - meet_context.md: the full meeting discussion for context

        Instructions:
        1. Read problem.tex and step.json carefully
        2. Read solution.tex if it exists
        3. Perform the mathematical work described in the step
        4. Write your result/improvement to solution.tex

        Be rigorous. Produce a complete mathematical argument.
    """).strip()

    def on_done():
        updated = get_room(repo_root, problem_id, room_id)
        if updated and updated.get("plan"):
            executed = [e["step"] for e in updated["plan"].get("executed_steps", [])]
            if step_idx not in executed:
                mark_step_done(repo_root, problem_id, room_id, step_idx, "partial", "agent did not mark complete")

    yield from _run_agent(
        repo_root, ws, prompt,
        executor_system,
        handle,
        f"meet/{room_id}/step/{step_idx}",
        max_turns=_MAX_EXEC_TURNS,
        on_done=on_done,
    )
