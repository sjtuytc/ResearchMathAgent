"""Download the UnsolvedMath dataset.

Source: https://huggingface.co/datasets/ulamai/UnsolvedMath
License: CC BY 4.0
Format: JSON — problems.json, sets.json, categories.json

Contains ~800+ open math problems across 12 curated sets including:
Millennium Prize, Hilbert's 23, Erdős (632), Smale's, Landau's, etc.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


DATASET_SLUG = "unsolved_math"
HF_REPO = "ulamai/UnsolvedMath"

METADATA = {
    "slug": DATASET_SLUG,
    "name": "Unsolved Math",
    "description": "Open mathematical problems drawn from 12 curated sets: Millennium Prize, Hilbert's 23, Erdős (632), Ben Green's 100, DARPA 23, Smale's, Landau's, Hardy-Littlewood, Richard Guy's Primes, Kourovka Notebook, Kirby Low-Dimensional Topology, OpenGarden.",
    "source": f"https://huggingface.co/datasets/{HF_REPO}",
    "license": "CC-BY-4.0",
    "version": "2024",
    "year": 2024,
    "tags": ["open-problems", "unsolved", "curated", "multi-area"],
}


def download(datasets_dir: Path, force: bool = False) -> int:
    out_dir = datasets_dir / DATASET_SLUG
    problems_dir = out_dir / "problems"

    if problems_dir.is_dir() and any(problems_dir.glob("*.json")) and not force:
        existing = sum(1 for _ in problems_dir.glob("*.json"))
        print(f"[unsolved_math] Already downloaded ({existing} problems). Use --force to re-download.")
        return existing

    problems_dir.mkdir(parents=True, exist_ok=True)

    try:
        from datasets import load_dataset  # type: ignore
        print("[unsolved_math] Loading from HuggingFace...")
        ds = load_dataset(HF_REPO, trust_remote_code=True)

        count = 0
        # Try the main split
        for split_name in ["train", "problems", "test", "validation"]:
            if split_name in ds:
                for row in ds[split_name]:
                    count += _save_row(row, count, problems_dir)
                break
        else:
            # Iterate all splits
            for split_name, split_ds in ds.items():
                for row in split_ds:
                    count += _save_row(row, count, problems_dir)

    except Exception as e:
        print(f"[unsolved_math] HuggingFace library failed ({e}), trying HTTP download...")
        count = _download_via_http(problems_dir)

    _write_metadata(out_dir, count)
    print(f"[unsolved_math] Downloaded {count} problems.")
    return count


def _save_row(row: dict, idx: int, problems_dir: Path) -> int:
    raw_id = row.get("id", idx)
    pid = f"um{int(raw_id):05d}" if str(raw_id).isdigit() else re.sub(r"[^A-Za-z0-9_]", "_", str(raw_id))[:60]
    tags = _build_tags(row)
    record = {
        "id": pid,
        "dataset": DATASET_SLUG,
        "title": str(row.get("title", row.get("name", pid))),
        "statement": str(row.get("statement", row.get("problem", row.get("description", "")))),
        "tex": "",
        "tags": tags,
        "difficulty": _map_difficulty(row.get("difficulty")),
        "solvability_score": None,
        "source_url": str(row.get("source_url", row.get("url", ""))),
        "year": int(row["year_proposed"]) if row.get("year_proposed") else None,
        "category": str(row.get("category", "")),
        "status": str(row.get("status", "open")),
        "background": str(row.get("background", "")),
        "problem_set": str(row.get("set", row.get("source_set", ""))),
    }
    (problems_dir / f"{pid}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 1


def _download_via_http(problems_dir: Path) -> int:
    import urllib.request
    base = "https://huggingface.co/datasets/ulamai/UnsolvedMath/resolve/main"
    count = 0
    for fname in ["problems.json", "data/problems.json", "train.json"]:
        try:
            url = f"{base}/{fname}"
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read())
            rows = data if isinstance(data, list) else data.get("data", data.get("problems", []))
            for i, row in enumerate(rows):
                count += _save_row(row, i, problems_dir)
            if count:
                break
        except Exception:
            continue
    return count


def _build_tags(row: dict) -> list[str]:
    tags = []
    cat = str(row.get("category", "")).lower()
    problem_set = str(row.get("set", row.get("source_set", ""))).lower()
    for kw, tag in [
        ("number", "number theory"), ("combin", "combinatorics"),
        ("algebra", "algebra"), ("analysis", "analysis"),
        ("topology", "topology"), ("geometry", "geometry"),
        ("graph", "graph theory"), ("probability", "probability"),
        ("erdős", "erdos"), ("erdos", "erdos"),
        ("millennium", "millennium prize"), ("hilbert", "hilbert"),
    ]:
        if kw in cat or kw in problem_set:
            tags.append(tag)
    return tags or ["open-problem"]


def _map_difficulty(d) -> float | None:
    if d is None:
        return None
    mapping = {"L1": 0.2, "L2": 0.4, "L3": 0.6, "L4": 0.8, "L5": 1.0}
    if isinstance(d, str) and d in mapping:
        return mapping[d]
    try:
        return min(1.0, max(0.0, float(d)))
    except (TypeError, ValueError):
        return None


def _write_metadata(out_dir: Path, count: int) -> None:
    meta = dict(METADATA)
    meta["problem_count"] = count
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
