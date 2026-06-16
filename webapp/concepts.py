"""Per-question concept and notation extractor."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .agent import AgentEvent


def _concepts_path(repo_root: Path, qid: str) -> Path:
    return repo_root / "documents" / "questions" / qid / "concepts.json"


def load_concepts(repo_root: Path, qid: str) -> list[dict]:
    p = _concepts_path(repo_root, qid)
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_concepts(repo_root: Path, qid: str, concepts: list[dict]) -> None:
    p = _concepts_path(repo_root, qid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(concepts, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Agent-driven extraction ─────────────────────────────────────────────────

_EXTRACT_SYSTEM = (
    "You are a mathematical exposition expert. Given a research-level math problem, "
    "extract every non-trivial concept, mathematical object, and notation that appears "
    "or is implicitly required. For each, give a precise definition and a concrete example. "
    "Focus on concepts that a well-prepared graduate student might still need to look up. "
    "Skip elementary undergraduate material (limits, derivatives, basic linear algebra) "
    "unless they appear in a specialized form central to this problem."
)

_EXTRACT_PROMPT = """\
Problem ID: {qid}
Title: {title}

Problem statement (LaTeX):
{problem_tex}

Extract all core concepts, mathematical objects, specialized notation, and key theorems \
referenced or implicitly required by this problem. Be thorough but focused: include \
concepts a graduate student in a neighboring field would not immediately know.

Return ONLY valid JSON — no markdown fences, no text outside the array:
[
  {{
    "name": "concept name (plain English)",
    "notation": "LaTeX notation string, or empty string if none",
    "category": "core|background|notation|theorem",
    "definition": "Precise 1-3 sentence mathematical definition.",
    "example": "A concrete, specific example that illustrates the concept. Make it simple but meaningful.",
    "related": ["related concept 1", "related concept 2"]
  }}
]

Categories:
- core: directly appears in the problem statement and is central
- background: required theoretical context/prerequisite
- notation: specialized notation or abbreviation used in the problem
- theorem: a named theorem that is directly invoked or needed

Order: core first, then background, then theorem, then notation.
Aim for 8-16 entries covering all essential mathematical content.
"""


def _call_claude_json(prompt: str, system: str, model: str = "claude-sonnet-4-6") -> str | None:
    binary = shutil.which("claude")
    if not binary:
        return None
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    cmd = [binary, "-p", prompt, "--output-format", "json", "--model", model,
           "--no-session-persistence", "--append-system-prompt", system]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
        if r.returncode != 0:
            return None
        obj = json.loads(r.stdout)
        return obj.get("result") or obj.get("text") or ""
    except Exception:
        return None


def generate_concepts(repo_root: Path, qid: str, title: str) -> Iterator[AgentEvent]:
    """Call Claude to extract concepts from the problem, save and yield AgentEvents."""
    problem_path = repo_root / "problems" / f"{qid}.tex"
    if not problem_path.is_file():
        yield AgentEvent("error", {"message": f"Problem file not found: {qid}.tex"})
        yield AgentEvent("done", {"reason": "error"})
        return

    yield AgentEvent("status", {"state": "running", "message": "Extracting concepts with Claude…"})

    problem_tex = problem_path.read_text(encoding="utf-8", errors="replace")[:6000]
    prompt = _EXTRACT_PROMPT.format(qid=qid, title=title, problem_tex=problem_tex)
    raw = _call_claude_json(prompt, _EXTRACT_SYSTEM)

    if not raw:
        yield AgentEvent("error", {"message": "Claude returned no response."})
        yield AgentEvent("done", {"reason": "error"})
        return

    raw = raw.strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        raw = m.group(0)

    try:
        concepts = json.loads(raw)
    except Exception:
        yield AgentEvent("error", {"message": f"Could not parse JSON response: {raw[:300]}"})
        yield AgentEvent("done", {"reason": "error"})
        return

    # Validate and normalize
    valid = []
    for c in concepts:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        valid.append({
            "name": str(c.get("name", "")),
            "notation": str(c.get("notation", "")),
            "category": str(c.get("category", "background")),
            "definition": str(c.get("definition", "")),
            "example": str(c.get("example", "")),
            "related": list(c.get("related", [])),
        })

    # Add metadata
    meta = {
        "_generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_model": "claude-sonnet-4-6",
        "_qid": qid,
    }
    save_concepts(repo_root, qid, valid)

    yield AgentEvent("text_delta", {"text": f"Extracted {len(valid)} concepts for {qid}.\n"})
    yield AgentEvent("done", {"reason": "end_turn", "count": len(valid), "concepts": valid})
