"""Strip pipeline-internal cruft from a `top_solution_*.txt` file.

`top_solution_*.txt` files contain:
  1. A rank/score header (two lines: ``Rank N - Stage X, Solver Y, Score Z/7``
     followed by ``===========...``).
  2. The proof body itself.
  3. The grader council's commentary appended at the tail
     (``**Part 1: The Grading Log**`` or sometimes ``**Step 1: The Grading
     Log**``, followed by Round 0 indictment, Refinement Loop, Coroner's
     Report, Chief Grader's Official Assessment, Strengths, Scaffolding
     Questions, and finally ``SCORE: N/7``).

For external comparison / BS-detector audit work, only (2) is the
"AI proof".  (1) reveals pipeline confirmation and (3) is meta-
commentary that confuses agents not in the pipeline.

This script extracts (2).  Strategy: drop the first two lines if they
match the rank header pattern, then truncate at the earliest
occurrence of any well-known grader-log marker.

Usage:
    python -m scripts.clean_solver_output runs/<id>/top_solution_1.txt
    python -m scripts.clean_solver_output --in PATH --out PATH
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Markers that signal the start of grader-council output.  Truncate at the
# earliest match.  Each is anchored to start-of-line to avoid false matches
# inside the proof body.
_GRADER_MARKERS = [
    r"^\*\*Round 0[: ]",                  # Inquisitor's first move
    r"^\*\*Round 0\\.",                   # variant punctuation
    r"^\*\*Part 1: The Grading Log\*\*",  # standard Part 1 header
    r"^\*\*Step 1: The Grading Log\*\*",  # observed variant
    r"^\*\*Part 2: The Final Verdict\*\*",
    r"^\*\*Coroner['’]s Report:?\*\*",
    r"^\*\*Chief Grader",
]
_GRADER_RE = re.compile("|".join(_GRADER_MARKERS), re.MULTILINE)

# Rank header pattern: ``Rank N — Stage X, Solver Y, Score Z.Z/7``.
_RANK_RE = re.compile(r"^Rank \d+\b.*Score\s+\d+(?:\.\d+)?/7\s*$")


def clean(text: str) -> tuple[str, dict]:
    """Return (cleaned, report).  report has stats for the caller to log."""
    report: dict = {}
    lines = text.splitlines()

    # Strip rank header + separator if present.
    stripped_head = 0
    if lines and _RANK_RE.match(lines[0]):
        stripped_head = 1
        if len(lines) > 1 and re.match(r"^=+\s*$", lines[1]):
            stripped_head = 2
    body = "\n".join(lines[stripped_head:])
    report["stripped_head_lines"] = stripped_head

    # Truncate at first grader-log marker.
    m = _GRADER_RE.search(body)
    if m:
        cut = m.start()
        report["truncated_at"] = m.group(0).strip()
        report["truncated_at_offset"] = cut
        body = body[:cut].rstrip() + "\n"
    else:
        report["truncated_at"] = None

    report["chars_in"] = len(text)
    report["chars_out"] = len(body)
    return body, report


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("input", nargs="?", help="path to top_solution_*.txt")
    p.add_argument("--in", dest="inp", help="alternative input path")
    p.add_argument("--out", help="output path (default: stdout)")
    args = p.parse_args()

    inp = args.inp or args.input
    if not inp:
        print("error: provide an input path", file=sys.stderr)
        sys.exit(2)
    text = Path(inp).read_text()
    cleaned, report = clean(text)

    if args.out:
        Path(args.out).write_text(cleaned)
    else:
        sys.stdout.write(cleaned)

    print(
        f"\n# clean_solver_output: head_lines={report['stripped_head_lines']} "
        f"truncated_at={report['truncated_at']!r} "
        f"chars {report['chars_in']} -> {report['chars_out']}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
