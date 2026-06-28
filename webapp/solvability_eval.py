"""Solvability evaluation using Claude Opus.

For each problem, runs a single-turn Opus prompt that reads the problem
statement and returns a structured JSON score (0-100) representing the
probability that a state-of-the-art AI research agent could produce a
mathematically correct and complete proof.

Results are cached in documents/questions/{qid}/solvability_eval.json so
re-evaluation is only triggered when the cache is missing or explicitly
refreshed.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_EVAL_MODEL = "claude-opus-4-8"
_EVAL_TIMEOUT = 180  # seconds per problem

_SYSTEM_PROMPT = (
    "You are a world-class mathematician and AI capabilities researcher. "
    "You will read a research-level mathematics problem and assess how likely "
    "a state-of-the-art AI research agent (using Claude with tool access, "
    "able to run code and search the web) could produce a mathematically "
    "correct and complete proof within a few hours of compute time. "
    "Be rigorous, honest, and calibrated in your assessment."
)

_USER_PROMPT_TEMPLATE = """You are evaluating the AI solvability of the following research-level mathematics problem:

--- BEGIN PROBLEM ---
{problem_tex}
--- END PROBLEM ---

Assess the probability (0–100) that a state-of-the-art AI research agent (Claude Opus with code execution, literature search, and mathematical reasoning) could produce a mathematically CORRECT and COMPLETE proof of this problem within a few hours.

Scoring guide:
- 0–10: Requires a fundamental mathematical breakthrough; no AI can do this today
- 10–25: Extremely hard; requires deep novelty beyond current AI; very unlikely
- 25–40: Very hard; requires multiple non-trivial insights; AI might get partial progress only
- 40–55: Hard but structured; AI could solve it with significant effort if it knows the right tools
- 55–70: Moderately difficult; AI has a real chance if it identifies the right approach
- 70–85: Well within reach; techniques are known, AI needs to execute carefully
- 85–100: Straightforward for a well-equipped AI; mostly technical execution

Consider:
1. Is the required mathematics within the training distribution of modern LLMs?
2. Are the key techniques (tools, lemmas, arguments) well-documented in the literature?
3. How much genuine novelty or creativity is required beyond known methods?
4. Is the problem verifiable step-by-step, or does it require a single insight "flash"?
5. How long/complex is a complete proof likely to be?

Respond with ONLY valid JSON, no markdown, no explanation outside the JSON:
{{
  "score": <integer 0-100>,
  "confidence": <"high" | "medium" | "low">,
  "reasoning": "<2-4 sentence explanation of your score>",
  "key_obstacles": ["<obstacle 1>", "<obstacle 2>", "<obstacle 3>"],
  "positive_factors": ["<factor 1>", "<factor 2>"],
  "estimated_proof_length": "<short | medium | long | very_long>"
}}"""


def _eval_cache_path(repo_root: Path, qid: str) -> Path:
    return repo_root / "documents" / "questions" / qid / "solvability_eval.json"


def load_eval(repo_root: Path, qid: str) -> dict | None:
    """Return cached evaluation dict, or None if missing."""
    p = _eval_cache_path(repo_root, qid)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_eval(repo_root: Path, qid: str, data: dict) -> None:
    p = _eval_cache_path(repo_root, qid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _call_vertex(prompt: str, system: str, model: str = _EVAL_MODEL) -> str | None:
    """Call the LLM with a single prompt and return the text result."""
    from .llm import complete
    return complete(prompt, system=system, model=model, max_tokens=4096)


def _parse_score_json(text: str) -> dict | None:
    """Extract JSON object from model response text."""
    if not text:
        return None
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # Find first {...} block
    m = re.search(r'\{[^{}]*"score"[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def evaluate_problem(repo_root: Path, qid: str, force: bool = False) -> dict | None:
    """Run solvability evaluation for one problem. Returns the evaluation dict."""
    if not force:
        cached = load_eval(repo_root, qid)
        if cached:
            return cached

    problem_path = repo_root / "problems" / f"{qid}.tex"
    if not problem_path.is_file():
        return None

    problem_tex = problem_path.read_text(encoding="utf-8", errors="replace")
    preamble_path = repo_root / "problems" / "preamble.tex"
    if preamble_path.is_file():
        preamble = preamble_path.read_text(encoding="utf-8", errors="replace")
        # Prepend minimal preamble context (macro definitions only)
        macro_lines = [l for l in preamble.splitlines()
                       if l.strip().startswith(r'\newcommand') or
                          l.strip().startswith(r'\DeclareMathOperator') or
                          l.strip().startswith(r'\def')]
        if macro_lines:
            problem_tex = "% Relevant macro definitions:\n" + "\n".join(macro_lines) + "\n\n" + problem_tex

    prompt = _USER_PROMPT_TEMPLATE.format(problem_tex=problem_tex[:8000])
    raw = _call_vertex(prompt, _SYSTEM_PROMPT)
    if not raw:
        return None

    parsed = _parse_score_json(raw)
    if not parsed or "score" not in parsed:
        return None

    score = int(max(0, min(100, parsed["score"])))
    result = {
        "qid": qid,
        "score": score,
        "confidence": parsed.get("confidence", "medium"),
        "reasoning": str(parsed.get("reasoning", "")),
        "key_obstacles": parsed.get("key_obstacles", []),
        "positive_factors": parsed.get("positive_factors", []),
        "estimated_proof_length": parsed.get("estimated_proof_length", "unknown"),
        "model": _EVAL_MODEL,
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _save_eval(repo_root, qid, result)
    return result


def evaluate_all(repo_root: Path, force: bool = False) -> dict[str, dict]:
    """Evaluate all q1-q10 in parallel. Returns {qid: eval_dict}."""
    results: dict[str, dict | None] = {}
    lock = threading.Lock()

    def _worker(qid: str) -> None:
        ev = evaluate_problem(repo_root, qid, force=force)
        with lock:
            results[qid] = ev

    threads = [
        threading.Thread(target=_worker, args=(f"q{i}",), daemon=True)
        for i in range(1, 11)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=_EVAL_TIMEOUT + 30)

    return {k: v for k, v in results.items() if v is not None}


def ensure_all_evaluated(repo_root: Path) -> None:
    """Background: evaluate any problem missing a cached score."""
    missing = [
        f"q{i}" for i in range(1, 11)
        if not _eval_cache_path(repo_root, f"q{i}").is_file()
    ]
    if not missing:
        return
    for qid in missing:
        evaluate_problem(repo_root, qid, force=False)
