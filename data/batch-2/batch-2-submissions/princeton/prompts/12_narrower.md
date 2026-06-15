# Librarian Narrower — load-bearing triage

**Source of truth:** `scratch/2026-05-24_librarian_books/narrower_q7.py`
**Status:** experimental (scratch). Not loaded by the live pipeline.
**Stage 2 of 3** in the new lit-search chain. See `00_README.md`.

Takes the aggregator output from stage 1 plus the notebook / proof / gap
report; buckets entries as LOAD-BEARING / SUPPORTING / REDUNDANT /
PERIPHERAL / UNFAMILIAR with per-entry gap citation. 3 draws for variance.

---

## NARROWER_PROMPT

```
## RESEARCH LIBRARIAN — NARROWER PASS

A previous librarian pass produced a list of works (papers, books,
monographs, lecture notes, surveys, theses) recalled from parametric
memory as potentially related to a stuck proof attempt. The list errs
on the side of breadth.

Your job: triage the list against the specific gaps the grader
identified. For each entry, judge from what you know of that work's
scope whether it plausibly *addresses* one of the named gaps — not
merely "is in the neighborhood".

You are NOT verifying with PDFs. Use parametric memory of each work's
contents. If you don't remember a work well enough to judge, say so —
"unfamiliar" is a valid bucket.

---
**Notebook:** {notebook}
---
**Near-miss proof:** {proof}
---
**Grader gap report (the gaps to address):** {gap_report}
---
**Aggregated list from prior librarian pass:**
{prior_list}
---

For each entry in the list, place it in exactly one of these buckets:

## LOAD-BEARING
Works whose contents you remember well enough to be confident they
contain machinery directly addressing a specific gap. For each:
- The entry (verbatim from the list)
- The specific gap it addresses (cite the gap by name/number from the
  grader report)
- One sentence: which chapter/theorem/section is the load-bearing
  piece, and why it closes that gap

## SUPPORTING
Works likely useful as background or to verify a step, but not
themselves closing a gap. One-line note each.

## REDUNDANT
Works that overlap with a LOAD-BEARING entry and would be cut for
parsimony. Name which load-bearing entry they overlap with.

## PERIPHERAL
In the neighborhood but you don't see a concrete connection to the
named gaps. One-line why.

## UNFAMILIAR
You don't remember the work's contents well enough to judge.

Rules:
- Every entry goes in exactly one bucket. No entry omitted.
- "LOAD-BEARING" should be selective — aim for 2-4 entries unless the
  list is unusually rich. Padding this bucket defeats the purpose.
- If two entries genuinely cover the same gap, the more canonical /
  more recent / better-targeted one goes in LOAD-BEARING and the
  other in REDUNDANT.
- Do not invent gap numbers. Cite the grader's actual gap names.

```
