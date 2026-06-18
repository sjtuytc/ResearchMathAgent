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
