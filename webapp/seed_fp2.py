"""Seed all tab content for first_proof_2 problems using Vertex AI (gcloud credits).

For each prob-01 … prob-10 in the first_proof_2 dataset this script:
  1. Creates documents/questions/{pid}/ with skeleton .tex documents
  2. Generates concepts via Vertex (concepts.json)
  3. Discovers literature via Vertex (literature/index.json)

Run directly:
    python -m webapp.seed_fp2

Or trigger via the server endpoint POST /api/seed/first_proof_2
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]


def _log(msg: str) -> None:
    print(f"[seed_fp2] {msg}", flush=True)


# ── LaTeX skeleton writers ────────────────────────────────────────────────────

_PREAMBLE_COMMENT = "% Auto-generated skeleton by RMA seed_fp2. Will be enriched by agents.\n"


def _write_overview(q_dir: Path, pid: str, title: str, statement: str) -> None:
    out = q_dir / "overview.tex"
    if out.is_file():
        return  # don't overwrite manual edits
    stmt = statement[:6000]
    doc = _PREAMBLE_COMMENT + f"""\\section*{{{_tex(title)}}}

\\textbf{{Problem ID:}} \\texttt{{{pid}}} \\quad \\textbf{{Dataset:}} first\\_proof\\_2

\\subsection*{{Problem Statement}}

\\begin{{quote}}
{stmt}
\\end{{quote}}

\\subsection*{{Mathematical Background}}

\\textit{{Background not yet written. Run the daily agent to generate.}}

\\subsection*{{Why This Problem Is Hard}}

\\textit{{Difficulty analysis pending.}}

\\subsection*{{Key Definitions and Tools}}

\\begin{{itemize}}
\\item \\textit{{(populate after first agent run)}}
\\end{{itemize}}
"""
    out.write_text(doc, encoding="utf-8")


def _write_progress(q_dir: Path, pid: str, title: str) -> None:
    out = q_dir / "progress.tex"
    if out.is_file():
        return
    doc = _PREAMBLE_COMMENT + f"""\\section*{{{_tex(pid.upper())}: Current Progress}}

\\textbf{{Status:}} Not started \\quad \\textbf{{Total attempts:}} 0

\\subsection*{{What Has Been Established}}

\\textit{{Nothing yet --- no agent runs recorded.}}

\\subsection*{{What Remains Open}}

\\begin{{itemize}}
\\item Complete proof not yet attempted.
\\item Hypothesis audit not yet performed.
\\item Boundary cases not yet analysed.
\\end{{itemize}}

\\subsection*{{Recommended Next Steps}}

\\begin{{enumerate}}
\\item Run the solver agent with \\texttt{{claude-opus-4-8}} via Vertex AI.
\\item Run the issue discovery agent to surface mathematical gaps.
\\item Review generated concepts and literature to refine strategy.
\\end{{enumerate}}
"""
    out.write_text(doc, encoding="utf-8")


def _write_strategies(q_dir: Path, pid: str, title: str) -> None:
    out = q_dir / "strategies.tex"
    if out.is_file():
        return
    doc = _PREAMBLE_COMMENT + f"""\\section*{{{_tex(pid.upper())}: Strategy Analysis}}

\\textbf{{Strategies tried:}} 0 \\quad \\textbf{{Total attempts:}} 0

\\subsection*{{Recommended Strategy}}

\\textit{{Strategy analysis pending. Run the solver agent to populate.}}

\\subsection*{{Strategy Space}}

\\subsubsection*{{Strategies Already Tried}}

\\textit{{None yet.}}

\\subsubsection*{{Untried Promising Directions}}

\\textit{{To be populated by the strategy agent.}}

\\subsubsection*{{Strategies Likely to Fail}}

\\textit{{To be determined after initial attempts.}}
"""
    out.write_text(doc, encoding="utf-8")


def _write_timeline(q_dir: Path, pid: str) -> None:
    out = q_dir / "timeline.tex"
    if out.is_file():
        return
    doc = _PREAMBLE_COMMENT + f"""\\section*{{{_tex(pid.upper())}: Attempt Timeline}}

\\textbf{{Total attempts:}} 0 \\quad \\textbf{{Successes:}} 0

\\subsection*{{Summary}}

No attempts recorded yet. The timeline is populated automatically after each agent run.

\\subsection*{{Issue Activity Log}}

\\textit{{No issue events recorded yet.}}
"""
    out.write_text(doc, encoding="utf-8")


def _tex(s: str) -> str:
    """Minimal LaTeX escaping for titles."""
    return s.replace("&", r"\&").replace("%", r"\%").replace("#", r"\#").replace("_", r"\_")


# ── Vertex AI helpers ─────────────────────────────────────────────────────────

def _call_vertex(prompt: str, system: str) -> str | None:
    try:
        from .vertex_llm import complete
        return complete(prompt, system=system, model="claude-opus-4-8", max_tokens=8192)
    except Exception as e:
        _log(f"Vertex call failed: {e}")
        return None


# ── Concepts generation (dataset-aware) ──────────────────────────────────────

_CONCEPT_SYSTEM = (
    "You are a mathematical exposition expert. Extract every non-trivial concept, "
    "mathematical object, and notation from this research problem. For each, give a "
    "precise definition and a concrete example. Focus on what a well-prepared graduate "
    "student might still need to look up. Respond ONLY with a JSON array."
)

_CONCEPT_PROMPT = """\
Problem ID: {pid}
Title: {title}

Problem statement (LaTeX):
{statement}

Return ONLY a JSON array of objects with these keys:
  name, notation, category (core|background|notation|theorem), definition, example, related (list)
Aim for 8-16 entries. Output raw JSON only, no markdown fences.
"""


def _generate_concepts(pid: str, title: str, statement: str) -> list[dict]:
    prompt = _CONCEPT_PROMPT.format(pid=pid, title=title, statement=statement[:5000])
    raw = _call_vertex(prompt, _CONCEPT_SYSTEM)
    if not raw:
        return []
    import re
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        items = json.loads(raw)
        return [c for c in items if isinstance(c, dict) and c.get("name")]
    except Exception:
        return []


# ── Literature discovery (dataset-aware) ─────────────────────────────────────

_LIT_SYSTEM = (
    "You are a mathematical research librarian. Given a research problem, identify "
    "the most relevant papers and books. Focus on foundational works and recent advances "
    "directly relevant to proving this result. Respond ONLY with a JSON array."
)

_LIT_PROMPT = """\
Problem ID: {pid}
Title: {title}

Problem statement:
{statement}

Identify 5-10 most relevant papers or books. For each provide:
  title, authors (list), year (int or null), url (arxiv/doi or ""), relevance (1-sentence explanation)
Output raw JSON array only.
"""


def _discover_literature(pid: str, title: str, statement: str) -> list[dict]:
    prompt = _LIT_PROMPT.format(pid=pid, title=title, statement=statement[:4000])
    raw = _call_vertex(prompt, _LIT_SYSTEM)
    if not raw:
        return []
    import re
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        items = json.loads(raw)
        return [p for p in items if isinstance(p, dict) and p.get("title")]
    except Exception:
        return []


# ── Main seed function ────────────────────────────────────────────────────────

def seed_fp2(repo_root: Path = REPO_ROOT, problems: list[str] | None = None) -> dict:
    """Seed all content for first_proof_2 problems. Returns status dict."""
    from .dataset_store import list_problems as ds_list, get_problem as ds_get
    from .concepts import save_concepts, load_concepts
    from .literature import add_paper, load_index

    all_problems = ds_list("first_proof_2") or []
    if problems:
        all_problems = [p for p in all_problems if p.get("id") in problems]

    results: dict[str, dict] = {}

    for prob in all_problems:
        pid = prob.get("id", "")
        if not pid:
            continue
        title = prob.get("title", pid)
        statement = prob.get("statement", prob.get("tex", ""))
        _log(f"seeding {pid}: {title[:55]}…")

        # 1. Create question directory and skeleton .tex docs
        q_dir = repo_root / "documents" / "questions" / pid
        q_dir.mkdir(parents=True, exist_ok=True)
        _write_overview(q_dir, pid, title, statement)
        _write_progress(q_dir, pid, title)
        _write_strategies(q_dir, pid, title)
        _write_timeline(q_dir, pid)
        _log(f"  {pid}: skeleton docs written")

        status = {"docs": True, "concepts": False, "literature": False}

        # 2. Generate concepts (skip if already done)
        if load_concepts(repo_root, pid):
            _log(f"  {pid}: concepts already exist, skipping")
            status["concepts"] = "cached"
        else:
            _log(f"  {pid}: generating concepts via Vertex…")
            concepts = _generate_concepts(pid, title, statement)
            if concepts:
                save_concepts(repo_root, pid, concepts)
                _log(f"  {pid}: {len(concepts)} concepts saved")
                status["concepts"] = len(concepts)
            else:
                _log(f"  {pid}: concept generation failed or empty")
            time.sleep(10)  # avoid quota bursts

        # 3. Discover literature (skip if already done)
        if load_index(repo_root, pid):
            _log(f"  {pid}: literature already exists, skipping")
            status["literature"] = "cached"
        else:
            _log(f"  {pid}: discovering literature via Vertex…")
            papers = _discover_literature(pid, title, statement)
            if papers:
                from datetime import datetime, timezone
                for p in papers:
                    try:
                        add_paper(
                            repo_root, pid,
                            url=p.get("url", ""),
                            title=p.get("title", ""),
                            authors=p.get("authors", []),
                            year=p.get("year"),
                            relevance=p.get("relevance", ""),
                            added_by="seed-agent",
                        )
                    except Exception as e:
                        _log(f"    could not add paper: {e}")
                _log(f"  {pid}: {len(papers)} papers added")
                status["literature"] = len(papers)
            else:
                _log(f"  {pid}: literature discovery failed or empty")
            time.sleep(10)

        results[pid] = status
        _log(f"  {pid}: done — {status}")

    return results


def seed_fp2_background(repo_root: Path = REPO_ROOT) -> None:
    """Run seed_fp2 in the background (called from server thread)."""
    try:
        result = seed_fp2(repo_root)
        _log(f"seed_fp2 complete: {json.dumps(result, indent=2)}")
    except Exception as e:
        _log(f"seed_fp2 ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Seed first_proof_2 content")
    parser.add_argument("--problems", help="Comma-separated list of problem IDs to seed")
    args = parser.parse_args()
    pids = [p.strip() for p in args.problems.split(",")] if args.problems else None
    seed_fp2(REPO_ROOT, pids)
