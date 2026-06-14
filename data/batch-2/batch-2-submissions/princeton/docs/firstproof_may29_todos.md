# FirstProof May 29 submission — outstanding TODOs

As of 2026-05-27, end of session. Submission window: 2 days.

## Must-have before submission

| # | Item | Why | Effort |
|---|---|---|---|
| 1 | **Confirm which branch FP clones.** Their `run.sh` will `git clone` the repo's default branch. Our default may still be `main` (stale). All today's work is on `fix/bs-gate-ranking-and-double-extract`. Either fast-forward `main` to `fix` OR change the GitHub default branch OR explicitly tell FP staff to clone the `fix` branch. | Without this, FP clones stale code → submission has none of today's autonomy fixes. | 5 min |
| 2 | **Deliver `secrets.env` to FP via their secure channel.** Must contain `GEMINI_API_KEY` (required) + `OPENAI_API_KEY` (optional, for cross-provider grader) + `SERPAPI_API_KEY` (optional, for literature search). | Container fails immediately without `GEMINI_API_KEY`. | 5 min |
| 3 | **End-to-end smoke test** of the deployed container's autonomous loop. The latest fix (`34b421d`) made `grader3` importable; we deployed Q4+Q8 with it but haven't yet seen a run where Grader 3 actually fires + rework launches. | Otherwise we're shipping untested integration. | One Q4+Q8 deploy already running as `i-05b9a65b235de7f9b`; check results. |

## High-value before submission (if time permits)

| # | Item | Why | Effort |
|---|---|---|---|
| 4 | **Refactor `scripts/grader3.py`, `librarian.py`, `fetch_and_distill.py`, `verify_pipeline.py` into `src/math_solver/`.** Currently sibling to the package — required the `COPY scripts /app/scripts` + `PYTHONPATH` Dockerfile wart. | Cleaner code review for FP reviewer; removes a fragility class. | 30-45 min |
| 5 | **Wire OpenAI grader as a confirmation gate.** Today's disagreement study showed OpenAI flagged 3 of 4 Gemini-7/7 proofs at Δ ≥ -1. Adding it as an alongside-grader on dual-gate-confirmed candidates would catch false confirmations. | Higher quality of accepted proofs; smaller false-positive-7/7 rate. | 30-45 min |
| 6 | ~~Diagnose the OpenAI disagreement study EC2 failure.~~ **RESOLVED 2026-05-27 PM.** Root cause: ad-hoc EC2 run didn't write outputs to a persistent location. Larger rerun done on laptop with explicit `--out /Users/arora/claudecode/openai_study_2026-05-27/`. | — | done |
| 7 | ~~Check whether `max_parallel` can be raised from 3 → up to 10.~~ **DONE 2026-05-27.** Default flipped 3 → 10 (commit `5ab0730`). Lower it back via `-var max_parallel=N` if a future run shows RAM pressure on r7i.2xlarge. | — | done |
| 8 | **Add Flash fallback to strip helpers.** Current regex-based `_extract_critique_only` (grader.py) and `_strip_part1` (extractor.py) miss ~12% of Gemini grader outputs (offline test: 255/291 succeed). When regex fails, fall through to Gemini Flash with structured output: "Extract just the Areas for Improvement + Scaffolding Questions sections" / "Extract Part 2 onward". Mirror the 3-tier pattern in `_proof_only` (sentinel → Flash → full text). Expected to raise strip success to ~95-98%. Cost ~$0.001/fallback call. After Q2+Q5 smoke morning inspection — first eyeball *which* outputs the regex misses, then design the Flash prompt. | Higher signal-to-noise in next-stage notebook; fewer agent calls poisoned by leaked Council prose. | ~30 min |

## Day-of deployment TODOs (must verify before FP run.sh fires)

| # | Item | Why | Effort |
|---|---|---|---|
| D1 | **Remove the pre-2026-01-01 search-date restriction in paper_hunter.** The librarian's "Contest-realism rule (hard): Cite only works published before 2026-01-01" was added to avoid the pipeline stumbling onto FirstProof's own posted material during development. For the actual contest run, this restriction should be **lifted** so paper_hunter can cite any work published before the contest deadline. Edit point: `CONTEST_DATE_RULE` in `scripts/librarian.py` (line ~53). Search code paths in `paper_hunter.py` for any equivalent date-cutoff prompt language. | The restriction was a development hack; shipping it to FP gratuitously narrows the search space. | 5-10 min |
| D2 | **Confirm FP env-var contract with Abouzaid + Ward.** There's been confusion about which env vars the container reads vs. defaults from terraform vars. Specifically clarify: `GEMINI_CONCURRENCY` (in-flight cap, semaphore-driven as of `06e1216`), `FIRSTPROOF_MAX_PARALLEL` (problem-level concurrency, defaults to terraform `max_parallel`), `OPENAI_GATE_DISABLED` (gate kill switch), `RUNS_DIR` (`/data/runs` in container per Dockerfile env). Verify whether FP's `run.sh` passes any of these via `docker run --env`, or whether they all come from `secrets.env`/Dockerfile defaults. Misconfiguration here silently disables features (the OAI gate was effectively off all of 2026-05-28 morning's smoke due to the U+2028 key issue, but a wrongly-set `OPENAI_GATE_DISABLED=1` would do the same intentionally and be hard to spot). | A silently-misconfigured FP run reverts us to the pre-tonight pipeline without anyone noticing until the .tex files are reviewed. | 15-30 min |
| D3 | **Measure runtime and adjust `total_budget` if needed.** Runs are taking longer than the back-of-envelope estimates suggested — `2WD = 108` may not be the right ceiling once the full chain fires (gauntlet + BS + OAI gate + Grader 3 + rework). Inspect the in-flight prototypes and tonight's `i-08c7ad12144de024c` for actual cell consumption vs. budget cap. If the actual usage is bumping against the budget, raise it via `-var total_budget=N` at deploy time. | Hitting the budget cap mid-rework wastes the rework attempt and ships a worse `.tex` than necessary. | 10-15 min of log inspection + 1 var change |
| D4 | **Tonight's prototype runs used budget 150.** Recorded here as a reference point for D3's calibration. The four 2026-05-28 PM AWS prototypes (instances `i-0ff19c1cc27de9a5c`, `i-0a8bfdb0e401ba009`, `i-00d9db1ee1c93a9f9`, `i-011bfd155068d0fac`) were launched with `total_budget=150`. Compare their final cell counts in `solutions.json` / `run.db` against 150 to see whether 150 is comfortable headroom or barely enough. | Anchors D3's budget-bump decision to concrete data. | — (just a data point) |

## Nice-to-have (post-submission)

| # | Item |
|---|---|
| 7 | Repo cleanup: `scratch/`, `runs/`, `notebooks/`, `design-process/`, `handoff/` archived or moved to a dev-only branch. Cosmetic. |
| 8 | `deploy/` rename to `dev-infra/aws/` to signal it's not part of FP submission. |
| 9 | Notebook over-pruning fix (IPT-misclassification from Q2 cb22 study). Diff-sized patch to notebook agent prompt. |
| 10 | Meta-LLM consultant for runtime ambiguity (the "voluntarily-called Pro" pattern from 2026-05-27 discussion). |
| 11 | Adaptive budget reallocation in batch.py: when some problems finish early, redirect remaining wallclock to hard problems. |
| 12 | Multi-iteration rework loop (current: 1 rework per problem; could iterate to ≥2 if time permits). |
| 13 | Solve Q4 (Srivastava finite-free Stam) — currently 4/7 best. Needs different strategy or more solver budget. |

## Bugs we know about but haven't fixed

| Where | What | Severity |
|---|---|---|
| OpenAI study EC2 deploy script | Bootstrap upload to S3 never reached / logged. Unknown root cause beyond the earlier IAM-prefix fix. | Medium — blocks the larger study |
| `_flash_pick_url` (fetch_and_distill.py) | No model-fallback chain. Will crash if Flash retires its current model mid-run. | Low — same Flash already passed today's deprecation; next retirement TBD |
| `flash_route` (grader3.py) | Same — no model fallback. | Low |

## Operational notes for the deploy

- **Default branch policy:** FP clones the repo. Ensure default branch (or explicit branch FP is told to clone) is `fix/bs-gate-ranking-and-double-extract`.
- **r7i.2xlarge:** the largest instance FP permits (see `allowed-instances.txt`). `hardware.json` says r7i.2xlarge; verify FP honors it.
- **24h timeout:** container's `--timeout-hours 23` runs inside FP's 24h cap, leaving 1h slack for FP's overhead.
- **secrets.env naming:** FP loads via `docker run --env-file secrets.env` per their `run.sh`. Variable names must match exactly: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `SERPAPI_API_KEY`.
