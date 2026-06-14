"""§3: Gap classification and KB recording."""
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path

DEFAULT_KB_FILE = os.getenv("FAILED_GAP_DB", "failed_gaps.jsonl")


def record_major_gap(
    approach: str,
    gap_description: str,
    lesson: str,
    kb_file: str = DEFAULT_KB_FILE,
) -> None:
    """
    Record a major gap to the KB when verifier detects it.
    Used to prevent the solver from repeating the same approach.

    The KB entry feeds into the advisor's failed_attempts_block.
    """
    entry = {
        "type": "verifier_major_gap",
        "approach": approach,
        "gap_description": gap_description,
        "lesson": lesson,
        "source": "verifier",
        "recorded_at": datetime.utcnow().isoformat(),
    }
    Path(kb_file).parent.mkdir(parents=True, exist_ok=True)
    with open(kb_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[gap_classifier] recorded major gap to {kb_file}: {approach[:60]}")


def get_failed_approaches(kb_file: str = DEFAULT_KB_FILE) -> list[str]:
    """
    Return list of approach descriptions that have failed (have major gaps).
    Used to build the advisor's failed_attempts_block to prevent repetition.
    """
    if not os.path.exists(kb_file):
        return []
    approaches = []
    with open(kb_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("type") == "verifier_major_gap":
                    approaches.append(
                        f"- Approach: {entry.get('approach', '?')}\n"
                        f"  Gap: {entry.get('gap_description', '?')}\n"
                        f"  Lesson: {entry.get('lesson', '?')}"
                    )
            except Exception:
                pass
    return approaches


def format_failed_approaches_block(kb_file: str = DEFAULT_KB_FILE) -> str:
    """Format failed approaches for injection into advisor prompt."""
    approaches = get_failed_approaches(kb_file)
    if not approaches:
        return ""
    return "# Previously Failed Approaches (do not repeat)\n" + "\n".join(approaches) + "\n"
