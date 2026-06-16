"""Download all external datasets into data/datasets/.

Usage:
  python3.12 -m webapp.downloaders.run_all [--force] [--no-statements]
  python3.12 -m webapp.downloaders.run_all --only formal_conjectures unsolved_math
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = REPO_ROOT / "data" / "datasets"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-download even if already present")
    parser.add_argument("--no-statements", action="store_true", help="Skip fetching Erdős statements from web")
    parser.add_argument("--only", nargs="+", choices=["formal_conjectures", "unsolved_math", "aim_problem_lists", "erdos_problems"],
                        help="Download only these datasets")
    args = parser.parse_args()

    DATASETS_DIR.mkdir(parents=True, exist_ok=True)

    targets = args.only or ["formal_conjectures", "unsolved_math", "aim_problem_lists", "erdos_problems"]
    totals: dict[str, int] = {}

    if "formal_conjectures" in targets:
        from .formal_conjectures import download as dl_fc
        print("\n=== Formal Conjectures ===")
        totals["formal_conjectures"] = dl_fc(DATASETS_DIR, force=args.force)

    if "unsolved_math" in targets:
        from .unsolved_math import download as dl_um
        print("\n=== Unsolved Math ===")
        totals["unsolved_math"] = dl_um(DATASETS_DIR, force=args.force)

    if "aim_problem_lists" in targets:
        from .aim_problem_lists import download as dl_aim
        print("\n=== AIM Problem Lists ===")
        totals["aim_problem_lists"] = dl_aim(DATASETS_DIR, force=args.force)

    if "erdos_problems" in targets:
        from .erdos_problems import download as dl_ep
        print("\n=== Erdős Problems ===")
        totals["erdos_problems"] = dl_ep(DATASETS_DIR, force=args.force, fetch_statements=not args.no_statements)

    print("\n=== Summary ===")
    for name, count in totals.items():
        print(f"  {name}: {count} problems")
    print(f"  Total: {sum(totals.values())} problems across {len(totals)} datasets")


if __name__ == "__main__":
    main()
