"""API helpers for browsing RMA pipeline proof outputs."""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROBLEMS = [f"q{i}" for i in range(1, 11)]


def _proof_outputs_root() -> Path:
    env = os.environ.get("RMA_PROOF_OUTPUTS")
    if env:
        return Path(env)
    # Default: sibling ResearchMathAgent repo
    candidate = REPO_ROOT.parent / "ResearchMathAgent" / "outputs" / "first_proof_1"
    if candidate.is_dir():
        return candidate
    # Fallback: same repo outputs
    return REPO_ROOT / "outputs" / "first_proof_1"


def list_experiments() -> list[dict]:
    root = _proof_outputs_root()
    if not root.is_dir():
        return []
    exps = []
    for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        problems = {}
        for qid in _PROBLEMS:
            status_path = d / qid / "artifacts" / "status.json"
            sol_path = d / f"{qid}_solution.tex"
            if status_path.is_file():
                try:
                    s = json.loads(status_path.read_text())
                    problems[qid] = {"status": s.get("status", "unknown"), "has_solution": sol_path.is_file()}
                except Exception:
                    problems[qid] = {"status": "error", "has_solution": False}
            else:
                problems[qid] = {"status": "not_started", "has_solution": False}
        exps.append({"name": d.name, "problems": problems})
    return exps


def get_proof(exp_name: str, problem_id: str) -> dict | None:
    root = _proof_outputs_root()
    exp_dir = root / exp_name
    if not exp_dir.is_dir():
        return None
    sol_path = exp_dir / f"{problem_id}_solution.tex"
    status_path = exp_dir / problem_id / "artifacts" / "status.json"
    ver_dir = exp_dir / problem_id / "artifacts" / "verifications"
    partial_path = exp_dir / problem_id / "partial_output.tex"

    status = {}
    if status_path.is_file():
        try:
            status = json.loads(status_path.read_text())
        except Exception:
            pass

    verification = {}
    if ver_dir.is_dir():
        vfiles = sorted(ver_dir.glob("verification_*.json"))
        if vfiles:
            try:
                verification = json.loads(vfiles[-1].read_text())
            except Exception:
                pass

    solution_tex = ""
    if sol_path.is_file():
        solution_tex = sol_path.read_text(encoding="utf-8", errors="replace")
    elif partial_path.is_file():
        solution_tex = partial_path.read_text(encoding="utf-8", errors="replace")

    return {
        "exp": exp_name,
        "problem_id": problem_id,
        "status": status.get("status", "not_started"),
        "solution_tex": solution_tex,
        "verification": verification,
    }
