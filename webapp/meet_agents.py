"""Agent runners for virtual meeting rooms.

Each agent contributes one "turn" to the discussion.
The coordinator has a special "synthesize" mode that produces the plan.
Plan execution runs each step as a targeted issue agent.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import textwrap
from pathlib import Path
from typing import Iterator

from .agent import AgentEvent
from .issue_agents import _run_agent, _seed_workspace
from .runs import RunHandle
from .meet import PERSONAS, get_room, post_message, set_plan, mark_step_done, transcript_text

_API_BASE = "http://localhost:8000"
_MAX_DISCUSSION_TURNS = 4
_MAX_SYNTH_TURNS = 8
_MAX_EXEC_TURNS = 30


# ── Persona system prompts ────────────────────────────────────────────────────

def _persona_system(participant: str, problem_id: str) -> str:
    p = PERSONAS.get(participant, PERSONAS["coordinator"])
    return (
        f"You are {participant} in a virtual research meeting about math problem {problem_id}. "
        f"Role: {p['role']} {p['style']}\n"
        "You have NO tools (no Bash, no file access). Only write text. "
        "Be concise and mathematical. Use LaTeX notation where helpful. "
        "You will post your response via curl at the end."
    )


def _coordinator_synth_system(problem_id: str) -> str:
    return (
        f"You are the coordinator synthesizing an action plan for math problem {problem_id}. "
        "You have Bash available (to call the API via curl). No other tools. "
        "Read the discussion transcript, then produce a concrete numbered plan and post it via the API."
    )


def _executor_system(problem_id: str) -> str:
    return (
        f"You are a math solver agent executing one step of a proof plan for {problem_id}. "
        "You have Read, Write, Edit, Bash, and Glob tools. "
        "Your workspace has problem.tex, preamble.tex, solution.tex (current best proof), "
        "and step.json (the step you must execute). "
        "Use Bash(curl) to post progress to the meet room and issue tracker. "
        "Write improvements to solution.tex. Be rigorous."
    )


# ── Discussion turn ───────────────────────────────────────────────────────────

def run_discussion_turn(
    repo_root: Path,
    problem_id: str,
    room_id: str,
    participant: str,
    handle: RunHandle | None = None,
) -> Iterator[AgentEvent]:
    """Run one discussion turn for `participant` in the meeting room."""
    room = get_room(repo_root, problem_id, room_id)
    if room is None:
        yield AgentEvent("error", {"message": f"Room {room_id} not found"})
        yield AgentEvent("done", {"reason": "error"})
        return

    transcript = transcript_text(room)
    persona = PERSONAS.get(participant, PERSONAS["coordinator"])

    # Build workspace (no proof needed for discussion turns, just context)
    base = Path(tempfile.gettempdir()) / "rma_meet_agents"
    base.mkdir(parents=True, exist_ok=True)
    ws = Path(tempfile.mkdtemp(prefix=f"meet_{problem_id}_", dir=base))

    # Write context files
    (ws / "transcript.md").write_text(transcript, encoding="utf-8")
    prob = repo_root / "problems" / f"{problem_id}.tex"
    if prob.is_file():
        shutil.copyfile(prob, ws / "problem.tex")

    prompt = textwrap.dedent(f"""
        You are **{participant}** ({persona['role']}).

        The meeting transcript is in transcript.md. Read it.
        Also read problem.tex for the problem statement.

        Add your contribution to the discussion. Be direct and mathematical.
        Your response should:
        - Engage with what was already said (agree, challenge, or extend)
        - Contribute a clear mathematical point (a strategy, a gap, a check)
        - Be focused: 3–8 sentences or a short bullet list

        After formulating your response, post it to the meeting room:

        curl -s -X POST {_API_BASE}/api/meets/{problem_id}/{room_id}/message \\
          -H 'Content-Type: application/json' \\
          -d '{{"author": "{participant}", "body": "YOUR CONTRIBUTION HERE"}}'

        Replace YOUR CONTRIBUTION HERE with your actual message (escape double quotes).
        Then confirm the post succeeded.
    """).strip()

    yield from _run_agent(
        ws, prompt,
        _persona_system(participant, problem_id),
        handle,
        f"meet/{room_id}/{participant}",
        max_turns=_MAX_DISCUSSION_TURNS,
        allowed_tools="Read Bash",
    )


# ── Plan synthesis ────────────────────────────────────────────────────────────

def run_synthesis(
    repo_root: Path,
    problem_id: str,
    room_id: str,
    handle: RunHandle | None = None,
) -> Iterator[AgentEvent]:
    """Coordinator synthesizes a numbered action plan from the discussion."""
    room = get_room(repo_root, problem_id, room_id)
    if room is None:
        yield AgentEvent("error", {"message": f"Room {room_id} not found"})
        yield AgentEvent("done", {"reason": "error"})
        return

    transcript = transcript_text(room)

    base = Path(tempfile.gettempdir()) / "rma_meet_agents"
    base.mkdir(parents=True, exist_ok=True)
    ws = Path(tempfile.mkdtemp(prefix=f"synth_{problem_id}_", dir=base))
    (ws / "transcript.md").write_text(transcript, encoding="utf-8")

    prompt = textwrap.dedent(f"""
        You are the **coordinator** for a research meeting on problem {problem_id}.

        The full discussion is in transcript.md. Read it carefully.

        Your task: synthesize a concrete, executable action plan.

        The plan MUST be valid JSON in this exact format — write it to plan.json:
        {{
          "summary": "one-sentence description of overall approach",
          "steps": [
            {{
              "idx": 0,
              "title": "short title",
              "body": "detailed description of what must be done",
              "agent": "solver-agent | verifier-agent | critic-agent",
              "depends_on": []
            }},
            ...
          ]
        }}

        Rules for steps:
        - Each step must be concrete and independently executable
        - 4–10 steps total
        - Assign "agent" based on the nature of the work
        - "depends_on" lists idx values of prerequisite steps

        After writing plan.json, read it back to verify it parses correctly:
        cat plan.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'OK: {{len(d[\"steps\"])}} steps')"

        Then post the plan to the meet room:
        curl -s -X POST {_API_BASE}/api/meets/{problem_id}/{room_id}/plan \\
          -H 'Content-Type: application/json' \\
          -d @plan.json

        Finally post a summary message to the room:
        curl -s -X POST {_API_BASE}/api/meets/{problem_id}/{room_id}/message \\
          -H 'Content-Type: application/json' \\
          -d '{{"author": "coordinator", "body": "Plan synthesized. Ready to execute."}}'
    """).strip()

    yield from _run_agent(
        ws, prompt,
        _coordinator_synth_system(problem_id),
        handle,
        f"meet/{room_id}/synthesize",
        max_turns=_MAX_SYNTH_TURNS,
    )


# ── Step execution ────────────────────────────────────────────────────────────

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
        4. Write your result/improvement to solution.tex (or a new file if appropriate)
        5. Post a progress update:
           curl -s -X POST {_API_BASE}/api/meets/{problem_id}/{room_id}/message \\
             -H 'Content-Type: application/json' \\
             -d '{{"author": "{step.get("agent", "solver-agent")}", "body": "Step {step_idx+1} progress: DESCRIPTION"}}'
        6. When done, mark the step complete:
           curl -s -X POST {_API_BASE}/api/meets/{problem_id}/{room_id}/steps/{step_idx}/done \\
             -H 'Content-Type: application/json' \\
             -d '{{"outcome": "success", "notes": "brief summary of what was accomplished"}}'

        Be rigorous. If you cannot complete the step, post an explanation and mark it
        with outcome "partial" instead of "success".
    """).strip()

    def on_done():
        # If agent didn't mark done itself, mark it with 'partial'
        updated = get_room(repo_root, problem_id, room_id)
        if updated and updated.get("plan"):
            executed = [e["step"] for e in updated["plan"].get("executed_steps", [])]
            if step_idx not in executed:
                mark_step_done(repo_root, problem_id, room_id, step_idx, "partial", "agent did not mark complete")

    yield from _run_agent(
        ws, prompt,
        _executor_system(problem_id),
        handle,
        f"meet/{room_id}/step/{step_idx}",
        max_turns=_MAX_EXEC_TURNS,
        on_done=on_done,
    )
