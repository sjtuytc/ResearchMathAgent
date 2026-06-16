"""Download Google DeepMind Formal Conjectures dataset.

Source: https://github.com/google-deepmind/formal-conjectures
License: Apache 2.0 (code), CC-BY 4.0 (content)
Format: Lean 4 .lean files cloned from git; HuggingFace mirror adds JSON metadata.

We use the HuggingFace mirror (phanerozoic/Lean4-FormalConjectures) for structured
access, falling back to git clone of the original repo.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


DATASET_SLUG = "formal_conjectures"
HF_REPO = "phanerozoic/Lean4-FormalConjectures"
GH_REPO = "https://github.com/google-deepmind/formal-conjectures"

METADATA = {
    "slug": DATASET_SLUG,
    "name": "Formal Conjectures (Google DeepMind)",
    "description": "2,571 formal mathematical conjectures expressed in Lean 4, including 1,029 open problems (marked `sorry`). Covers number theory, combinatorics, analysis, algebra, and more.",
    "source": GH_REPO,
    "license": "Apache-2.0 / CC-BY-4.0",
    "version": "2025-05",
    "year": 2025,
    "tags": ["lean4", "formal-math", "conjectures", "open-problems", "google-deepmind"],
}


def download(datasets_dir: Path, force: bool = False) -> int:
    out_dir = datasets_dir / DATASET_SLUG
    problems_dir = out_dir / "problems"

    if problems_dir.is_dir() and any(problems_dir.glob("*.json")) and not force:
        existing = sum(1 for _ in problems_dir.glob("*.json"))
        print(f"[formal_conjectures] Already downloaded ({existing} problems). Use --force to re-download.")
        return existing

    problems_dir.mkdir(parents=True, exist_ok=True)

    # Try HuggingFace datasets library first (fast, structured)
    try:
        from datasets import load_dataset  # type: ignore
        print("[formal_conjectures] Loading from HuggingFace...")
        ds = load_dataset(HF_REPO, split="train", trust_remote_code=True)
        count = 0
        for row in ds:
            pid = _make_id(row.get("name", "") or row.get("file", f"fc{count:04d}"), count)
            record = {
                "id": pid,
                "dataset": DATASET_SLUG,
                "title": row.get("name", pid),
                "statement": row.get("declaration", ""),
                "tex": "",
                "tags": _infer_tags(row.get("file", ""), row.get("declaration", "")),
                "difficulty": None,
                "solvability_score": None,
                "source_url": f"{GH_REPO}/blob/main/{row.get('file', '')}",
                "year": 2025,
                "lean4": row.get("declaration", ""),
                "lean4_file": row.get("file", ""),
            }
            (problems_dir / f"{pid}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            count += 1
        _write_metadata(out_dir, count)
        print(f"[formal_conjectures] Downloaded {count} problems via HuggingFace.")
        return count
    except Exception as e:
        print(f"[formal_conjectures] HuggingFace failed ({e}), falling back to git clone...")

    # Fallback: git clone and parse .lean files
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["git", "clone", "--depth=1", GH_REPO, tmp],
            check=True, capture_output=True
        )
        count = 0
        for lean_file in sorted(Path(tmp).rglob("*.lean")):
            text = lean_file.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(
                r"(?:theorem|def|lemma|conjecture)\s+(\w+)[^\n]*\n(?:.*\n)*?.*sorry", text
            ):
                pid = f"fc{count:04d}"
                name = m.group(1)
                snippet = m.group(0)[:2000]
                record = {
                    "id": pid,
                    "dataset": DATASET_SLUG,
                    "title": name,
                    "statement": snippet,
                    "tex": "",
                    "tags": _infer_tags(str(lean_file), snippet),
                    "difficulty": None,
                    "solvability_score": None,
                    "source_url": GH_REPO,
                    "year": 2025,
                    "lean4": snippet,
                    "lean4_file": str(lean_file.relative_to(tmp)),
                }
                (problems_dir / f"{pid}.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                count += 1

    _write_metadata(out_dir, count)
    print(f"[formal_conjectures] Downloaded {count} problems via git clone.")
    return count


def _make_id(name: str, idx: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]", "_", name)[:60].strip("_") or f"fc{idx:04d}"
    return slug


def _infer_tags(path: str, text: str) -> list[str]:
    tags = ["formal-math", "lean4"]
    path_lower = path.lower()
    text_lower = text.lower()
    for kw, tag in [
        ("numbertheory", "number theory"), ("number_theory", "number theory"),
        ("combinatorics", "combinatorics"), ("algebra", "algebra"),
        ("analysis", "analysis"), ("topology", "topology"),
        ("geometry", "geometry"), ("grouptheory", "group theory"),
    ]:
        if kw in path_lower or kw in text_lower:
            tags.append(tag)
    return list(dict.fromkeys(tags))


def _write_metadata(out_dir: Path, count: int) -> None:
    meta = dict(METADATA)
    meta["problem_count"] = count
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
