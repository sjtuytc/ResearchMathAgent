#!/usr/bin/env python3
"""Import ResearchMath-14k from HuggingFace into the dataset store.

Usage:
    python3 scripts/import_researchmath14k.py [--max N] [--resume]

Options:
    --max N     Import at most N problems (default: all 14056)
    --resume    Skip problems that already exist on disk
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_SLUG = "researchmath_14k"
DATASET_DIR = REPO_ROOT / "data" / "datasets" / DATASET_SLUG
PROBLEMS_DIR = DATASET_DIR / "problems"

# ResearchMath-14k's 11 broad domains → our normalized domain tags
_LEVEL1_TAGS = {
    "Analysis, PDEs, and Dynamics": ["Analysis", "PDE"],
    "Mathematical Physics": ["Mathematical Physics", "Analysis"],
    "Discrete Mathematics and Combinatorics": ["Combinatorics"],
    "Number Theory": ["Number Theory"],
    "Geometry and Topology": ["Geometry", "Topology"],
    "Theoretical Computer Science": ["TCS"],
    "Algebra and Representation Theory": ["Algebra"],
    "Probability, Statistics, and Machine Learning": ["Probability"],
    "Applied and Computational Mathematics": ["Linear Algebra"],
    "Logic and Foundations": ["Logic"],
    "Cross-disciplinary topics": [],
}

_STATUS_DIFFICULTY = {
    "open": 0.9,
    "unknown": 0.75,
    "partially solved": 0.6,
    "solved": 0.4,
}


def _parse_year(paper_id: str) -> int | None:
    """Parse year from arXiv-style paper_id (e.g. '2301.12345' → 2023)."""
    m = re.match(r"^(\d{2})(\d{2})\.", paper_id or "")
    if m:
        yy = int(m.group(1))
        return 2000 + yy if yy < 90 else 1900 + yy
    return None


def _make_tags(row: dict) -> list[str]:
    tags: list[str] = []
    l1 = row.get("taxonomy_level_1") or ""
    l2 = row.get("taxonomy_level_2") or ""
    l3 = row.get("taxonomy_level_3") or ""
    tags.extend(_LEVEL1_TAGS.get(l1, [l1] if l1 else []))
    if l2 and l2 not in tags:
        tags.append(l2)
    if l3 and l3 not in tags:
        tags.append(l3)
    status = (row.get("open_status") or "").lower()
    if status == "open":
        tags.append("open")
    elif status == "solved":
        tags.append("solved")
    return tags


def _make_id(index: int) -> str:
    return f"rm-{index:05d}"


def convert_row(index: int, row: dict) -> dict:
    """Convert a HuggingFace row to our problem schema."""
    statement = (row.get("self_contained_problem") or "").strip()
    original = (row.get("original_question") or "").strip()
    paper_id = (row.get("paper_id") or "").strip()
    question_link = (row.get("question_link") or "").strip()
    l1 = (row.get("taxonomy_level_1") or "").strip()
    l2 = (row.get("taxonomy_level_2") or "").strip()
    l3 = (row.get("taxonomy_level_3") or "").strip()
    open_status = (row.get("open_status") or "unknown").strip().lower()
    status_search = (row.get("status_search_result") or "").strip()

    title = l3 or l2 or l1 or f"Problem {index}"
    if len(title) > 120:
        title = title[:117] + "..."

    difficulty = _STATUS_DIFFICULTY.get(open_status, 0.75)

    tex = statement
    if tex and not tex.strip().startswith("\\documentclass"):
        tex = (
            "\\documentclass{amsart}\n"
            "\\usepackage{amsmath,amssymb,amsthm,hyperref}\n"
            "\\begin{document}\n"
            + tex
            + "\n\\end{document}\n"
        )

    record: dict = {
        "id": _make_id(index),
        "dataset": DATASET_SLUG,
        "title": title,
        "statement": statement,
        "tex": tex,
        "tags": _make_tags(row),
        "difficulty": difficulty,
        "solvability_score": None,
        "source_url": question_link or None,
        "year": _parse_year(paper_id),
        # ResearchMath-14k-specific extras
        "open_status": open_status,
        "paper_id": paper_id or None,
        "original_question": original or None,
        "taxonomy_level_1": l1 or None,
        "taxonomy_level_2": l2 or None,
        "taxonomy_level_3": l3 or None,
        "status_summary": status_search or None,
    }
    return record


def main():
    parser = argparse.ArgumentParser(description="Import ResearchMath-14k dataset")
    parser.add_argument("--max", type=int, default=None, metavar="N",
                        help="Maximum number of problems to import (default: all)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip problems that already exist on disk")
    args = parser.parse_args()

    try:
        from datasets import load_dataset
    except ImportError:
        print("ERROR: 'datasets' package not installed", file=sys.stderr)
        sys.exit(1)

    PROBLEMS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading amphora/ResearchMath-14k (split=test)...")
    ds = load_dataset("amphora/ResearchMath-14k", split="test", trust_remote_code=True)

    imported = 0
    skipped = 0
    errors = 0

    for i, row in enumerate(ds):
        if args.max is not None and imported >= args.max:
            break

        pid = _make_id(i)
        dest = PROBLEMS_DIR / f"{pid}.json"

        if args.resume and dest.is_file():
            skipped += 1
            if skipped % 500 == 0:
                print(f"  skipped {skipped} existing problems...")
            continue

        try:
            record = convert_row(i, row)
            dest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            imported += 1
        except Exception as e:
            print(f"  ERROR on row {i}: {e}", file=sys.stderr)
            errors += 1
            continue

        if imported % 500 == 0 and imported > 0:
            print(f"  imported {imported} problems...")

    # Write / update metadata
    meta = {
        "slug": DATASET_SLUG,
        "name": "ResearchMath-14k",
        "description": (
            "14,056 research-level mathematics problems collected from arXiv papers and "
            "workshop problem lists, spanning 11 broad mathematical domains. Each problem "
            "is self-contained in LaTeX and annotated with open/solved/partially-solved status "
            "and supporting evidence. From arXiv:2605.28003."
        ),
        "source": "https://huggingface.co/datasets/amphora/ResearchMath-14k",
        "paper": "https://arxiv.org/abs/2605.28003",
        "license": "CC BY 4.0",
        "version": "1.0.0",
        "year": 2025,
        "problem_count": imported + skipped,
        "tags": ["research-level", "open-problems", "arXiv", "LaTeX", "status-annotated"],
        "domains": [
            "Analysis, PDEs, and Dynamics",
            "Mathematical Physics",
            "Discrete Mathematics and Combinatorics",
            "Number Theory",
            "Geometry and Topology",
            "Theoretical Computer Science",
            "Algebra and Representation Theory",
            "Probability, Statistics, and Machine Learning",
            "Applied and Computational Mathematics",
            "Logic and Foundations",
            "Cross-disciplinary topics",
        ],
    }
    (DATASET_DIR / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nDone. Imported: {imported}, skipped: {skipped}, errors: {errors}")
    print(f"Dataset at: {DATASET_DIR}")

    # Build the list index so queries are fast (avoids reading 14k files on every request)
    print("Building _index.json for fast queries...")
    import sys; sys.path.insert(0, str(REPO_ROOT))
    try:
        from webapp.dataset_store import build_index
        build_index(DATASET_SLUG)
        print("Index built.")
    except Exception as e:
        print(f"Warning: could not build index: {e}")


if __name__ == "__main__":
    main()
