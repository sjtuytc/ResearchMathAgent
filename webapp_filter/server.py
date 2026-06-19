"""Lightweight read-only FastAPI server for browsing the 14k ResearchMath dataset.

Deliberately restricted: no agent runs, no PDF compilation, no background
threads, no write operations. Isolated from the solve app so a crash here
cannot affect it and vice versa.

Serves at an internal port (8012 dev / 8013 prod) behind the proxy.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATASETS_DIR = REPO_ROOT / "data" / "datasets"

_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,120}$")

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

app = FastAPI(title="ResearchMath Filter", version="1.0.0")


# ── helpers ──────────────────────────────────────────────────────────────────

def _ok_slug(s: str) -> bool:
    return bool(s and _SLUG_RE.match(s))


def _ok_id(s: str) -> bool:
    return bool(s and _ID_RE.match(s))


def _load_index(slug: str) -> list[dict] | None:
    p = DATASETS_DIR / slug / "_index.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_metadata(slug: str) -> dict:
    p = DATASETS_DIR / slug / "metadata.json"
    meta: dict = {}
    if p.is_file():
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    meta.setdefault("slug", slug)
    meta.setdefault("name", slug)
    return meta


# ── dataset endpoints ─────────────────────────────────────────────────────────

@app.get("/api/datasets")
def list_datasets() -> JSONResponse:
    out = []
    if not DATASETS_DIR.is_dir():
        return JSONResponse({"datasets": out})
    for d in sorted(DATASETS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta = _load_metadata(d.name)
        if not meta.get("problem_count"):
            prob_dir = d / "problems"
            meta["problem_count"] = sum(1 for _ in prob_dir.glob("*.json")) if prob_dir.is_dir() else 0
        out.append(meta)
    return JSONResponse({"datasets": out})


@app.get("/api/datasets/{slug}")
def dataset_meta(slug: str) -> JSONResponse:
    if not _ok_slug(slug):
        return JSONResponse({"error": "invalid slug"}, status_code=400)
    if not (DATASETS_DIR / slug).is_dir():
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(_load_metadata(slug))


# ── problem listing with pagination ──────────────────────────────────────────

@app.get("/api/problems")
def list_problems(
    dataset: str = Query("researchmath_14k"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    search: str = Query(""),
    tags: str = Query(""),
    domain: str = Query(""),
    status: str = Query(""),
    sort: str = Query("id"),
) -> JSONResponse:
    if not _ok_slug(dataset):
        return JSONResponse({"error": "invalid dataset"}, status_code=400)

    index = _load_index(dataset)
    if index is None:
        return JSONResponse({"error": "dataset not found or index missing"}, status_code=404)

    items: list[dict] = index

    # ── filter ──
    search_lo = search.lower().strip()
    if search_lo:
        items = [
            p for p in items
            if search_lo in p.get("title", "").lower()
            or search_lo in p.get("statement", "").lower()
            or any(search_lo in t.lower() for t in p.get("tags", []))
            or search_lo in p.get("taxonomy_level_1", "").lower()
            or search_lo in p.get("taxonomy_level_2", "").lower()
        ]

    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        if tag_list:
            items = [
                p for p in items
                if any(
                    any(tl in tag.lower() for tl in tag_list)
                    for tag in p.get("tags", [])
                )
            ]

    if domain:
        dl = domain.lower().strip()
        items = [
            p for p in items
            if dl in p.get("taxonomy_level_1", "").lower()
            or dl in p.get("taxonomy_level_2", "").lower()
        ]

    if status:
        items = [p for p in items if p.get("open_status", "") == status]

    # ── sort ──
    if sort == "title":
        items = sorted(items, key=lambda p: p.get("title", ""))
    elif sort == "difficulty_asc":
        items = sorted(items, key=lambda p: p.get("difficulty") or 0.5)
    elif sort == "difficulty_desc":
        items = sorted(items, key=lambda p: p.get("difficulty") or 0.5, reverse=True)
    # default: keep original order (id order from index)

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start:start + page_size]

    # Strip heavy tex field from listing to keep responses small
    for p in page_items:
        p.pop("tex", None)

    return JSONResponse({
        "problems": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "dataset": dataset,
    })


# ── single problem detail ─────────────────────────────────────────────────────

@app.get("/api/problem/{dataset}/{problem_id}")
def get_problem(dataset: str, problem_id: str) -> JSONResponse:
    if not _ok_slug(dataset):
        return JSONResponse({"error": "invalid dataset"}, status_code=400)
    if not _ok_id(problem_id):
        return JSONResponse({"error": "invalid problem id"}, status_code=400)
    p = DATASETS_DIR / dataset / "problems" / f"{problem_id}.json"
    if not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"error": "parse error"}, status_code=500)
    return JSONResponse(data)


# ── domains / tags summary ────────────────────────────────────────────────────

@app.get("/api/domains/{dataset}")
def list_domains(dataset: str) -> JSONResponse:
    if not _ok_slug(dataset):
        return JSONResponse({"error": "invalid dataset"}, status_code=400)
    index = _load_index(dataset)
    if index is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    domains: dict[str, int] = {}
    for p in index:
        d = p.get("taxonomy_level_1", "")
        if d:
            domains[d] = domains.get(d, 0) + 1
    sorted_domains = sorted(domains.items(), key=lambda x: -x[1])
    return JSONResponse({"domains": [{"name": k, "count": v} for k, v in sorted_domains]})


@app.get("/api/status-counts/{dataset}")
def status_counts(dataset: str) -> JSONResponse:
    if not _ok_slug(dataset):
        return JSONResponse({"error": "invalid dataset"}, status_code=400)
    index = _load_index(dataset)
    if index is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    counts: dict[str, int] = {}
    for p in index:
        s = p.get("open_status", "unknown") or "unknown"
        counts[s] = counts.get(s, 0) + 1
    return JSONResponse({"counts": counts, "total": len(index)})


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "filter"})


# ── insights ──────────────────────────────────────────────────────────────────

_BENCHMARK_SLUGS = {"first_proof_1", "first_proof_2"}


def _dataset_stats(slug: str) -> dict | None:
    index = _load_index(slug)
    if index is None:
        return None
    meta = _load_metadata(slug)

    counts: dict[str, int] = {}
    domains: dict[str, int] = {}
    n_with_diff = 0
    diff_sum = 0.0

    for p in index:
        s = p.get("open_status") or "unknown"
        counts[s] = counts.get(s, 0) + 1
        d = p.get("taxonomy_level_1", "")
        if d:
            domains[d] = domains.get(d, 0) + 1
        diff = p.get("difficulty")
        if diff is not None:
            n_with_diff += 1
            diff_sum += diff

    total = len(index)
    unknown = counts.get("unknown", 0)
    solved = counts.get("solved", 0)
    partial = counts.get("partially_solved", 0)
    top_domains = sorted(domains.items(), key=lambda x: -x[1])[:6]

    return {
        "slug": slug,
        "name": meta.get("name", slug),
        "description": meta.get("description", ""),
        "problem_count": total,
        "status_counts": counts,
        "top_domains": [{"name": k, "count": v} for k, v in top_domains],
        "coverage_pct": round((total - unknown) / total * 100) if total else 0,
        "solved_rate": round(solved / total * 100) if total else 0,
        "partial_rate": round(partial / total * 100) if total else 0,
        "avg_difficulty": round(diff_sum / n_with_diff * 100) if n_with_diff else None,
        "missing_difficulty": total - n_with_diff,
    }


def _generate_todos(datasets: list[dict]) -> list[dict]:
    todos: list[dict] = []

    for ds in datasets:
        slug, name, total = ds["slug"], ds["name"], ds["problem_count"]
        counts = ds["status_counts"]
        unknown = counts.get("unknown", 0)
        solved = counts.get("solved", 0)
        partial = counts.get("partially_solved", 0)
        open_ = counts.get("open", 0)

        unknown_pct = round(unknown / total * 100) if total else 0
        if unknown_pct > 25:
            todos.append({
                "priority": "high", "dataset": slug,
                "title": f"{name}: {unknown_pct}% status unknown ({unknown:,} problems)",
                "body": f"{unknown:,} of {total:,} problems have no status annotation. Reviewing these could surface valuable open problems.",
                "action": {"tab": "browse", "dataset": slug, "status": "unknown"},
            })

        if solved < 5 and total > 50:
            todos.append({
                "priority": "medium", "dataset": slug,
                "title": f"{name}: only {solved} solved problem{'s' if solved != 1 else ''}",
                "body": f"Extremely low solve rate. {partial} partially-solved problems may be near completion.",
                "action": {"tab": "browse", "dataset": slug, "status": "partially_solved"},
            })
        elif open_ > 0 and partial > 0:
            todos.append({
                "priority": "low", "dataset": slug,
                "title": f"{name}: {partial} partially-solved to revisit",
                "body": f"These {partial} problems have partial solutions—good candidates for deeper investigation.",
                "action": {"tab": "browse", "dataset": slug, "status": "partially_solved"},
            })

        missing_diff = ds["missing_difficulty"]
        if missing_diff > 0 and missing_diff / total > 0.4:
            todos.append({
                "priority": "low", "dataset": slug,
                "title": f"{name}: {missing_diff:,} problems missing difficulty ratings",
                "body": "Difficulty scores improve filtering. A batch evaluation pass would fill the gaps.",
                "action": {"tab": "browse", "dataset": slug},
            })

    # Website feature todos
    todos += [
        {
            "priority": "high", "dataset": None,
            "title": "Add cross-dataset unified search",
            "body": "Search currently operates per-dataset. A unified search across all datasets would help discover related problems scattered across sources.",
            "action": None,
        },
        {
            "priority": "medium", "dataset": None,
            "title": "Add difficulty range filter",
            "body": "The sidebar should allow filtering by a difficulty band (e.g. 40–70%) not just status and domain.",
            "action": None,
        },
        {
            "priority": "medium", "dataset": None,
            "title": "Add 'Copy to Solve' button on problem detail",
            "body": "A one-click button to open a problem in the Solve workspace would tighten the filter→solve workflow.",
            "action": None,
        },
        {
            "priority": "low", "dataset": None,
            "title": "Starred / bookmarked problem list",
            "body": "Allow starring problems to revisit without re-running the same search.",
            "action": None,
        },
        {
            "priority": "low", "dataset": None,
            "title": "Show related problems in detail view",
            "body": "When viewing a problem, surface other problems in the same domain and difficulty band from the same or other datasets.",
            "action": None,
        },
    ]

    # Sort: high → medium → low
    order = {"high": 0, "medium": 1, "low": 2}
    todos.sort(key=lambda t: order.get(t["priority"], 9))
    return todos


@app.get("/api/insights")
def get_insights() -> JSONResponse:
    datasets_stats: list[dict] = []
    if DATASETS_DIR.is_dir():
        for d in sorted(DATASETS_DIR.iterdir()):
            if not d.is_dir() or d.name in _BENCHMARK_SLUGS:
                continue
            stats = _dataset_stats(d.name)
            if stats:
                datasets_stats.append(stats)

    total_problems = sum(d["problem_count"] for d in datasets_stats)
    todos = _generate_todos(datasets_stats)

    return JSONResponse({
        "datasets": datasets_stats,
        "total_problems": total_problems,
        "dataset_count": len(datasets_stats),
        "todos": todos,
    })


# ── SPA ───────────────────────────────────────────────────────────────────────

if STATIC_DIR.is_dir():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        ico = STATIC_DIR / "favicon.ico"
        if ico.is_file():
            return FileResponse(ico)
        return JSONResponse({"error": "not found"}, status_code=404)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
