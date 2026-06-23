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
        full_count = sum(1 for _ in (d / "problems").glob("*.json")) if (d / "problems").is_dir() else 0
        ss = get_solve_set(d.name)
        # Solve system exposes exactly the curated solve_set (10) per dataset.
        meta["problem_count"] = len(ss) if ss is not None else full_count
        meta["full_problem_count"] = full_count
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


def _index_path(slug: str) -> Path:
    return DATASETS_DIR / slug / "_index.json"


def _load_index(slug: str) -> list[dict] | None:
    """Load the pre-built list index (no tex field). Returns None if missing/stale."""
    p = _index_path(slug)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_index(slug: str) -> list[dict]:
    """Read all problem files and write _index.json. Returns the indexed list."""
    pdir = _problem_dir(slug)
    records: list[dict] = []
    for pfile in sorted(pdir.glob("*.json")):
        try:
            p = json.loads(pfile.read_text(encoding="utf-8"))
        except Exception:
            continue
        p.setdefault("dataset", slug)
        records.append({k: v for k, v in p.items() if k != "tex"})
    _index_path(slug).write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return records


def _solve_set_path(slug: str) -> Path:
    return DATASETS_DIR / slug / "solve_set.json"


def get_solve_set(slug: str) -> list[str] | None:
    """Curated problem IDs the solve system exposes for a dataset, or None.

    Each dataset is sampled down to exactly 10 "valuable unsolved" problems
    (written by the filtering-system sampler to solve_set.json). The solve app
    restricts every dataset to this set; the read-only filter app is unaffected
    because it has its own loaders and does not import this module.
    """
    p = _solve_set_path(slug)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    ids = data.get("problem_ids") if isinstance(data, dict) else data
    return [str(i) for i in ids] if ids else None


def _apply_solve_set(slug: str, records: list[dict]) -> list[dict]:
    """Restrict + order a problem list to the dataset's solve_set (if present)."""
    ss = get_solve_set(slug)
    if ss is None:
        return records
    order = {pid: i for i, pid in enumerate(ss)}
    kept = [p for p in records if p.get("id") in order]
    kept.sort(key=lambda p: order.get(p.get("id"), 1_000_000))
    return kept


def _load_problems_for_slug(slug: str) -> list[dict]:
    """Return the dataset's problems, restricted to the solve_set when present."""
    cached = _load_index(slug)
    if cached is not None:
        for p in cached:
            p.setdefault("dataset", slug)
        return _apply_solve_set(slug, cached)
    # Fall back to reading individual files (small datasets or first run)
    pdir = _problem_dir(slug)
    if not pdir.is_dir():
        return []
    records: list[dict] = []
    for pfile in sorted(pdir.glob("*.json")):
        try:
            p = json.loads(pfile.read_text(encoding="utf-8"))
        except Exception:
            continue
        p.setdefault("dataset", slug)
        records.append({k: v for k, v in p.items() if k != "tex"})
    return _apply_solve_set(slug, records)


def list_problems(
    dataset: str | None = None,
    sort: str = "id",
    tags: list[str] | None = None,
    min_difficulty: float | None = None,
    max_difficulty: float | None = None,
    min_solvability: float | None = None,
    max_solvability: float | None = None,
    tier: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """Return problems across all datasets (or one), with filtering + sorting.

    sort values: "id", "title", "difficulty_asc", "difficulty_desc",
                 "solvability_asc", "solvability_desc"
    ``tier`` filters by solvability category (likely|plausible|hard|open).
    Each returned problem gets ``solvability_score`` and ``solvability_tier``.
    """
    slugs = [dataset] if dataset else [d.name for d in sorted(DATASETS_DIR.iterdir()) if d.is_dir() and not d.name.startswith("_")]
    problems: list[dict] = []

    for slug in slugs:
        scores = _load_solvability_cache(slug)
        slug_problems = _load_problems_for_slug(slug)
        for p in slug_problems:
            pid = p.get("id", "")
            if pid in scores:
                p["solvability_score"] = scores[pid]
            p["solvability_tier"] = solvability_tier(p.get("solvability_score"))
        problems.extend(slug_problems)

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
    if tier:
        tier_set = {t.strip().lower() for t in tier.split(",") if t.strip()}
        problems = [p for p in problems if p.get("solvability_tier") in tier_set]
    if search:
        q = search.lower()
        problems = [p for p in problems
                    if q in p.get("title", "").lower()
                    or q in (p.get("statement", "") or "").lower()
                    or q in (_primary_category(p) or "").lower()
                    or any(q in t.lower() for t in p.get("tags", []))]

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

    # Return only the light fields the list view needs (full records, incl.
    # statement and dataset-specific blobs, are fetched per-problem via
    # get_problem). Adds a normalised ``category``. Keeps the payload small.
    _KEEP = ("id", "dataset", "title", "tags", "difficulty", "year",
             "solvability_score", "solvability_tier", "open_status")
    out = []
    for p in problems:
        rec = {k: p[k] for k in _KEEP if k in p}
        cat = _primary_category(p)
        if cat:
            rec["category"] = cat
        out.append(rec)
    return out


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
    p["solvability_tier"] = solvability_tier(p.get("solvability_score"))
    evals = _load_eval_store(dataset)
    if problem_id in evals:
        p["solv_eval"] = evals[problem_id]
    return p


def find_problem_tex(repo_root, problem_id: str, dataset: str | None = None) -> str:
    """Return the LaTeX/statement text for a problem, searching everywhere.

    Resolution order:
      1. repo_root/problems/<pid>.tex   (the fp1 q1-q10 benchmark files)
      2. the given dataset's store record
      3. any dataset's store record (last resort)
    Returns "" if not found. Lets issue/meeting agents work on ANY dataset,
    not just the ones with a hand-written .tex file.
    """
    from pathlib import Path
    try:
        p = Path(repo_root) / "problems" / f"{problem_id}.tex"
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass

    def _from(slug: str) -> str:
        try:
            rec = get_problem(slug, problem_id)
        except Exception:
            return ""
        if not rec:
            return ""
        return rec.get("tex") or rec.get("statement") or ""

    if dataset:
        t = _from(dataset)
        if t:
            return t
    # last resort: scan every dataset for this id
    try:
        for meta in list_datasets():
            slug = meta.get("slug", "")
            if slug and slug != dataset:
                t = _from(slug)
                if t:
                    return t
    except Exception:
        pass
    return ""


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


# ── Solvability eval store (full per-problem evaluation: tier, reasoning, …) ─────

def _eval_store_path(slug: str) -> Path:
    return DATASETS_DIR / slug / "solvability_eval.json"


def _load_eval_store(slug: str) -> dict[str, dict]:
    p = _eval_store_path(slug)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# Solvability tiers (categories) derived from the normalised 0-1 score.
SOLVABILITY_TIERS = [
    ("likely",    0.70, "Likely solvable"),
    ("plausible", 0.40, "Plausibly solvable"),
    ("hard",      0.20, "Hard"),
    ("open",      0.00, "Open / breakthrough"),
]


def solvability_tier(score: float | None) -> str | None:
    """Map a normalised 0-1 solvability score to a category tier slug."""
    if score is None:
        return None
    for slug, lo, _label in SOLVABILITY_TIERS:
        if score >= lo:
            return slug
    return "open"


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


def _primary_category(p: dict) -> str | None:
    """Best available mathematical-domain category for a problem.

    Prefers native dataset fields (``category``, taxonomy, AIM list name) and
    falls back to the first tag.
    """
    for k in ("category", "primary_category", "taxonomy_level_1",
              "aim_list_name", "domain", "area", "field"):
        v = p.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    tags = p.get("tags") or []
    for t in tags:
        if isinstance(t, str) and t.strip() and t.strip().lower() not in (
                "open-problem", "open", "workshop", "conjecture", "erdos"):
            return t.strip()
    return tags[0].strip() if tags and isinstance(tags[0], str) else None
