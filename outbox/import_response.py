#!/usr/bin/env python3
"""
Import a Claude response from the outbox back into the RMA system.

Usage:
    python3 import_response.py <response_file.txt>

The response file should be the raw Claude output following the q6_bundle.md format.
This script will:
  1. Parse the structured sections
  2. Update the q6 issue status (close if RESOLVED)
  3. Save the clean proof LaTeX
  4. Create any new issues found
  5. Save a summary document
"""
from __future__ import annotations
import json
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ISSUES_DIR = REPO_ROOT / "webapp" / "issues" / "first_proof_1" / "q6"
DOCS_DIR   = REPO_ROOT / "webapp" / "documents" / "first_proof_1" / "q6"
PROOF_TEX  = REPO_ROOT / "webapp" / "issues" / "q6" / "working_solution.tex"


def extract(text: str, tag: str) -> str:
    m = re.search(rf"=== {tag} ===\n(.*?)\n=== END_{tag} ===", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def load_response(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def update_ky_fan_issue(verdict: str, fix: str, ts: str):
    """Find the open Ky Fan issue and close or comment on it."""
    ISSUES_DIR.mkdir(parents=True, exist_ok=True)
    for f in sorted(ISSUES_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = data.get("title", "")
        if "ky fan" in title.lower() or "non-hermitian" in title.lower():
            if "RESOLVED" in verdict.upper():
                data["status"] = "resolved"
                comment = {
                    "role": "agent",
                    "author": "import-script",
                    "created_at": ts,
                    "body": f"**RESOLVED** by external Claude review.\n\n{verdict[:800]}"
                }
                data.setdefault("comments", []).append(comment)
                if fix and fix.lower() != "no fix needed":
                    data["comments"].append({
                        "role": "agent",
                        "author": "import-script",
                        "created_at": ts,
                        "body": f"Fix applied:\n```latex\n{fix[:2000]}\n```"
                    })
                f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"  ✓ Closed issue: {title}")
            else:
                comment = {
                    "role": "agent",
                    "author": "import-script",
                    "created_at": ts,
                    "body": f"**Review comment** (external Claude):\n\n{verdict[:1200]}"
                }
                data.setdefault("comments", []).append(comment)
                f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"  ~ Updated (still open): {title}")
            return
    print("  ! Could not find Ky Fan issue file — no issue updated.")


def save_proof(tex: str):
    if not tex or len(tex) < 100:
        print("  ! Proof LaTeX too short, skipping save.")
        return
    PROOF_TEX.parent.mkdir(parents=True, exist_ok=True)
    # Prepend a note
    header = (
        "% === IMPORTED FROM EXTERNAL CLAUDE REVIEW ===\n"
        f"% Imported: {datetime.now(timezone.utc).isoformat()}\n"
        "% Source: outbox/q6_bundle.md workflow — Task D\n"
        "% =============================================\n\n"
    )
    PROOF_TEX.write_text(header + tex, encoding="utf-8")
    print(f"  ✓ Proof saved: {PROOF_TEX.relative_to(REPO_ROOT)}")


def create_new_issues(issues_json: str, ts: str):
    try:
        issues = json.loads(issues_json)
    except Exception:
        print("  ! Could not parse new issues JSON.")
        return
    if not issues:
        print("  ~ No new issues to create.")
        return
    ISSUES_DIR.mkdir(parents=True, exist_ok=True)
    for i, iss in enumerate(issues):
        slug = re.sub(r"[^a-z0-9]+", "-", (iss.get("title","issue") or "issue").lower())[:40]
        fname = ISSUES_DIR / f"ext_{int(datetime.now().timestamp())}_{i}_{slug}.json"
        obj = {
            "id": fname.stem,
            "title": iss.get("title",""),
            "body": iss.get("body",""),
            "status": "open",
            "severity": iss.get("severity","minor"),
            "created_at": ts,
            "created_by": "import-script",
            "comments": [],
        }
        fname.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  ✓ New issue: {obj['title'][:60]} [{obj['severity']}]")


def save_document(verdict: str, constant_section: str, ts: str):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    doc_path = DOCS_DIR / f"external_review_{date_str}.md"
    doc = f"""# External Claude Review — q6 (ε-Light Subsets)
*Generated: {ts}*

## Proof Verification Verdict

{verdict}

## Constant Analysis / Improvement Attempt

{constant_section}
"""
    doc_path.write_text(doc, encoding="utf-8")
    print(f"  ✓ Document saved: {doc_path.relative_to(REPO_ROOT)}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 import_response.py <response_file.txt>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    text = load_response(path)
    ts = datetime.now(timezone.utc).isoformat()

    verdict   = extract(text, "TASK_A_VERDICT")
    fix       = extract(text, "TASK_B_FIX")
    constant  = extract(text, "TASK_C_CONSTANT")
    proof_tex = extract(text, "TASK_D_PROOF")
    new_iss   = extract(text, "TASK_D_ISSUES_JSON")

    print("\n=== Importing q6 external review ===\n")

    print("[1/4] Updating open issue…")
    update_ky_fan_issue(verdict, fix, ts)

    print("[2/4] Saving clean proof LaTeX…")
    save_proof(proof_tex)

    print("[3/4] Creating any new issues…")
    create_new_issues(new_iss, ts)

    print("[4/4] Saving review document…")
    save_document(verdict, constant, ts)

    print("\nDone. Reload the web UI to see changes.")


if __name__ == "__main__":
    main()
