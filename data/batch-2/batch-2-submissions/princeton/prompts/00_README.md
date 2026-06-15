# Pipeline Prompts

One file per agent, numbered in pipeline order. Each file contains the
prompt template exactly as used in the code, with {placeholders} intact.

| File | Agent | Version | Source |
|------|-------|---------|--------|
| 01_solver.md | Research Solver (W parallel instances per stage) | v5 | `agents/solver.py` |
| 02_grader.md | Council of Graders + Aggregator (ensemble exit check) | — | `agents/grader.py` |
| 03_bs_detector.md | Hallucination Detector (runs parallel to grader) | — | `agents/bs_detector.py` |
| 04_conjecture_extractor.md | Conjecture Extractor (fires after 2 stuck stages) | — | `agents/extractor.py` |
| 05_notebook.md | Research Notebook Agent (UPDATE and AUDIT modes) | v2 | `agents/notebook.py` + `agents/notebook_v2_prompt.txt` |
| 06_polisher.md | Proof Polisher (final exposition pass) | — | `agents/polisher.py` |
| 07_paper_hunter.md | Paper Hunter (mines fetched papers for new ideas) | — | `agents/paper_hunter.py` |
| 08_paper_guide.md | Paper Guide (conceptual guide for stuck solver) | — | `agents/paper_guide.py` |
| 09_triage.md | Abstract Triage (filters arxiv candidates) | v1 | `agents/triage.py` |
| 10_literature.md | Literature Agent (answers paper questions) | STUB | `agents/literature.py` |
| 11_librarian_books.md | Librarian Books-Expanded (recall + substitute clause + aggregator) | v3 | `scratch/2026-05-24_librarian_books/librarian_gauntlet_q7_books.py` (scratch) |
| 12_narrower.md | Librarian Narrower (LOAD-BEARING triage of aggregator output) | v1 | `scratch/2026-05-24_librarian_books/narrower_q7.py` (scratch) |
| 13_chapter_picker.md | Chapter Picker (parametric chapter selection per substitute) | v1 | `scratch/2026-05-24_librarian_books/chapter_picker_q7.py` (scratch) |

## Key design decisions (as of 2026-05-11)

### Solver v5 (01_solver.md)
Six notebook entry types with distinct rules replace the old
[SUPPORTED]/[SPECULATIVE]/[DISCARDED] system.  Stage 1 explicitly
reads the Proof Skeleton before brainstorming.  Veritas Phase 1 now
also catches uncredited use of Research Hypotheses as proof steps.

### Notebook v2 (05_notebook.md)
**VF entries are immutable** — the notebook agent cannot create, modify,
or remove them.  Only the external vetting pipeline (2×7/7 + aggregator
7/7) can grant VF status.  Key structural changes:
- Proof Skeletons (PS-A/B/C, max 3 active): steps labeled
  [settled] / [open: OC-X] / [wrong].
- [settled] requires grader acceptance across ≥2 attempts.
- IPT reasons must come from grader quotes, not solver self-assessment.
- Auditor persona blocks any VF modification or self-promotion.
- Architect states single Next Priority sentence passed to solvers.

## Pipeline flow (simplified)

```
Stage 1..D:
  W × Solver  →  W × BS Detector  →  W × Grader
                                           ↓
                                      Notebook UPDATE (v2)
                                           ↓
                            (stuck ≥2) Conjecture Extractor
                                           ↓
                            (search on) arxiv → Triage → PDF
                                           ↓
                                      Paper Hunter / Paper Guide
                                           ↓
                            (score=7) Ensemble exit check (3 draws + Aggregator)
                                           ↓
                                      Polisher → done
```

## CLI flags for notebook control

- `--notebook-file PATH`: static notebook; AI agent skipped each stage (human-in-the-loop mode)
- `--seed-notebook-file PATH`: seed the AI notebook agent with this file's content; agent still updates after each stage

## Editing notes

- `IMPORTANT: Only diff-sized patches justified by specific failure transcripts.`
- `10_literature.md` is a stub; prompt not yet written (the literature agent is not invoked by the W×D loop, only by debug paths).
- The `{placeholders}` in each file match exactly the `.format(...)` calls in the source.

## Experimental lit-search chain (files 11–13)

3-stage parametric-recall chain for sourcing prior literature beyond
what `paper_hunter` covers. **Lives in scratch** —
`scratch/2026-05-24_librarian_books/`. The three `.md` files here are
snapshots of the inline prompt strings; the canonical source is the
scratch `.py` file in each row's Source column. If you edit one,
update the other.

Run order: 11 → 12 → 13. Inputs needed: notebook, near-miss proof,
grader gap report (same shape as `scratch/2026-05-23_q7_literature/inputs/`).
Pipeline-to-extraction (fetch PDF → reconcile TOC → slice → paper_hunter)
is currently manual; see the README in the main repo for details.

Promotion gate: variance check on ≥1 other problem and review before
moving to `agents/`. Q8 adaptation in progress at
`scratch/2026-05-24_q8_librarian_books/`.
