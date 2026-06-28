"""LLM-based proof evaluation using the First Proof benchmark rubric (Appendix E)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_EVAL_SYSTEM = """You are an expert mathematician evaluating a research-level mathematical proof.
Evaluate the proof along the four fine-grained dimensions from the First Proof benchmark (Appendix E):

1. **Final Answer Accuracy** (0 or 1): Is the final answer/bound/construction claimed in the proof correct, independent of the derivation process?
   - 1 = the claimed conclusion is mathematically correct
   - 0 = the claimed conclusion is wrong or cannot be determined

2. **Logical Correctness** (0–5): Does each step follow valid logical inferences with correct application of definitions, theorems, and assumptions, with no invalid deductions?
   - 0 = severely flawed logic throughout
   - 1 = major logical errors that invalidate the proof
   - 2 = significant errors but partial correctness
   - 3 = mostly correct with minor gaps or errors
   - 4 = nearly flawless, only trivial issues
   - 5 = every step is logically sound and rigorously justified

3. **Proof Completeness** (0–5): Are all essential steps explicitly provided, with no missing arguments or unjustified leaps?
   - 0 = proof is largely incomplete or a sketch
   - 1 = major steps missing
   - 2 = several important cases or lemmas left unjustified
   - 3 = mostly complete but some steps hand-waved
   - 4 = nearly complete, only minor details omitted
   - 5 = fully explicit, every step justified

4. **Proof Clarity** (0–5): Is the proof coherent, well-structured, and easy for a mathematician in the field to follow?
   - 0 = incomprehensible or disorganized
   - 1 = very hard to follow
   - 2 = somewhat unclear
   - 3 = readable but room for improvement
   - 4 = clear and well-organized
   - 5 = exceptionally clear, well-structured, and readable

Return ONLY a JSON object with exactly these keys (no prose, no markdown fencing):
{
  "answer_accuracy": <0 or 1>,
  "logical_correctness": <integer 0..5>,
  "proof_completeness": <integer 0..5>,
  "proof_clarity": <integer 0..5>,
  "verdict": "<one sentence overall assessment>",
  "notes": "<2-4 sentences on main strengths and weaknesses>"
}"""

_EVAL_PROMPT = """Problem statement (LaTeX):
<problem>
{problem}
</problem>

Proof to evaluate (LaTeX source):
<proof>
{proof}
</proof>

Carefully evaluate this proof on all four dimensions and return the JSON scores."""


def _eval_path(repo_root: Path, problem_id: str) -> Path:
    return repo_root / "documents" / "questions" / problem_id / "proof_eval.json"


def load_proof_eval(repo_root: Path, problem_id: str) -> dict | None:
    p = _eval_path(repo_root, problem_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_proof_eval(repo_root: Path, problem_id: str, result: dict) -> None:
    p = _eval_path(repo_root, problem_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


def evaluate_proof(repo_root: Path, problem_id: str, dataset: str = "first_proof_1",
                   force: bool = False) -> dict:
    """Run LLM evaluation of the best proof. Returns the result dict (and caches it)."""
    if not force:
        cached = load_proof_eval(repo_root, problem_id)
        if cached:
            return cached

    # Load the problem statement (legacy first_proof_1 .tex, else the dataset store).
    prob_path = repo_root / "problems" / f"{problem_id}.tex"
    if prob_path.is_file():
        problem_text = prob_path.read_text(encoding="utf-8", errors="replace")[:6000]
    else:
        try:
            from .dataset_store import get_problem
            p = get_problem(dataset, problem_id) or {}
            problem_text = (p.get("tex") or p.get("statement") or "")[:6000]
        except Exception:
            problem_text = ""
    if not problem_text:
        return {"error": f"Problem statement not found: {dataset}/{problem_id}"}

    # Load the best proof
    try:
        from .proofs import get_best_proof
        best = get_best_proof(problem_id, dataset)
        if not best or not best.get("solution_tex"):
            return {"error": "No best proof available — run the agent and consolidate first"}
        proof_tex = best["solution_tex"][:15000]
    except Exception as e:
        return {"error": f"Could not load best proof: {e}"}

    prompt = _EVAL_PROMPT.format(problem=problem_text, proof=proof_tex)

    try:
        from .llm import complete
        raw = complete(prompt, system=_EVAL_SYSTEM, max_tokens=1024)
        if not raw:
            return {"error": "LLM returned empty response"}
    except Exception as e:
        return {"error": f"LLM call failed: {e}"}

    # Parse the JSON
    raw = raw.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        import re
        m = re.search(r'\{[^{}]*"answer_accuracy"[^{}]*\}', raw, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(0))
            except Exception:
                return {"error": "Could not parse LLM JSON response", "raw": raw[:500]}
        else:
            return {"error": "Could not parse LLM JSON response", "raw": raw[:500]}

    # Validate and clamp
    result["answer_accuracy"] = max(0, min(1, int(result.get("answer_accuracy", 0))))
    for key in ("logical_correctness", "proof_completeness", "proof_clarity"):
        result[key] = max(0, min(5, int(result.get(key, 0))))

    _save_proof_eval(repo_root, problem_id, result)
    logger.info("Proof eval for %s: %s", problem_id, result)
    return result
