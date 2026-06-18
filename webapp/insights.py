"""Insight storage helpers.

Insights are stored as JSON files under webapp/insights/:
  system.json                   — system-wide insight
  datasets/<slug>.json          — per-dataset insight
  questions/<dataset>/<qid>.json — per-question insight

Each file has the schema:
  {
    "id":            "system" | "<slug>" | "<qid>",
    "level":         "system" | "dataset" | "question",
    "dataset":       "<slug>" | null,
    "generated_at":  ISO timestamp,
    "generated_by":  "document-manager",
    "summary":       "...",
    "problems":      ["...", ...],
    "highlights":    ["...", ...],
    "suggested_todos": [{"title": "...", "priority": "high|medium|low"}, ...]
  }
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _insights_root(repo_root: Path) -> Path:
    p = repo_root / "webapp" / "insights"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _system_path(repo_root: Path) -> Path:
    return _insights_root(repo_root) / "system.json"


def _dataset_path(repo_root: Path, slug: str) -> Path:
    d = _insights_root(repo_root) / "datasets"
    d.mkdir(exist_ok=True)
    return d / f"{slug}.json"


def _question_path(repo_root: Path, qid: str, dataset: str) -> Path:
    d = _insights_root(repo_root) / "questions" / dataset
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{qid}.json"


def get_system_insight(repo_root: Path) -> dict | None:
    p = _system_path(repo_root)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_dataset_insight(repo_root: Path, slug: str) -> dict | None:
    p = _dataset_path(repo_root, slug)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_question_insight(repo_root: Path, qid: str, dataset: str = "first_proof_1") -> dict | None:
    p = _question_path(repo_root, qid, dataset)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_system_insight(repo_root: Path, data: dict) -> dict:
    data.setdefault("generated_by", "document-manager")
    data.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    data["level"] = "system"
    data["id"] = "system"
    _system_path(repo_root).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def save_dataset_insight(repo_root: Path, slug: str, data: dict) -> dict:
    data.setdefault("generated_by", "document-manager")
    data.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    data["level"] = "dataset"
    data["id"] = slug
    data["dataset"] = slug
    _dataset_path(repo_root, slug).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def save_question_insight(repo_root: Path, qid: str, dataset: str, data: dict) -> dict:
    data.setdefault("generated_by", "document-manager")
    data.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    data["level"] = "question"
    data["id"] = qid
    data["dataset"] = dataset
    _question_path(repo_root, qid, dataset).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def list_all_insights(repo_root: Path) -> list[dict]:
    """Return metadata for all stored insights (without full content)."""
    results: list[dict] = []
    root = _insights_root(repo_root)

    sys_p = root / "system.json"
    if sys_p.is_file():
        try:
            d = json.loads(sys_p.read_text(encoding="utf-8"))
            results.append({"level": "system", "id": "system", "generated_at": d.get("generated_at")})
        except Exception:
            pass

    ds_dir = root / "datasets"
    if ds_dir.is_dir():
        for f in sorted(ds_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                results.append({"level": "dataset", "id": f.stem, "dataset": f.stem, "generated_at": d.get("generated_at")})
            except Exception:
                pass

    q_dir = root / "questions"
    if q_dir.is_dir():
        for ds_d in sorted(q_dir.iterdir()):
            if not ds_d.is_dir():
                continue
            for f in sorted(ds_d.glob("*.json")):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    results.append({"level": "question", "id": f.stem, "dataset": ds_d.name, "generated_at": d.get("generated_at")})
                except Exception:
                    pass

    return results
