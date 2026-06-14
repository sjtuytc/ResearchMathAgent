from __future__ import annotations

import os
import shutil
import sys
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path


REQUIRED_PATHS = (
    "README.md",
    "TODO.md",
    "main.tex",
    "references.bib",
    "neurips_2026.sty",
    "problems",
    "skills",
    "output_solutions",
    "figures/teaser.pdf",
    "figures/model.pdf",
    "config/default.yaml",
)

OPTIONAL_TOOLS = (
    ("latexmk", "compile paper and proof PDFs"),
    ("pdflatex", "compile LaTeX documents"),
    ("bibtex", "build bibliographies"),
    ("git", "track and compare run artifacts"),
)


@dataclass(frozen=True)
class Check:
    status: str
    label: str
    detail: str


def run_doctor(args: Namespace) -> int:
    repo_root = _resolve_repo_root(args.repo_root)
    checks: list[Check] = []

    if repo_root is None:
        print("RMA doctor")
        print("FAIL repo root: could not find README.md and problems/ from this directory")
        return 1

    checks.append(Check("PASS", "repo root", str(repo_root)))
    checks.extend(_check_python())
    checks.extend(_check_required_paths(repo_root))
    checks.extend(_check_optional_tools())
    checks.extend(_check_writable_runs(repo_root))

    print("RMA doctor")
    for check in checks:
        print(f"{check.status:4} {check.label}: {check.detail}")

    failures = [check for check in checks if check.status == "FAIL"]
    warnings = [check for check in checks if check.status == "WARN"]

    print()
    if failures:
        print(f"Doctor found {len(failures)} blocking issue(s).")
        return 1
    if warnings:
        print(f"Doctor passed with {len(warnings)} warning(s).")
        return 0
    print("Doctor passed.")
    return 0


def _resolve_repo_root(repo_root: str | None) -> Path | None:
    if repo_root:
        candidate = Path(repo_root).expanduser().resolve()
        return candidate if _looks_like_repo_root(candidate) else None

    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if _looks_like_repo_root(candidate):
            return candidate
    return None


def _looks_like_repo_root(path: Path) -> bool:
    return (path / "README.md").is_file() and (path / "problems").is_dir()


def _check_python() -> list[Check]:
    version = sys.version_info
    detail = f"{version.major}.{version.minor}.{version.micro}"
    if version >= (3, 10):
        return [Check("PASS", "python", detail)]
    return [Check("FAIL", "python", f"{detail}; Python >= 3.10 is required")]


def _check_required_paths(repo_root: Path) -> list[Check]:
    checks = []
    for relative in REQUIRED_PATHS:
        path = repo_root / relative
        if path.exists():
            checks.append(Check("PASS", relative, "found"))
        else:
            checks.append(Check("FAIL", relative, "missing"))
    return checks


def _check_optional_tools() -> list[Check]:
    checks = []
    for executable, purpose in OPTIONAL_TOOLS:
        found = shutil.which(executable)
        if found:
            checks.append(Check("PASS", executable, found))
        else:
            checks.append(Check("WARN", executable, f"not found; needed to {purpose}"))
    return checks


def _check_writable_runs(repo_root: Path) -> list[Check]:
    output_dir = repo_root / "output_solutions"
    target = output_dir if output_dir.exists() else repo_root

    if os.access(target, os.W_OK):
        detail = "output_solutions/ exists and is writable" if output_dir.exists() else "repo root is writable; output_solutions/ can be created later"
        return [Check("PASS", "output directory", detail)]
    return [Check("FAIL", "output directory", f"{target} is not writable")]
