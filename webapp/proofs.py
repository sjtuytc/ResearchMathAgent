"""API helpers for browsing RMA pipeline proof outputs."""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROBLEMS = [f"q{i}" for i in range(1, 11)]
_RECENT_SECS = 24 * 3600


def _proof_outputs_root(dataset: str = "first_proof_1") -> Path:
    env = os.environ.get("RMA_PROOF_OUTPUTS")
    if env:
        p = Path(env)
        # If env points to first_proof_1 root, adapt for other datasets
        if dataset != "first_proof_1":
            p = p.parent / dataset
        return p
    candidate = REPO_ROOT.parent / "ResearchMathAgent" / "outputs" / dataset
    if candidate.is_dir():
        return candidate
    return REPO_ROOT / "outputs" / dataset


def _is_skeleton(name: str) -> bool:
    return "rma-skeleton" in name


_MIN_TEX_BYTES = 500  # files smaller than this are stubs/placeholders


def _find_solution_tex(exp_dir: Path, problem_id: str) -> Path | None:
    """Return the best (largest non-stub) solution .tex file for a problem in a run."""
    candidates: list[Path] = []

    def _add(p: Path) -> None:
        if p.is_file() and p.stat().st_size >= _MIN_TEX_BYTES:
            candidates.append(p)

    # Primary: <exp>/<pid>_solution.tex
    _add(exp_dir / f"{problem_id}_solution.tex")
    # Old format: <exp>/<pid>_proof.tex
    _add(exp_dir / f"{problem_id}_proof.tex")
    # Refinements (prefer later/larger)
    ref_dir = exp_dir / problem_id / "artifacts" / "refinements"
    if ref_dir.is_dir():
        for p in sorted(ref_dir.glob("refined_solution_*.tex"), reverse=True):
            _add(p)
    # Proposal fallback
    prop_dir = exp_dir / problem_id / "artifacts" / "proposals"
    if prop_dir.is_dir():
        for p in sorted(prop_dir.glob("proposal_*.tex")):
            _add(p)

    if not candidates:
        return None
    # Prefer the largest file (most content)
    return max(candidates, key=lambda p: p.stat().st_size)


def _score_problem_in_run(exp_dir: Path, problem_id: str) -> tuple[int, dict]:
    """Return (score, info_dict) for a problem in a run directory.

    Score: verification.passed → +1000; +max(0, 100-issue_count); 0 if no status.
    info_dict has: source_run, model, created_at, updated_at,
                   verification_passed, issue_count, has_solution.
    """
    source_run = exp_dir.name
    info: dict = {
        "source_run": source_run,
        "model": None,
        "created_at": None,
        "updated_at": None,
        "verification_passed": False,
        "issue_count": 100,
        "has_solution": False,
    }

    # Check solution exists
    sol = _find_solution_tex(exp_dir, problem_id)
    if sol is None:
        return -1, info
    info["has_solution"] = True

    # Read per-problem metadata.json
    meta_path = exp_dir / problem_id / "artifacts" / "metadata.json"
    if meta_path.is_file():
        try:
            m = json.loads(meta_path.read_text())
            info["model"] = m.get("model_name") or _model_from_name(source_run)
            info["created_at"] = m.get("created_at")
            info["updated_at"] = m.get("updated_at")
        except Exception:
            pass
    if not info["model"]:
        info["model"] = _model_from_name(source_run)
    if not info["created_at"]:
        info["created_at"] = _date_from_name(source_run)

    # Read status.json
    status_path = exp_dir / problem_id / "artifacts" / "status.json"
    score = 0
    if status_path.is_file():
        try:
            s = json.loads(status_path.read_text())
            v = s.get("verification", {})
            passed = bool(v.get("passed", False))
            issue_count = int(v.get("issue_count", 100))
            info["verification_passed"] = passed
            info["issue_count"] = issue_count
            score = (1000 if passed else 0) + max(0, 100 - issue_count)
        except Exception:
            pass

    # Tiebreaker: date encoded in exp_name (newer = higher score)
    date_score = _date_score_from_name(source_run) / 1e6
    score_float = score + date_score

    return score_float, info


_MONTHS = {m: i for i, m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1
)}


def _model_from_name(exp_name: str) -> str:
    """Extract a model label from an experiment name."""
    import re
    m = re.search(r'_(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\d+_(.+)$', exp_name, re.IGNORECASE)
    if m:
        return m.group(2)
    parts = exp_name.rsplit("_", 1)
    return parts[-1] if len(parts) > 1 else exp_name


def _date_from_name(exp_name: str) -> str:
    """Extract a human-readable date string from an experiment name."""
    import re
    m = re.search(r'_((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\d+)', exp_name, re.IGNORECASE)
    return m.group(1) if m else ""


def _date_score_from_name(exp_name: str) -> int:
    """Return a numeric date score (higher = more recent) parsed from an experiment name."""
    import re
    m = re.search(r'_(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(\d+)', exp_name, re.IGNORECASE)
    if not m:
        return 0
    mon = _MONTHS.get(m.group(1).lower(), 0)
    day = int(m.group(2))
    vm = re.search(r'_v(\d+)_', exp_name)
    ver = int(vm.group(1)) if vm else 0
    return mon * 100 + day + ver * 10000


# ── best-folder helpers ──────────────────────────────────────────────────────

def _best_dir(dataset: str = "first_proof_1") -> Path:
    return _proof_outputs_root(dataset) / "best"


def consolidate_best(dataset: str = "first_proof_1",
                     compile_pdfs: bool = True) -> dict[str, dict]:
    """Scan all non-skeleton runs, write outputs/<dataset>/best/<pid>/ with
    solution.tex + best_meta.json (+ solution.pdf if compile_pdfs=True).
    Returns mapping pid → best_meta."""
    root = _proof_outputs_root(dataset)
    if not root.is_dir():
        return {}

    problems = _PROBLEMS if dataset == "first_proof_1" else _discover_problems(root)

    best: dict[str, tuple[float, dict, Path]] = {}  # pid → (score, info, sol_path)

    for exp_dir in root.iterdir():
        if not exp_dir.is_dir():
            continue
        if exp_dir.name == "best":
            continue
        if _is_skeleton(exp_dir.name):
            continue
        for pid in problems:
            score, info = _score_problem_in_run(exp_dir, pid)
            if not info["has_solution"]:
                continue
            if pid not in best or score > best[pid][0]:
                sol = _find_solution_tex(exp_dir, pid)
                if sol:
                    best[pid] = (score, info, sol)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {}
    for pid, (score, info, sol_path) in best.items():
        out_dir = _best_dir(dataset) / pid
        out_dir.mkdir(parents=True, exist_ok=True)
        dest_tex = out_dir / "solution.tex"
        shutil.copy2(sol_path, dest_tex)
        meta = {**info, "dataset": dataset, "problem_id": pid, "updated_at": now}
        (out_dir / "best_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if compile_pdfs:
            compile_best_pdf(pid, dataset)
        result[pid] = meta

    return result


def compile_best_pdf(problem_id: str, dataset: str = "first_proof_1") -> bool:
    """Compile best/<pid>/solution.tex to best/<pid>/solution.pdf.
    Returns True if the PDF now exists (compiled or cached)."""
    from .latex import compile_tex, build_main_tex, latex_available
    import shutil as _shutil
    import subprocess
    import tempfile

    out_dir = _best_dir(dataset) / problem_id
    tex_path = out_dir / "solution.tex"
    pdf_path = out_dir / "solution.pdf"

    if pdf_path.is_file() and pdf_path.stat().st_mtime >= tex_path.stat().st_mtime:
        return True  # already up to date

    if not tex_path.is_file():
        return False

    tool = latex_available()
    if not tool:
        return False

    content = tex_path.read_text(encoding="utf-8", errors="replace")
    preamble = REPO_ROOT / "problems" / "preamble.tex"
    has_preamble = preamble.is_file()

    try:
        with tempfile.TemporaryDirectory(prefix="rma_best_") as tmp:
            build = Path(tmp)
            if has_preamble:
                _shutil.copyfile(preamble, build / "preamble.tex")
            (build / "main.tex").write_text(build_main_tex(content, has_preamble), encoding="utf-8")
            if "tectonic" in tool:
                cmd = [tool, "main.tex"]
            elif _shutil.which("latexmk"):
                cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
            else:
                cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
            proc = subprocess.run(cmd, cwd=build, text=True, capture_output=True, timeout=240)
            out_pdf = build / "main.pdf"
            if proc.returncode == 0 and out_pdf.is_file():
                _shutil.copy2(out_pdf, pdf_path)
                return True
    except Exception:
        pass
    return False


def _discover_problems(root: Path) -> list[str]:
    """Collect all problem IDs seen across non-skeleton run dirs."""
    pids: set[str] = set()
    for exp_dir in root.iterdir():
        if not exp_dir.is_dir() or exp_dir.name == "best" or _is_skeleton(exp_dir.name):
            continue
        for p in exp_dir.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                pids.add(p.name)
    return sorted(pids)


def list_best_proofs(dataset: str = "first_proof_1") -> list[dict]:
    """Return one dict per problem with best-run metadata (from best/ folder)."""
    best_root = _best_dir(dataset)
    problems = _PROBLEMS if dataset == "first_proof_1" else None
    result = []

    if best_root.is_dir():
        seen: set[str] = set()
        dirs = sorted(best_root.iterdir(), key=lambda p: p.name)
        for d in dirs:
            if not d.is_dir():
                continue
            pid = d.name
            meta_path = d / "best_meta.json"
            sol_path = d / "solution.tex"
            meta: dict = {"problem_id": pid, "dataset": dataset}
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text())
                except Exception:
                    pass
            meta["has_solution"] = sol_path.is_file()
            result.append(meta)
            seen.add(pid)
        # Add placeholders for problems without any solution
        if problems:
            for pid in problems:
                if pid not in seen:
                    result.append({"problem_id": pid, "dataset": dataset, "has_solution": False,
                                   "verification_passed": False, "issue_count": 100})
    else:
        if problems:
            for pid in problems:
                result.append({"problem_id": pid, "dataset": dataset, "has_solution": False,
                               "verification_passed": False, "issue_count": 100})

    # Sort q1..q10 in natural order
    def _sort_key(x: dict) -> tuple:
        pid = x.get("problem_id", "")
        import re
        m = re.match(r'^([a-z]+)(\d+)$', pid)
        if m:
            return (m.group(1), int(m.group(2)))
        return (pid, 0)

    result.sort(key=_sort_key)
    return result


def get_best_proof(problem_id: str, dataset: str = "first_proof_1") -> dict | None:
    """Return best proof data for a problem, reading from best/ folder."""
    d = _best_dir(dataset) / problem_id
    if not d.is_dir():
        return None
    sol_path = d / "solution.tex"
    meta_path = d / "best_meta.json"

    meta: dict = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            pass

    solution_tex = ""
    if sol_path.is_file():
        solution_tex = sol_path.read_text(encoding="utf-8", errors="replace")

    return {
        "problem_id": problem_id,
        "dataset": dataset,
        "solution_tex": solution_tex,
        "has_solution": bool(solution_tex),
        "source_run": meta.get("source_run", ""),
        "model": meta.get("model", ""),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "verification_passed": meta.get("verification_passed", False),
        "issue_count": meta.get("issue_count", 100),
    }


def maybe_update_best(exp_dir: Path, problem_id: str, dataset: str = "first_proof_1") -> bool:
    """Check if this run is better than current best; if so, update best/ folder.
    Returns True if best was updated."""
    if _is_skeleton(exp_dir.name):
        return False
    new_score, new_info = _score_problem_in_run(exp_dir, problem_id)
    if not new_info["has_solution"]:
        return False

    best_root = _best_dir(dataset) / problem_id
    meta_path = best_root / "best_meta.json"
    current_score = -1.0
    if meta_path.is_file():
        try:
            existing = json.loads(meta_path.read_text())
            v_passed = existing.get("verification_passed", False)
            issue_cnt = int(existing.get("issue_count", 100))
            current_score = (1000 if v_passed else 0) + max(0, 100 - issue_cnt)
        except Exception:
            pass

    if new_score <= current_score:
        return False

    sol = _find_solution_tex(exp_dir, problem_id)
    if not sol:
        return False

    best_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sol, best_root / "solution.tex")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {**new_info, "dataset": dataset, "problem_id": problem_id, "updated_at": now}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


# ── legacy API (kept for backward compat) ────────────────────────────────────

def list_experiments(dataset: str = "first_proof_1") -> list[dict]:
    root = _proof_outputs_root(dataset)
    if not root.is_dir():
        return []
    now = time.time()
    exps = []
    dirs = sorted(
        (d for d in root.iterdir() if d.is_dir() and d.name != "best" and not _is_skeleton(d.name)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for i, d in enumerate(dirs):
        exp_mtime = d.stat().st_mtime
        problems = {}
        latest_problem_mtime = 0.0
        for qid in _PROBLEMS:
            status_path = d / qid / "artifacts" / "status.json"
            sol_path = _find_solution_tex(d, qid)
            sol_mtime = sol_path.stat().st_mtime if sol_path else 0.0
            latest_problem_mtime = max(latest_problem_mtime, sol_mtime)
            pdf_path = d / f"{qid}_solution.pdf"
            if status_path.is_file():
                try:
                    s = json.loads(status_path.read_text())
                    problems[qid] = {
                        "status": s.get("status", "unknown"),
                        "has_solution": sol_path is not None,
                        "has_pdf": pdf_path.is_file(),
                        "is_new": sol_mtime > 0 and (now - sol_mtime) < _RECENT_SECS,
                        "sol_mtime": sol_mtime,
                    }
                except Exception:
                    problems[qid] = {"status": "error", "has_solution": False, "has_pdf": False, "is_new": False, "sol_mtime": 0.0}
            else:
                has_sol = sol_path is not None
                problems[qid] = {"status": "not_started" if not has_sol else "proposed",
                                 "has_solution": has_sol, "has_pdf": pdf_path.is_file(),
                                 "is_new": sol_mtime > 0 and (now - sol_mtime) < _RECENT_SECS,
                                 "sol_mtime": sol_mtime}
        exps.append({
            "name": d.name,
            "problems": problems,
            "mtime": exp_mtime,
            "is_latest": i == 0,
            "has_recent": (now - latest_problem_mtime) < _RECENT_SECS if latest_problem_mtime > 0 else False,
        })
    return exps


def get_proof(exp_name: str, problem_id: str, dataset: str = "first_proof_1") -> dict | None:
    root = _proof_outputs_root(dataset)
    exp_dir = root / exp_name
    if not exp_dir.is_dir():
        return None
    sol_path = _find_solution_tex(exp_dir, problem_id)
    status_path = exp_dir / problem_id / "artifacts" / "status.json"
    ver_dir = exp_dir / problem_id / "artifacts" / "verifications"

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
    if sol_path:
        solution_tex = sol_path.read_text(encoding="utf-8", errors="replace")

    return {
        "exp": exp_name,
        "problem_id": problem_id,
        "status": status.get("status", "not_started"),
        "solution_tex": solution_tex,
        "verification": verification,
    }
