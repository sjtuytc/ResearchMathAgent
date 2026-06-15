"""Abstract Triage Agent — cheap filter between arxiv search and PDF fetch."""
from __future__ import annotations

import re

from ..gemini import call_gemini
from ..models import Paper, TriageOutput, TriageResult


# ── Prompt ───────────────────────────────────────────────────────────────────
_PROMPT_TEMPLATE = """\
# Abstract Triage — cheap relevance filter between arxiv search and PDF fetch.
#
# Your job: read N arxiv abstracts and decide which (if any) are worth the
# downstream cost of fetching the full PDF and feeding it to a Paper Hunter
# agent. False positives waste downstream cost; false negatives leak useful
# results. Be skeptical but not stingy.

[Problem]
{problem}

[Notebook (Level 1 — PROVEN and SUPPORTED only)]
{notebook_level1}

[Search Gap — the specific question this search is trying to answer]
{search_gap}

[Search Query that produced these candidates]
{search_query}

[Candidates]
{candidates}

---

### What counts as a KEEP

A candidate is worth a PDF fetch if its abstract gives concrete evidence
that the full paper contains at least one of:

1. A **named theorem, lemma, or construction** that directly addresses
   the Search Gap (e.g., the inequality the proof is stuck on, the
   classification result the proof needs, the lemma whose hypotheses
   match the current usage).
2. A **counterexample, obstruction, or impossibility result** for the
   conjectured direction in the Search Gap.
3. A **closely related framework or technique** (paracontrolled
   distributions, BSS barrier, hyperbolic-polynomial convexity, slice
   filtration, Godement–Jacquet functional, …) that the abstract
   explicitly invokes and the current proof attempt would plausibly
   benefit from.
4. A **survey** that systematizes the relevant area and would let the
   solver locate the right specialized reference.

### What counts as a DROP

- The abstract is about a different problem with superficial keyword
  overlap (same words, different mathematical objects).
- The abstract is general expository / motivational with no concrete
  technical content named.
- The paper studies the same area but in the wrong regime (wrong
  dimension, wrong characteristic, wrong category) and the abstract
  gives no reason to think the techniques transfer.
- The candidate is a duplicate or near-duplicate of a stronger candidate
  already on the KEEP list.

When uncertain, prefer KEEP for papers that name a specific theorem
relevant to the Search Gap; prefer DROP for papers whose abstract is
only thematically related.

### Output format

For each candidate, in input order, output:

  - ARXIV_ID: <id>
  - DECISION: KEEP | DROP
  - REASON: <one sentence; cite the specific abstract claim that drove the decision>

Then output a SHORTLIST section with the KEEPs in ranked order (most
promising first, max 5):

  SHORTLIST
  1. <arxiv_id> — <≤10-word handle, e.g. "Bauschke et al. hyperbolic polynomial convexity">
  2. ...

If no candidate is worth fetching, output exactly:

  NO_RELEVANT_CANDIDATES: <one sentence explaining what was missing>
"""

_DECISION_PATTERN = re.compile(
    r"ARXIV_ID\s*:\s*(?P<id>\S+)\s*\n"
    r"DECISION\s*:\s*(?P<decision>KEEP|DROP)\s*\n"
    r"REASON\s*:\s*(?P<reason>.+)",
    re.IGNORECASE,
)
_NO_RELEVANT_PATTERN = re.compile(r"NO_RELEVANT_CANDIDATES\s*:\s*(.+)", re.IGNORECASE)
_SHORTLIST_PATTERN = re.compile(r"SHORTLIST\s*\n(.*?)(?=\n\n|\Z)", re.DOTALL | re.IGNORECASE)


def _format_candidates(papers: list[Paper]) -> str:
    lines = []
    for p in papers:
        lines.append(
            f"- ARXIV_ID: {p.arxiv_id}\n"
            f"  TITLE: {p.title}\n"
            f"  AUTHORS: {', '.join(p.authors[:3])}\n"
            f"  DATE: {p.date}\n"
            f"  CATEGORY: {p.primary_category}\n"
            f"  ABSTRACT: {p.abstract[:400]}"
        )
    return "\n\n".join(lines)


def _parse_triage(text: str, papers: list[Paper]) -> TriageOutput:
    no_rel_m = _NO_RELEVANT_PATTERN.search(text)
    if no_rel_m:
        return TriageOutput(
            shortlist=[], no_relevant=True,
            no_relevant_reason=no_rel_m.group(1).strip()
        )

    results: dict[str, TriageResult] = {}
    for m in _DECISION_PATTERN.finditer(text):
        arxiv_id = m.group("id").strip()
        results[arxiv_id] = TriageResult(
            arxiv_id=arxiv_id,
            decision=m.group("decision").upper(),
            reason=m.group("reason").strip(),
        )

    # Assign rank from SHORTLIST section order
    shortlist_m = _SHORTLIST_PATTERN.search(text)
    if shortlist_m:
        shortlist_text = shortlist_m.group(1)
        rank = 1
        for line in shortlist_text.splitlines():
            line = line.strip().lstrip("-•*1234567890. ").strip()
            # find arxiv id in this line
            for aid in results:
                if aid in line:
                    if results[aid].decision == "KEEP":
                        results[aid].rank = rank
                        rank += 1
                    break

    keeps = sorted(
        [r for r in results.values() if r.decision == "KEEP"],
        key=lambda r: (r.rank or 999),
    )
    return TriageOutput(shortlist=keeps[:5], no_relevant=False)


async def run_triage(
    *,
    problem: str,
    notebook_level1: str,
    search_gap: str,
    search_query: str,
    candidates: list[Paper],
    notebook_id: str,
    run_id: str,
    store=None,
) -> TriageOutput:
    if not candidates:
        return TriageOutput(shortlist=[], no_relevant=True,
                            no_relevant_reason="No candidates returned by search.")

    prompt = _PROMPT_TEMPLATE.format(
        problem=problem,
        notebook_level1=notebook_level1,
        search_gap=search_gap,
        search_query=search_query,
        candidates=_format_candidates(candidates),
    )
    call = await call_gemini(
        prompt,
        run_id=run_id,
        notebook_id=notebook_id,
        agent="abstract_triage",
        inputs={"n_candidates": len(candidates), "search_gap": search_gap},
        store=store,
    )
    return _parse_triage(call.output, candidates)
