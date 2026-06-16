"""Central dataset/problem store for ResearchMathAgent-web.

All datasets live under  data/datasets/<slug>/
  metadata.json      — dataset-level info
  problems/<id>.json — one file per problem

Problem schema (all fields optional except id/dataset/title):
  id, dataset, title, statement, tex, tags, difficulty (0-1),
  solvability_score (0-1 or null), source_url, year

Solvability scores are computed lazily from run outputs and cached in
  data/datasets/<slug>/solvability_cache.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = REPO_ROOT / "data" / "datasets"


# ── Dataset listing ─────────────────────────────────────────────────────────

def list_datasets() -> list[dict]:
    """Return all available datasets with metadata."""
    out = []
    if not DATASETS_DIR.is_dir():
        return out
    for d in sorted(DATASETS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        else:
            meta = {}
        meta.setdefault("slug", d.name)
        meta.setdefault("name", d.name)
        meta.setdefault("problem_count", sum(1 for _ in (d / "problems").glob("*.json")) if (d / "problems").is_dir() else 0)
        out.append(meta)
    return out


def get_dataset_meta(slug: str) -> dict | None:
    d = DATASETS_DIR / slug
    if not d.is_dir():
        return None
    meta_path = d / "metadata.json"
    meta = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    meta.setdefault("slug", slug)
    meta.setdefault("name", slug)
    return meta


# ── Problem access ───────────────────────────────────────────────────────────

def _problem_dir(slug: str) -> Path:
    return DATASETS_DIR / slug / "problems"


def list_problems(
    dataset: str | None = None,
    sort: str = "id",
    tags: list[str] | None = None,
    min_difficulty: float | None = None,
    max_difficulty: float | None = None,
    min_solvability: float | None = None,
    max_solvability: float | None = None,
    search: str | None = None,
) -> list[dict]:
    """Return problems across all datasets (or one), with filtering + sorting.

    sort values: "id", "title", "difficulty_asc", "difficulty_desc",
                 "solvability_asc", "solvability_desc"
    """
    slugs = [dataset] if dataset else [d.name for d in sorted(DATASETS_DIR.iterdir()) if d.is_dir()]
    problems: list[dict] = []

    for slug in slugs:
        pdir = _problem_dir(slug)
        if not pdir.is_dir():
            continue
        scores = _load_solvability_cache(slug)
        for pfile in sorted(pdir.glob("*.json")):
            try:
                p = json.loads(pfile.read_text(encoding="utf-8"))
            except Exception:
                continue
            p.setdefault("dataset", slug)
            pid = p.get("id", pfile.stem)
            # merge live solvability score
            if pid in scores:
                p["solvability_score"] = scores[pid]
            problems.append(p)

    # ── filters ──
    if tags:
        tag_set = {t.lower() for t in tags}
        problems = [p for p in problems if tag_set & {t.lower() for t in p.get("tags", [])}]
    if min_difficulty is not None:
        problems = [p for p in problems if (p.get("difficulty") or 0) >= min_difficulty]
    if max_difficulty is not None:
        problems = [p for p in problems if (p.get("difficulty") or 1) <= max_difficulty]
    if min_solvability is not None:
        problems = [p for p in problems if (p.get("solvability_score") or 0) >= min_solvability]
    if max_solvability is not None:
        problems = [p for p in problems if (p.get("solvability_score") or 1) <= max_solvability]
    if search:
        q = search.lower()
        problems = [p for p in problems if q in p.get("title", "").lower() or q in p.get("statement", "").lower() or any(q in t.lower() for t in p.get("tags", []))]

    # ── sort ──
    _none_last = lambda v, default: default if v is None else v
    if sort == "title":
        problems.sort(key=lambda p: p.get("title", "").lower())
    elif sort == "difficulty_asc":
        problems.sort(key=lambda p: _none_last(p.get("difficulty"), 999))
    elif sort == "difficulty_desc":
        problems.sort(key=lambda p: _none_last(p.get("difficulty"), -1), reverse=True)
    elif sort == "solvability_asc":
        problems.sort(key=lambda p: _none_last(p.get("solvability_score"), 999))
    elif sort == "solvability_desc":
        problems.sort(key=lambda p: _none_last(p.get("solvability_score"), -1), reverse=True)
    else:
        # default: group by dataset, then natural sort by id
        problems.sort(key=lambda p: (p.get("dataset", ""), _natural_key(p.get("id", ""))))

    # Strip the heavy tex field from list view
    return [{k: v for k, v in p.items() if k != "tex"} for p in problems]


def get_problem(dataset: str, problem_id: str) -> dict | None:
    """Return full problem record including tex."""
    _validate_slug(dataset)
    _validate_id(problem_id)
    path = _problem_dir(dataset) / f"{problem_id}.json"
    if not path.is_file():
        return None
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    p.setdefault("dataset", dataset)
    scores = _load_solvability_cache(dataset)
    if problem_id in scores:
        p["solvability_score"] = scores[problem_id]
    return p


def upsert_problem(dataset: str, record: dict) -> None:
    """Write or update a problem JSON file."""
    _validate_slug(dataset)
    pid = record.get("id", "")
    _validate_id(pid)
    pdir = _problem_dir(dataset)
    pdir.mkdir(parents=True, exist_ok=True)
    path = pdir / f"{pid}.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing.update(record)
        record = existing
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Solvability scores ───────────────────────────────────────────────────────

def _solvability_cache_path(slug: str) -> Path:
    return DATASETS_DIR / slug / "solvability_cache.json"


def _load_solvability_cache(slug: str) -> dict[str, float]:
    p = _solvability_cache_path(slug)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def compute_solvability_scores(dataset: str) -> dict[str, float]:
    """Aggregate run outputs for a dataset and write solvability_cache.json.

    Solvability = fraction of runs that reached 'solved' or 'verified' status.
    Runs live under outputs/<exp>/<problem_id>/artifacts/status.json
    """
    import os
    outputs_root_env = os.environ.get("RMA_PROOF_OUTPUTS")
    if outputs_root_env:
        outputs_root = Path(outputs_root_env)
    else:
        outputs_root = REPO_ROOT.parent / "ResearchMathAgent" / "outputs" / dataset
        if not outputs_root.is_dir():
            outputs_root = REPO_ROOT / "outputs" / dataset

    scores: dict[str, list[bool]] = {}
    if outputs_root.is_dir():
        for exp_dir in outputs_root.iterdir():
            if not exp_dir.is_dir():
                continue
            for status_file in exp_dir.rglob("status.json"):
                pid = status_file.parent.parent.name  # exp/<pid>/artifacts/status.json
                try:
                    st = json.loads(status_file.read_text())
                    solved = st.get("status") in ("solved", "verified", "correct")
                    scores.setdefault(pid, []).append(solved)
                except Exception:
                    pass

    result = {pid: sum(v) / len(v) for pid, v in scores.items() if v}

    # persist cache
    cache_path = _solvability_cache_path(dataset)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def get_solvability_scores(dataset: str | None = None) -> dict[str, dict[str, float]]:
    """Return {dataset_slug: {problem_id: score}} for all datasets (or one)."""
    slugs = [dataset] if dataset else [d.name for d in sorted(DATASETS_DIR.iterdir()) if d.is_dir()]
    return {slug: _load_solvability_cache(slug) for slug in slugs}


# ── Validation helpers ───────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ValueError(f"Invalid dataset slug: {slug!r}")


def _validate_id(pid: str) -> None:
    if not _ID_RE.match(pid):
        raise ValueError(f"Invalid problem id: {pid!r}")


def _natural_key(s: str) -> tuple:
    return tuple(int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", s))
