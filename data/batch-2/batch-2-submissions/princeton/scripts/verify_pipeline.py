"""verify_pipeline.py — proof verification against fetched literature.

Pipeline (4 stages):
  1. ANNOTATE         proof + problem + librarian_findings  → per-step citations
  2. GROUP BY PAPER   (mechanical)                          → {paper: [steps]}
  3a. PINPOINT        (step, paper summary)                 → exact theorem label
  3b. VERIFY          (step, full-PDF pdftotext)            → SUPPORTS / DOES NOT APPLY / CONTRADICTS / NOT FOUND
  4. AGGREGATE        per-step verdicts + feedback.md

Reuses the prompts from scratch/2026-05-25_proof_annotator/. Inputs read from
the problem-dir layout that Package A (librarian) + Package B (fetch_and_distill)
already produce:
  <problem-dir>/
    inputs/
      problem.txt              (optional; falls back to inputs/notebook.md problem field)
      near_miss_proof.txt      proof to verify
    librarian_findings.md      (from Package A)
    pdfs/<slug>.pdf            (from Package B)
    summaries/<slug>.md        (from Package B)
    fetch_and_distill_log.json (from Package B; maps slug -> authors/title/year)

Outputs (all written under <problem-dir>/verify/):
  annotated.md            stage 1
  per_paper_groups.json   stage 2
  pinpoint_results.json   stage 3a
  findings.md             stage 3b (full verdicts, verbatim source statements)
  feedback.md             stage 4 (non-SUPPORTS only — actionable)
  log.json                end-to-end run log

Usage:
  python verify_pipeline.py run <problem-dir>
  python verify_pipeline.py run <problem-dir> --proof-path /path/to/other_proof.txt
  python verify_pipeline.py run <problem-dir> --concurrency 4

PDF identity check: Package B already does its own verify (regex + size). We
ALSO re-check page-1 with Gemini per Sanjeev's request — paranoia is cheap.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from math_solver.gemini import call_gemini  # noqa: E402

ANNOTATOR_DIR = Path(__file__).resolve().parent / "grader3_prompts"
ANNOTATOR_PROMPT = ANNOTATOR_DIR / "proof_annotator_prompt.md"
PINPOINTER_PROMPT = ANNOTATOR_DIR / "pinpointer_prompt.md"
LIT_FINDINGS_PROMPT = ANNOTATOR_DIR / "literature_findings_prompt.md"

MAX_PDF_CHARS = 280_000          # cap full-PDF text per literature-findings call
PAGE1_CHARS = 12_000             # cap for identity-check
DEFAULT_CONCURRENCY = 4


# ─── Prompt loading ────────────────────────────────────────────────────────

def load_prompt(path: Path) -> tuple[str, str]:
    """Split a Markdown prompt file into (system_instruction, user_template)."""
    raw = path.read_text(encoding="utf-8")
    # SYSTEM_INSTRUCTION is the section after "## SYSTEM_INSTRUCTION"
    si_match = re.search(r"## SYSTEM_INSTRUCTION\s*(.*?)## USER_CONTENTS", raw, re.DOTALL)
    user_match = re.search(r"## USER_CONTENTS[^\n]*\n+```\s*(.*?)```", raw, re.DOTALL)
    if not si_match or not user_match:
        raise ValueError(f"Could not parse prompt sections from {path.name}")
    return si_match.group(1).strip(), user_match.group(1).strip()


# ─── pdftotext helpers ─────────────────────────────────────────────────────

def pdftotext_full(pdf_path: Path) -> str:
    """Full-PDF text for the pinpoint+classify stage.

    Routes through ``fetch_and_distill.extract_text`` so this call site gets
    the same primary/fallback fault tolerance as the distill chain: tries
    pdftotext -layout, falls back to pypdf on SubprocessError /
    FileNotFoundError / empty output. Without this wrapper, a per-PDF
    pdftotext failure mid-batch (corrupt PDF that slipped past the
    fetch-time verifier, encoding edge case) silently loses that step's
    verification signal.

    The returned text is truncated to ``MAX_PDF_CHARS`` to match the prior
    contract — verify-stage Flash calls don't expect to see the entire
    Cogdell.
    """
    from fetch_and_distill import extract_text  # local import to keep verify_pipeline standalone
    return extract_text(pdf_path)[:MAX_PDF_CHARS]


def pdftotext_page1(pdf_path: Path) -> str:
    out = subprocess.run(
        ["pdftotext", "-layout", "-f", "1", "-l", "1", str(pdf_path), "-"],
        capture_output=True, text=True, timeout=30,
    )
    return out.stdout[:PAGE1_CHARS]


# ─── Stage 1: Annotate ─────────────────────────────────────────────────────

async def stage1_annotate(*, problem: str, proof: str, librarian_findings: str,
                          run_id: str) -> str:
    si, user = load_prompt(ANNOTATOR_PROMPT)
    user_msg = user.format(
        problem=problem,
        proof_text=proof,
        suggested_references=librarian_findings,
        additional_context="(none — verification mode, not gap-closing)",
    )
    call = await call_gemini(
        user_msg,
        system_instruction=si,
        run_id=run_id, notebook_id="verify",
        agent="proof_annotator_v2",
        inputs={"proof_chars": len(proof), "librarian_chars": len(librarian_findings)},
        store=None,
    )
    return call.output


# ─── Stage 2: Parse annotation + group by paper ────────────────────────────

STEP_RE = re.compile(
    r"\*\*Step\s+(\d+):\s*([^*\n]+?)\*\*\s*\n"                       # heading
    r"\*Claim:\*\s*(.+?)\n"                                          # claim line
    r"\*Citation:\*\s*\[?(CONFIDENT|APPROX|UNABLE TO LOCATE)\]?\s*(.+?)(?:\n|$)",
    re.DOTALL,
)


def parse_annotation(annotated: str) -> list[dict]:
    steps = []
    for m in STEP_RE.finditer(annotated):
        steps.append({
            "step_num": int(m.group(1)),
            "step_name": m.group(2).strip(),
            "claim": m.group(3).strip(),
            "confidence": m.group(4).strip(),
            "citation": m.group(5).strip(),
        })
    return steps


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}

def extract_paper_key(citation: str) -> str | None:
    """Heuristic surname slug from an annotator citation. Used to match against
    Package B's <surname>__<title_slug>.pdf naming."""
    if "UNABLE TO LOCATE" in citation.upper():
        return None
    # Strip leading "[type]" tag
    body = re.sub(r"^\s*\[[^\]]+\]\s*", "", citation)
    # Authors are everything before the first quoted span
    qm = re.search(r"[\"'“]", body)
    authors = body[:qm.start()] if qm else body
    # Drop the first parenthetical group (year, arxiv id, doi, etc.) since
    # its contents would otherwise leak into the author-token list.
    authors = re.split(r"[(]", authors, 1)[0].strip(" ,;")
    if not authors:
        return None
    first_author = authors.split(",")[0].split(" and ")[0]
    tokens = re.findall(r"[A-Za-z]+", first_author)
    # Drop name suffixes (Jr, Sr, II, III, IV) so they don't get picked as
    # the surname.
    tokens = [t for t in tokens if t.lower() not in _NAME_SUFFIXES]
    if not tokens:
        return None
    return tokens[-1].lower()


def group_by_paper(steps: list[dict], available_slugs: list[str]) -> dict[str, list[dict]]:
    """Match each step's citation to one of Package B's available <slug>.pdf
    files. Match strategy: surname prefix. Returns {slug: [steps]}."""
    groups: dict[str, list[dict]] = {slug: [] for slug in available_slugs}
    groups["__unmatched__"] = []
    for step in steps:
        key = extract_paper_key(step["citation"])
        if key is None:
            continue  # UNABLE TO LOCATE — skip, not assigned to any paper
        # Find the slug whose first token matches `key`
        matches = [s for s in available_slugs if s.split("__")[0] == key]
        if len(matches) == 1:
            groups[matches[0]].append(step)
        elif len(matches) > 1:
            # Multiple candidates — assign to all (let verifier disambiguate)
            for s in matches:
                groups[s].append(step)
        else:
            groups["__unmatched__"].append(step)
    return groups


# ─── PDF identity check ────────────────────────────────────────────────────

IDENTITY_SI = """You are verifying that a PDF file is the paper a math
proof author cited. You are shown the expected citation (authors, title,
year) and page 1 of a candidate PDF. Decide YES or NO.

Output exactly one line:
VERDICT: YES | NO
Reason: <one short sentence>

Be strict. Author name match alone is not enough — the title must
substantively match too (allowing translation, abbreviation, or minor
rewording, but not a completely different work by the same authors).
"""


async def verify_pdf_identity(*, slug: str, pdf_path: Path,
                              expected: dict, run_id: str) -> tuple[bool, str]:
    page1 = pdftotext_page1(pdf_path)
    if not page1.strip():
        return False, "empty page1 (encrypted or image-only PDF?)"
    user_msg = (
        f"**Expected citation:**\n"
        f"Authors: {expected.get('authors','?')}\n"
        f"Title: {expected.get('title','?')}\n"
        f"Year: {expected.get('year','?')}\n\n"
        f"**Page 1 of candidate PDF:**\n{page1}"
    )
    call = await call_gemini(
        user_msg,
        system_instruction=IDENTITY_SI,
        run_id=run_id, notebook_id=f"verify/{slug}",
        agent="pdf_identity_check",
        inputs={"slug": slug, "expected_title": expected.get("title","")[:80]},
        store=None,
    )
    verdict = "YES" in call.output.split("VERDICT:", 1)[-1].split("\n", 1)[0].upper()
    reason = call.output.strip()[:200]
    return verdict, reason


# ─── Stage 3a: Pinpoint ────────────────────────────────────────────────────

async def stage3a_pinpoint(*, step: dict, source_name: str, source_summary: str,
                           run_id: str) -> dict:
    si, user = load_prompt(PINPOINTER_PROMPT)
    user_msg = user.format(
        step_claim=f"Step {step['step_num']} ({step['step_name']}): {step['claim']}",
        source_name=source_name,
        source_summary=source_summary,
        annotator_pointer=step["citation"],
    )
    call = await call_gemini(
        user_msg,
        system_instruction=si,
        run_id=run_id, notebook_id=f"verify/{source_name}/step{step['step_num']}",
        agent="pinpointer",
        inputs={"step": step["step_num"], "source": source_name},
        store=None,
    )
    out = call.output
    label_m = re.search(r"Label:\s*(.+?)(?:\n|$)", out)
    reason_m = re.search(r"Reason:\s*(.+)", out, re.DOTALL)
    label = label_m.group(1).strip() if label_m else "UNABLE TO LOCATE"
    # Verify the label string-matches the summary (fabrication guard)
    if label.upper() != "UNABLE TO LOCATE" and label not in source_summary:
        label = f"UNABLE TO LOCATE (fabricated: '{label}' not in summary)"
    return {
        "step_num": step["step_num"], "step_name": step["step_name"],
        "source": source_name, "label": label,
        "reason": (reason_m.group(1).strip()[:300] if reason_m else ""),
    }


# ─── Stage 3b: Literature Findings (full-PDF verify) ───────────────────────

async def stage3b_findings(*, step: dict, problem: str, source_name: str,
                           pdf_text: str, annotator_pointer: str,
                           run_id: str) -> dict:
    si, user = load_prompt(LIT_FINDINGS_PROMPT)
    user_msg = user.format(
        problem=problem,
        step_num=step["step_num"],
        step_name=step["step_name"],
        step_claim=step["claim"],
        annotator_citation=annotator_pointer,
        source_content=pdf_text,
    )
    call = await call_gemini(
        user_msg,
        system_instruction=si,
        run_id=run_id, notebook_id=f"verify/{source_name}/step{step['step_num']}_full",
        agent="literature_findings",
        inputs={"step": step["step_num"], "source": source_name,
                "pdf_chars": len(pdf_text)},
        store=None,
    )
    out = call.output
    # Parse verdict
    verdict = "UNKNOWN"
    for v in ("SUPPORTS", "DOES NOT APPLY", "CONTRADICTS", "NOT FOUND"):
        if re.search(rf"\b{v}\b", out):
            verdict = v
            break
    return {
        "step_num": step["step_num"], "step_name": step["step_name"],
        "source": source_name, "verdict": verdict,
        "block": out.strip(),
    }


# ─── Driver ────────────────────────────────────────────────────────────────

def load_fetch_log(problem_dir: Path) -> dict[str, dict]:
    """Map slug → entry metadata from Package B's fetch_and_distill_log.json."""
    log_path = problem_dir / "fetch_and_distill_log.json"
    if not log_path.exists():
        return {}
    log = json.loads(log_path.read_text())
    meta: dict[str, dict] = {}
    for rec in log.get("fetch_records", []):
        slug = rec.get("slug")
        if not slug:
            continue
        # Only include records that successfully fetched
        any_ok = any(
            hit.get("status") == 200 and hit.get("verify", {}).get("verified")
            for q in rec.get("queries", []) for hit in q.get("hits", [])
        )
        if any_ok or (problem_dir / "pdfs" / f"{slug}.pdf").exists():
            meta[slug] = {
                "authors": rec.get("authors", ""),
                "title": rec.get("title", ""),
                "year": rec.get("year", ""),
            }
    return meta


async def run_pipeline(problem_dir: Path, proof_path: Path | None,
                       concurrency: int, skip_annotate: bool = False) -> None:
    inputs = problem_dir / "inputs"
    proof_file = proof_path or (inputs / "near_miss_proof.txt")
    proof = proof_file.read_text(encoding="utf-8")
    # Problem statement: prefer dedicated file, else top of notebook
    if (inputs / "problem.txt").exists():
        problem = (inputs / "problem.txt").read_text(encoding="utf-8")
    else:
        nb = (inputs / "notebook.md").read_text(encoding="utf-8")
        # Heuristic: first 2000 chars of notebook (contains problem statement)
        problem = nb[:2000]
    librarian = (problem_dir / "librarian_findings.md").read_text(encoding="utf-8")

    out_dir = problem_dir / "verify"
    out_dir.mkdir(exist_ok=True)
    run_id = f"verify_{problem_dir.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    log = {"run_id": run_id, "started": datetime.now().isoformat(), "stages": {}}

    # ── Stage 1
    annotated_path = out_dir / "annotated.md"
    if skip_annotate and annotated_path.exists():
        print(f"[verify] stage 1 — skipped (reusing {annotated_path.name})")
        annotated = annotated_path.read_text(encoding="utf-8")
    else:
        print(f"[verify] stage 1 — annotate ({len(proof)} chars proof, "
              f"{len(librarian)} chars librarian)…")
        annotated = await stage1_annotate(
            problem=problem, proof=proof, librarian_findings=librarian,
            run_id=run_id,
        )
        annotated_path.write_text(annotated, encoding="utf-8")
    steps = parse_annotation(annotated)
    log["stages"]["annotate"] = {"steps_parsed": len(steps),
                                 "by_confidence": {
                                     c: sum(1 for s in steps if s["confidence"] == c)
                                     for c in ("CONFIDENT", "APPROX", "UNABLE TO LOCATE")
                                 }}
    print(f"[verify]   parsed {len(steps)} annotated steps")

    # ── Stage 2
    pdf_files = sorted((problem_dir / "pdfs").glob("*.pdf"))
    summaries = {p.stem: p for p in (problem_dir / "summaries").glob("*.md")}
    available_slugs = [p.stem for p in pdf_files]
    fetch_meta = load_fetch_log(problem_dir)
    groups = group_by_paper(steps, available_slugs)
    (out_dir / "per_paper_groups.json").write_text(
        json.dumps({k: [s["step_num"] for s in v] for k, v in groups.items()}, indent=2),
        encoding="utf-8",
    )
    n_assigned = sum(len(v) for k, v in groups.items() if k != "__unmatched__")
    print(f"[verify] stage 2 — grouped {n_assigned} step-citations across "
          f"{sum(1 for k,v in groups.items() if v and k!='__unmatched__')} papers "
          f"({len(groups['__unmatched__'])} unmatched)")

    # ── PDF identity check (paranoia, parallel)
    print(f"[verify] PDF identity check on {len(available_slugs)} fetched PDFs…")
    sem = asyncio.Semaphore(concurrency)

    def _slug_to_expected(slug: str) -> dict:
        """Synthesize expected-paper metadata from the slug filename when
        Package B's fetch_log doesn't have an entry (e.g., for manually
        dropped PDFs). Slug format: <surname>__<title_slug>."""
        parts = slug.split("__", 1)
        return {
            "authors": parts[0].title() if parts else "?",
            "title": parts[1].replace("_", " ") if len(parts) > 1 else "?",
            "year": "?",
        }

    async def _id_one(slug: str) -> tuple[str, bool, str]:
        async with sem:
            expected = fetch_meta.get(slug) or _slug_to_expected(slug)
            ok, reason = await verify_pdf_identity(
                slug=slug, pdf_path=problem_dir / "pdfs" / f"{slug}.pdf",
                expected=expected, run_id=run_id,
            )
            return slug, ok, reason

    id_results = await asyncio.gather(*[_id_one(s) for s in available_slugs])
    id_verdicts = {slug: (ok, reason) for slug, ok, reason in id_results}
    for slug, ok, reason in id_results:
        flag = "✓" if ok else "✗"
        print(f"[verify]   {flag} {slug}: {reason.splitlines()[0][:120]}")
    # Drop PDFs that failed identity from downstream
    for slug, (ok, _) in id_verdicts.items():
        if not ok:
            groups[slug] = []
    log["stages"]["identity_check"] = {
        slug: {"verdict": ok, "reason": reason}
        for slug, (ok, reason) in id_verdicts.items()
    }

    # ── Stage 3a: pinpoint (per (step, paper) where summary exists)
    print(f"[verify] stage 3a — pinpoint…")
    pinpoint_tasks = []
    for slug, slug_steps in groups.items():
        if slug == "__unmatched__" or not slug_steps:
            continue
        if slug not in summaries:
            continue  # no summary — skip pinpoint, go straight to 3b
        summary_text = summaries[slug].read_text(encoding="utf-8")

        async def _pin(step=None, slug=slug, summary_text=summary_text):
            async with sem:
                return await stage3a_pinpoint(
                    step=step, source_name=slug, source_summary=summary_text,
                    run_id=run_id,
                )

        for step in slug_steps:
            pinpoint_tasks.append(_pin(step=step))
    pinpoints = await asyncio.gather(*pinpoint_tasks) if pinpoint_tasks else []
    (out_dir / "pinpoint_results.json").write_text(
        json.dumps(pinpoints, indent=2), encoding="utf-8",
    )
    print(f"[verify]   pinpointed {len(pinpoints)} (step, paper) pairs")

    # ── Stage 3b: literature findings (full-PDF verify)
    print(f"[verify] stage 3b — verify against full PDFs…")
    pdf_text_cache: dict[str, str] = {}

    async def _verify(step: dict, slug: str) -> dict:
        async with sem:
            if slug not in pdf_text_cache:
                pdf_text_cache[slug] = pdftotext_full(problem_dir / "pdfs" / f"{slug}.pdf")
            # Augment annotator pointer with pinpoint label if available
            pp = next(
                (p for p in pinpoints
                 if p["step_num"] == step["step_num"] and p["source"] == slug),
                None,
            )
            pointer = step["citation"]
            if pp and "UNABLE TO LOCATE" not in pp["label"]:
                pointer = f"{step['citation']}  [Pinpointer: {pp['label']}]"
            return await stage3b_findings(
                step=step, problem=problem, source_name=slug,
                pdf_text=pdf_text_cache[slug], annotator_pointer=pointer,
                run_id=run_id,
            )

    verify_tasks = [
        _verify(step, slug)
        for slug, slug_steps in groups.items()
        for step in slug_steps
        if slug != "__unmatched__" and slug in available_slugs
    ]
    findings = await asyncio.gather(*verify_tasks) if verify_tasks else []
    log["stages"]["verify"] = {
        "n": len(findings),
        "verdicts": {
            v: sum(1 for f in findings if f["verdict"] == v)
            for v in ("SUPPORTS", "DOES NOT APPLY", "CONTRADICTS", "NOT FOUND", "UNKNOWN")
        },
    }

    # ── Stage 4: write findings.md + feedback.md
    findings_md_parts = [f"# Verification Findings — {run_id}\n"]
    feedback_md_parts = [f"# Verification Feedback (non-SUPPORTS only) — {run_id}\n"]
    for f in sorted(findings, key=lambda x: (x["step_num"], x["source"])):
        block = (
            f"\n## Step {f['step_num']} ({f['step_name']}) "
            f"× {f['source']}\n"
            f"**Verdict:** {f['verdict']}\n\n{f['block']}\n"
        )
        findings_md_parts.append(block)
        if f["verdict"] != "SUPPORTS":
            feedback_md_parts.append(block)
    (out_dir / "findings.md").write_text("\n".join(findings_md_parts), encoding="utf-8")
    (out_dir / "feedback.md").write_text("\n".join(feedback_md_parts), encoding="utf-8")

    # Unmatched citations
    if groups["__unmatched__"]:
        unm = "\n# Unmatched citations (no PDF fetched for these)\n\n"
        for s in groups["__unmatched__"]:
            unm += f"- Step {s['step_num']} ({s['step_name']}): {s['citation']}\n"
        (out_dir / "unmatched.md").write_text(unm, encoding="utf-8")
        log["stages"]["unmatched"] = [s["step_num"] for s in groups["__unmatched__"]]

    log["finished"] = datetime.now().isoformat()
    (out_dir / "log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")

    # Summary
    print(f"\n[verify] DONE")
    print(f"  annotated.md      ({len(steps)} steps)")
    print(f"  pinpoint_results  ({len(pinpoints)})")
    v = log["stages"]["verify"]["verdicts"]
    print(f"  verify verdicts:  SUPPORTS={v['SUPPORTS']}  "
          f"DOES NOT APPLY={v['DOES NOT APPLY']}  "
          f"CONTRADICTS={v['CONTRADICTS']}  "
          f"NOT FOUND={v['NOT FOUND']}  UNKNOWN={v['UNKNOWN']}")
    print(f"  outputs in        {out_dir}")


# ─── CLI ───────────────────────────────────────────────────────────────────

@click.group()
def cli():
    pass


@cli.command("run")
@click.argument("problem_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--proof-path", default=None, type=click.Path(exists=True, path_type=Path),
              help="Override the proof to verify (default: inputs/near_miss_proof.txt).")
@click.option("--concurrency", default=DEFAULT_CONCURRENCY, type=int, show_default=True,
              help="Max parallel LLM calls.")
@click.option("--skip-annotate", is_flag=True,
              help="Reuse existing verify/annotated.md instead of re-running the annotator.")
def run_cmd(problem_dir: Path, proof_path: Path | None, concurrency: int,
            skip_annotate: bool) -> None:
    asyncio.run(run_pipeline(problem_dir, proof_path, concurrency, skip_annotate))


if __name__ == "__main__":
    cli()
