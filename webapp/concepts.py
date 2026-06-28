"""Per-question concept and notation extractor."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .agent import AgentEvent

logger = logging.getLogger(__name__)


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


# Only claude-opus-4-8 (no version suffix) is available on the NAIRR Vertex project.
_VERTEX_CONCEPT_MODEL = "claude-opus-4-8"
# Gap between background extractions to avoid competing with solve-run quota.
_EXTRACTION_GAP_SECS = 20


def _call_llm(prompt: str, system: str) -> str | None:
    """Call Claude via Vertex for concept extraction."""
    from .llm import complete
    return complete(prompt, system=system, model=_VERTEX_CONCEPT_MODEL, max_tokens=8192)


def ensure_all_concepts(repo_root: Path, q_titles: dict | None = None) -> None:
    """Background: extract concepts for any question missing a concepts file.

    Spaces out extractions by _EXTRACTION_GAP_SECS to avoid competing
    with concurrent solve-run quota on Vertex.
    """
    logger.info("ensure_all_concepts: checking q1-q10...")
    first = True
    for i in range(1, 11):
        qid = f"q{i}"
        if load_concepts(repo_root, qid):
            logger.debug("ensure_all_concepts: %s already has concepts, skipping", qid)
            continue
        if not first:
            time.sleep(_EXTRACTION_GAP_SECS)
        first = False
        title = (q_titles or {}).get(qid, qid)
        logger.info("ensure_all_concepts: extracting concepts for %s", qid)
        results = list(generate_concepts(repo_root, qid, title))
        done = next((e for e in results if e.type == "done"), None)
        if done and done.data.get("count", 0) > 0:
            logger.info("ensure_all_concepts: %s — %d concepts extracted", qid, done.data["count"])
        else:
            err = next((e for e in results if e.type == "error"), None)
            logger.warning("ensure_all_concepts: %s failed — %s", qid,
                           err.data.get("message") if err else "unknown")


def ensure_fp2_concepts(repo_root: Path) -> None:
    """Background: extract concepts for any first_proof_2 problem missing a concepts file.

    Mirrors ensure_all_concepts but reads problem statements from the dataset
    store rather than problems/*.tex files.
    """
    try:
        from .dataset_store import list_problems as ds_list, get_problem as ds_get
    except Exception as exc:
        logger.warning("ensure_fp2_concepts: could not import dataset_store — %s", exc)
        return

    problems = ds_list("first_proof_2") or []
    if not problems:
        logger.debug("ensure_fp2_concepts: no first_proof_2 problems found, skipping")
        return

    logger.info("ensure_fp2_concepts: checking %d first_proof_2 problems…", len(problems))
    first = True
    for prob in problems:
        pid = prob.get("id", "")
        if not pid:
            continue
        if load_concepts(repo_root, pid):
            logger.debug("ensure_fp2_concepts: %s already has concepts, skipping", pid)
            continue
        if not first:
            time.sleep(_EXTRACTION_GAP_SECS)
        first = False
        title = prob.get("title", pid)
        # Fetch full record to get the statement/tex
        full = ds_get("first_proof_2", pid)
        if not full:
            logger.warning("ensure_fp2_concepts: could not load problem record for %s", pid)
            continue
        statement = full.get("statement") or full.get("tex") or ""
        if not statement:
            logger.warning("ensure_fp2_concepts: %s has no statement text, skipping", pid)
            continue
        logger.info("ensure_fp2_concepts: extracting concepts for %s", pid)
        results = list(generate_concepts(repo_root, pid, title, problem_tex=statement))
        done = next((e for e in results if e.type == "done"), None)
        if done and done.data.get("count", 0) > 0:
            logger.info("ensure_fp2_concepts: %s — %d concepts extracted", pid, done.data["count"])
        else:
            err = next((e for e in results if e.type == "error"), None)
            logger.warning(
                "ensure_fp2_concepts: %s failed — %s", pid,
                err.data.get("message") if err else "unknown",
            )


def generate_concepts(
    repo_root: Path, qid: str, title: str, problem_tex: str | None = None
) -> Iterator[AgentEvent]:
    """Call Claude to extract concepts from the problem, save and yield AgentEvents.

    If *problem_tex* is provided it is used directly; otherwise the text is read
    from problems/{qid}.tex (first_proof_1 behaviour).
    """
    if problem_tex is None:
        problem_path = repo_root / "problems" / f"{qid}.tex"
        if not problem_path.is_file():
            yield AgentEvent("error", {"message": f"Problem file not found: {qid}.tex"})
            yield AgentEvent("done", {"reason": "error"})
            return
        problem_tex = problem_path.read_text(encoding="utf-8", errors="replace")

    yield AgentEvent("status", {"state": "running", "message": "Extracting concepts with Claude…"})

    problem_tex = problem_tex[:6000]
    prompt = _EXTRACT_PROMPT.format(qid=qid, title=title, problem_tex=problem_tex)
    raw = _call_llm(prompt, _EXTRACT_SYSTEM)

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
        "_model": "claude-opus-4-8",
        "_qid": qid,
    }
    save_concepts(repo_root, qid, valid)

    yield AgentEvent("text_delta", {"text": f"Extracted {len(valid)} concepts for {qid}.\n"})
    yield AgentEvent("done", {"reason": "end_turn", "count": len(valid), "concepts": valid})
