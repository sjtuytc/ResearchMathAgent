# Skill — Injecting literature into the solver pipeline

Captures patterns and results from the 2026-05-20 retrieval-architecture
session and the 2026-05-21 Q8 literature experiment. Read this before
launching any run that means to use external literature.

## The three injection channels

| Channel | Visibility | Best for |
|---|---|---|
| `--inject-pdf <file>` | Paper-hunter runs once, notebook agent absorbs findings; PDF then attached to EVERY solver/grader/BS call | Quick "give the pipeline a paper" — but bloats every call and notebook agent reformats the findings, diluting them |
| `--seed-notebook-file <file>` | Content seeds the notebook; visible to solvers AND graders/BS via their `additional_materials` block | Long-lived context (lineage notebook, top solutions). Findings put here get notebook-treated (categorized into VF / SNT / RH / IPT) |
| `--additional-materials <file>` | Solver-only labeled `**Additional Materials:**` field, on every solver call, never reaches graders/BS | Verified external findings the solver should weigh as candidate techniques. New as of 2026-05-21. |

Plus `--solver-brief <file>` (vestigial from pre-2026-05-04, untouched since
initial commit) — injects content into the prev-attempts pool, labeled
"ADVERSARIAL GAP ANALYSIS." Solver-only. Use the new
`--additional-materials` instead; `--solver-brief` is retained for
backward-compat but discourage in new work.

## Pattern A: TOC-mediated book reader

Validated 2026-05-21 on Cannas da Silva, *Lectures on Symplectic
Geometry*. Recipe in `scratch/2026-05-21_q8_literature/book_findings_q8.py`.

1. **Source the PDF.** Author homepages frequently host the canonical
   PDF. Books are first-class literature — do NOT bail on "no arxiv ID."
2. **Extract TOC** from PDF pages 1-15 with `pypdf` (or earlier if the
   TOC is shorter). The `PdfReader.pages[i].extract_text()` call gives
   clean text for typical academic books.
3. **Reading-Planner** Gemini call: (problem, near-miss proof, BS gap
   report, book metadata, TOC text) → JSON list of `{chapter, pages,
   addresses_gap, why}`. Pick ≤6 entries, tight selection beats broad.
4. **Slice** the PDF with `pypdf.PdfWriter` per the planner's page ranges.
5. **Hand to `paper_hunter`** with `pdf_paths=[slice_path]` and the BS gap
   report as `hints`. Output: FINDING entries with verbatim extracts.

The slice (not the full book) is what reaches `paper_hunter`. For Cannas
(225 pages), the planner picked 30 pages.

## Pattern B: Paper-Hunter Gauntlet (3 draws + verifying aggregator)

Validated 2026-05-21 on Cannas. Recipe in
`scratch/2026-05-21_q8_literature/paper_hunter_gauntlet_q8.py`.

A single `paper_hunter` call is untrustworthy — Gemini hallucinates
attributions, misassigns gaps, or quotes plausibly but inaccurately.
The gauntlet structure:

1. **3 independent `paper_hunter` draws** on identical inputs
   (problem + notebook + top solutions + PDF + BS gap report).
2. **Aggregator** with the PDF attached (so it can verify quotes
   against source) classifies every claim into:
   - **AGREED:** ≥2 draws cite the same result for the same gap with
     compatible verbatim extracts.
   - **SINGLE-DRAW:** one draw, verbatim verified against PDF.
   - **DISPUTED:** ≥2 draws cite the same result but disagree on gap
     assignment or "How to use."
   - **SUSPECT:** quote does not appear in the PDF.
3. **Brief** packages AGREED + labeled SINGLE-DRAW for
   `--additional-materials`; DISPUTED and SUSPECT go to a separate
   audit file.

**Why this matters:** in the Q8 / Cannas experiment, only **1 of 4
single-call findings survived as AGREED**. The single-call output
included an overconfident Theorem-9.1 misattribution (DROPPED by
gauntlet) and a gap-misassignment for the cotangent-lift
symplectomorphism (DISPUTED). The gauntlet is the validation layer
before any finding becomes "load-bearing" for solver injection.

This pattern also unlocks the **VF-promotion** design in
`docs/vf_promotion_design.md`: a finding that survives the gauntlet on
two independent runs is the "two independent runs" criterion for
promoting an Open Conjecture to a Verified Fact.

## Pattern C: Contest-realism date filter

For FirstProof Challenge 2 simulation: librarians, citation expanders,
and aggregators must reject papers published in the current contest
year. Implementation:

- **Prompt-level rule:** "Cite only papers published before
  YYYY-01-01. Do not cite any paper from YYYY or later, including
  preprints."
- **Post-filter regex** on extracted arxiv IDs:
  `^(YY)(0[1-9]|1[0-2])\.\d{4,5}$` blocks the year-month prefixes
  for the forbidden year.

Used in `scratch/2026-05-21_q8_literature/librarian_gauntlet_q8.py`.
The Q8 librarian-gauntlet draws produced zero 2026 IDs without the
post-filter ever firing — the prompt-level rule was sufficient. Keep
the post-filter as defense-in-depth.

## What we learned from the Q8 experiment

| Variant | Result vs. lineage |
|---|---|
| `--inject-pdf` (v1, 25c4f67dc3c5) | Worse. Token bloat 20K→33K; notebook agent dilutes paper_hunter's findings |
| Contaminated notebook (v2, be03ec646f8b) | Much worse. Notebook absorbed prior failed Cannas attempts as IPT, poisoning new run |
| Clean notebook + `--additional-materials` brief (v3, bbae256fdf37) | Lineage-comparable. Brief reached solver but was not used in load-bearing way — solvers found their own path to 6/7 |

**Headline negative finding:** even gauntlet-verified findings, delivered
through the cleanest channel (Additional Materials, solver-only,
labeled, on every call), did not get incorporated as load-bearing
techniques in v3's stage-4 proofs. The solver chose its own approach
("spacetime extension over $(0,1] \times \mathbb{R}^4$") and treated
the brief as background.

**Hypotheses for why** (untested):
- Solver system_instruction's "verify before use" disposition is too
  conservative — verified extracts get treated as "candidate" anyway.
- The brief's prescriptive synthesis ("$H_t = \rho \pi^*(\partial_t f_t)$")
  competes with the solver's own reasoning, which the solver prefers.
- Q8's load-bearing gap (gluing-compatibility between vertex patches
  and edge collars) requires a structural insight that no single
  textbook chapter provides. The Cannas slice gave techniques, not
  the missing structural idea.
- One book is not enough. McDuff-Salamon, Polterovich 1991, or
  ad-hoc symplectic-topology research papers may each carry a piece
  of the puzzle.

## Operational guidance

- **Default to TOC-first** for new books. Even before slicing, run
  the planner on the TOC and confirm the chapter selection looks
  on-topic for the gap. If the planner can't find clearly-relevant
  chapters, skip the book.
- **Always gauntlet** before injecting paper_hunter output into a
  solver run. Single-call findings are untrustworthy.
- **Prefer `--additional-materials`** over `--inject-pdf` for verified
  findings. PDF on every call is noisy and notebook-distorted.
- **Pair with a clean lineage notebook**. Do not seed a follow-up run
  with a notebook that absorbed a previous failed injection — the
  notebook agent's IPT entries actively discourage the next run from
  retrying the same direction.
- **Scanned PDFs** (image-only or low-OCR-quality) are a known risk —
  pypdf may return empty `extract_text()` for image pages. Test text
  extraction on the first 20 pages before launching the full pipeline.
  If pypdf fails, give Gemini the raw scanned PDF and ask it to read
  the TOC directly via vision; only then decide whether to invest.

## Related artifacts

- `scratch/2026-05-20_retrieval_prototype/` — overnight stress-test:
  librarian gauntlets, citation expansion, embedding rank, ensemble.
- `scratch/2026-05-21_q8_literature/` — Q8-specific: librarian
  gauntlet, TOC-mediated book reader, paper-hunter gauntlet, three
  failed injection runs.
- `docs/skills_prompt_optimization.md` — prompt revision procedure.
- `docs/vf_promotion_design.md` — VF promotion criteria (depends on
  the gauntlet pattern).
