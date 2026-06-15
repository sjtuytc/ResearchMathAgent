"""§5: Simple JSONL-based persistent caches for lemmas, citations, and gaps."""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock


class _JSONLCache:
    """Thread-safe JSONL key-value cache."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = Lock()
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        self._cache[entry["key"]] = entry
                    except Exception:
                        pass

    @staticmethod
    def _key(content: str) -> str:
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, content: str) -> dict | None:
        with self._lock:
            return self._cache.get(self._key(content))

    def save(self, content: str, data: dict) -> None:
        key = self._key(content)
        entry = {"key": key, "saved_at": datetime.utcnow().isoformat(), **data}
        with self._lock:
            self._cache[key] = entry
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")


class LemmaDB(_JSONLCache):
    """
    Cache for verified lemmas.
    Prevents re-verifying the same sub-claims across rounds.

    Usage:
        db = LemmaDB("lemma_db.jsonl")
        cached = db.get(lemma_statement)
        if cached:
            use cached["verified"], cached["proof_sketch"]
        else:
            db.save(lemma_statement, {"verified": True, "proof_sketch": "..."})
    """
    def __init__(self, path: str = "lemma_db.jsonl") -> None:
        super().__init__(path)


class CitationDB(_JSONLCache):
    """
    Cache for citation verification results.
    Prevents re-checking the same paper references.

    Usage:
        db = CitationDB("citation_db.jsonl")
        cached = db.get(f"{ref}|{claim}")
        if cached:
            use cached["supported"], cached["caveat"]
        else:
            db.save(f"{ref}|{claim}", {"supported": True, "caveat": None})
    """
    def __init__(self, path: str = "citation_db.jsonl") -> None:
        super().__init__(path)


class FailedGapDB(_JSONLCache):
    """
    Cache for major gaps with lessons learned.
    Used to inject into advisor's failed_attempts_block.

    Usage:
        db = FailedGapDB("failed_gap_db.jsonl")
        db.save(approach, {"gap": "...", "lesson": "..."})
        entries = [db._cache[k] for k in db._cache]
    """
    def __init__(self, path: str = "failed_gap_db.jsonl") -> None:
        super().__init__(path)

    def get_all_lessons(self) -> list[str]:
        with self._lock:
            return [
                f"- Approach: {e.get('approach', e.get('key', '?'))}\n"
                f"  Lesson: {e.get('lesson', '?')}"
                for e in self._cache.values()
                if e.get("lesson")
            ]
