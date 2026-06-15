# Math Solver Pipeline

An autonomous multi-agent system for research-level mathematics. Given a problem statement, it runs parallel solver instances for multiple stages, grades each proof attempt, maintains a shared research notebook, and stops when an ensemble-verified solution is found.

Conceptually extends the Momus IMO paper to the research setting.

---

## First Proof Batch-2 submission

This repository is a First Proof Batch-2 submission. First Proof launches
an EC2 instance, builds this repo's Docker image, runs the container
against a common input file, collects `/data/output/`, and terminates
the instance.

**Container contract** (per First Proof's `run.sh`):

```bash
docker run --rm \
  -v input.json:/data/input/input.json:ro \
  -v output-dir:/data/output \
  --env-file secrets.env \
  <image>
```

Our image's `ENTRYPOINT` is `math-solver firstproof` with `CMD` set to
`--input /data/input/input.json --output-dir /data/output`. The
container reads the input JSON, solves each problem in parallel (capped
by `--max-parallel`), writes each `<id>.tex` incrementally to
`/data/output/`, plus `token_log.jsonl` and `solutions.json`, then
exits.

**`secrets.env` contents (required + optional):**

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | YES | All solver / grader / BS-detector / notebook calls go to Gemini. The pipeline crashes without this. |
| `OPENAI_API_KEY` | optional | Enables the optional cross-provider grader fallback (`gpt-5.5-pro`). Container runs Gemini-only if unset. |
| `SERPAPI_API_KEY` | optional | Enables the literature-search agent (Grader 3 / librarian / fetch_and_distill). Container skips literature verification gracefully if unset. |

**`hardware.json`** specifies `r7i.2xlarge` (8 vCPU / 64 GiB RAM) — required
because each per-problem subprocess holds a Pro-tier in-flight context
and we run up to 3 problems concurrently. 4 GiB instances OOM-kill;
this size is the empirically-validated minimum.

**Autonomous loop wiring** (per `src/math_solver/batch.py:run_firstproof`):
solver → incremental `.tex` write → Grader 3 (citation hypothesis check
against fetched literature) → optional W=6 D=6 rework if Grader 3 flags
issues → `.tex` overwritten only if rework produces a strictly better
proof. The best-so-far `.tex` is always on disk so a mid-flight SIGTERM
at the 24h cap leaves a valid output for every problem.

**For First Proof reviewers:** the directories `deploy/`, `scratch/`,
`handoff/`, `design-process/`, `notebooks/`, `runs/` are our own
development tooling and history — **NOT** part of the submission. FP's
`run.sh` only needs `Dockerfile`, `hardware.json`, `pyproject.toml`,
`src/`, and `scripts/`. The `deploy/` directory in particular holds
our own AWS harness used for stress-testing during development; FP
runs its own infrastructure and ignores ours.

---

## Setup

Requirements: Python ≥ 3.11, a Gemini API key.

```bash
# from the repo root
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .

# Gemini API key (required; the pipeline only uses Google Gemini today)
export GEMINI_API_KEY="..."

# Optional: control where run outputs land (default: <repo>/runs)
export RUNS_DIR="$(pwd)/runs"
```

The pipeline writes one directory per run under `RUNS_DIR/<RUN_ID>/`, containing a SQLite `run.db` with all agent calls and persisted state. Inspect with `sqlite3 runs/<RUN_ID>/run.db ".schema"`.

---

## Quick start

```bash
# Put your problem statement in a plain-text file
cat > problems/my_problem.txt <<EOF
Prove that ...
EOF

# Basic run: 4 solvers, budget 20 (≈ 5 stages), no arxiv search.
# --total-budget is required (consumption-driven cap on solver cells).
# --depth is a sanity ceiling that prevents runaway if budget is large.
caffeinate -dims .venv/bin/python -m math_solver.main run \
  problems/my_problem.txt --width 4 --depth 10 --total-budget 20 --no-search

# Larger run with child-spawn enabled (Mode A: single-conjecture branch)
caffeinate -dims .venv/bin/python -m math_solver.main run \
  problems/my_problem.txt --width 6 --depth 10 --no-search \
  --allow-child-spawn --total-budget 80 \
  --label "first attempt"

# Seed from the best stage of a previous run
caffeinate -dims .venv/bin/python -m math_solver.main run \
  problems/my_problem.txt --width 4 --depth 10 --total-budget 24 --no-search \
  --seed-run <RUN_ID>

# With an injected reference PDF (paper_hunter reads it stage 0 + periodically)
caffeinate -dims .venv/bin/python -m math_solver.main run \
  problems/my_problem.txt --width 4 --depth 10 --total-budget 24 \
  --inject-pdf papers/reference.pdf

# Check run status / list runs
.venv/bin/python -m math_solver.main status <RUN_ID>
.venv/bin/python -m math_solver.main list-runs
```

Key flags:

- `--total-budget N` (**required**). Hard cap on solver-cell consumption for the lineage (parent + any child/successor spawns). One cell = one solver call. The orchestrator schedules the next stage while `cells_used + W ≤ N`, then stops. Conjecture-stage rounds also consume from this pool.
- `--width W` parallel solvers per stage.
- `--depth D` sanity ceiling on the stage count (default 10). Prevents runaway loops if budget never gets consumed.
- `--no-search` disable arxiv during run.
- `--allow-child-spawn` enable Mode A: spawn a child run when the extractor emits exactly one conjecture (rare with the W-parallel-extractor flow; most extractions go to Mode B + a conjecture stage instead — see Pipeline pseudocode below).
- `--seed-run <ID>` seed from the best of a previous run.
- `--inject-pdf <path>` repeatable; PDFs are read by `paper_hunter`.
- `--label "..."` human-readable label for `list-runs`.

**Always use `caffeinate -dims`** on macOS to prevent sleep killing long runs. Linux is fine without it. Note: `caffeinate` does NOT keep the system awake when the lid is closed — keep the lid open or run in clamshell mode (external display + keyboard + power).

Typical cost: W=4, budget 20 (about 5 stages no PDFs) is roughly $10-15 of Gemini Pro spend. W=6, budget 80 with PDFs and a child-spawn lineage is $30-50. Always cap with `--total-budget` for unattended runs.

---

## Outer vs inner stages

The pipeline has two nested loops, used throughout this README, the
handoffs, and the data model:

- **Outer stage** (`d`, `1..D`) — one full pass of the W×D main loop:
  W parallel solvers → graders/BS → notebook update → optional search.
  This is the headline "stage" referenced in scores like
  `[3,3,2,2,2,7]` and in `SolutionRecord.stage`.

- **Inner stage** (`r`, `1..R`, with `R = CONJECTURE_ROUNDS = 2`) — the
  rounds *inside* a conjecture stage. A conjecture stage fires between
  outer stages when `no_progress_count >= 2`: W parallel
  conjecture-extractor draws → cluster picks 2 load-bearing
  conjectures → R rounds of solvers attacking those conjectures
  (2/3 prove + 1/3 disprove per surviving conjecture, single grader,
  no BS detector). Any 7/7 marks a conjecture RESOLVED. The conjecture
  stage shares the parent's `d` (it does not increment depth).

In `SolutionRecord`, both collapse to a single integer `stage` field
with `stage_type` disambiguating: `parent` for outer-stage solver
attempts, `conjecture` for inner-stage attempts (stamped with
`stage_when_fired = d`), and `gauntlet_draw` for the verify_solution
per-draw + aggregator records appended during dual-gate extended
grading. `top_solutions()` filters to `stage_type=="parent"` so
inner-stage and gauntlet records don't compete for headline ranking.

## Pipeline pseudocode

```
INPUT: problem.txt, W (width), D (depth), search_mode

# ── Initialisation ──────────────────────────────────────────────────────
notebook ← NotebookAgent(problem)          # AI drafts initial notebook
if injected_pdfs:
    findings ← PaperHunter(problem, notebook, injected_pdfs,
                            hints="read in full — primary references")
    notebook ← NotebookAgent(problem, notebook, findings, mode=UPDATE)

prev_outputs ← seed_run.best_outputs  OR  []
no_progress  ← 0

# ── Main loop ────────────────────────────────────────────────────────────
for stage in 1 .. D:

    # 1. Solve
    solver_outputs[0..W-1] ← parallel:
        Solver(problem, notebook,
               sample(prev_outputs, PREV_CTX_SIZE))

    # 2a. Detect hallucinations (runs first, feeds grader)
    bs_flags[0..W-1] ← parallel:
        BSDetector(problem, solver_outputs[i])

    # 2b. Grade (stopping-condition check only, not for selection)
    grades[0..W-1] ← parallel:
        Grader(problem, solver_outputs[i], bs_flags[i],
               notebook, paper_library)

    # 3. Ensemble exit check for any 7/7
    for each solver_i with grade == 7/7:
        confirmed ← verify_solution(
            3 × Grader(problem, solver_outputs[i]) + Aggregator
        )
        if confirmed:
            DONE → polish → output

    # 4. Notebook update
    bundle ← format(solver_outputs, grades, bs_flags)  # Part 3 + critiques only
    notebook ← NotebookAgent(problem, notebook, bundle, mode=UPDATE)

    # 4b. Progress tracking
    if max(grades) > prev_best:
        no_progress ← 0
    else:
        no_progress += 1

    # 4c. Conjecture extractor fires when stuck ≥ 2 stages
    if no_progress >= 2:
        conjecture_round += 1
        # W parallel extractor draws (each picks a random subset of solvers
        # internally) → cluster picks 2 most-distinct representatives.
        candidates ← parallel:
            ConjectureExtractor(problem, notebook,
                                 solver_outputs, grades)  [W draws]
        top_two ← ClusterAgent(problem, candidates).top_two
        # Mode A: if exactly one conjecture was emitted across all draws,
        # spawn a child run dedicated to it (rare with W=6 — usually skipped).
        # Mode B (the common path): pull the load-bearing conjecture from
        # each of the top-2 tuples → active set of k=2 conjectures. Then run
        # a CONJECTURE STAGE: R=2 rounds of solvers attacking the active set
        # with 2/3 prove + 1/3 disprove, single-grader (no BS, no ensemble),
        # per-conjecture top-2/top-2 leaderboards fed forward between rounds.
        # Any 7/7 → RESOLVED → OC status: CLOSED (proved — pending vetting).
        active ← [t.load_bearing for t in top_two]
        for r in 1..R:                                # CONJECTURE_ROUNDS = 2
            surviving ← [c for c in active if not c.resolved]
            assign 2P+1D solvers per surviving conjecture
            solvers attempt prove / disprove; single-grader scores
            update per-c top-2 prove + top-2 disprove leaderboards
            mark 7/7 outputs as resolved; reallocate freed slots
        notebook ← NotebookAgent(notebook, conjecture_stage_results,
                                  mode=UPDATE)
        no_progress ← 0

    # 5. arxiv search (if search_mode=ENABLED and notebook requests it)
    for query in notebook.search_queries:
        candidates ← search_arxiv(query)
        shortlist  ← Triage(problem, notebook, candidates)
        for paper in shortlist:
            fetch_pdf(paper)
        findings ← PaperHunter(problem, notebook, new_pdfs)
        notebook ← NotebookAgent(problem, notebook, findings, mode=UPDATE)

    # 5b. Periodic re-read of injected PDFs (every 2 stages)
    if injected_pdfs and stage % 2 == 0:
        findings ← PaperHunter(problem, notebook, injected_pdfs,
                                hints="focus on current gaps")
        notebook ← NotebookAgent(problem, notebook, findings, mode=UPDATE)

    # 6. Prune outputs for next stage
    prev_outputs ← top solutions within 3 of max score
                   (proof text + grader critique, no praise)

OUTPUT: top_solution_1.txt, polished_solution_1.txt, run.db
```

---

## Agent roles

| Agent | File | Role |
|-------|------|------|
| **Solver** | `agents/solver.py` | Generates proof attempts (Part 1: strategy, Part 2: partial results, Part 3: proof). Council: Classicist, Visionary, Experimenter, Momus, Veritas, Chief Architect. |
| **Grader** | `agents/grader.py` | Scores 0–7 using Inquisitorial Logic (Inquisitor, Architect, Slip Hunter). Also runs ensemble exit check via 3 draws + Aggregator. |
| **BS Detector** | `agents/bs_detector.py` | Flags hallucinated citations and unjustified jumps before the grader sees the proof. Council: Auditor, Apologist, Metaphorist. |
| **Notebook** | `agents/notebook.py` | Maintains the shared research notebook across stages. UPDATE mode absorbs new material; AUDIT mode cross-checks consistency. Council: Cartographer, Archaeologist, Architect, Conjecture Drafter, Veritas, Chief Synthesizer. |
| **Conjecture Extractor** | `agents/extractor.py` | Fires when stuck ≥ 2 stages. Emits a *tuple* of 1–3 conjectures plus an implication proof ("tuple ⇒ The Problem"). Run W times in parallel each time it fires. Council: Formalist, Strategist, Advocatus Diaboli, Conjecture Auditor (rules i–v), Chief Architect. |
| **Cluster** | `agents/cluster.py` | Groups the W parallel extractor draws by technique family and picks the two most-distinct representatives. The two selected tuples are injected as Mode B sub-lemmas. |
| **Polisher** | `agents/polisher.py` | Final exposition pass — does not change mathematical content. |
| **Paper Hunter** | `agents/paper_hunter.py` | Reads fetched PDFs and extracts findings relevant to current notebook gaps. |
| **Triage** | `agents/triage.py` | Filters arxiv candidate abstracts down to a shortlist for full PDF download. |
| **Paper Guide** | `agents/paper_guide.py` | Conceptual guide for a stuck solver: given a specific paper, what ideas from it bear on the problem? |
| **Literature** | `agents/literature.py` | Answers specific mathematical questions using the fetched paper library. (Stub.) |

All prompts are in `prompts/` — see `prompts/00_README.md`.

---

## State and persistence

Each run gets a directory: `runs/<RUN_ID>/run.db` (SQLite).

Two tables:
- `state` — serialised `RunState` (notebook content, all solution records, run status, paper library)
- `agent_calls` — every LLM call with inputs, output, tokens, stage, agent name

Mid-stage resume: if a run crashes, completed solver/BS/grader calls are cached by `(stage, agent_prefix)`. On restart with the same run ID, cached calls are replayed without re-querying the model.

Seeding: `--seed-run <ID>` loads the best solutions from the seed run's last stage plus its notebook. The seeded run initialises its notebook by reformatting the seed notebook rather than building from scratch.

---

## Key files

```
src/math_solver/
  orchestrator.py   # The W×D loop (entry point: Orchestrator.run())
  main.py           # CLI (click): run, status, list-runs, check-incomplete
  agents/           # One file per agent
  gemini.py         # call_gemini() — all LLM calls, retries, SQLite logging
  state.py          # RunStore (SQLite wrapper) + RunState
  models.py         # Pydantic: RunState, SolutionRecord, AgentCall, Paper, ...
  config.py         # RUNS_DIR, WIDTH, DEPTH, GEMINI_MODEL, PREV_CTX_SIZE, ...
problems/           # Problem .txt files
papers/             # Manually injected PDFs
prompts/            # Prompt text for all agents (for review, not loaded at runtime)
runs/               # Output — one subdirectory per run ID
handoff/handoff.md  # Canonical handoff (run history, recent changes, how-to)
handoff/archive/    # Dated archived handoffs
MEMO_role_inversion.md  # Design memo on solver/grader role inversion
```

---

## Experimental: librarian-books lit-search chain (scratch)

In `scratch/2026-05-24_librarian_books/` — a 3-stage parametric-recall
chain for sourcing prior literature beyond what `agents/paper_hunter.py`
covers. Not yet promoted to `agents/`; experimental, runs from scratch.

1. **`librarian_gauntlet_q7_books.py`** — v2 librarian prompt. Recalls
   papers, books, monographs, lecture notes, surveys, and theses as
   first-class objects (the original librarian was paper-shaped). When
   a canonical reference is publisher-locked, also recalls openly-hosted
   substitutes (TIFR / IHÉS / MSRI / HIM / Park City lecture-notes
   volumes, homepage book drafts, survey chapters). 3 draws + aggregator.
2. **`narrower_q7.py`** — triage pass over the aggregated list against
   the grader's gap report. Buckets: LOAD-BEARING / SUPPORTING /
   REDUNDANT / PERIPHERAL / UNFAMILIAR, with a specific gap citation
   per LOAD-BEARING entry. 3 draws for variance.
3. **`chapter_picker_q7.py`** — for each open-access substitute the
   librarian named, a separate Gemini call returns chapter/section
   recommendations tied to the gaps. Pure parametric (no PDF read).

All three are pure parametric recall — no SerpApi, no web fetch, no
PDF. The companion `search_books.py` probes SerpApi web + pdftotext
for actual book PDFs and is what shows public-web book retrieval is
hard for publisher-locked monographs, which validates the
substitute-recall clause.

Inputs: notebook, near-miss proof, grader gap report (same shape as
`scratch/2026-05-23_q7_literature/inputs/`). Outputs land in
`gauntlet_outputs/`, `narrower_outputs/`, `chapter_picker_outputs/`
within the same scratch dir.

**Inputs each stage expects:**
- Stage 1 (`librarian_gauntlet_*_books.py`): `inputs/notebook_post_stage4.md`,
  `inputs/near_miss_proof.txt`, `inputs/gap_report.txt` in a sibling
  dated scratch dir.
- Stage 2 (`narrower_*.py`): the v2 aggregator output from stage 1
  (parses the `## Aggregator output` section out of the gauntlet `.md`).
- Stage 3 (`chapter_picker_*.py`): the substitutes named by stage 1.
  Currently hand-edited into a `SUBSTITUTES` list at the top of the
  driver; swap to programmatic extraction if reused often.

**To reuse on a new problem:** copy the three drivers into a new dated
scratch dir (`scratch/<YYYY-MM-DD>_<problem>_librarian_books/`),
re-point `INPUTS` to the new problem's notebook / proof / gap-report,
update `KEY` / `LABEL` / `agent` strings for traceability, and run the
three in order. The prompt text itself is problem-agnostic.

**Pipeline to extraction (not yet automated).** Stage 3 emits chapter
recommendations from parametric memory; turning those into actual
findings requires (a) fetching the named PDF, (b) reconciling the
picker's chapter numbers against the actual ToC (parametric picks
drift, especially for less-cited works), (c) slicing the chapter
ranges, (d) running `paper_hunter` on the slice with the gap report
as hints. Pattern A in `docs/skills_literature_injection.md` covers
(b)-(d); (a) is currently manual (Claude-in-Cowork or human fetch)
and is the obvious future automation target.

**Staged book PDFs:** open-access books fetched during stage-3 follow-up
go in `scratch/2026-05-24_librarian_books/pdfs/`. Currently staged:
Witte Morris, *Introduction to Arithmetic Groups* (arxiv v6, 2015).
Thurston *Geometry and Topology of Three-Manifolds* (MSRI / now
slmath.org) — fetch on-demand; URL changed when MSRI rebranded.

**Promotion gate.** Move to `agents/` requires a variance check on ≥1
other problem and review — see `feedback_prompt_iteration.md`. Q8
adaptation is in progress at `scratch/2026-05-24_q8_librarian_books/`.

---

## Design constraints

- Do not rewrite prompts without a specific failure transcript justifying the change.
- The model is `gemini-3.1-pro-preview` (configurable in `config.py` or `GEMINI_MODEL` env var).
- `RUNS_DIR` env var controls output location (default: `<repo>/runs`).
- Do not use `--notebook-file` (human-notebook mode) in seeded runs — it freezes the notebook and prevents AI updates from compounding between stages.

---

## History note — the May-17 → May-19 BS-detector detour

For context if you're auditing this pipeline's verdicts. On 2026-05-17 the
pipeline produced a dual-gate-confirmed proof of Nelson Q2 (run
`02d59be97325`) with a BS detector that did **not** see the notebook.
On 2026-05-18 the BS detector was upgraded with notebook context plus a
Hypothesis Auditor persona. With the stricter setup, follow-up runs
absorbed an auditor-derived "fix" to the standard JPSS K_1(𝔭^c)
definition — adding a top-block constraint that is not in the literature
— and produced subsequently "confirmed" proofs whose K_1 was wrong and
whose final argument relied on unnecessary factorization machinery. On
2026-05-19 an external grader and an about-to-publish PDF proof
(using Godement-Jacquet zeta + Mellin inversion) independently confirmed
that the original 2026-05-17 raw confirmed proof had the correct K_1
definition and was essentially correct. The stricter audit regime was
not "wrong" per se; the over-strictness lived in the *dual gate*, where
BS-clean is a binding requirement alongside grader 7/7, bypassing the
grader's Slip-vs-Fallacy adjudication of BS flags. The polisher was
removed during this work; gold-grader protocols for post-hoc
calibration are now an active line of work.

See `handoff/handoff.md` for the full story, and
`handoff/archive/2026-05-17_nelson_q2.md` for the original confirmation
lineage.
