"""
xinjie-harness/harness_0507.py  — Current baseline
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bug-fixed and feature-extended successor to harness_0429.py (which itself
superseded harness_0423.py). Same event-sourced, single-advisor architecture
as 0429, with the following corrections and additions.

Bug fixes over harness_0429.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  1. Stale KB metadata after verification — KB summary now reads from
     final_solutions when a verified entry exists, instead of always
     showing the agent's unverified self-declaration from task_outputs.
  2. Advisor overriding writeup self-declaration (trust-chain bug) —
     the writeup's own trailing metadata block is now trusted; the
     advisor's ``solves_original_problem`` flag is used only as a
     fallback when the writeup omits the block.  Disagreements are logged.
  3. Metadata drift in verify-refine loop — ``problem_solved`` and
     ``is_relaxation`` are now updated after each verify call so
     subsequent refine rounds verify against the verifier's verdict,
     not the stale initial claim.
  4. Referenced outputs served stale pre-verification drafts —
     ``get_referenced_outputs`` now serves the verified-and-refined
     Final_Solution (labelled with verification metadata) when one
     exists, falling back to the raw task_output only as an explicitly
     labelled "unverified self-report".
  5. Verifier prompt verified against wrong problem — ``Run_Verify``
     now takes ``original_problem`` and ``claim`` as separate arguments
     so the verifier sees both side-by-side for partial results.
  6. Refiner output not standalone — the refine prompt now shows
     Original Problem vs Claim separately and forbids references to
     the revision process, producing self-contained artifacts.

New feature: PUSH_ORIGINAL (originality pressure)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  When PUSH_ORIGINAL=1 (default off), an originality-pressure rubric
  is spliced into the advisor prompt:
    (a) per-task scoring (0–10) of how well each prior task attacked
        the *original* problem,
    (b) cross-round push-back via reference_task_ids when a prior
        task scored ≤ 4,
    (c) granularity-aware solver-prompt rule: each task is classified
        "exploration" vs "subtask"; only exploration tasks carry a
        "stay close to the original problem" footer.
  With PUSH_ORIGINAL off, the advisor prompts are byte-identical to
  the harness_0429.py baseline.

Other improvements over harness_0429.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  • Structured writeup metadata enforcement: writeup prompts require
    a trailing JSON block; missing blocks trigger a single retry.
  • Self-declared vs verified field separation: task_outputs.jsonl now
    stores raw agent claims under ``self_declared_problem_solved`` /
    ``self_declared_is_relaxation`` with ``verification_status``.
  • Provenance fields on writeup entries: ``advisor_statement``,
    ``advisor_solves_original_problem``, ``writeup_declared_*``, and
    ``metadata_block_present`` for auditing disagreements.
  • verifier_records.jsonl: append-only log of every Run_Verify call
    with full provenance (prompt, response, parsed verdict).
  • In-flight verification notes in KB: ``[VERIFICATION IN PROGRESS]``
    prevents the advisor from assigning redundant re-verification.
  • LaTeX typesetting: uses problem-file stem as document title;
    distinguishes full-problem vs relaxation solutions.

Architecture (unchanged from harness_0429.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  One ``GlobalMemory`` class is the single source of truth for run
  state.  Event-sourced: every KB mutation is appended to
  ``memory/kb_events.jsonl``.  Resume = replay of the per-entity JSONL
  files; no snapshot files to keep in sync.

  Files under ``memory/``:
      kb_events.jsonl        - typed KB mutation events (replayed)
      task_outputs.jsonl     - solver / writeup / assembly outputs (replayed);
                               self-declared claims stored under
                               ``self_declared_*`` with ``verification_status``
      final_solutions.jsonl  - Stage-3 verified solutions (replayed)
      advisor_rounds.jsonl   - completed Stage-2 rounds (replayed)
      verifier_records.jsonl - every Run_Verify call (debug / training)
      verify.jsonl           - per-attempt verifier verdicts (debug)
      refine.jsonl           - per-attempt refined-proof bodies (debug)
      conversation.jsonl     - prompt+response stream (debug)

  Files outside the memory layer: advisor_directions.json,
  benchmark.json, solution.tex, final_status.txt, error.log,
  Overall_Usage/usage.jsonl, and the cross-run solver_history_*.jsonl.

Pipeline:

  Stage 0  │ Literature research (LIT_ENABLED=1, default on): one
             web_search-enabled LLM call enumerates every paper likely to
             contain useful theorems/lemmas/techniques for the problem, then
             each paper's PDF is downloaded and a dedicated reader agent
             (parallel across papers, no web_search) extracts overall summary
             + labelled theorems/lemmas with proof sketches + portable proof
             techniques + other useful info. One JSON object per paper is
             written to literature_research.jsonl. This output feeds Stage 1
             only — it does NOT enter the shared KB.        [search: web_search on; readers: off]
  Stage 1  │ Advisor directions: read the Stage 0 literature extractions
             and synthesise them into a strategic briefing. Web search is
             enabled so the advisor can chase down extra details for any
             paper the Stage 0 extraction did not cover deeply enough.
             → advisor_directions.json                                 [web_search on]
  Stage 1.5│ Deep-Read (optional, DEEP_READ_ENABLED=1): triage ≤N
             papers from Stage 1 directions, fetch arXiv PDFs, extract
             lemmas via high-reasoning LLM, inject into shared KB.
             → imported_papers.json
             (Distinct from Stage 0: this pass picks papers using the
              advisor's already-formed directions and DOES write into KB.)
  Stage 2  │ Single-Advisor Orchestrated Solving                      [advisor: web_search on]
                                                                       [solver: web_search on]
             One persistent advisor drives all solver agents:
             · Each round the advisor reads the full shared KB, the
               structured outputs from the previous round's solvers,
               and the remaining budget, then:
                 — writes complete prompts for 1–MAX_PARALLEL_AGENTS
                   solver agents (parallel, stateless, one-shot)
                 — emits editorial KB updates (proven results, failed
                   attempts, bottlenecks, frontier)
                 — flags partial results for immediate write-up
                 — signals an action:
                     continue   – keep exploring (default)
                     done       – no more work needed
             · Solvers are stateless: each receives an advisor-drafted
               prompt and appends a structured <SOLVER_REPORT> block;
               local code auto-merges the report into the shared KB.
             · The advisor decides per-round how much prior context
               (full previous solver output vs KB-slice summary) to
               expose in each new solver prompt.
             · Optional originality pressure (PUSH_ORIGINAL=1) — see
               above for details.
             · Budget: ADVISOR_BUDGET (default 5) advisor calls.
             · The shared knowledge base (proven_results, failed_attempts,
               bottlenecks, frontier, advisor_notes, partial_writeups_done)
               lives inside ``GlobalMemory`` and is persisted as a typed
               event log (``memory/kb_events.jsonl``).  KB entries are
               annotated with verification status from final_solutions
               when available.
             · Full conversation history (every prompt + response) is
               written to ``memory/conversation.jsonl`` for debugging.
             · The resume position is the tail of
               ``memory/advisor_rounds.jsonl``: each fully-completed round
               appends an event with budget remaining + task counter, and
               on restart the constructor replays the log to recover state.
               No separate checkpoint file. A mid-round crash replays the
               advisor call (same atomicity contract as before).
  Stage 2.9│ Assembly: after the advisor loop ends, an advisor reviews
             the shared KB and drafts an assembly prompt, then a solver
             assembles the best possible self-contained solution.
  Stage 3  │ Verify + Refine (VERIFY_ROUNDS rounds) on the assembled
             solution from Stage 2.9 and any write-up outputs from
             Stage 2.  Verification verdicts (including updated
             problem_solved / is_relaxation) are written back into the
             shared KB.  The verifier receives both the original problem
             and the stated claim as separate fields.
  Stage 3.5│ Finalize (optional, FINALIZE_ENABLED=1): two-track
             final-output stage.
             Track A: if a non-relaxation proof exists, polish it
               (permission to relax bounds slightly) then typeset.
             Track B: otherwise, compile a progress report then typeset.
             When enabled, replaces Stage 5 typeset and overrides
             benchmark.json's solution text with the polished proof.
             → solution.tex
  Stage 4  │ Verified solution → benchmark.json                      [BENCHMARK_MODEL]
  Stage 5  │ Verified solution → solution.tex  (LaTeX typesetting)   [TYPESET_MODEL]
             (legacy fallback — skipped when finalize wrote solution.tex)

Partial results:
  When a meaningful partial result is found, the advisor can flag it
  for a dedicated write-up agent (prompt fully drafted by the advisor).
  Verified partial results are recorded in the shared KB (written_up=true).

Cross-run memory:
  solver_history_<problem>.jsonl persists final solver notes across runs so
  future runs avoid repeating confirmed dead ends.

Problems:
  Place .txt files in xinjie-harness/problems/ and set PROBLEM_FILE=<name>.
  If only one .txt file exists, it is auto-selected.

Key env vars:
  MODEL                default: gpt-5.5-pro
  BENCHMARK_MODEL      strategy summary in benchmark.json   default: o4-mini
  SUMMARIZE_MODEL      proof sketch in shared KB            default: o4-mini
  TYPESET_MODEL        LaTeX typesetting (Stage 5)          default: o4-mini
  ADVISOR_BUDGET       total advisor calls in Stage 2       default: 5
  STAGE2_DEADLINE_HOURS wall-clock hours from RUN_START_TS   default: 21
                       after which Stage 2 self-terminates at
                       the next round boundary (set 0 to disable).
                       Start time is persisted in memory/run_start_time.txt
                       so resume does NOT reset the budget.
  VERIFY_ROUNDS        verification rounds per solution      default: 2
  MAX_PARALLEL_AGENTS  solver agents per round (max 3)      default: 2
  PUSH_ORIGINAL        splice the originality-pressure rubric into the advisor
                       prompts (per-task scoring against the original problem,
                       push-back-via-reference, exploration-vs-subtask footer
                       rule); off = baseline                  default: 0
  LIT_ENABLED          run Stage 0 literature research        default: 1
  LIT_PARALLEL         parallel reader agents in Stage 0      default: 5
  DEEP_READ_ENABLED    run Stage 1.5 literature deep-read     default: 0
  DEEP_READ_MAX_PAPERS max papers to fetch in deep-read       default: 5
  DEEP_READ_LEMMAS_PER_PAPER max lemmas extracted per paper   default: 3
  FINALIZE_ENABLED     run Stage 3.5 finalize (Track A/B)    default: 0
  PROBLEM_FILE         e.g. "p001_complex_rademacher.txt"
  OUTPUT_ROOT_DIR      default: ./TEMP
  RESUME_DIR           resume an interrupted run
  PROBLEM_DATA_DIR     directory for solver_history_*.jsonl files
                       default: same directory as this script
  OPENAI_API_KEY       or place key in .openai_api_key next to this script
  OPENAI_ORG_ID        optional
"""

import hashlib
import json
import os
import random
import re
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep, time as wall_time

try:
    from openai import OpenAI
except ImportError as exc:
    raise RuntimeError(
        "Install the OpenAI Python package: python3 -m pip install openai"
    ) from exc

from deep_read import run_deep_read  # noqa: E402  (sibling module)
from finalize import (  # noqa: E402  (sibling module)
    finalize_full_proof,
    finalize_progress_report,
    find_full_proof_seed,
    collect_verified_partials,
)
from literature_research import (  # noqa: E402  (sibling module)
    run_literature_research,
    format_literature_for_directions,
)


# ─── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR         = Path(__file__).resolve().parent
LOCAL_ENV_FILE     = SCRIPT_DIR / ".env"
LOCAL_API_KEY_FILE = SCRIPT_DIR / ".openai_api_key"
PROBLEMS_DIR       = SCRIPT_DIR / "problems"


# ─── Env helpers ──────────────────────────────────────────────────────────────

def load_local_env_file(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def load_secret_file(path):
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def env_int(name, default):
    v = os.getenv(name)
    return int(v) if v and v.strip() else default


def env_bool(name, default=True):
    v = os.getenv(name)
    if not v or not v.strip():
        return default
    return v.strip().lower() in {"true", "1", "yes"}


def normalize_effort(value):
    n = (value or "").strip().lower()
    return None if n in {"", "none", "off"} else n


# ─── Load env + API key ───────────────────────────────────────────────────────

load_local_env_file(LOCAL_ENV_FILE)

api_key = load_secret_file(LOCAL_API_KEY_FILE) or os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError(
        "Provide an API key via .openai_api_key (next to this script) "
        "or OPENAI_API_KEY in the .env file or environment."
    )


# ─── Problem data directory ───────────────────────────────────────────────────
# Holds files that are global across runs for a given problem:
#   proof_techniques_db.jsonl  — novel lemmas/techniques extracted from papers
#   solver_history_<stem>.jsonl — cross-run solver progress notes

_pdd = os.getenv("PROBLEM_DATA_DIR", "").strip()
PROBLEM_DATA_DIR = Path(_pdd).resolve() if _pdd else SCRIPT_DIR
PROBLEM_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ─── Model ────────────────────────────────────────────────────────────────────

MODEL            = os.getenv("MODEL",            "gpt-5.5-pro")
BENCHMARK_MODEL  = os.getenv("BENCHMARK_MODEL",  "o4-mini")
SUMMARIZE_MODEL  = os.getenv("SUMMARIZE_MODEL",  "o4-mini")
TYPESET_MODEL    = os.getenv("TYPESET_MODEL",    "o4-mini")


# ─── Problem resolution ───────────────────────────────────────────────────────

def resolve_problem_file():
    env_val = os.getenv("PROBLEM_FILE", "").strip()
    if env_val:
        for candidate in [Path(env_val), SCRIPT_DIR / env_val, PROBLEMS_DIR / env_val]:
            if candidate.exists():
                return candidate
        raise FileNotFoundError(
            f"PROBLEM_FILE={env_val!r} not found. Tried:\n"
            + "\n".join(f"  {c}" for c in [Path(env_val), SCRIPT_DIR / env_val, PROBLEMS_DIR / env_val])
        )
    if PROBLEMS_DIR.exists():
        files = sorted(PROBLEMS_DIR.glob("*.txt"))
        if len(files) == 1:
            print(f"[problem] auto-selected: {files[0].name}")
            return files[0]
        if len(files) > 1:
            listing = "\n".join(f"  {f.name}" for f in files)
            raise RuntimeError(
                "Multiple problems found in problems/. "
                "Set PROBLEM_FILE=<filename> to pick one:\n" + listing
            )
    raise FileNotFoundError(
        "No problem file found. Place a .txt file in xinjie-harness/problems/ "
        "or set PROBLEM_FILE=<path>."
    )


PROBLEM_PATH = resolve_problem_file()
print(f"[problem] {PROBLEM_PATH}")
with open(PROBLEM_PATH, encoding="utf-8") as _f:
    problem = _f.read().strip()
print(problem)


# ─── Config ───────────────────────────────────────────────────────────────────

ADVISOR_BUDGET         = env_int("ADVISOR_BUDGET",         5)  # total advisor calls in Stage 2
VERIFY_ROUNDS          = env_int("VERIFY_ROUNDS",          2)
QUEUED_TIMEOUT_SECONDS      = env_int("QUEUED_TIMEOUT_SECONDS",      30 * 60)
IN_PROGRESS_TIMEOUT_SECONDS = env_int("IN_PROGRESS_TIMEOUT_SECONDS", 2 * 60 * 60)

# Exponential backoff for run_response failures (exception path + non-completed
# status). Polling itself stays at a fixed 2s — backoff only applies between
# (failed submit) and (next submit). Cap each sleep at RETRY_MAX_SECONDS.
# Retry is unbounded by attempt count (matches prior behaviour) so a 21h run
# survives transient API outages; ctrl-C if you need to bail out.
RETRY_BASE_SECONDS = env_int("RETRY_BASE_SECONDS",  30)
# RETRY_MAX_SECONDS  = env_int("RETRY_MAX_SECONDS",   600)
RETRY_MAX_SECONDS  = env_int("RETRY_MAX_SECONDS",   400)

# After this many consecutive rate-limit failures within a single run_response
# call, downgrade the reasoning effort (xhigh → high by default) for the
# remaining retries of THIS call. Reset on successful return. Set threshold to
# 0 to disable. Only rate-limit failures count; 5xx/timeout/other failures do
# not increment the counter. Only applies to stages whose name starts with one
# of RATE_LIMIT_DOWNGRADE_STAGES (comma-separated prefixes; default: lit_search
# only — so e.g. "lit_search" matches, but "lit_read_*" / advisor / solver
# stages are untouched).
RATE_LIMIT_DOWNGRADE_THRESHOLD = env_int("RATE_LIMIT_DOWNGRADE_THRESHOLD", 10)
RATE_LIMIT_DOWNGRADE_TO        = normalize_effort(
    os.getenv("RATE_LIMIT_DOWNGRADE_TO", "high")
)
RATE_LIMIT_DOWNGRADE_STAGES = tuple(
    s.strip() for s in os.getenv("RATE_LIMIT_DOWNGRADE_STAGES", "lit_search").split(",")
    if s.strip()
)
# Wall-clock cutoff for Stage 2 (advisor-orchestrated solving). When the
# total elapsed time since the FIRST start of this run (persisted across
# resumes via memory/run_start_time.txt) reaches this many hours and we
# are still inside the Stage-2 loop, terminate Stage 2 at the next round
# boundary so the downstream stages (2.9 assembly, 3 verify+refine, 3.5
# finalize) still get a chance to run within the 24h competition budget.
# Set to 0 to disable the cutoff entirely (useful for local debugging).
STAGE2_DEADLINE_HOURS  = env_int("STAGE2_DEADLINE_HOURS",  21)

# Hard wall-clock cap on the retry / backoff path inside ``run_response``.
# Distinct from STAGE2_DEADLINE_HOURS:
#   - STAGE2_DEADLINE_HOURS is a SOFT cap on the Stage 2 advisor loop,
#     checked at round boundaries inside ``orchestrated_solve_loop_v2``.
#     In-flight API calls finish normally; the loop simply doesn't start
#     a new round once exceeded.
#   - HARD_DEADLINE_HOURS is a HARD cap on retries inside ``run_response``.
#     Once exceeded, any new submit / non-completed retry / SDK-exception
#     retry is skipped; the function returns ``("", empty_usage)`` instead
#     of looping forever. In-flight polling is NOT interrupted — it is
#     already bounded by QUEUED_TIMEOUT_SECONDS / IN_PROGRESS_TIMEOUT_SECONDS.
# Defaults to STAGE2_DEADLINE_HOURS + 2 so Stage 2.9 / 3 / 3.5 / 4 / 5
# get a 2h healthy-completion window after Stage 2 exits, and the harness
# winds down well before the 24h container kill. Set to 0 to disable.
HARD_DEADLINE_HOURS    = env_int("HARD_DEADLINE_HOURS",    STAGE2_DEADLINE_HOURS + 2)
if HARD_DEADLINE_HOURS > 0 and HARD_DEADLINE_HOURS <= STAGE2_DEADLINE_HOURS:
    print(f"[config] WARNING: HARD_DEADLINE_HOURS={HARD_DEADLINE_HOURS} <= "
          f"STAGE2_DEADLINE_HOURS={STAGE2_DEADLINE_HOURS}; Stage 3+ pipeline "
          f"won't get any post-Stage-2 time. Recommended: HARD > STAGE2 + 1.")

BACKGROUND = env_bool("BACKGROUND", True)

# When True, splice an "Originality Pressure" rubric into the advisor prompts
# that (a) makes the advisor score each prior task's attack on the *original*
# problem, (b) requires push-back-via-reference for shallow / relaxed prior
# results, and (c) requires every task assignment to be classified
# `"exploration"` vs `"subtask"` with a granularity-aware solver-prompt footer
# rule. With PUSH_ORIGINAL off, the rendered advisor prompts are byte-identical
# to the baseline.
PUSH_ORIGINAL = env_bool("PUSH_ORIGINAL", False)

# Stage 0: Literature research — broad LLM-driven search + per-paper deep-read
# BEFORE Stage 1 directions. Output (literature_research.jsonl) feeds the
# Stage 1 direction-writing prompt ONLY; it does NOT enter the shared KB.
# (Stage 1.5 deep-read below is a separate, post-Stage-1 pass that DOES
# inject into the KB on a narrower set triaged from the directions.)
LIT_ENABLED              = env_bool("LIT_ENABLED",             True)
LIT_PARALLEL             = env_int ("LIT_PARALLEL",             5)
LIT_SEARCH_REASONING     = normalize_effort(os.getenv("LIT_SEARCH_REASONING", "xhigh"))
LIT_SEARCH_MAX_TOKENS    = env_int ("LIT_SEARCH_MAX_TOKENS",   128000)
LIT_READ_REASONING       = normalize_effort(os.getenv("LIT_READ_REASONING",   "xhigh"))
LIT_READ_MAX_TOKENS      = env_int ("LIT_READ_MAX_TOKENS",     128000)

# Stage 1.5: Deep-Read — fetch and extract lemmas from arXiv papers cited in
# the advisor directions. Toggled by DEEP_READ_ENABLED (default off).
DEEP_READ_ENABLED            = env_bool("DEEP_READ_ENABLED", True)
DEEP_READ_MAX_PAPERS         = env_int ("DEEP_READ_MAX_PAPERS",       5)
DEEP_READ_LEMMAS_PER_PAPER   = env_int ("DEEP_READ_LEMMAS_PER_PAPER", 3)
DEEP_READ_PARALLEL           = env_int ("DEEP_READ_PARALLEL",         5)
DEEP_READ_TRIAGE_REASONING   = normalize_effort(os.getenv("DEEP_READ_TRIAGE_REASONING",  "medium"))
DEEP_READ_EXTRACT_REASONING  = normalize_effort(os.getenv("DEEP_READ_EXTRACT_REASONING", "xhigh"))
# DEEP_READ_TRIAGE_MAX_TOKENS  = env_int ("DEEP_READ_TRIAGE_MAX_TOKENS",  16000)
# DEEP_READ_EXTRACT_MAX_TOKENS = env_int ("DEEP_READ_EXTRACT_MAX_TOKENS", 16000)
DEEP_READ_TRIAGE_MAX_TOKENS  = env_int ("DEEP_READ_TRIAGE_MAX_TOKENS",  128000)
DEEP_READ_EXTRACT_MAX_TOKENS = env_int ("DEEP_READ_EXTRACT_MAX_TOKENS", 128000)
DEEP_READ_PAPER_MAX_CHARS    = env_int ("DEEP_READ_PAPER_MAX_CHARS",   250_000)


# Stage 3.5: Finalize — two-track final-output stage (Track A: full-proof polish
# + typeset; Track B: progress report + typeset). Replaces the legacy Stage 5
# typeset for runs where finalize is enabled. Toggle off via FINALIZE_ENABLED=false
# to fall back to legacy path.
# FINALIZE_ENABLED              = env_bool("FINALIZE_ENABLED",                False)
FINALIZE_ENABLED              = env_bool("FINALIZE_ENABLED",                True)
ANNOTATE_TEX                  = env_bool("ANNOTATE_TEX",                    False)
FINALIZE_POLISH_REASONING     = normalize_effort(os.getenv("FINALIZE_POLISH_REASONING",  "xhigh"))
FINALIZE_POLISH_MAX_TOKENS    = env_int ("FINALIZE_POLISH_MAX_TOKENS",      128_000)
FINALIZE_TYPESET_REASONING    = normalize_effort(os.getenv("FINALIZE_TYPESET_REASONING", "xhigh"))
FINALIZE_TYPESET_MAX_TOKENS   = env_int ("FINALIZE_TYPESET_MAX_TOKENS",     128_000)

PLAN_REASONING        = normalize_effort(os.getenv("PLAN_REASONING",        "xhigh"))
SOLVE_REASONING       = normalize_effort(os.getenv("SOLVE_REASONING",       "xhigh"))
ADVISOR_REASONING     = normalize_effort(os.getenv("ADVISOR_REASONING",     "xhigh"))
VERIFY_REASONING      = normalize_effort(os.getenv("VERIFY_REASONING",      "xhigh"))
REFINE_REASONING      = normalize_effort(os.getenv("REFINE_REASONING",      "")) or SOLVE_REASONING

PLAN_VERBOSITY        = os.getenv("PLAN_VERBOSITY",        "medium")
SOLVE_VERBOSITY       = os.getenv("SOLVE_VERBOSITY",       "medium")
ADVISOR_VERBOSITY     = os.getenv("ADVISOR_VERBOSITY",     "medium")
VERIFY_VERBOSITY      = os.getenv("VERIFY_VERBOSITY",      "medium")
REFINE_VERBOSITY      = os.getenv("REFINE_VERBOSITY",      SOLVE_VERBOSITY)

PLAN_MAX_TOKENS          = env_int("PLAN_MAX_TOKENS",          128_000)
SOLVE_MAX_TOKENS         = env_int("SOLVE_MAX_TOKENS",         128_000)
ADVISOR_MAX_TOKENS       = env_int("ADVISOR_MAX_TOKENS",        32_000)
VERIFY_MAX_TOKENS        = env_int("VERIFY_MAX_TOKENS",        128_000)
REFINE_MAX_TOKENS        = env_int("REFINE_MAX_TOKENS",        SOLVE_MAX_TOKENS)

# Pricing in USD per 1M tokens (override via env to match your model).
INPUT_TOKEN_PRICE  = float(os.getenv("INPUT_TOKEN_PRICE_PER_1M",  "30.00"))
CACHED_TOKEN_PRICE = float(os.getenv("CACHED_TOKEN_PRICE_PER_1M", "30.00"))
OUTPUT_TOKEN_PRICE = float(os.getenv("OUTPUT_TOKEN_PRICE_PER_1M", "180.00"))


# ─── Output dirs ──────────────────────────────────────────────────────────────

RESUME_DIR      = os.getenv("RESUME_DIR", "").strip()
OUTPUT_ROOT_DIR = Path(os.getenv("OUTPUT_ROOT_DIR", str(SCRIPT_DIR / "TEMP")))

if RESUME_DIR:
    OUTPUT_DIR = Path(RESUME_DIR)
    if not OUTPUT_DIR.exists():
        raise RuntimeError(f"RESUME_DIR does not exist: {RESUME_DIR}")
    print(f"[RESUME] Resuming from: {OUTPUT_DIR}")
else:
    OUTPUT_DIR = OUTPUT_ROOT_DIR

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
print(f"[output] {OUTPUT_DIR}")

USAGE_DIR = OUTPUT_DIR / "Overall_Usage"
USAGE_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE       = OUTPUT_DIR / "error.log"
USAGE_LOG_FILE = USAGE_DIR / "usage.jsonl"
LOG_FILE.touch()

# Stage output files (run-specific). Memory-managed files (task_outputs,
# final_solutions, KB events, advisor rounds, verify/refine/conversation logs)
# live under MEMORY_DIR and are owned by the GlobalMemory instance.
DIRECTIONS_FILE      = OUTPUT_DIR / "advisor_directions.json"
LITERATURE_FILE      = OUTPUT_DIR / "literature_research.jsonl"
IMPORTED_PAPERS_FILE = OUTPUT_DIR / "imported_papers.json"
BENCHMARK_FILE       = OUTPUT_DIR / "benchmark.json"
LATEX_FILE           = OUTPUT_DIR / "solution.tex"
STATUS_FILE          = OUTPUT_DIR / "final_status.txt"
MEMORY_DIR           = OUTPUT_DIR / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# Persistent wall-clock start time — survives resume. The Stage 2 deadline
# check is measured against this anchor, NOT against process start, so a
# crash-and-restart at hour 10 does NOT silently grant another 21h. To
# explicitly reset (e.g. for testing), delete memory/run_start_time.txt.
RUN_START_FILE = MEMORY_DIR / "run_start_time.txt"
if RUN_START_FILE.exists():
    try:
        RUN_START_TS = float(RUN_START_FILE.read_text().strip())
        _elapsed_h = (wall_time() - RUN_START_TS) / 3600.0
        print(f"[run] resumed (originally started at "
              f"{datetime.fromtimestamp(RUN_START_TS):%Y-%m-%d %H:%M:%S}, "
              f"elapsed {_elapsed_h:.2f}h)")
    except Exception as _exc:
        print(f"[run] run_start_time.txt unreadable ({_exc}); writing a fresh anchor")
        RUN_START_TS = wall_time()
        RUN_START_FILE.write_text(str(RUN_START_TS), encoding="utf-8")
else:
    RUN_START_TS = wall_time()
    RUN_START_FILE.write_text(str(RUN_START_TS), encoding="utf-8")
    print(f"[run] fresh start at {datetime.fromtimestamp(RUN_START_TS):%Y-%m-%d %H:%M:%S}")

if STAGE2_DEADLINE_HOURS > 0:
    _cutoff_ts = RUN_START_TS + STAGE2_DEADLINE_HOURS * 3600.0
    print(f"[run] Stage 2 cutoff: {STAGE2_DEADLINE_HOURS}h from start → "
          f"{datetime.fromtimestamp(_cutoff_ts):%Y-%m-%d %H:%M:%S}")
else:
    print("[run] Stage 2 cutoff: disabled (STAGE2_DEADLINE_HOURS=0)")

if HARD_DEADLINE_HOURS > 0:
    _hard_cutoff_ts = RUN_START_TS + HARD_DEADLINE_HOURS * 3600.0
    print(f"[run] Hard retry cutoff: {HARD_DEADLINE_HOURS}h from start → "
          f"{datetime.fromtimestamp(_hard_cutoff_ts):%Y-%m-%d %H:%M:%S}  "
          f"(run_response stops retrying past this point)")
else:
    print("[run] Hard retry cutoff: disabled (HARD_DEADLINE_HOURS=0)")

# Cross-run solver history: persists solver progress notes from every past run
# for this problem, so future runs can avoid repeating confirmed dead ends.
SOLVER_HISTORY_FILE  = PROBLEM_DATA_DIR / f"solver_history_{PROBLEM_PATH.stem}.jsonl"

# Stage 1.5 deep-read: cached PDF→text per arXiv paper (cross-run, cross-problem),
# so repeated runs (or different problems citing the same paper) skip re-download.
PAPER_CACHE_DIR      = PROBLEM_DATA_DIR / "papers"


# ─── OpenAI client ────────────────────────────────────────────────────────────

organization = os.getenv("OPENAI_ORG_ID") or os.getenv("OPENAI_ORGANIZATION")
client_kwargs = {"api_key": api_key, "timeout": 1800, "max_retries": 0}
if organization:
    client_kwargs["organization"] = organization

client = OpenAI(**client_kwargs)


# ─── Locks ────────────────────────────────────────────────────────────────────
#
# Most jsonl-file locks are now owned by GlobalMemory. The two locks that
# remain at module scope guard the legacy error log and the per-run usage log,
# both of which are debug streams not part of the run's recoverable state.

_log_lock              = threading.Lock()
_usage_lock            = threading.Lock()
_solver_history_lock   = threading.Lock()


# ─── Usage tracking ───────────────────────────────────────────────────────────

def _compute_usage(response, elapsed, stage_name):
    usage = getattr(response, "usage", None)
    input_tokens = cached_tokens = output_tokens = reasoning_tokens = total_tokens = 0
    if usage:
        input_tokens     = getattr(usage, "input_tokens",  0) or 0
        output_tokens    = getattr(usage, "output_tokens", 0) or 0
        total_tokens     = getattr(usage, "total_tokens",  0) or 0
        in_det = getattr(usage, "input_tokens_details", None)
        if in_det:
            cached_tokens = getattr(in_det, "cached_tokens", 0) or 0
        out_det = getattr(usage, "output_tokens_details", None)
        if out_det:
            reasoning_tokens = getattr(out_det, "reasoning_tokens", 0) or 0
    non_cached = max(input_tokens - cached_tokens, 0)
    cost = (
        non_cached    * INPUT_TOKEN_PRICE
        + cached_tokens * CACHED_TOKEN_PRICE
        + output_tokens * OUTPUT_TOKEN_PRICE
    ) / 1_000_000
    return {
        "stage":               stage_name,
        "model":               MODEL,
        "elapsed_seconds":     round(elapsed, 3),
        "input_tokens":        int(input_tokens),
        "cached_input_tokens": int(cached_tokens),
        "output_tokens":       int(output_tokens),
        "reasoning_tokens":    int(reasoning_tokens),
        "total_tokens":        int(total_tokens),
        "cost_usd":            round(float(cost), 6),
        "response_id":         getattr(response, "id", None),
    }


def _log_usage(info):
    with _usage_lock:
        with open(USAGE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(info, ensure_ascii=False) + "\n")
            f.flush()


# ─── Full-fidelity API-response audit ────────────────────────────────────────
#
# Captures every Responses API call (completed, non-completed terminal, and
# SDK-exception paths) as a single row in memory/api_responses.jsonl. Each
# row carries the rendered prompt and the complete serialised response —
# including reasoning items, web_search_call items (with action.query +
# action.sources), message content blocks, the usage block, and anything
# else the SDK exposes. Designed so that a downstream auditor can reconstruct
# exactly what the model saw, what it searched, what sources it touched, and
# what it returned, for every single API submission.
#
# Best-effort: a failure in this audit must never break the main pipeline.


def _serialize_response_safely(response):
    """Return a JSON-safe dict for an OpenAI Responses object.

    Prefers pydantic v2 ``model_dump(mode="json")`` so embedded datetimes,
    enums, Path-likes, etc. are coerced to JSON-safe scalars by the SDK.
    Falls back through ``model_dump()`` / ``dict()`` / ``model_dump_json``
    / ``json()`` / a final ``repr`` placeholder. Never raises.
    """
    if response is None:
        return None
    for fn_name, kwargs in (
        ("model_dump",      {"mode": "json"}),
        ("model_dump",      {}),
        ("dict",            {}),
    ):
        fn = getattr(response, fn_name, None)
        if callable(fn):
            try:
                return fn(**kwargs)
            except Exception:
                continue
    for fn_name in ("model_dump_json", "json"):
        fn = getattr(response, fn_name, None)
        if callable(fn):
            try:
                return json.loads(fn())
            except Exception:
                continue
    return {"_serialization_failed": True, "repr": repr(response)[:8000]}


def _log_api_response(stage_name, request_kwargs, response, started_at, *,
                      status_hint=None, exception=None):
    """Persist the full audit of one API submission to api_responses.jsonl.

    Writes one row to ``memory/api_responses.jsonl``. Captures, in order:
      - ``timestamp``       : wall-clock at log time,
      - ``stage``           : the harness stage label (e.g. ``advisor_r3``),
      - ``elapsed_seconds`` : wall-clock from submit to log point,
      - ``prompt``          : the rendered prompt verbatim, extracted from
                              ``request_kwargs["input"]`` and lifted to the
                              top level for grep-friendly inspection,
      - ``request``         : the full request kwargs sent to
                              ``client.responses.create(**kwargs)``, **with
                              ``input`` removed** (it lives at top level as
                              ``prompt``). Includes model, reasoning effort,
                              verbosity, max_output_tokens, tools / web-search
                              config, service_tier, background flag — every
                              knob that affected the call,
      - ``response_id`` / ``response_status``,
      - ``response``        : the full ``response.model_dump(mode="json")``
                              when available — reasoning + web_search_call
                              items (query, sources, urls) + message content
                              + usage + everything else the SDK exposes,
      - ``exception``       : ``repr(e)`` when the SDK raised.

    ``request_kwargs`` is the dict that was (or would have been) splatted
    into ``client.responses.create(**kwargs)``. When called from the
    completed / non-completed branches it is the actual sent kwargs; from
    the exception branch it may be ``locals().get("kwargs", ...)`` since
    the exception can in principle occur before kwargs is fully built.
    As a defensive fallback, a bare string is treated as the prompt with
    no other request metadata.

    Any failure inside this helper is caught and turned into a diagnostic
    print — it MUST NOT propagate, because the audit is downstream of the
    real API call and breaking the pipeline for the sake of audit logging
    would be perverse.
    """
    try:
        elapsed = None
        if started_at is not None:
            try:
                elapsed = round(monotonic() - started_at, 3)
            except Exception:
                elapsed = None
        # Split request_kwargs into the prompt (top-level, grep-friendly)
        # and the rest of the request metadata. Shallow copy of the dict
        # is fine because the values we mutate are scalars and small
        # nested dicts owned by run_response.
        if isinstance(request_kwargs, dict):
            prompt       = request_kwargs.get("input")
            request_meta = {k: v for k, v in request_kwargs.items() if k != "input"}
        else:
            # Defensive fallback: caller passed a bare string (legacy).
            prompt       = request_kwargs
            request_meta = None
        entry = {
            "timestamp":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stage":           stage_name,
            "elapsed_seconds": elapsed,
            "prompt":          prompt,
            "request":         request_meta,
            "response_id":     getattr(response, "id",     None) if response is not None else None,
            "response_status": getattr(response, "status", None) if response is not None else status_hint,
            "response":        _serialize_response_safely(response),
            "exception":       repr(exception) if exception is not None else None,
        }
        memory.log_api_response(entry)
    except Exception as exc:
        # Diagnostic only — never block the pipeline.
        print(f"[api_responses] log failed for stage={stage_name}: {exc}")


# ─── Hard deadline (per-call retry cap) ──────────────────────────────────────
#
# run_response's retry loop is intentionally unbounded by attempt count so
# transient OpenAI outages don't kill a 21h run. The cost is that a single
# permanently-stuck call (e.g., max_output_tokens too small → status always
# "incomplete"; persistent 429 with reasoning downgrade not enough) can keep
# the harness from ever returning to its round-boundary deadline check.
#
# HARD_DEADLINE_HOURS caps the total wall-clock at which retries are still
# attempted. Once exceeded:
#   - new submits are skipped
#   - non-completed retry sleeps are skipped
#   - SDK-exception retry sleeps are skipped
#   - any in-flight response.id is cancelled (best effort)
#   - run_response returns ``("", empty_usage)``
#
# Empty-string returns flow through callers' existing fallback paths:
#   advisor → empty plan → loop_complete; verify → verdict_class defaults
#   to "incorrect" → if_final_true="false"; refine → empty solution
#   replaces the in-progress one (downside: that refine round is lost).
#
# In-flight polling is intentionally NOT interrupted by this check. The
# existing QUEUED_TIMEOUT_SECONDS (30 min) + IN_PROGRESS_TIMEOUT_SECONDS
# (60 min) already bound polling time, and aborting a healthy in-flight
# call would waste tokens already paid for.

def _hard_deadline_exceeded() -> bool:
    if HARD_DEADLINE_HOURS <= 0:
        return False
    return (wall_time() - RUN_START_TS) / 3600.0 >= HARD_DEADLINE_HOURS


def _empty_usage_dict(stage_name, model=None, elapsed_seconds=0.0):
    """Zero-token usage dict, shape-compatible with ``_compute_usage``'s
    return. Used when ``run_response`` aborts (HARD_DEADLINE) so callers
    that read ``usage["input_tokens"]`` / aggregators / cost summaries
    don't crash on missing keys.
    """
    return {
        "stage":               stage_name,
        "model":               model or MODEL,
        "elapsed_seconds":     round(float(elapsed_seconds or 0.0), 3),
        "input_tokens":        0,
        "cached_input_tokens": 0,
        "output_tokens":       0,
        "reasoning_tokens":    0,
        "total_tokens":        0,
        "cost_usd":            0.0,
        "response_id":         None,
    }


def _abort_for_hard_deadline(stage_name, model, request_kwargs, response,
                             started_at, attempts):
    """Cancel any in-flight job (best effort), audit-log, return empty result.

    Returns ``("", empty_usage_dict)`` so the call site signature matches
    the normal-completion return path.
    """
    elapsed_h = (wall_time() - RUN_START_TS) / 3600.0
    print(f"[{stage_name}][HARD_DEADLINE] elapsed {elapsed_h:.2f}h >= "
          f"{HARD_DEADLINE_HOURS}h budget — aborting after {attempts} attempt(s) "
          f"without further retry.")
    # Best-effort cancel of any in-flight response id; failure is ignored.
    if response is not None:
        rid = getattr(response, "id", None)
        if rid:
            try:
                client.responses.cancel(rid)
                print(f"[{stage_name}][HARD_DEADLINE] cancelled in-flight response {rid}")
            except Exception as cancel_exc:
                print(f"[{stage_name}][HARD_DEADLINE] cancel error (ignoring): {cancel_exc}")
    # Audit-log to api_responses.jsonl so downstream tooling can
    # distinguish HARD_DEADLINE aborts from sdk_exception / non_completed_*.
    _log_api_response(
        stage_name,
        request_kwargs if request_kwargs is not None else {},
        response,
        started_at,
        status_hint="hard_deadline_aborted",
    )
    elapsed_seconds = 0.0
    if started_at is not None:
        try:
            elapsed_seconds = monotonic() - started_at
        except Exception:
            pass
    return "", _empty_usage_dict(stage_name, model=model, elapsed_seconds=elapsed_seconds)


# ─── Core API call ────────────────────────────────────────────────────────────

def _backoff_delay(attempt):
    """Exponential backoff with 0–50% jitter, capped at RETRY_MAX_SECONDS."""
    base = min(RETRY_BASE_SECONDS * (2 ** (attempt - 1)), RETRY_MAX_SECONDS)
    return base * (1.0 + random.random() * 0.5)


_RATE_LIMIT_PATTERNS = (
    "rate_limit_exceeded",
    "rate limit",
    "ratelimit",
    "tokens per min",
    "tpm",
    "tokens per minute",
)


def _is_rate_limit_failure(response, exception):
    """Best-effort detection of OpenAI rate-limit failures across both the
    non-completed response path and the exception path."""
    if exception is not None:
        msg = str(exception).lower()
        return any(p in msg for p in _RATE_LIMIT_PATTERNS)
    if response is not None:
        err = getattr(response, "error", None)
        code = getattr(err, "code", None) or ""
        msg  = getattr(err, "message", None) or ""
        haystack = f"{code} {msg}".lower()
        return any(p in haystack for p in _RATE_LIMIT_PATTERNS)
    return False


def run_response(prompt, stage_name, reasoning_effort, verbosity, max_output_tokens, web_search, model=None):
    _model = model or MODEL
    # Local mutable copy so we can downgrade on persistent rate-limit failures
    # without affecting future calls. Reset implicitly on function return.
    current_reasoning   = reasoning_effort
    rate_limit_attempts = 0
    downgrade_enabled   = (
        RATE_LIMIT_DOWNGRADE_THRESHOLD > 0
        and current_reasoning is not None
        and any(stage_name.startswith(p) for p in RATE_LIMIT_DOWNGRADE_STAGES)
    )
    print(
        f"[{stage_name}] model={_model} reasoning={current_reasoning or 'none'} "
        f"verbosity={verbosity} max_tokens={max_output_tokens} "
        f"background={BACKGROUND} web_search={web_search}"
    )
    attempts = 0  # counts failed submit→fail cycles for exponential backoff
    while True:
        # CHECK 1: HARD_DEADLINE before attempting a (new or retry) submit.
        # Fires before the first submit too — if the run is already past
        # the hard cutoff when run_response is even called, we don't bother
        # touching the API.
        if _hard_deadline_exceeded():
            return _abort_for_hard_deadline(
                stage_name, _model, {"input": prompt}, None, None, attempts,
            )
        response = None
        try:
            started_at = monotonic()
            kwargs = {
                "model":             _model,
                "input":             prompt,
                "text":              {"verbosity": verbosity},
                "max_output_tokens": max_output_tokens,
                "background":        BACKGROUND,
                "service_tier":      "priority",
            }
            if current_reasoning:
                kwargs["reasoning"] = {"effort": current_reasoning}
            if web_search:
                kwargs["tools"]       = [{"type": "web_search"}]
                kwargs["tool_choice"] = "auto"
                kwargs["include"]     = ["web_search_call.action.sources"]

            response = client.responses.create(**kwargs)

            queued_since      = None
            in_progress_since = None
            cancelled         = False
            while response.status in {"queued", "in_progress"}:
                if response.status == "queued":
                    in_progress_since = None  # not running yet
                    if queued_since is None:
                        queued_since = monotonic()
                    elif monotonic() - queued_since > QUEUED_TIMEOUT_SECONDS:
                        print(
                            f"[{stage_name}] job {response.id} stuck in 'queued' for "
                            f">{QUEUED_TIMEOUT_SECONDS//60} min — cancelling and resubmitting"
                        )
                        try:
                            client.responses.cancel(response.id)
                            print("job canceled")
                        except Exception as cancel_exc:
                            print(f"[{stage_name}] cancel error (ignoring): {cancel_exc}")
                        cancelled = True
                        break
                else:
                    queued_since = None  # job is running; reset so a re-queue would be caught
                    if in_progress_since is None:
                        in_progress_since = monotonic()
                    elif monotonic() - in_progress_since > IN_PROGRESS_TIMEOUT_SECONDS:
                        print(
                            f"[{stage_name}] job {response.id} stuck in 'in_progress' for "
                            f">{IN_PROGRESS_TIMEOUT_SECONDS//60} min — cancelling and resubmitting"
                        )
                        try:
                            client.responses.cancel(response.id)
                            print("job canceled")
                        except Exception as cancel_exc:
                            print(f"[{stage_name}] cancel error (ignoring): {cancel_exc}")
                        cancelled = True
                        break
                sleep(2)
                response = client.responses.retrieve(response.id)

            if cancelled:
                sleep(60)
                continue

            if response.status == "completed":
                elapsed = monotonic() - started_at
                info = _compute_usage(response, elapsed, stage_name)
                print(
                    f"[{stage_name}] done {elapsed:.1f}s "
                    f"tokens(in={info['input_tokens']} cached={info['cached_input_tokens']} "
                    f"out={info['output_tokens']} reason={info['reasoning_tokens']}) "
                    f"cost=${info['cost_usd']:.6f} id={info['response_id']}"
                )
                _log_usage(info)
                _log_api_response(stage_name, kwargs, response, started_at)
                return response.output_text or "", info

            print(f"[{stage_name}] non-completed status: {response.status} | {response}")
            with _log_lock:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {stage_name} | {response}\n\n")
            _log_api_response(
                stage_name, kwargs, response, started_at,
                status_hint=f"non_completed_{getattr(response, 'status', 'unknown')}",
            )
            attempts += 1
            if _is_rate_limit_failure(response, None):
                rate_limit_attempts += 1
                if (downgrade_enabled
                        and rate_limit_attempts >= RATE_LIMIT_DOWNGRADE_THRESHOLD
                        and current_reasoning != RATE_LIMIT_DOWNGRADE_TO):
                    old = current_reasoning
                    current_reasoning = RATE_LIMIT_DOWNGRADE_TO
                    print(f"[{stage_name}] rate-limited {rate_limit_attempts}× — "
                          f"downgrading reasoning {old} → {current_reasoning} for remaining retries")
            delay = _backoff_delay(attempts)
            print(f"[{stage_name}] backoff {delay:.1f}s before resubmit (attempt {attempts})")
            # CHECK 2: HARD_DEADLINE before non-completed retry sleep. Skip
            # the sleep + retry if we'd cross the cutoff just by waiting.
            if _hard_deadline_exceeded():
                return _abort_for_hard_deadline(
                    stage_name, _model, kwargs, response, started_at, attempts,
                )
            sleep(delay)

        except Exception as e:
            print(f"[{stage_name}] error: {e}")
            with _log_lock:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    rid = getattr(response, "id", None)
                    f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {stage_name} | response_id={rid} | {e}\n")
            _log_api_response(
                stage_name,
                # Prefer the actual sent kwargs when available; if the SDK
                # raised before kwargs was fully built, fall back to a bare
                # {"input": prompt} so the prompt is still recorded.
                locals().get("kwargs", {"input": prompt}),
                response,
                locals().get("started_at"),
                status_hint="sdk_exception",
                exception=e,
            )
            attempts += 1
            if _is_rate_limit_failure(None, e):
                rate_limit_attempts += 1
                if (downgrade_enabled
                        and rate_limit_attempts >= RATE_LIMIT_DOWNGRADE_THRESHOLD
                        and current_reasoning != RATE_LIMIT_DOWNGRADE_TO):
                    old = current_reasoning
                    current_reasoning = RATE_LIMIT_DOWNGRADE_TO
                    print(f"[{stage_name}] rate-limited {rate_limit_attempts}× — "
                          f"downgrading reasoning {old} → {current_reasoning} for remaining retries")
            delay = _backoff_delay(attempts)
            print(f"[{stage_name}] backoff {delay:.1f}s before resubmit (attempt {attempts})")
            # CHECK 3: HARD_DEADLINE before exception-retry sleep. Same
            # rationale as CHECK 2 but on the exception path.
            if _hard_deadline_exceeded():
                return _abort_for_hard_deadline(
                    stage_name, _model,
                    locals().get("kwargs", {"input": prompt}),
                    response,
                    locals().get("started_at"),
                    attempts,
                )
            sleep(delay)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def extract_solution_metadata(text, fallback_problem):
    """Extract the trailing metadata JSON block from a solver response.

    Returns (solution_text, problem_solved, is_relaxation).
    If the block is absent or unparseable, returns the full text and the
    fallback_problem with is_relaxation=False.
    """
    pattern = r"```(?:json)?\s*(\{[^`]*\"problem_solved\"[^`]*\})\s*```"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if m:
        try:
            meta = json.loads(m.group(1))
            problem_solved = (meta.get("problem_solved") or fallback_problem).strip()
            is_relaxation  = bool(meta.get("is_relaxation", False))
            solution_text  = text[:m.start()].rstrip()
            return solution_text, problem_solved, is_relaxation
        except Exception:
            pass
    return text, fallback_problem, False


def extract_json_object(text):
    # Strategy 1: code-fenced blocks — try each match and validate with
    # json.loads, because embedded ``` inside JSON string values can cause
    # the non-greedy regex to return a truncated span.
    for m in re.finditer(r"```(?:json)?\s*(\{.+?\})\s*```", text, re.DOTALL | re.IGNORECASE):
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            continue
    for m in re.finditer(r"```(?:json)?\s*(\[.+?\])\s*```", text, re.DOTALL | re.IGNORECASE):
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            continue
    # Strategy 2: first { to last } (covers cases where code fences are
    # broken by embedded ``` in solver prompts).
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1].strip()
    # Strategy 3: same for arrays
    start = text.find("[")
    end   = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1].strip()
    raise ValueError("No JSON object or array found in response.")



def _aggregate_usage(usages):
    """Sum a list of usage dicts (from run_response) into one combined entry."""
    if not usages:
        return {}
    result = dict(usages[0])
    for u in usages[1:]:
        result["input_tokens"]        = result.get("input_tokens",        0) + u.get("input_tokens",        0)
        result["cached_input_tokens"] = result.get("cached_input_tokens", 0) + u.get("cached_input_tokens", 0)
        result["output_tokens"]       = result.get("output_tokens",       0) + u.get("output_tokens",       0)
        result["reasoning_tokens"]    = result.get("reasoning_tokens",    0) + u.get("reasoning_tokens",    0)
        result["total_tokens"]        = result.get("total_tokens",        0) + u.get("total_tokens",        0)
        result["cost_usd"]            = result.get("cost_usd",           0.) + u.get("cost_usd",           0.)
        result["elapsed_seconds"]     = result.get("elapsed_seconds",    0.) + u.get("elapsed_seconds",    0.)
    result["cost_usd"]        = round(result["cost_usd"],        6)
    result["elapsed_seconds"] = round(result["elapsed_seconds"], 3)
    result["response_id"]     = usages[-1].get("response_id")
    return result


def _append_solver_history(task_id, task_title, notes_text):
    """Persist the final solver notes for one task to the cross-run history file."""
    entry = {
        "run_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "output_dir":    str(OUTPUT_DIR),
        "task_id":       task_id,
        "task_title":    task_title,
        "notes":         notes_text,
    }
    with _solver_history_lock:
        with open(SOLVER_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()


def _load_solver_history():
    """Return all past solver-notes entries for this problem."""
    records = []
    if not SOLVER_HISTORY_FILE.exists():
        return records
    with open(SOLVER_HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def _format_past_notes_for_prompt(history):
    """Format past solver-history records into a concise prompt section."""
    if not history:
        return ""
    lines = ["# Past Attempts on This Problem (from previous runs)",
             "The following approaches were explored in earlier runs.",
             "Avoid repeating confirmed dead ends; build on any partial progress.\n"]
    for rec in history:
        lines.append(f"## Run {rec['run_timestamp']} — Task: {rec.get('task_title', rec.get('plan_title', ''))}")
        notes = rec.get("notes", {})
        if isinstance(notes, dict):
            current = notes.get("current_best", {})
            lines.append(f"Best result: {current.get('statement', 'none')}")
            ruled_out = notes.get("ruled_out", [])
            if ruled_out:
                lines.append("Ruled out: " + "; ".join(ruled_out))
            live = notes.get("live_directions", [])
            if live:
                lines.append("Still promising: " + "; ".join(live))
            for attempt in notes.get("attempts", []):
                outcome = attempt.get("outcome", "")
                if outcome in ("failed", "partial"):
                    tech    = attempt.get("technique", "")
                    obs     = attempt.get("obstacle", "")
                    result  = attempt.get("result", "")
                    summary = attempt.get("approach", "")
                    detail  = result or obs or ""
                    lines.append(f"  • [{outcome}] {tech}: {summary}" + (f" — {detail}" if detail else ""))
        else:
            lines.append(str(notes))
        lines.append("")
    return "\n".join(lines)


# ─── Cross-task reference attachment exception ───────────────────────────────

class UnknownReferencedTaskIDs(ValueError):
    """Raised in strict mode when reference_task_ids contains unknown IDs."""


# ─── GlobalMemory: single source of truth for run state ───────────────────────
#
# Event-sourced. Every mutation appends to a typed JSONL on disk; the
# constructor replays those JSONLs to rebuild in-memory state. There is no
# separate snapshot / checkpoint to keep in sync.
#
# Schema (JSONL files under MEMORY_DIR):
#
#   kb_events.jsonl       Typed KB events. Replayed on init.
#                         {type: "proven_result_add",    statement, proof_sketch, written_up, source_plan, turn}
#                         {type: "proven_result_update", statement, verified, proof_excerpt, solution_ref, written_up, [problem_solved]}
#                            ``problem_solved`` (optional): the verifier's
#                            self-contained restatement of what the surviving
#                            turn actually proved. Stored alongside the
#                            original ``statement`` (the writeup's target);
#                            shown in kb_for_advisor only when it differs.
#                         {type: "failed_attempt",       approach, reason, ruled_out_at_turn, source_plan}
#                         {type: "bottleneck",           value}
#                         {type: "frontier",             value}        (latest wins)
#                         {type: "advisor_note",         round, note}
#                         {type: "writeup_claim",        statement}
#                         {type: "writeup_release",      statement}
#
#   task_outputs.jsonl    One row per solver/writeup/assembly output.
#                         Keyed by task_id. Latest row wins on replay.
#
#   final_solutions.jsonl One row per Stage-3 verified-or-not Final_Solution.
#
#   advisor_rounds.jsonl  One row per fully-completed Stage-2 round. The
#                         tail row determines the resume position (replaces
#                         stage2_checkpoint.json). status ∈ {"in_progress",
#                         "loop_complete"} where "loop_complete" means the
#                         loop has terminated (advisor said "done", budget
#                         hit zero, or no tasks were assigned).
#
#   verify.jsonl, refine.jsonl, conversation.jsonl  Append-only debug
#                         streams, not replayed.
#
#   verifier_records.jsonl  Append-only, isolated record of each Run_Verify
#                         call: the original problem, the claim being verified,
#                         the solution shown to the verifier, the rendered
#                         prompt, the raw response, and the parsed verdict
#                         (correct, gaps, problem_solved, is_relaxation). One
#                         row per call; designed to be consumed standalone
#                         (e.g. for training/evaluating a separate verifier).

class GlobalMemory:
    """Thread-safe, event-sourced memory for one run.

    The KB schema (proven_results / failed_attempts / bottlenecks / frontier /
    advisor_notes / partial_writeups_done) is identical to the legacy
    shared_knowledge_base.json, but each mutation is now a typed event
    appended to ``kb_events.jsonl``. Reads return latest-wins reductions.

    Locks: ``_state_lock`` is reentrant — held across read-modify-emit so
    concurrent threads cannot both pass the same "not yet present" check.
    Per-file write locks prevent interleaved JSON lines on disk.
    """

    def __init__(self, memory_dir):
        self._dir = Path(memory_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

        self._kb_events_file        = self._dir / "kb_events.jsonl"
        self._task_outputs_file     = self._dir / "task_outputs.jsonl"
        self._final_solutions_file  = self._dir / "final_solutions.jsonl"
        self._advisor_rounds_file   = self._dir / "advisor_rounds.jsonl"
        self._verify_file           = self._dir / "verify.jsonl"
        self._refine_file           = self._dir / "refine.jsonl"
        self._conversation_file     = self._dir / "conversation.jsonl"
        self._verifier_records_file = self._dir / "verifier_records.jsonl"
        # Full raw dump of every Responses API call: rendered prompt + the
        # complete `response.model_dump(mode="json")` (reasoning items,
        # web_search_call items with action.query + action.sources, message
        # content blocks, usage block, etc.). Pure debug stream — never
        # replayed; written by run_response for completed, non-completed,
        # AND exceptional calls so the audit covers every submission attempt.
        self._api_responses_file    = self._dir / "api_responses.jsonl"

        self._state_lock                = threading.RLock()
        self._kb_events_file_lock       = threading.Lock()
        self._task_outputs_file_lock    = threading.Lock()
        self._final_solutions_file_lock = threading.Lock()
        self._advisor_rounds_file_lock  = threading.Lock()
        self._verify_file_lock          = threading.Lock()
        self._refine_file_lock          = threading.Lock()
        self._conversation_file_lock    = threading.Lock()
        self._verifier_records_file_lock = threading.Lock()
        self._api_responses_file_lock    = threading.Lock()

        # In-memory state (rebuilt by _replay).
        self._proven_results        = {}    # statement → entry
        self._failed_attempts       = {}    # approach  → entry
        self._bottlenecks           = []    # ordered, deduped
        self._advisor_notes         = []    # [{round, note}]
        self._frontier              = ""
        self._partial_writeups_done = []    # ordered, deduped
        self._task_outputs          = {}    # task_id → entry
        self._final_solutions       = {}    # task_id → entry
        self._completed_rounds      = []    # ordered list of round records
        self._loop_complete         = False

        self._replay()

    # ── Replay ───────────────────────────────────────────────────────────────

    def _replay(self):
        for ev in self._read_jsonl(self._kb_events_file):
            self._apply_kb_event(ev)
        for entry in self._read_jsonl(self._task_outputs_file):
            tid = entry.get("task_id")
            if tid:
                # Back-compat: rows written before the rename used the bare
                # names problem_solved / is_relaxation. Migrate them to the
                # self_declared_* names so all readers see one schema. The
                # verification_status marker is added too if missing.
                if "self_declared_problem_solved" not in entry and "problem_solved" in entry:
                    entry["self_declared_problem_solved"] = entry.pop("problem_solved")
                if "self_declared_is_relaxation" not in entry and "is_relaxation" in entry:
                    entry["self_declared_is_relaxation"] = entry.pop("is_relaxation")
                entry.setdefault("verification_status", "unverified_self_report")
                self._task_outputs[tid] = entry
        for entry in self._read_jsonl(self._final_solutions_file):
            tid = entry.get("task_id")
            if tid:
                self._final_solutions[tid] = entry
        for entry in self._read_jsonl(self._advisor_rounds_file):
            self._completed_rounds.append(entry)
            if entry.get("status") == "loop_complete":
                self._loop_complete = True

    @staticmethod
    def _read_jsonl(path):
        if not path.exists():
            return []
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    @staticmethod
    def _append_jsonl(path, lock, obj):
        with lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                f.flush()

    # ── KB event application ─────────────────────────────────────────────────

    def _apply_kb_event(self, ev):
        t = ev.get("type")
        if t == "proven_result_add":
            stmt = ev.get("statement", "")
            if stmt and stmt not in self._proven_results:
                self._proven_results[stmt] = {
                    "statement":    stmt,
                    "proof_sketch": ev.get("proof_sketch", ""),
                    "written_up":   ev.get("written_up", False),
                    "source_plan":  ev.get("source_plan", ""),
                    "turn":         ev.get("turn", -1),
                }
        elif t == "proven_result_update":
            stmt = ev.get("statement", "")
            if not stmt:
                return
            existing = self._proven_results.setdefault(stmt, {
                "statement":    stmt,
                "proof_sketch": "",
                "written_up":   False,
                "source_plan":  "unknown",
                "turn":         -1,
            })
            for k in ("verified", "proof_excerpt", "solution_ref",
                      "written_up", "proof_sketch", "source_plan",
                      "problem_solved", "is_relaxation"):
                if k in ev:
                    existing[k] = ev[k]
        elif t == "failed_attempt":
            ap = ev.get("approach", "")
            if ap and ap not in self._failed_attempts:
                self._failed_attempts[ap] = {
                    "approach":          ap,
                    "reason":            ev.get("reason", ""),
                    "ruled_out_at_turn": ev.get("ruled_out_at_turn", -1),
                    "source_plan":       ev.get("source_plan", ""),
                }
        elif t == "bottleneck":
            v = ev.get("value", "")
            if v and v not in self._bottlenecks:
                self._bottlenecks.append(v)
        elif t == "frontier":
            self._frontier = ev.get("value", "")
        elif t == "advisor_note":
            self._advisor_notes.append({
                "round": ev.get("round"),
                "note":  ev.get("note", ""),
            })
        elif t == "writeup_claim":
            v = ev.get("statement", "")
            if v and v not in self._partial_writeups_done:
                self._partial_writeups_done.append(v)
        elif t == "writeup_release":
            v = ev.get("statement", "")
            if v in self._partial_writeups_done:
                self._partial_writeups_done.remove(v)

    def _emit_kb_event(self, ev):
        # Caller MUST hold self._state_lock.
        self._apply_kb_event(ev)
        self._append_jsonl(self._kb_events_file, self._kb_events_file_lock, ev)

    # ── Mutating KB API ──────────────────────────────────────────────────────

    def add_proven_result(self, statement, proof_sketch="", source_plan="",
                          turn=-1, written_up=False):
        statement = (statement or "").strip()
        if not statement or statement.lower() == "none yet":
            return False
        with self._state_lock:
            if statement in self._proven_results:
                return False
            self._emit_kb_event({
                "type":         "proven_result_add",
                "statement":    statement,
                "proof_sketch": proof_sketch or "",
                "written_up":   bool(written_up),
                "source_plan":  source_plan or "",
                "turn":         turn,
            })
            return True

    def update_proven_result_verification(self, statement, verified,
                                          proof_excerpt, solution_ref,
                                          problem_solved=None,
                                          is_relaxation=None):
        """Record the verifier's verdict for a proven_result.

        ``statement`` is the KB key — what the writeup originally targeted.
        ``problem_solved``, if provided, is the verifier's self-contained
        restatement of what the surviving turn actually proved (may equal
        ``statement`` or be a relaxation/refinement of it).
        ``is_relaxation`` is the verifier's verdict on whether the proved
        claim is a relaxation/weakening of the original problem.
        """
        statement = (statement or "").strip()
        if not statement:
            return
        ev = {
            "type":          "proven_result_update",
            "statement":     statement,
            "verified":      verified,
            "proof_excerpt": proof_excerpt or "",
            "solution_ref":  solution_ref or "",
            "written_up":    True,
        }
        if problem_solved is not None:
            ev["problem_solved"] = problem_solved.strip() if isinstance(problem_solved, str) else problem_solved
        if is_relaxation is not None:
            ev["is_relaxation"] = bool(is_relaxation)
        with self._state_lock:
            self._emit_kb_event(ev)

    def mark_proven_result_written_up(self, statement):
        statement = (statement or "").strip()
        if not statement:
            return
        with self._state_lock:
            if statement not in self._proven_results:
                return
            self._emit_kb_event({
                "type":       "proven_result_update",
                "statement":  statement,
                "written_up": True,
            })

    def add_failed_attempt(self, approach, reason="", source_plan="", turn=-1):
        approach = (approach or "").strip()
        if not approach:
            return False
        with self._state_lock:
            if approach in self._failed_attempts:
                return False
            self._emit_kb_event({
                "type":              "failed_attempt",
                "approach":          approach,
                "reason":            reason or "",
                "ruled_out_at_turn": turn,
                "source_plan":       source_plan or "",
            })
            return True

    def add_bottleneck(self, value):
        if not isinstance(value, str):
            value = str(value or "")
        value = value.strip()
        if not value:
            return False
        with self._state_lock:
            if value in self._bottlenecks:
                return False
            self._emit_kb_event({"type": "bottleneck", "value": value})
            return True

    def set_frontier(self, value):
        if not isinstance(value, str):
            value = str(value or "")
        value = value.strip()
        if not value:
            return
        with self._state_lock:
            if value == self._frontier:
                return
            self._emit_kb_event({"type": "frontier", "value": value})

    def add_advisor_note(self, round_num, note):
        note = (note or "").strip()
        if not note:
            return
        with self._state_lock:
            self._emit_kb_event({
                "type":  "advisor_note",
                "round": round_num,
                "note":  note,
            })

    def try_claim_writeup(self, statement):
        """Atomic check-and-claim. Returns True iff this call newly held the slot."""
        if not statement:
            return False
        with self._state_lock:
            if statement in self._partial_writeups_done:
                return False
            self._emit_kb_event({"type": "writeup_claim", "statement": statement})
            return True

    def release_writeup_claim(self, statement):
        if not statement:
            return
        with self._state_lock:
            if statement not in self._partial_writeups_done:
                return
            self._emit_kb_event({"type": "writeup_release", "statement": statement})

    # ── Bulk mutations from agent outputs ────────────────────────────────────

    def apply_advisor_kb_updates(self, kb_updates, source="advisor"):
        """Apply the advisor's editorial KB updates."""
        if not kb_updates:
            return
        with self._state_lock:
            for pr in kb_updates.get("new_proven_results", []) or []:
                if isinstance(pr, dict):
                    self.add_proven_result(
                        pr.get("statement") or "",
                        proof_sketch=pr.get("sketch", ""),
                        source_plan=source,
                    )
                else:
                    self.add_proven_result(str(pr), source_plan=source)

            for fa in kb_updates.get("new_failed_attempts", []) or []:
                if isinstance(fa, dict):
                    self.add_failed_attempt(
                        fa.get("approach") or "",
                        reason=fa.get("reason", ""),
                        source_plan=source,
                    )
                else:
                    self.add_failed_attempt(str(fa), source_plan=source)

            for b in kb_updates.get("new_bottlenecks", []) or []:
                self.add_bottleneck(b)

            frontier = kb_updates.get("frontier") or ""
            if frontier:
                self.set_frontier(frontier)

    def apply_solver_report(self, report, task_id):
        """Auto-merge a parsed <SOLVER_REPORT> dict into the KB."""
        if not report:
            return
        with self._state_lock:
            for pr in report.get("proven_results", []) or []:
                self.add_proven_result(
                    (pr.get("statement") or "").strip(),
                    proof_sketch=pr.get("sketch", ""),
                    source_plan=task_id,
                )
            for fa in report.get("failed_attempts", []) or []:
                self.add_failed_attempt(
                    (fa.get("approach") or "").strip(),
                    reason=fa.get("reason", ""),
                    source_plan=task_id,
                )

    # ── Task outputs ─────────────────────────────────────────────────────────

    def add_task_output(self, *, task_id, kind, round_num, description,
                        full_text, solution,
                        self_declared_problem_solved,
                        self_declared_is_relaxation,
                        usage,
                        advisor_statement=None,
                        advisor_solves_original_problem=None,
                        writeup_declared_problem_solved=None,
                        writeup_declared_is_relaxation=None,
                        metadata_block_present=None):
        # task_outputs.jsonl is the immutable raw record of what each agent
        # emitted at generation time. The verification_status marker and the
        # self_declared_* field names exist so any reader knows these values
        # are the agent's own claim about its own output, NOT a verified
        # ground truth. The verifier's verdict — and the verified+refined
        # solution text — live in final_solutions.jsonl, never overwriting
        # this row.
        entry = {
            "task_id":                     task_id,
            "kind":                        kind,
            "round":                       round_num,
            "description":                 description,
            "full_text":                   full_text,
            "solution":                    solution,
            "self_declared_problem_solved": self_declared_problem_solved,
            "self_declared_is_relaxation":  self_declared_is_relaxation,
            "verification_status":         "unverified_self_report",
            "usage":                       usage,
        }
        # Provenance fields (writeup-only signals). Recorded so we can audit
        # advisor↔writeup disagreement after the fact. Canonical fields above
        # always reflect the writeup's self-declaration when present.
        if advisor_statement is not None:
            entry["advisor_statement"] = advisor_statement
        if advisor_solves_original_problem is not None:
            entry["advisor_solves_original_problem"] = advisor_solves_original_problem
        if writeup_declared_problem_solved is not None:
            entry["writeup_declared_problem_solved"] = writeup_declared_problem_solved
        if writeup_declared_is_relaxation is not None:
            entry["writeup_declared_is_relaxation"] = writeup_declared_is_relaxation
        if metadata_block_present is not None:
            entry["metadata_block_present"] = metadata_block_present
        with self._state_lock:
            self._task_outputs[task_id] = entry
        self._append_jsonl(
            self._task_outputs_file, self._task_outputs_file_lock, entry,
        )
        return entry

    def has_task_output(self, task_id):
        with self._state_lock:
            return task_id in self._task_outputs

    def get_task_output(self, task_id):
        with self._state_lock:
            entry = self._task_outputs.get(task_id)
            return dict(entry) if entry else None

    def all_task_outputs(self):
        with self._state_lock:
            return {tid: dict(e) for tid, e in self._task_outputs.items()}

    def task_id_index_for_advisor(self):
        """Render every prior task ID with round + description, for the
        advisor's reference_task_ids picker."""
        with self._state_lock:
            if not self._task_outputs:
                return "(none yet — no solver tasks have completed.)"
            rows = []
            for tid, entry in self._task_outputs.items():
                rnd  = entry.get("round", "?")
                desc = entry.get("description", "") or ""
                rows.append((rnd if isinstance(rnd, int) else 0, tid, rnd, desc))
            rows.sort(key=lambda x: (x[0], x[1]))
            return "\n".join(
                f"  - {tid} (round {rnd}) — {desc}" for _, tid, rnd, desc in rows
            )

    def assembly_task_index_for_advisor(self):
        """Richer task index used by the Stage 2.9 assembly advisor.

        Same shape as ``task_id_index_for_advisor`` but adds per-task flags
        the assembly advisor needs to decide what to load via reference_task_ids:
        kind, problem_solved, is_relaxation, and verification status drawn
        from final_solutions.jsonl.
        """
        with self._state_lock:
            if not self._task_outputs:
                return "(none yet — no task outputs recorded.)"
            rows = []
            for tid, entry in self._task_outputs.items():
                rnd  = entry.get("round", "?")
                desc = entry.get("description", "") or ""
                kind = entry.get("kind", "?")

                fe = self._final_solutions.get(tid)
                if fe is None:
                    # No verifier verdict on disk for this task — show only
                    # the agent's self-declared values, marked unverified so
                    # the advisor cannot conflate them with verified facts.
                    vtag      = "verify=pending"
                    ps        = entry.get("self_declared_problem_solved", "") or ""
                    is_relax  = bool(entry.get("self_declared_is_relaxation", False))
                    ps_label  = "self_declared_problem_solved"
                    rel_label = "self_declared_is_relaxation"
                else:
                    v = (fe.get("if_final_true") or "").lower()
                    if v == "true":
                        vtag = "verify=✓"
                    elif v == "false":
                        vtag = "verify=✗"
                    else:
                        vtag = f"verify={v or 'pending'}"
                    # Verifier-canonical values from final_solutions.jsonl —
                    # these are the source of truth post-verification.
                    ps        = fe.get("problem_solved", "") or ""
                    is_relax  = bool(fe.get("is_relaxation", False))
                    ps_label  = "verifier_problem_solved"
                    rel_label = "verifier_is_relaxation"

                rows.append((
                    rnd if isinstance(rnd, int) else 0,
                    tid, rnd, kind, vtag, is_relax, ps, desc,
                    ps_label, rel_label,
                ))
            rows.sort(key=lambda x: (x[0], x[1]))

            lines = []
            for _, tid, rnd, kind, vtag, is_relax, ps, desc, ps_label, rel_label in rows:
                head = (
                    f"  - {tid} (round {rnd}, kind={kind}, {vtag}, "
                    f"{rel_label}={is_relax}) — {desc}"
                )
                lines.append(head)
                if ps:
                    lines.append(f"      {ps_label}: {ps}")
            return "\n".join(lines)

    def get_referenced_outputs(self, task_ids, *, strict, log_prefix):
        """Format a verbatim block of referenced prior task outputs.

        For each task ID we prefer the verifier-canonical artifact when one
        exists in final_solutions.jsonl: the refined ``Final_Solution`` text
        that survived verify+refine, with a metadata header carrying the
        verifier's verdict (verified ✓/✗, is_relaxation, problem_solved).
        Otherwise we fall back to the raw task_outputs.full_text — clearly
        labelled as an unverified self-report so the consuming agent does
        not mistake an in-flight or never-verified draft for ground truth.

        Strict mode raises ``UnknownReferencedTaskIDs`` if any ID is unknown;
        lenient mode logs a warning and skips. Returns "" when nothing to
        attach.
        """
        if not task_ids:
            return ""
        with self._state_lock:
            sections = []
            missing  = []
            for tid in task_ids:
                entry = self._task_outputs.get(tid)
                if entry is None:
                    missing.append(tid)
                    continue
                desc = entry.get("description", "") or ""
                fe   = self._final_solutions.get(tid)

                if fe is not None and fe.get("Final_Solution"):
                    v = (fe.get("if_final_true") or "").lower()
                    if v == "true":
                        verdict_tag = "verified ✓"
                    elif v == "false":
                        verdict_tag = "verified ✗ (refined attempt still has gaps — DO NOT trust as established fact)"
                    else:
                        verdict_tag = f"verified {v or 'pending'}"
                    metadata = (
                        f"[{verdict_tag} | "
                        f"is_relaxation: {bool(fe.get('is_relaxation', False))} | "
                        f"problem_solved (verifier-canonical, self-contained): "
                        f"{(fe.get('problem_solved') or '').strip()}]"
                    )
                    body = fe.get("Final_Solution") or ""
                    source_note = (
                        "Source: final_solutions.jsonl — verified+refined text, "
                        "the artifact that actually survived the verify+refine loop."
                    )
                else:
                    metadata = (
                        f"[unverified self-report — verification not run or not yet complete | "
                        f"self_declared_is_relaxation: "
                        f"{bool(entry.get('self_declared_is_relaxation', False))} | "
                        f"self_declared_problem_solved (the agent's own claim, NOT verified): "
                        f"{(entry.get('self_declared_problem_solved') or '').strip()}]"
                    )
                    body = entry.get("full_text") or entry.get("solution") or ""
                    source_note = (
                        "Source: task_outputs.jsonl — raw agent output. The values in "
                        "the metadata line above are self-declared and have not been "
                        "checked. Treat the proof as a draft, not as established."
                    )

                header = (
                    f"## Task {tid}" + (f" — {desc}" if desc else "")
                    + f"\n{metadata}\n{source_note}"
                )
                sections.append(f"{header}\n{body}".rstrip())

            if missing:
                if strict:
                    known = sorted(self._task_outputs.keys())
                    raise UnknownReferencedTaskIDs(
                        f"reference_task_ids unknown in strict mode: {missing}. "
                        f"Known task IDs at this point: {known}"
                    )
                print(f"{log_prefix} WARNING: skipping unknown reference_task_ids "
                      f"(lenient): {missing}. "
                      f"Known: {sorted(self._task_outputs.keys())}")

            if not sections:
                return ""
            intro = (
                "# Referenced Prior Solver Outputs\n"
                "Below are the full outputs of the prior tasks the orchestrator "
                "asked you to read. Each section starts with a metadata line that "
                "tells you whether the artifact has been verified by an independent "
                "verifier+refiner: a `verified ✓` block is the canonical, refined "
                "text and its claim/relaxation flags are authoritative; an "
                "`unverified self-report` block is a raw draft whose claim flags "
                "are the agent's own self-declaration and have NOT been checked. "
                "Examine the actual arguments — do not rely solely on summaries "
                "elsewhere in this prompt."
            )
            return intro + "\n\n" + "\n\n".join(sections)

    # ── Final solutions ──────────────────────────────────────────────────────

    def add_final_solution(self, task_id, if_final_true, final_solution,
                           problem_solved, is_relaxation):
        entry = {
            "task_id":        task_id,
            "if_final_true":  if_final_true,
            "Final_Solution": final_solution,
            "problem_solved": problem_solved,
            "is_relaxation":  is_relaxation,
        }
        with self._state_lock:
            self._final_solutions[task_id] = entry
        self._append_jsonl(
            self._final_solutions_file, self._final_solutions_file_lock, entry,
        )
        return entry

    def has_final_solution(self, task_id):
        with self._state_lock:
            return task_id in self._final_solutions

    def get_final_solution(self, task_id):
        with self._state_lock:
            entry = self._final_solutions.get(task_id)
            return dict(entry) if entry else None

    def all_final_solutions(self):
        with self._state_lock:
            return {tid: dict(e) for tid, e in self._final_solutions.items()}

    def has_any_verified_solution(self):
        with self._state_lock:
            for e in self._final_solutions.values():
                if _is_kb_verified(e.get("if_final_true")):
                    return True
            return False

    # ── Stage-2 progression state (replaces stage2_checkpoint.json) ──────────

    def record_advisor_round(self, *, round_num, status,
                             budget_remaining_after, task_counter_after,
                             plan, usage):
        entry = {
            "round":                  round_num,
            "status":                 status,
            "budget_remaining_after": budget_remaining_after,
            "task_counter_after":     task_counter_after,
            "plan":                   plan,
            "usage":                  usage,
        }
        with self._state_lock:
            self._completed_rounds.append(entry)
            if status == "loop_complete":
                self._loop_complete = True
        self._append_jsonl(
            self._advisor_rounds_file, self._advisor_rounds_file_lock, entry,
        )

    def stage2_resume_state(self, total_budget):
        """Return where to resume orchestrated_solve_loop_v2 from.

        On a fresh run: round_num=0, full budget, task_counter=1.
        Otherwise: snapshot from the last fully-recorded round.
        """
        with self._state_lock:
            if not self._completed_rounds:
                return {
                    "round_num":           0,
                    "budget_remaining":    total_budget,
                    "task_counter":        1,
                    "loop_complete":       False,
                    "last_solver_outputs": [],
                }
            last = self._completed_rounds[-1]
            return {
                "round_num":           last["round"],
                "budget_remaining":    last["budget_remaining_after"],
                "task_counter":        last["task_counter_after"],
                "loop_complete":       self._loop_complete,
                "last_solver_outputs": self._build_round_solver_outputs(last["round"]),
            }

    def _build_round_solver_outputs(self, round_num):
        """Reconstruct the {task_id, description, output, usage} list the
        advisor expects for a given round."""
        out = []
        for tid, entry in self._task_outputs.items():
            if entry.get("kind") == "solver" and entry.get("round") == round_num:
                out.append({
                    "task_id":     tid,
                    "description": entry.get("description", ""),
                    "output":      entry.get("full_text", ""),
                    "usage":       entry.get("usage", {}),
                })
        def _sort_key(o):
            tid = o["task_id"]
            try:
                return (0, int(tid.lstrip("t")))
            except Exception:
                return (1, tid)
        out.sort(key=_sort_key)
        return out

    # ── Debug streams (append-only, not replayed) ────────────────────────────

    def log_conversation(self, entry):
        self._append_jsonl(
            self._conversation_file, self._conversation_file_lock, entry,
        )

    def log_verify(self, entry):
        self._append_jsonl(self._verify_file, self._verify_file_lock, entry)

    def log_refine(self, entry):
        self._append_jsonl(self._refine_file, self._refine_file_lock, entry)

    def log_verifier_record(self, entry):
        """Isolated, self-contained record of a single Run_Verify call.

        Captures the exact (problem, solution) pair shown to the verifier,
        the rendered prompt, the raw response, and the parsed verdict. One
        row per verifier call — designed to be consumed standalone (e.g. for
        training or evaluating a separate verifier model) without needing
        to cross-reference conversation.jsonl or verify.jsonl.
        """
        self._append_jsonl(
            self._verifier_records_file, self._verifier_records_file_lock, entry,
        )

    def log_api_response(self, entry):
        """Append the full raw audit of one Responses API call.

        Written by run_response for every completed / non-completed /
        exceptional API submission. Each row carries the rendered prompt
        and (when a response object exists) its full
        ``model_dump(mode="json")`` — including reasoning items,
        web_search_call items (action.query + action.sources), message
        content blocks, the usage block, and any other output items the
        SDK returned. Pure debug stream — never replayed.

        Uses ``default=str`` so any stray non-JSON-safe values (datetimes,
        Path objects, etc.) degrade to repr() instead of raising.
        """
        with self._api_responses_file_lock:
            with open(self._api_responses_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
                f.flush()

    # ── KB views (read-only formatters used by prompts) ──────────────────────

    def kb_for_solver(self, frontier_override=None):
        with self._state_lock:
            lines = ["# Session Progress (do not re-prove; build on these)"]
            if self._proven_results:
                lines.append("\n## Previous Solver Notes (exploration log — not yet verified unless tagged)")
                for r in self._proven_results.values():
                    v = r.get("verified")
                    if v is True:
                        tag = " [VERIFIED ✓]"
                    elif v is False:
                        tag = " [VERIFIED ✗]"
                    elif r.get("written_up"):
                        tag = " [pending verification]"
                    else:
                        tag = ""
                    lines.append(f"  •{tag} {r['statement']}")
            else:
                lines.append("\n## Previous Solver Notes\n  (none yet)")

            failed_list = list(self._failed_attempts.values())
            if failed_list:
                recent = failed_list[-10:]
                lines.append("\n## Ruled-out approaches (do not retry)")
                for fa in recent:
                    lines.append(f"  • {fa['approach']}")
                if len(failed_list) > 10:
                    lines.append(f"  … ({len(failed_list) - 10} more ruled out, see kb_events.jsonl)")

            goal = frontier_override or self._frontier
            if goal:
                lines.append(f"\n## Your immediate goal\n{goal}")

            return "\n".join(lines)

    def kb_for_advisor(self):
        with self._state_lock:
            lines = ["# Shared Knowledge Base (full view — all agents, current run)"]
            if self._proven_results:
                lines.append("\n## Solver Notes (exploration log — not yet verified unless tagged)")
                for r in self._proven_results.values():
                    v = r.get("verified")
                    in_flight_note = None
                    if v is True:
                        vtag = "[VERIFIED ✓] "
                    elif v is False:
                        vtag = "[VERIFIED ✗] "
                    elif r.get("written_up"):
                        vtag = "[VERIFICATION IN PROGRESS] "
                        in_flight_note = (
                            "An independent verifier+refiner agent pair is "
                            "checking this write-up RIGHT NOW in the background. "
                            "Do NOT assign solver tasks to re-verify, critique, "
                            "or re-prove this — wait for the verdict in a "
                            "future round."
                        )
                    else:
                        vtag = ""
                    src = r.get("source_plan", "")
                    ref = r.get("solution_ref", "")
                    stmt = r.get("statement", "")
                    lines.append(
                        f"  • {vtag}{stmt}"
                        + (f"  (from: {src})" if src else "")
                    )
                    if in_flight_note is not None:
                        lines.append(f"    {in_flight_note}")
                    ps = (r.get("problem_solved") or "").strip()
                    if ps and ps != stmt.strip():
                        lines.append(
                            f"    Verifier's restatement of what was actually proved: {ps}"
                        )
                    if "is_relaxation" in r:
                        lines.append(
                            f"    Verifier's is_relaxation verdict: {bool(r['is_relaxation'])}"
                        )
                    excerpt = r.get("proof_excerpt", "") or r.get("proof_sketch", "")
                    if excerpt:
                        lines.append(f"    Proof sketch: {excerpt}")
                    if ref:
                        lines.append(f"    Full proof on disk: {ref}")
            else:
                lines.append("\n## Solver Notes\n  (none yet)")

            if self._failed_attempts:
                lines.append("\n## Failed / Ruled-out Approaches")
                for fa in self._failed_attempts.values():
                    reason = fa.get("reason", "")
                    lines.append(f"  • {fa['approach']}" + (f": {reason}" if reason else ""))

            if self._bottlenecks:
                lines.append("\n## Known Bottlenecks")
                for b in self._bottlenecks:
                    lines.append(f"  • {b}")

            if self._advisor_notes:
                lines.append("\n## Your Strategic Notes (from your own prior rounds)")
                for n in self._advisor_notes:
                    lines.append(f"  Round {n['round']}: {n['note']}")

            if self._frontier:
                lines.append(f"\n## Current Frontier\n{self._frontier}")

            return "\n".join(lines)

    # ── Read accessors for finalize stage (and other consumers) ──────────────

    def all_failed_attempts(self):
        with self._state_lock:
            return [dict(e) for e in self._failed_attempts.values()]

    def all_bottlenecks(self):
        with self._state_lock:
            return list(self._bottlenecks)

    def all_advisor_notes(self):
        with self._state_lock:
            return [dict(n) for n in self._advisor_notes]

    def stats(self):
        with self._state_lock:
            return {
                "task_outputs":     len(self._task_outputs),
                "final_solutions":  len(self._final_solutions),
                "proven_results":   len(self._proven_results),
                "failed_attempts":  len(self._failed_attempts),
                "bottlenecks":      len(self._bottlenecks),
                "advisor_notes":    len(self._advisor_notes),
                "completed_rounds": len(self._completed_rounds),
                "loop_complete":    self._loop_complete,
            }


# Instantiate the run-wide memory now that paths and the class exist. Replay
# happens here — every JSONL under MEMORY_DIR is read in order, in-memory
# state is reconstructed, and the rest of this module operates against
# ``memory`` as the single source of truth.
memory = GlobalMemory(MEMORY_DIR)
print(f"[memory] {MEMORY_DIR} — replayed: {memory.stats()}")


# ─── Proof-sketch helper (LLM call kept outside GlobalMemory) ────────────────

_PROOF_SKETCH_PROMPT = """\
A mathematical proof has just been written up and verified. Summarise the core proof strategy in \
2-3 sentences. Focus on *why* it works and the key technique or lemma used — not just *what* was \
proved. Be precise enough that a mathematician reading only this summary would know which approach \
was taken and where the main difficulty was resolved.

# Statement proved
{statement}

# Proof
{solution_text}

Output only the 2-3 sentence summary, no preamble.
""".strip()


def _summarise_proof(statement, solution_text):
    prompt = _PROOF_SKETCH_PROMPT.format(
        statement=statement,
        solution_text=solution_text,
    )
    try:
        summary, _ = run_response(
            prompt,
            stage_name="proof_sketch",
            reasoning_effort="medium",
            verbosity="medium",
            max_output_tokens=2000,
            web_search=False,
            model=SUMMARIZE_MODEL,
        )
        return summary.strip()
    except Exception as exc:
        print(f"[proof_sketch] summarisation failed ({exc}), using mechanical fallback")
        fallback = solution_text[:400].strip()
        return (fallback + "…") if len(solution_text) > 400 else fallback


# if_final_true labels that count as "verified" for the proven_results KB.
# - "true"        : verifier verdict = Correct (no gaps or only cosmetic minor).
# - "nearly true" : refine exhausted with only MINOR gaps remaining and no
#                   MAJOR gaps (verdict = Correct after minor fixes). The
#                   proof is essentially correct modulo routine patches, so
#                   the advisor can build on it as a working lemma.
# Anything else (e.g. "false") is NOT considered verified.
KB_VERIFIED_LABELS = {"true", "nearly true"}


def _is_kb_verified(if_final_true) -> bool:
    return (if_final_true or "").strip().lower() in KB_VERIFIED_LABELS


def _update_kb_verification(statement, verified, solution_text, solution_ref="",
                            problem_solved=None, is_relaxation=None):
    """Summarise the proof and record verification verdict in the KB.

    ``problem_solved`` is the verifier's restatement of what the surviving
    turn actually proved. The KB entry is keyed by ``statement`` (the original
    target) and stores ``problem_solved`` as a separate field — the advisor
    sees both when they differ. ``is_relaxation`` is the verifier's verdict
    on whether the proved claim is weaker than the original — surfaced to
    the advisor next to the verified tag.
    """
    excerpt = _summarise_proof(statement, solution_text)
    memory.update_proven_result_verification(
        statement, verified, excerpt, solution_ref,
        problem_solved=problem_solved,
        is_relaxation=is_relaxation,
    )



# ─── Stage 1: Advisor directions ─────────────────────────────────────────────
#
# The advisor reads the Stage 0 literature extractions (already searched,
# downloaded, and deep-read by dedicated agents) and synthesises them into a
# single strategic briefing: concrete directions to try, key obstacles, and a
# recommended starting point. Web search is still enabled here so the advisor
# can follow a URL from Stage 0 for additional detail the extraction did not
# capture, or chase a citation thread Stage 0 did not pursue — Stage 0 is the
# primary source, but it is not exhaustive.

ADVISOR_DIRECTIONS_PROMPT_TEMPLATE = """\
You are a mathematical research advisor with access to web search. A separate \
literature-research stage (Stage 0) has already searched the literature, downloaded the \
relevant papers, and produced detailed per-paper extractions (overall summary, labelled \
theorems/lemmas with proof sketches, proof techniques with applicability notes, and other \
useful info). Treat those extractions as your primary source — they were produced by agents \
that read the full PDFs, and are more reliable for what each paper actually contains than a \
fresh web search would be. Use web search to fill gaps: chase a citation Stage 0 did not \
pursue, look up a specific lemma in more depth via the URL Stage 0 already provided, or \
verify a fact you are unsure about. Your job is to synthesise this material into a \
strategic briefing for a team of solver agents tackling the problem below.

# Problem
{problem}

# Past Attempts on This Problem (from previous runs)
{past_notes_section}

# Literature Research (Stage 0 deep-read extractions)
The block below contains the full extraction from each paper Stage 0 picked. Treat the \
statements, sketches, and techniques here as your primary source — they were extracted from \
the actual paper text, not from titles or abstracts.

{literature_section}

# Instructions
Synthesise the literature above into a strategic briefing. Identify the most promising \
directions to explore, the techniques from the literature most relevant here, and the key \
obstacles. When you reuse a result, technique, or pointer from the literature, cite the \
specific paper (title or arXiv ID) and the labelled statement/technique from Stage 0. \
Reuse URLs verbatim from the Stage 0 entries when citing them; any *new* URL you cite \
after a web-search lookup must be exact and verifiable — do NOT fabricate, paraphrase, or \
approximate URLs.

Be opinionated. Do not list every conceivable approach — identify the most promising ones and \
explain concretely *why* they are promising for this specific problem, grounding each \
direction in concrete Stage 0 material where possible.

Output a single JSON object inside a markdown code block:

```json
{{
  "strategic_overview": "1–2 paragraph assessment of the problem landscape — what makes it hard, what the field's standard tools are (with pointers into the Stage 0 papers), and where the best leverage is",
  "directions": [
    {{
      "name": "short descriptive name",
      "description": "specific enough that a mathematician can start working immediately",
      "key_ideas": ["core idea 1", "core idea 2"],
      "relevant_techniques": ["technique or lemma from the literature, with a brief note on how it applies; cite the Stage 0 paper (title or arXiv ID) when reusing"],
      "potential_obstacles": "what might prevent this from working"
    }}
  ],
  "key_obstacles": "the main barriers to solving the original problem as stated",
  "recommended_starting_point": "which direction to try first, and what the very first step should be"
}}
```
""".strip()


def _format_directions_for_solver(d):
    """Render the advisor-directions JSON as readable text for the solver prompt."""
    lines = [d.get("strategic_overview", "")]
    lines.append("\n## Directions to Explore")
    for direction in d.get("directions", []):
        lines.append(f"\n### {direction.get('name', '')}")
        lines.append(direction.get("description", ""))
        if direction.get("key_ideas"):
            lines.append("Key ideas: " + "; ".join(direction["key_ideas"]))
        if direction.get("relevant_techniques"):
            lines.append("Relevant techniques: " + "; ".join(direction["relevant_techniques"]))
        if direction.get("potential_obstacles"):
            lines.append(f"Potential obstacles: {direction['potential_obstacles']}")
    if d.get("key_obstacles"):
        lines.append(f"\n## Key Obstacles\n{d['key_obstacles']}")
    if d.get("recommended_starting_point"):
        lines.append(f"\n## Recommended Starting Point\n{d['recommended_starting_point']}")
    return "\n".join(lines)


def run_advisor_directions(literature_records):
    if DIRECTIONS_FILE.exists():
        print(f"[RESUME] Advisor directions already generated: {DIRECTIONS_FILE.name}")
        with open(DIRECTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)

    literature_section = format_literature_for_directions(literature_records) or (
        "(Stage 0 literature research produced no usable extractions — proceed "
        "from your own knowledge only.)"
    )

    prompt = ADVISOR_DIRECTIONS_PROMPT_TEMPLATE.format(
        problem=problem,
        past_notes_section=_format_past_notes_for_prompt(_load_solver_history()),
        literature_section=literature_section,
    )
    print(f"\n{'='*80}\n[Stage 1] Advisor Directions\n{'='*80}")
    # Literature section can be very large; trim the printed copy to avoid
    # drowning the log. The full prompt is still sent to the API.
    if len(prompt) > 4000:
        print(prompt[:2000] + f"\n... [truncated; full prompt is {len(prompt)} chars] ...\n" + prompt[-1500:])
    else:
        print(prompt)

    output_text, usage = run_response(
        prompt,
        stage_name="advisor_directions",
        reasoning_effort=PLAN_REASONING,
        verbosity=PLAN_VERBOSITY,
        max_output_tokens=PLAN_MAX_TOKENS,
        web_search=True,
    )
    print(output_text)

    try:
        directions = json.loads(extract_json_object(output_text))
        if not isinstance(directions, dict):
            raise ValueError("Expected a JSON object.")
    except Exception as e:
        print(f"[advisor_directions] JSON parse failed ({e}), storing raw text")
        directions = {"strategic_overview": output_text, "directions": [], "key_obstacles": "", "recommended_starting_point": ""}

    directions["_usage"] = usage
    with open(DIRECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(directions, f, ensure_ascii=False, indent=2)
    print(f"[advisor_directions] saved to {DIRECTIONS_FILE.name}")
    return directions


# ─── Stage 2: Single-Advisor Orchestrated Solving ─────────────────────────────
#
# Architecture: one persistent advisor, stateless one-shot solvers.
#
# Each round:
#   1. Advisor call — reads full KB + last solver outputs + remaining budget
#      → emits: KB updates, task assignments (with full solver prompts),
#               write-up tasks, action signal ("continue"|"done")
#   2. Solver calls (1–MAX_PARALLEL_AGENTS in parallel) — each receives the
#      advisor-drafted prompt + an auto-appended structured report format.
#      Local code parses the report and merges results into the shared KB.
#   3. Write-up agents — spawned immediately for advisor-flagged partials.
#
# Budget: ADVISOR_BUDGET (default 5) = max advisor calls.
# After the loop, Stage 2.9 assembles a final solution from the shared KB.
#
# Conversation history: every API call is appended to memory/conversation.jsonl.

# ── Conversation log + Stage-2 progression state ─────────────────────────────
#
# Both used to be bespoke files (stage2_conversation.jsonl + stage2_checkpoint.json).
# They now live inside GlobalMemory:
#
#   • Every prompt+response pair → memory.log_conversation(...) → conversation.jsonl
#   • Every fully-completed round → memory.record_advisor_round(...) → advisor_rounds.jsonl
#   • Resume state derives from memory.stage2_resume_state(); no checkpoint file.


# ── Solver report format ──────────────────────────────────────────────────────
# Automatically appended by local code to every advisor-drafted solver prompt.

SOLVER_REPORT_APPENDIX = """\
---
# Required: Structured Progress Report

At the very end of your response, output this block (fill in all fields):

<SOLVER_REPORT>
{
  "proven_results": [
    {
      "statement": "exact statement of what was proved",
      "is_original_problem": false,
      "sketch": "1-2 sentence proof sketch"
    }
  ],
  "failed_attempts": [
    {
      "approach": "short name",
      "reason": "one sentence: why it failed or what obstacle was hit"
    }
  ],
  "progress_notes": "brief free-text summary of where things stand and what remains to prove"
}
</SOLVER_REPORT>"""


def _extract_solver_report(text):
    m = re.search(r"<SOLVER_REPORT>\s*(.*?)\s*</SOLVER_REPORT>", text, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        try:
            return json.loads(raw)
        except Exception:
            pass
    return {"proven_results": [], "failed_attempts": [], "progress_notes": ""}


def update_kb_from_solver_report(text, task_id):
    """Auto-update the shared KB from a solver's structured <SOLVER_REPORT> block."""
    report = _extract_solver_report(text)
    memory.apply_solver_report(report, task_id)
    return report


# ── Advisor prompt templates ──────────────────────────────────────────────────

# Spliced into both advisor templates only when PUSH_ORIGINAL is set. With
# PUSH_ORIGINAL off, ``originality_section`` is the empty string and the
# rendered prompts are byte-identical to the baseline.
ORIGINALITY_RUBRIC = """\
# Originality Pressure (per-round duty)

Your portfolio of solver tasks must continually attack the *original problem* — \
not drift into a chain of shallow relaxations. After reviewing last round's \
solver outputs, score each completed task on how well it attacked the original \
problem (0–10):
  10 = direct attack on the full original problem with high probability of success
   5 = useful partial result, but more ambition is warranted
   0 = trivial recombination of known results / shallow relaxation that adds no insight

**Cross-round push-back protocol.** If a prior task scored ≤ 4 and the direction \
is not genuinely dead, your default next move is to spawn a follow-up task that
  (a) lists that prior task in `reference_task_ids`,
  (b) explicitly tells the new solver where the previous attempt retreated \
(relaxed assumptions, weakened bounds, missing case, etc.),
  (c) names a specific technique to try in order to close the gap to the original problem.
Do not let weak results stand unchallenged across rounds. If a direction truly \
is dead, record it in `kb_updates.new_failed_attempts` with a one-sentence reason.

**Granularity-aware solver-prompt rule.** Classify every task you assign as \
either `"exploration"` or `"subtask"`:
- `"exploration"` — the solver attacks the full original problem (or a substantial \
fraction of it). Its `solver_prompt` MUST end with a footer instructing the solver \
to stay close to the original problem and not retreat into a trivial relaxation; \
if the full problem is out of reach, the solver should report the strongest partial \
it can prove rather than redefining the goal.
- `"subtask"` — a lemma, special case, decomposition piece, or specific sub-claim. \
Its `solver_prompt` MUST tell the solver to focus narrowly on the assigned sub-task. \
Do NOT include the originality footer here — pushing a lemma-prover toward the full \
problem is counterproductive. Briefly state how the sub-task serves the original \
problem so the solver understands its role, then specify the sub-task precisely.

**Extra JSON fields you must produce in `<ADVISOR_PLAN>`** (in addition to the \
base schema described below):
- Inside each entry of `task_assignments`, add:
    "task_kind": "exploration" | "subtask"
- On rounds 2+ (when there are prior solver outputs to score), add a top-level field:
    "prior_task_scores": [
      {"task_id": "t3", "score": 7, "comment": "1–2 sentence rationale"},
      ...
    ]
"""


ADVISOR_INIT_PROMPT_TEMPLATE = """\
You are a mathematical research advisor with access to web search. Your job is to orchestrate \
solver agents to assemble the best possible proof for the problem below. You have {total_budget} \
advisor calls total (including this one). Plan strategically. Use web search whenever you need \
to look up specific results, verify claims, or find techniques.

# Problem
{problem}

# Strategic Directions (from literature survey)
{directions_text}

# Past Attempts on This Problem (from previous runs)
{past_notes_section}

# Your Role
You are the sole orchestrator. You will:
1. Maintain a priority task list and a shared knowledge base.
2. Each round, assign 1–{max_parallel} tasks to solver agents (parallel API calls).
3. Decide exactly what context each solver needs — you write their full prompts verbatim.
4. When you want a solver (or write-up agent) to read the **full text** of a prior \
   solver's output (e.g., to critique, attack, extend, or assemble it), put those task \
   IDs in `reference_task_ids` — the harness will auto-prepend the full output verbatim. \
   Do NOT try to paste prior outputs inline; just reference them by ID.
5. When significant partial results emerge, flag them for a dedicated write-up agent \
   (you write that prompt too, including all proof details found so far).

Note: you do NOT need to assemble a final solution yourself. When the budget runs out, \
a separate assembly stage will automatically synthesise the best possible solution from \
the shared KB. Focus every round on *exploration and proving new results*.

{originality_section}# Output Format
Reasoning prose first, then your plan inside an <ADVISOR_PLAN> tag. \
The content between the tags must be a single valid JSON object — do NOT wrap it in a \
markdown code block.

<ADVISOR_PLAN>
{{
  "reasoning": "your strategic thinking — what to try first and why",
  "strategic_note": "2-3 sentence note for your future self: what you learned this round, what you decided, and why. This will be shown to you in every subsequent round as a memory aid.",
  "kb_updates": {{
    "new_proven_results": [],
    "new_failed_attempts": [],
    "new_bottlenecks": [],
    "frontier": "the most important thing to establish next"
  }},
  "task_assignments": [
    {{
      "task_id": "t1",
      "description": "one-line label for logging",
      "reference_task_ids": [],
      "solver_prompt": "THE COMPLETE PROMPT to send verbatim to this solver. Include the problem statement, relevant KB results, proof technique hints, and precise instructions. Use `reference_task_ids` to pull in any prior solver outputs you want this solver to read in full — do NOT paste them inline here."
    }}
  ],
  "writeup_tasks": [
    {{
      "statement": "exact statement of the result being written up",
      "solves_original_problem": false,
      "reference_task_ids": [],
      "writeup_agent_prompt": "complete prompt for the write-up agent"
    }}
  ],
  "action": "continue"
}}
</ADVISOR_PLAN>

**reference_task_ids:** list of prior task IDs whose full outputs should be auto-attached \
to the agent's prompt. Strict for solver tasks (unknown IDs cause the task to fail) and \
lenient for writeups (unknown IDs are skipped with a warning). On round 1 there are no \
prior tasks, so leave this empty.

**solves_original_problem (writeup_tasks only):** set to `true` ONLY when the `statement` is \
the full original problem (not a relaxation, not a lemma, not a partial). When `true` and \
the resulting write-up passes verify+refine, the assembly stage will reuse the verified \
write-up verbatim instead of spending a fresh solver call. Set to `false` for any partial \
result, lemma, or relaxation. This flag is also used by the verifier to pick its framing: \
`true` ⇒ verify against the original problem verbatim; `false` ⇒ verify against the \
write-up's stated claim. Setting it incorrectly will give you a misleading verification \
verdict, so be honest about what is actually being written up.

**writeup_agent_prompt (writeup_tasks only):** the write-up agent will be evaluated by an \
independent referee, and the resulting artifact then flows downstream into benchmark and \
LaTeX-typesetting stages, none of which have access to this conversation, the shared KB, \
the solver outputs, or any custom notation introduced along the way. Your prompt MUST \
therefore instruct the agent to produce a **fully self-contained artifact**: \
(1) state the exact claim being proved up front, with every symbol, hypothesis, \
quantifier, and notational convention defined inline; (2) write the proof so a reader who \
has never seen the solver history, the KB, or this conversation can follow it end-to-end; \
(3) avoid any reference to "the problem above", "the previous result", "the construction \
we used", or other shorthand that depends on context the referee cannot see. If the agent \
needs concrete prior outputs to build on, list them in `reference_task_ids` (which \
auto-attaches them verbatim) — do NOT assume inherited context.

**action values:** `"continue"` — keep exploring; `"done"` — no more work needed.

Assign at most {max_parallel} solver tasks this round. Start with the highest-priority direction.
""".strip()


ADVISOR_PLAN_PROMPT_TEMPLATE = """\
You are a mathematical research advisor with access to web search. Your job is to orchestrate \
solver agents to assemble the best possible proof for the problem below. You are actively \
solving this problem — this is round {prev_round}+1 of an ongoing effort, and the shared \
knowledge base records what has already been established. Use web search whenever you need \
to look up specific results, verify claims, or find techniques.

# Problem We Are Solving
{problem}

# Budget
Advisor calls used so far: {calls_used} of {total_budget}. \
**Remaining (including this call): {remaining_budget}.**

# Shared Knowledge Base (full view of progress so far)
{kb_section}

# Solver Outputs — Round {prev_round}
{solver_outputs_section}

# Available Prior Task IDs (use in reference_task_ids to auto-attach full outputs)
{task_id_index_section}

# Your Role
You are the sole orchestrator. Each round you:
1. Review what the solvers found and integrate it into the KB.
2. Reprioritise the task list based on the new state of the proof.
3. Assign 1–{max_parallel} tasks to solver agents (parallel API calls), writing each \
   solver's complete prompt verbatim. When the new solver should read the **full text** \
   of one or more prior solvers' outputs (e.g., to critique, attack as a red-team, \
   extend, or directly build on a proof attempt), list those task IDs in \
   `reference_task_ids` — the harness will auto-prepend their full outputs verbatim. \
   Do NOT paste prior outputs inline in `solver_prompt`; reference them by ID instead. \
   Use `solver_prompt` for instructions, KB-summary context, and pointers like \
   "examine Task t3's argument for gaps".
4. When significant partial results emerge, flag them for a dedicated write-up agent \
   (you write that prompt too, including all proof details found so far). The write-up \
   task can also use `reference_task_ids` to pull in prior outputs.

Note: you do NOT need to assemble a final solution yourself. When the budget runs out, \
a separate assembly stage will automatically synthesise the best possible solution from \
the shared KB. Focus every round on *exploration and proving new results*.

{originality_section}# Output Format
Reasoning prose first, then your plan inside an <ADVISOR_PLAN> tag. \
The content between the tags must be a single valid JSON object — do NOT wrap it in a \
markdown code block.

<ADVISOR_PLAN>
{{
  "reasoning": "what the solvers found, what it means, and what to do next",
  "strategic_note": "2-3 sentence note for your future self: what you learned this round, what you decided, and why. This will be shown to you in every subsequent round as a memory aid.",
  "kb_updates": {{
    "new_proven_results": [{{"statement": "...", "sketch": "..."}}],
    "new_failed_attempts": [{{"approach": "...", "reason": "one sentence"}}],
    "new_bottlenecks": ["..."],
    "frontier": "the most important next thing to establish"
  }},
  "task_assignments": [
    {{
      "task_id": "t{next_task_num}",
      "description": "one-line label",
      "reference_task_ids": [],
      "solver_prompt": "complete prompt for this solver"
    }}
  ],
  "writeup_tasks": [
    {{
      "statement": "...",
      "solves_original_problem": false,
      "reference_task_ids": [],
      "writeup_agent_prompt": "complete prompt for write-up agent"
    }}
  ],
  "action": "continue | done"
}}
</ADVISOR_PLAN>

**reference_task_ids:** list of prior task IDs (drawn from the index above) whose full \
outputs should be auto-attached to the agent's prompt. **Strict** for solver tasks: \
unknown IDs cause that task to fail before its API call. **Lenient** for writeups: \
unknown IDs are skipped with a warning. Reference only IDs from completed rounds — \
referencing the same round's tasks (running in parallel) will fail in strict mode.

**solves_original_problem (writeup_tasks only):** set to `true` ONLY when the `statement` is \
the full original problem (not a relaxation, not a lemma, not a partial). When `true` and \
the resulting write-up passes verify+refine, the assembly stage will reuse the verified \
write-up verbatim instead of spending a fresh solver call. Set to `false` for any partial \
result, lemma, or relaxation. This flag is also used by the verifier to pick its framing: \
`true` ⇒ verify against the original problem verbatim; `false` ⇒ verify against the \
write-up's stated claim. Setting it incorrectly will give you a misleading verification \
verdict, so be honest about what is actually being written up.

**writeup_agent_prompt (writeup_tasks only):** the write-up agent will be evaluated by an \
independent referee, and the resulting artifact then flows downstream into benchmark and \
LaTeX-typesetting stages, none of which have access to this conversation, the shared KB, \
the solver outputs, or any custom notation introduced along the way. Your prompt MUST \
therefore instruct the agent to produce a **fully self-contained artifact**: \
(1) state the exact claim being proved up front, with every symbol, hypothesis, \
quantifier, and notational convention defined inline; (2) write the proof so a reader who \
has never seen the solver history, the KB, or this conversation can follow it end-to-end; \
(3) avoid any reference to "the problem above", "the previous result", "the construction \
we used", or other shorthand that depends on context the referee cannot see. If the agent \
needs concrete prior outputs to build on, list them in `reference_task_ids` (which \
auto-attaches them verbatim) — do NOT assume inherited context.

Assign at most {max_parallel} parallel solver tasks.
""".strip()


def _format_solver_outputs_for_advisor(solver_outputs):
    """Format last round's solver outputs for the advisor prompt."""
    if not solver_outputs:
        return "(No solver outputs yet — this is the first round.)"
    lines = []
    for so in solver_outputs:
        lines.append(f"## Task {so['task_id']} — {so.get('description', '')}")
        report = _extract_solver_report(so["output"])
        lines.append("**Proven results:**")
        for pr in report.get("proven_results", []):
            lines.append(f"  • {pr.get('statement','')} — {pr.get('sketch','')}")
        if not report.get("proven_results"):
            lines.append("  (none)")
        lines.append("**Failed attempts:**")
        for fa in report.get("failed_attempts", []):
            lines.append(f"  • {fa.get('approach','')}: {fa.get('reason','')}")
        if not report.get("failed_attempts"):
            lines.append("  (none)")
        lines.append(f"**Progress notes:** {report.get('progress_notes','')}")
        lines.append(f"\n<full_solver_output task_id=\"{so['task_id']}\">")
        lines.append(so["output"])
        lines.append("</full_solver_output>\n")
    return "\n".join(lines)


def _repair_json_escapes(raw):
    r"""Fix invalid \X escape sequences (e.g. \sum, \frac, \begin from LaTeX)
    by doubling the backslash so json.loads treats them as literal text.

    Walks the string respecting JSON-string boundaries and consumes valid
    \X pairs as a unit, so the second backslash of a valid \\ pair is never
    treated as a candidate for doubling. A naive regex would corrupt valid
    sequences like \\dots into \\\dots (which then re-fails to parse).
    """
    valid_escape = set('"\\/bfnrtu')
    out = []
    in_string = False
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if not in_string:
            out.append(c)
            if c == '"':
                in_string = True
            i += 1
            continue
        if c == '"':
            out.append(c)
            in_string = False
            i += 1
            continue
        if c == '\\':
            nxt = raw[i + 1] if i + 1 < n else ''
            if nxt in valid_escape:
                out.append(c)
                out.append(nxt)
                i += 2
            else:
                out.append('\\\\')
                i += 1
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _parse_json_lenient(raw):
    """Try json.loads; on failure, repair common escape issues and retry."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = _repair_json_escapes(raw)
        return json.loads(repaired)


def _extract_advisor_plan(advisor_text):
    """Parse the advisor's JSON plan from <ADVISOR_PLAN> tags.

    Falls back to extract_json_object if the tags are missing.
    """
    # Primary: extract from <ADVISOR_PLAN> ... </ADVISOR_PLAN>
    m = re.search(r"<ADVISOR_PLAN>\s*(.*?)\s*</ADVISOR_PLAN>", advisor_text, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        try:
            parsed = _parse_json_lenient(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            print(f"[advisor] WARNING: <ADVISOR_PLAN> tag found but JSON invalid: {exc}")
            print(f"[advisor] (first 500 chars of tag content): {raw[:500]}")

    # Fallback: try generic JSON extraction
    try:
        raw = extract_json_object(advisor_text)
        parsed = _parse_json_lenient(raw)
        if isinstance(parsed, dict):
            print("[advisor] WARNING: no <ADVISOR_PLAN> tag — fell back to generic JSON extraction")
            return parsed
    except Exception as exc:
        print(f"[advisor] WARNING: failed to parse advisor JSON: {exc}")
        print(f"[advisor] (first 500 chars of response): {advisor_text[:500]}")

    return {
        "reasoning":        "could not parse advisor output",
        "kb_updates":       {},
        "task_assignments": [],
        "writeup_tasks":    [],
        "action":           "continue",
    }


def _apply_advisor_kb_updates(kb_updates, source="advisor"):
    """Apply the advisor's editorial KB updates (distinct from auto-merge from solver reports)."""
    memory.apply_advisor_kb_updates(kb_updates, source=source)


# ── Cross-task reference attachment ──────────────────────────────────────────
#
# When the advisor wants a new solver (or write-up) to read the full text of
# a prior task's output, it lists those task IDs in ``reference_task_ids`` and
# the harness mechanically prepends the referenced outputs verbatim (full
# text, no truncation) before the advisor's prompt.
#
# Strict mode (solver tasks): unknown task IDs raise — the advisor must only
#   reference tasks that have actually completed.
# Lenient mode (writeup tasks): unknown task IDs are skipped with a warning,
#   because writeups can be flagged in round 1 (no prior tasks exist) or can
#   reference in-flight writeups whose outputs aren't yet recorded.
#
# The actual lookup lives on GlobalMemory; this helper is the prompt-shaping
# wrapper.

def _prepend_referenced_outputs(advisor_prompt, task_ids, *, strict, log_prefix):
    block = memory.get_referenced_outputs(
        task_ids, strict=strict, log_prefix=log_prefix,
    )
    if not block:
        return advisor_prompt
    return block + "\n\n---\n\n" + advisor_prompt.lstrip()


# ── One-shot solver runner ────────────────────────────────────────────────────

def run_solver_task(advisor_prompt, task_id, round_num):
    """
    One-shot stateless solver call.
    The advisor writes the full prompt; local code appends the structured
    report format. Returns (solver_text, usage).
    """
    full_prompt = advisor_prompt.rstrip() + "\n\n" + SOLVER_REPORT_APPENDIX
    stage_name  = f"solver_r{round_num}_{task_id}"
    print(f"\n{'='*60}\n[solver] Round {round_num} | Task {task_id}\n{'='*60}")

    solver_text, usage = run_response(
        full_prompt,
        stage_name=stage_name,
        reasoning_effort=SOLVE_REASONING,
        verbosity=SOLVE_VERBOSITY,
        max_output_tokens=SOLVE_MAX_TOKENS,
        web_search=True,
    )
    print(f"\n[solver r{round_num}/{task_id}] (first 800 chars):\n{solver_text[:800]}…")

    memory.log_conversation({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type":      "solver",
        "round":     round_num,
        "task_id":   task_id,
        "prompt":    full_prompt,
        "response":  solver_text,
        "usage":     usage,
    })
    return solver_text, usage


def _store_solver_output(solver_text, usage, task_id, round_num, description,
                         kind="solver"):
    """Extract solution metadata and persist via memory.add_task_output.

    ``full_text`` is the raw solver response (including the trailing
    SOLVER_REPORT block and any other structured tail). It is the canonical
    source for cross-task ``reference_task_ids`` attachments and is persisted
    to ``task_outputs.jsonl`` so resumed runs replay it back into memory.
    """
    solution_text, problem_solved, is_relaxation = extract_solution_metadata(
        solver_text, problem,
    )
    return memory.add_task_output(
        task_id                       = task_id,
        kind                          = kind,
        round_num                     = round_num,
        description                   = description,
        full_text                     = solver_text,
        solution                      = solution_text,
        self_declared_problem_solved  = problem_solved,
        self_declared_is_relaxation   = is_relaxation,
        usage                         = usage,
    )


# ── Write-up agent (advisor-drafted prompt) ───────────────────────────────────

WRITEUP_FORMAT_REQUIREMENTS_TEMPLATE = """\
# Required Output Format (enforced by the harness)

The original problem is reproduced below verbatim. Your write-up MUST contain the \
following four pieces, in order:

<ORIGINAL_PROBLEM>
{original_problem}
</ORIGINAL_PROBLEM>

1. A `## Original Problem` section that quotes the text inside <ORIGINAL_PROBLEM> \
above **verbatim**, with no edits, paraphrasing, or reformatting.

2. A `## Problem Solved` section stating the *exact* statement your proof establishes, \
written in **fully self-contained form**: define every symbol, quantifier, hypothesis, \
and notational convention inline, so a reader who sees only this section understands the \
precise claim with no reference to the Original Problem section, the proof body, or any \
external context. If this claim differs from the original problem in any way (weakened \
hypotheses, special case, partial result, single lemma, etc.), say so explicitly and \
explain *how* it differs.

3. The proof itself, organised however you see fit.

4. A trailing fenced JSON block — the very last thing in your response — with this \
exact shape:

```json
{{
  "original_problem": "...the original problem text, copied verbatim from <ORIGINAL_PROBLEM>...",
  "problem_solved": "...the exact statement your proof establishes...",
  "is_relaxation": true | false
}}
```

Set `is_relaxation` to `true` whenever `problem_solved` is anything weaker than, \
narrower than, or otherwise different from the original problem. Set it to `false` \
only when your proof establishes the original problem exactly as stated.

The harness parses the JSON block; a missing or malformed block triggers a retry.
""".strip()


WRITEUP_RETRY_REMINDER = """\

---

NOTE FROM THE HARNESS: your previous response did not include the required trailing \
JSON metadata block. Re-emit your complete write-up — `## Original Problem` section \
(verbatim), `## Problem Solved` section, the proof, and end with the mandatory fenced \
JSON block:

```json
{
  "original_problem": "...verbatim...",
  "problem_solved": "...exact statement proved...",
  "is_relaxation": true | false
}
```

The JSON block must be the last thing in your response.
""".strip()


def _writeup_has_metadata_block(text):
    """True iff the write-up response contains the required trailing JSON block."""
    return bool(re.search(
        r"```(?:json)?\s*\{[^`]*\"problem_solved\"[^`]*\}\s*```",
        text, re.DOTALL | re.IGNORECASE,
    ))


def spawn_writeup_from_advisor(writeup_task, round_num):
    """
    Run a write-up agent using a prompt fully drafted by the advisor.
    The advisor decides what proof details to include; local code only runs
    the call and feeds the result through verify+refine.
    """
    stmt           = writeup_task.get("statement", "")
    advisor_prompt = writeup_task.get("writeup_agent_prompt", "")
    reference_ids  = writeup_task.get("reference_task_ids", []) or []
    solves_orig    = bool(writeup_task.get("solves_original_problem", False))
    if not advisor_prompt:
        return None

    # Atomic check-and-claim. partial_writeups_done now means "already in
    # flight or done" — concurrent submissions for the same statement see
    # the claim and skip, avoiding duplicate LLM calls.
    if not memory.try_claim_writeup(stmt):
        print(f"[writeup] Already in flight or done — skipping: {stmt[:60]}")
        return None

    writeup_idx = f"writeup_r{round_num}_{hashlib.md5(stmt.encode()).hexdigest()[:6]}"
    print(f"\n{'='*60}\n[writeup] Round {round_num}: {stmt[:80]}\n{'='*60}")

    # Append harness-enforced format requirements after the advisor's free-form
    # prompt so the write-up always declares (verbatim) the original problem,
    # what was actually solved, and whether it is a relaxation.
    format_requirements = WRITEUP_FORMAT_REQUIREMENTS_TEMPLATE.format(
        original_problem=problem,
    )
    prompt_body = f"{advisor_prompt}\n\n{format_requirements}"

    # Lenient reference attachment: writeups can be flagged in round 1 (no
    # prior tasks exist) or reference in-flight writeups whose outputs aren't
    # yet visible — unknown IDs are warned-and-skipped, not errored.
    prompt = _prepend_referenced_outputs(
        prompt_body, reference_ids,
        strict=False, log_prefix=f"[writeup {writeup_idx}]",
    )

    try:
        memory.log_conversation({
            "timestamp":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type":               "writeup_prompt",
            "round":              round_num,
            "task_id":            writeup_idx,
            "statement":          stmt,
            "reference_task_ids": reference_ids,
            "prompt":             prompt,
        })

        writeup_text, usage = run_response(
            prompt,
            stage_name=f"writeup_{writeup_idx}",
            reasoning_effort=SOLVE_REASONING,
            verbosity=SOLVE_VERBOSITY,
            max_output_tokens=SOLVE_MAX_TOKENS,
            web_search=True,
        )

        # Enforcement: if the required metadata block is missing, retry once
        # with a stricter reminder appended to the original prompt.
        if not _writeup_has_metadata_block(writeup_text):
            print(f"[writeup {writeup_idx}] missing required JSON metadata block — retrying once")
            retry_prompt = f"{prompt}\n\n{WRITEUP_RETRY_REMINDER}"
            retry_text, retry_usage = run_response(
                retry_prompt,
                stage_name=f"writeup_{writeup_idx}_retry",
                reasoning_effort=SOLVE_REASONING,
                verbosity=SOLVE_VERBOSITY,
                max_output_tokens=SOLVE_MAX_TOKENS,
                web_search=True,
            )
            usage = _aggregate_usage([usage, retry_usage])
            if _writeup_has_metadata_block(retry_text):
                writeup_text = retry_text
            else:
                print(f"[writeup {writeup_idx}] WARNING: retry still missing JSON metadata "
                      f"block — proceeding with fallback metadata")
                writeup_text = retry_text

        print(f"\n[writeup {writeup_idx}] (first 500 chars):\n{writeup_text[:500]}…")

        memory.log_conversation({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type":      "writeup_response",
            "round":     round_num,
            "task_id":   writeup_idx,
            "response":  writeup_text,
            "usage":     usage,
        })

        solution_text, ps, is_relax = extract_solution_metadata(writeup_text, stmt)
        metadata_present = _writeup_has_metadata_block(writeup_text)
        # Canonical labels come from the writeup's own self-declaration. The
        # advisor's `solves_orig` is a pre-flight intent flag; we keep it as
        # provenance below but never let it overwrite what the writeup declared
        # actually was proved. Fallback: if the writeup omitted the metadata
        # block entirely, fall back to the advisor's framing (statement +
        # intent), which is the best signal available.
        if metadata_present:
            ps_final            = ps
            is_relaxation_final = is_relax
        else:
            ps_final            = stmt
            is_relaxation_final = not solves_orig
        # Surface advisor↔writeup disagreement in the run log so it's easy to
        # find later. Only meaningful when the writeup actually emitted a block.
        if metadata_present and bool(solves_orig) != (not is_relaxation_final):
            print(f"[writeup {writeup_idx}] advisor solves_original_problem="
                  f"{solves_orig} but writeup self-declared is_relaxation="
                  f"{is_relaxation_final} — trusting writeup")
        description_text = (
            f"writeup (full problem): {stmt}"
            if not is_relaxation_final
            else f"writeup (partial): {stmt}"
        )
        memory.add_task_output(
            task_id                       = writeup_idx,
            kind                          = "writeup",
            round_num                     = round_num,
            description                   = description_text,
            full_text                     = writeup_text,
            solution                      = solution_text,
            self_declared_problem_solved  = ps_final,
            self_declared_is_relaxation   = is_relaxation_final,
            usage                         = usage,
            advisor_statement                = stmt,
            advisor_solves_original_problem  = bool(solves_orig),
            writeup_declared_problem_solved  = ps if metadata_present else None,
            writeup_declared_is_relaxation   = is_relax if metadata_present else None,
            metadata_block_present           = metadata_present,
        )

        # Mark written-up immediately so the advisor sees [pending verification]
        # in subsequent rounds while verify+refine runs in the background.
        memory.mark_proven_result_written_up(stmt)
    except Exception:
        # Writeup-LLM phase failed: release the claim so a future round can retry.
        print(f"[writeup] {writeup_idx} draft failed — releasing slot for retry")
        memory.release_writeup_claim(stmt)
        raise

    # ── verify + refine (runs concurrently with subsequent rounds) ──
    # Errors here do NOT release the claim — the writeup itself succeeded;
    # only the verification verdict is missing. The advisor will see
    # [written up] (no verification tag) and Stage 3's residual sweep
    # will catch it as a fallback.
    try:
        print(f"[writeup→verify] {writeup_idx} entering verify+refine")
        final_entry = verify_refine_stage(writeup_idx, {"title": writeup_idx})
        verified    = _is_kb_verified(final_entry["if_final_true"])
        _update_kb_verification(
            statement      = stmt,
            verified       = verified,
            solution_text  = final_entry["Final_Solution"],
            solution_ref   = f"final_solutions.jsonl task_id={writeup_idx}",
            problem_solved = final_entry.get("problem_solved"),
            is_relaxation  = final_entry.get("is_relaxation"),
        )
        print(f"[writeup→verify] {writeup_idx} verified={verified}")
    except Exception as exc:
        print(f"[writeup→verify] {writeup_idx} verification error (will retry in Stage 3): {exc}")
        traceback.print_exc()

    return memory.get_task_output(writeup_idx)


# ── Advisor runner ────────────────────────────────────────────────────────────

def run_advisor_round(round_num, remaining_budget, last_solver_outputs,
                      directions_text, total_budget, task_counter):
    """Single advisor call. Returns (plan_dict, advisor_text, usage)."""
    calls_used = total_budget - remaining_budget

    originality_section = (ORIGINALITY_RUBRIC + "\n") if PUSH_ORIGINAL else ""

    if round_num == 1:
        prompt = ADVISOR_INIT_PROMPT_TEMPLATE.format(
            problem=problem,
            total_budget=total_budget,
            directions_text=directions_text,
            past_notes_section=_format_past_notes_for_prompt(_load_solver_history()),
            max_parallel=MAX_PARALLEL_AGENTS,
            originality_section=originality_section,
        )
    else:
        prompt = ADVISOR_PLAN_PROMPT_TEMPLATE.format(
            problem=problem,
            calls_used=calls_used,
            total_budget=total_budget,
            remaining_budget=remaining_budget,
            kb_section=memory.kb_for_advisor(),
            solver_outputs_section=_format_solver_outputs_for_advisor(last_solver_outputs),
            task_id_index_section=memory.task_id_index_for_advisor(),
            prev_round=round_num - 1,
            next_task_num=task_counter,
            max_parallel=MAX_PARALLEL_AGENTS,
            originality_section=originality_section,
        )

    print(f"\n{'='*80}\n[advisor] Round {round_num} | Budget: {remaining_budget}/{total_budget} remaining\n{'='*80}")

    advisor_text, usage = run_response(
        prompt,
        stage_name=f"advisor_r{round_num}",
        reasoning_effort=ADVISOR_REASONING,
        verbosity=ADVISOR_VERBOSITY,
        max_output_tokens=ADVISOR_MAX_TOKENS,
        web_search=True,
    )
    print(f"\n[advisor r{round_num}]:\n{advisor_text}")

    memory.log_conversation({
        "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type":             "advisor",
        "round":            round_num,
        "remaining_budget": remaining_budget,
        "prompt":           prompt,
        "response":         advisor_text,
        "usage":            usage,
    })

    plan = _extract_advisor_plan(advisor_text)
    print(f"[advisor r{round_num}] action={plan.get('action')!r} "
          f"tasks={len(plan.get('task_assignments', []))} "
          f"writeups={len(plan.get('writeup_tasks', []))}")
    return plan, advisor_text, usage


# ── Stage 2.9: Assembly prompts ───────────────────────────────────────────────
#
# Stage 2.9 first scans final_solutions for any verified write-up of the
# original problem (if_final_true=true, is_relaxation=false). If one exists
# it is reused verbatim as ``assembly_final`` and the assembly advisor is
# never called. Otherwise, the assembly advisor runs and uses the same
# reference_task_ids pattern as the regular advisor: it sees a richer task
# index and picks which write-ups / partial solver outputs to load in full
# for the assembly solver.

ASSEMBLY_ADVISOR_PROMPT_TEMPLATE = """\
You are a mathematical research advisor. The exploration phase has ended; the shared \
knowledge base contains every result the solvers and write-up agents produced this run. \
A pre-assembly scan has already determined that **no single verified write-up covers the \
full original problem** — only partial / verified-but-relaxed / unverified material is on \
hand. Your job is to plan one final assembly solver call that stitches the strongest \
material into the best possible self-contained solution.

# Original Problem
{problem}

# Shared Knowledge Base (full view — summaries only)
{kb_section}

# Available Task Outputs (use in reference_task_ids to auto-attach full text)
{assembly_task_index_section}

# Your Role
Pick the prior task outputs the assembly solver should read in full (verified write-ups \
of partials, the strongest solver attempts, etc.) and write the assembly solver's prompt. \
The harness will auto-prepend the full text of every ID in `reference_task_ids` to the \
solver prompt, so do NOT paste those outputs inline — reference them by ID. Do prefer \
write-ups marked verify=✓ (already verified by the verifier) over raw solver attempts.

Your `solver_prompt` must:
1. State the problem.
2. Tell the solver which referenced task IDs to build on and what role each plays — the \
   solver sees the referenced outputs as a "Referenced Prior Solver Outputs" preamble.
3. Explain the overall proof strategy: how the pieces fit together, what the main \
   argument flow should be.
4. Explicitly warn about failed approaches so the solver does not repeat them.
5. If only a partial result is achievable, tell the solver exactly what to prove and \
   what to flag as open.
6. Instruct the solver NOT to re-derive results that are already verified in the \
   referenced outputs — quote / reuse them instead.

# Output Format
Reasoning prose first, then your plan inside an <ASSEMBLY_PLAN> tag. The content between \
the tags must be a single valid JSON object — do NOT wrap it in a markdown code block.

<ASSEMBLY_PLAN>
{{
  "reasoning": "which write-ups / partials you chose to reference and why",
  "reference_task_ids": ["writeup_r5_abc123", "t7"],
  "solver_prompt": "complete prompt for the assembly solver"
}}
</ASSEMBLY_PLAN>

**reference_task_ids:** strict — every ID must be present in the task index above. By \
Stage 2.9 every prior task is on disk, so unknown IDs would indicate a typo.
""".strip()


ASSEMBLY_SOLVER_FALLBACK_PROMPT_TEMPLATE = """\
You are a mathematical solver. Your task is to assemble the strongest possible \
self-contained solution to the problem below, drawing on all the results that \
have been established during an extended research session.

# Problem
{problem}

# Established Results and Progress
{kb_section}

# Instructions
Synthesize all proven results into one rigorous, self-contained proof. \
A reader should be able to follow your argument without reference to the \
solver history — restate every lemma you use and give full proofs.

If the full original problem cannot be solved from the available results, \
assemble the best partial result and state clearly:
  1. What has been proved (with full proof).
  2. What remains open.

Do NOT introduce new unproven claims. Build only on the established results above.
""".strip()


def _find_complete_verified_writeup():
    """Return the earliest write-up entry that fully solves the original problem.

    Eligibility: task_id starts with ``writeup_``, ``if_final_true == "true"``,
    and ``is_relaxation == False`` in final_solutions.jsonl. The
    ``is_relaxation`` flag is the **verifier's** final verdict — the verifier
    sees both the canonical Original Problem and the Claim Being Verified and
    emits ``<IS_RELAXATION>`` by comparing them; ``verify_refine_stage``
    overwrites the in-memory flag with that verdict on every verify round, so
    the value persisted to final_solutions.jsonl is what the verifier last
    decided. This filter therefore selects write-ups the verifier judged to
    establish the Original Problem exactly. Among multiple eligible entries
    we pick the one from the earliest round so the choice is deterministic
    across resume.
    """
    candidates = []
    for tid, fe in memory.all_final_solutions().items():
        if not tid.startswith("writeup_"):
            continue
        if (fe.get("if_final_true") or "").lower() != "true":
            continue
        if fe.get("is_relaxation", True):
            continue
        task_entry = memory.get_task_output(tid) or {}
        round_num  = task_entry.get("round", 10**9)
        candidates.append((round_num, tid, fe, task_entry))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    _, tid, fe, task_entry = candidates[0]
    return {"task_id": tid, "final_solution": fe, "task_output": task_entry}


def _run_assembly_advisor(round_label):
    """Call the assembly advisor for Stage 2.9.

    Returns a dict::
        {"action": "solve",    "reference_task_ids": [...], "solver_prompt": "..."}
        {"action": "fallback"}                                # parsing failed

    The caller (Stage 2.9) is responsible for the pre-assembly verified-writeup
    scan; this function is invoked only when no complete verified write-up
    exists, so the prompt explicitly states that.
    """
    kb_section = memory.kb_for_advisor()
    prompt = ASSEMBLY_ADVISOR_PROMPT_TEMPLATE.format(
        problem=problem,
        kb_section=kb_section,
        assembly_task_index_section=memory.assembly_task_index_for_advisor(),
    )

    print(f"\n{'='*80}\n[Stage 2.9] Assembly advisor\n{'='*80}")

    advisor_text, usage = run_response(
        prompt,
        stage_name=f"assembly_advisor_{round_label}",
        reasoning_effort=ADVISOR_REASONING,
        verbosity=ADVISOR_VERBOSITY,
        max_output_tokens=ADVISOR_MAX_TOKENS,
        web_search=False,
    )
    print(f"\n[assembly_advisor]:\n{advisor_text}")

    memory.log_conversation({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type":      "assembly_advisor",
        "round":     round_label,
        "prompt":    prompt,
        "response":  advisor_text,
        "usage":     usage,
    })

    plan_match = re.search(
        r"<ASSEMBLY_PLAN>\s*(.*?)\s*</ASSEMBLY_PLAN>",
        advisor_text, re.DOTALL,
    )
    if plan_match:
        try:
            parsed = _parse_json_lenient(plan_match.group(1).strip())
        except Exception as exc:
            print(f"[assembly_advisor] WARNING: <ASSEMBLY_PLAN> JSON invalid: {exc}")
            parsed = None

        if isinstance(parsed, dict):
            solver_prompt = (parsed.get("solver_prompt") or "").strip()
            ref_ids       = parsed.get("reference_task_ids") or []
            if not isinstance(ref_ids, list):
                print(f"[assembly_advisor] WARNING: reference_task_ids not a list "
                      f"({type(ref_ids).__name__}) — coercing to empty list")
                ref_ids = []
            if solver_prompt:
                return {
                    "action":             "solve",
                    "reference_task_ids": ref_ids,
                    "solver_prompt":      solver_prompt,
                }
            print("[assembly_advisor] WARNING: <ASSEMBLY_PLAN> parsed but solver_prompt empty")

    print("[assembly_advisor] WARNING: could not extract assembly plan — using fallback")
    return {"action": "fallback"}


# ── Main Stage 2 loop ─────────────────────────────────────────────────────────

MAX_PARALLEL_AGENTS = min(env_int("MAX_PARALLEL_AGENTS", 2), 3)  # hard cap at 3

# Background pool for write-up agents. Writeups are fire-and-forget from the
# loop's perspective — they run concurrently with subsequent rounds and are
# drained at end-of-loop before Stage 2.9 assembly so the assembly sees the
# full picture (written_up=True flags settled).
_writeup_executor      = ThreadPoolExecutor(
    max_workers=MAX_PARALLEL_AGENTS, thread_name_prefix="writeup",
)
_writeup_futures       = []
_writeup_futures_lock  = threading.Lock()


def _submit_writeup(writeup_task, round_num):
    fut = _writeup_executor.submit(spawn_writeup_from_advisor, writeup_task, round_num)
    with _writeup_futures_lock:
        _writeup_futures.append(fut)
    return fut


def _drain_writeup_futures(label="end-of-loop"):
    """Wait for all in-flight writeups to finish and surface any errors."""
    with _writeup_futures_lock:
        pending = [f for f in _writeup_futures if not f.done()]
    if not pending:
        return
    print(f"[writeup] [{label}] waiting for {len(pending)} in-flight writeup(s)…")
    for fut in as_completed(pending):
        try:
            fut.result()
        except Exception as exc:
            print(f"[writeup] background writeup error: {exc}")
            traceback.print_exc()


def orchestrated_solve_loop_v2(directions):
    """
    Single-advisor orchestrated solving loop with mid-loop crash recovery.

    One advisor drives the entire session. Each round:
      1. Advisor call — sees full KB + previous solver outputs + remaining budget
         → writes complete solver prompts, KB updates, write-up tasks, action
      2. Solver calls (1–MAX_PARALLEL_AGENTS, parallel) — stateless, one-shot
         → structured <SOLVER_REPORT> auto-merged into shared KB
      3. Write-up agents for any partials flagged by the advisor

    Resume position is derived from ``memory.stage2_resume_state``, which
    inspects the tail of ``advisor_rounds.jsonl``. There is no separate
    checkpoint file — round-completion events are the checkpoint. A mid-round
    crash (between the advisor call and the round's atomic record) replays
    the advisor call; the same atomicity contract as the legacy harness.

    Loop ends when advisor emits "done", budget hits zero, or no tasks are assigned.

    After the loop, Stage 2.9 asks the advisor to draft an assembly prompt,
    then spawns one solver to assemble the final solution from the shared KB.
    Verification happens later in Stage 3 (outside this function).
    """
    directions_text = _format_directions_for_solver(
        {k: v for k, v in directions.items() if k != "_usage"}
    )

    # ── Resume position derived from the memory event log ─────────────────────
    state = memory.stage2_resume_state(ADVISOR_BUDGET)
    round_num           = state["round_num"]
    budget              = state["budget_remaining"]
    task_counter        = state["task_counter"]
    last_solver_outputs = state["last_solver_outputs"]
    skip_loop           = state["loop_complete"]

    if skip_loop:
        print(f"[RESUME] Stage 2 loop already complete ({round_num} rounds). "
              f"Skipping to Stage 2.9 assembly.")
    elif round_num > 0:
        print(f"[RESUME] Resuming Stage 2 from round {round_num + 1} "
              f"(budget: {budget}/{ADVISOR_BUDGET}, task_counter: {task_counter})")

    # ── Main advisor–solver loop ──────────────────────────────────────────────
    if not skip_loop:
        while budget > 0:
            # ── Wall-clock deadline check ─────────────────────────────────────
            # If the run has been alive (across resumes) for more than
            # STAGE2_DEADLINE_HOURS, terminate the Stage 2 loop at this round
            # boundary so the downstream stages still run within the 24h
            # competition budget. Checked at round boundaries (not mid-round)
            # to keep the memory event log consistent — the last fully-
            # completed round's atomic-commit event is still the resume point.
            if STAGE2_DEADLINE_HOURS > 0:
                elapsed_h = (wall_time() - RUN_START_TS) / 3600.0
                if elapsed_h >= STAGE2_DEADLINE_HOURS:
                    print(f"\n{'!'*80}")
                    print(f"[stage2/deadline] wall-clock elapsed {elapsed_h:.2f}h >= "
                          f"{STAGE2_DEADLINE_HOURS}h budget — terminating Stage 2 "
                          f"loop after {round_num} fully-completed round(s).")
                    print(f"[stage2/deadline] In-flight background writeups will "
                          f"still be drained before Stage 2.9 assembly.")
                    print(f"{'!'*80}\n")
                    memory.record_advisor_round(
                        round_num=round_num,
                        status="loop_complete",
                        budget_remaining_after=budget,
                        task_counter_after=task_counter,
                        plan={"reason": "stage2_deadline_reached",
                              "elapsed_hours": round(elapsed_h, 3),
                              "deadline_hours": STAGE2_DEADLINE_HOURS},
                        usage=None,
                    )
                    break
                else:
                    remaining_h = STAGE2_DEADLINE_HOURS - elapsed_h
                    print(f"[stage2/deadline] {elapsed_h:.2f}h elapsed, "
                          f"{remaining_h:.2f}h until Stage 2 cutoff "
                          f"({STAGE2_DEADLINE_HOURS}h budget)")

            round_num += 1

            # ── Advisor call ──────────────────────────────────────────────
            plan, _advisor_text, _adv_usage = run_advisor_round(
                round_num           = round_num,
                remaining_budget    = budget,
                last_solver_outputs = last_solver_outputs,
                directions_text     = directions_text,
                total_budget        = ADVISOR_BUDGET,
                task_counter        = task_counter,
            )
            budget -= 1

            # Apply advisor's editorial KB updates
            _apply_advisor_kb_updates(plan.get("kb_updates", {}), source=f"advisor_r{round_num}")

            # Persist the advisor's strategic note so future rounds can see it
            memory.add_advisor_note(round_num, plan.get("strategic_note") or "")

            # Spawn write-up agents for any flagged partials.
            # Submitted to a background pool so they do NOT stall the round —
            # they run concurrently with solvers and with subsequent rounds.
            # All in-flight writeups are drained after the loop ends.
            for wu in plan.get("writeup_tasks", []):
                _submit_writeup(wu, round_num)

            action = plan.get("action", "continue")
            if action == "done":
                print(f"[advisor] Action 'done' at round {round_num} — stopping.")
                memory.record_advisor_round(
                    round_num=round_num, status="loop_complete",
                    budget_remaining_after=budget,
                    task_counter_after=task_counter,
                    plan=plan, usage=_adv_usage,
                )
                break

            # ── Spawn solver tasks ────────────────────────────────────────
            assignments = plan.get("task_assignments", [])[:MAX_PARALLEL_AGENTS]
            if not assignments:
                print(f"[advisor] No task assignments at round {round_num} — stopping.")
                memory.record_advisor_round(
                    round_num=round_num, status="loop_complete",
                    budget_remaining_after=budget,
                    task_counter_after=task_counter,
                    plan=plan, usage=_adv_usage,
                )
                break

            last_solver_outputs = []

            # Resolve reference_task_ids (strict mode) up-front, before
            # spawning any solver. A failure here drops *that* assignment
            # from the round and logs the error; sibling assignments still
            # run. This way the advisor can't accidentally launch a solver
            # blind to the prior argument it was supposed to examine.
            resolved_assignments = []
            for a in assignments:
                ref_ids = a.get("reference_task_ids", []) or []
                tid_for_log = a.get("task_id") or f"t{task_counter}"
                try:
                    a["_solver_prompt_full"] = _prepend_referenced_outputs(
                        a.get("solver_prompt", ""), ref_ids,
                        strict=True,
                        log_prefix=f"[orchestrator r{round_num}/{tid_for_log}]",
                    )
                    resolved_assignments.append(a)
                except UnknownReferencedTaskIDs as exc:
                    print(f"[orchestrator] Skipping task {tid_for_log} "
                          f"(reference_task_ids resolution failed): {exc}")
            assignments = resolved_assignments
            if not assignments:
                print(f"[advisor] All assignments failed strict reference resolution "
                      f"at round {round_num} — continuing to next round.")
                memory.record_advisor_round(
                    round_num=round_num, status="in_progress",
                    budget_remaining_after=budget,
                    task_counter_after=task_counter,
                    plan=plan, usage=_adv_usage,
                )
                continue

            if len(assignments) == 1:
                a       = assignments[0]
                task_id = a.get("task_id") or f"t{task_counter}"
                solver_text, sol_usage = run_solver_task(
                    a["_solver_prompt_full"], task_id, round_num,
                )
                task_counter += 1
                update_kb_from_solver_report(solver_text, task_id)
                _store_solver_output(solver_text, sol_usage, task_id, round_num, a.get("description", ""))
                _append_solver_history(task_id, a.get("description", task_id),
                                       _extract_solver_report(solver_text).get("progress_notes", ""))
                last_solver_outputs.append({
                    "task_id":     task_id,
                    "description": a.get("description", ""),
                    "output":      solver_text,
                    "usage":       sol_usage,
                })
            else:
                print(f"\n[orchestrator] Launching {len(assignments)} parallel solver(s) for round {round_num}")
                # Assign stable task IDs before launching
                for pi, a in enumerate(assignments):
                    if not a.get("task_id"):
                        a["task_id"] = f"t{task_counter + pi}"

                with ThreadPoolExecutor(max_workers=len(assignments)) as ex:
                    futures = {
                        ex.submit(run_solver_task, a["_solver_prompt_full"], a["task_id"], round_num): a
                        for a in assignments
                    }
                    for fut in as_completed(futures):
                        a = futures[fut]
                        task_id = a["task_id"]
                        try:
                            solver_text, sol_usage = fut.result()
                            update_kb_from_solver_report(solver_text, task_id)
                            _store_solver_output(solver_text, sol_usage, task_id, round_num,
                                                 a.get("description", ""))
                            _append_solver_history(task_id, a.get("description", task_id),
                                                   _extract_solver_report(solver_text).get("progress_notes", ""))
                            last_solver_outputs.append({
                                "task_id":     task_id,
                                "description": a.get("description", ""),
                                "output":      solver_text,
                                "usage":       sol_usage,
                            })
                        except Exception as exc:
                            print(f"[orchestrator] Solver task {task_id} error: {exc}")
                            traceback.print_exc()

                task_counter += len(assignments)

            # ── Round atomic-commit ──────────────────────────────────────
            # The advisor_round event is the resume checkpoint: until it's
            # appended, a crash will replay this round.
            memory.record_advisor_round(
                round_num=round_num, status="in_progress",
                budget_remaining_after=budget,
                task_counter_after=task_counter,
                plan=plan, usage=_adv_usage,
            )

        else:
            # while-condition became false: budget exhausted
            print(f"[advisor] Budget exhausted after {round_num} advisor round(s).")
            memory.record_advisor_round(
                round_num=round_num, status="loop_complete",
                budget_remaining_after=budget,
                task_counter_after=task_counter,
                plan=None, usage=None,
            )

    print(f"[orchestrator] Stage 2 complete. {round_num} round(s), "
          f"{len(memory.all_task_outputs())} task output(s) recorded.")

    # Drain background writeups before assembly so Stage 2.9's KB view
    # reflects every completed writeup and Stage 3 can verify them.
    _drain_writeup_futures(label="pre-assembly")

    # ── Stage 2.9: Assembly ──────────────────────────────────────────────────
    # First, scan final_solutions for a verified write-up of the full original
    # problem (if_final_true=true, is_relaxation=false). If one exists, reuse
    # it verbatim as ``assembly_final`` — no fresh advisor or solver call. We
    # still write both a task_outputs row (so resume guards are satisfied) and
    # a final_solutions row (so Stage 3 skips it via has_final_solution).
    #
    # Otherwise, the assembly advisor runs and uses the same reference_task_ids
    # pattern as the regular advisor: it picks which write-ups / partials the
    # assembly solver should read in full, and the harness auto-prepends those
    # outputs verbatim to the solver's prompt.

    assembly_id   = "assembly_final"
    assembly_round = round_num + 1

    if memory.has_task_output(assembly_id):
        print(f"[RESUME] Assembly solver output already exists — skipping.")
    else:
        complete = _find_complete_verified_writeup()
        if complete is not None:
            wu_id    = complete["task_id"]
            wu_final = complete["final_solution"]
            wu_task  = complete["task_output"]

            assembly_text       = wu_final.get("Final_Solution") or wu_task.get("full_text", "")
            # Pull the verifier-canonical claim from final_solutions; fall
            # back to the task_outputs self-declaration only if missing.
            problem_solved_text = (
                wu_final.get("problem_solved")
                or wu_task.get("self_declared_problem_solved", "")
            )
            is_relax = bool(wu_final.get(
                "is_relaxation",
                wu_task.get("self_declared_is_relaxation", False),
            ))

            print(f"\n{'='*80}\n[Stage 2.9] Reusing verified write-up {wu_id} as "
                  f"{assembly_id} (no fresh assembly call)\n{'='*80}")

            memory.add_task_output(
                task_id                       = assembly_id,
                kind                          = "assembly",
                round_num                     = assembly_round,
                description                   = f"reused from {wu_id} (verified, non-relaxation)",
                full_text                     = assembly_text,
                solution                      = assembly_text,
                self_declared_problem_solved  = problem_solved_text,
                self_declared_is_relaxation   = is_relax,
                usage                         = {},
            )
            memory.add_final_solution(
                task_id        = assembly_id,
                if_final_true  = "true",
                final_solution = assembly_text,
                problem_solved = problem_solved_text,
                is_relaxation  = is_relax,
            )
            _update_kb_verification(
                statement      = problem_solved_text,
                verified       = True,
                solution_text  = assembly_text,
                solution_ref   = f"final_solutions.jsonl task_id={assembly_id} (reused from {wu_id})",
                problem_solved = problem_solved_text,
                is_relaxation  = is_relax,
            )
            print(f"[Stage 2.9] {assembly_id} marked verified — Stage 3 will skip it.")
        else:
            print(f"\n{'='*80}\n[Stage 2.9] Assembly — no complete verified write-up; "
                  f"running assembly advisor\n{'='*80}")

            decision = _run_assembly_advisor(round_label=assembly_round)

            if decision["action"] == "solve":
                base_prompt = decision["solver_prompt"]
                ref_ids     = decision["reference_task_ids"]
                solver_prompt = _prepend_referenced_outputs(
                    base_prompt, ref_ids,
                    strict=True,
                    log_prefix=f"[assembly {assembly_id}]",
                )
                description = (
                    f"final assembly (refs={ref_ids})" if ref_ids
                    else "final assembly from KB"
                )
            else:
                solver_prompt = ASSEMBLY_SOLVER_FALLBACK_PROMPT_TEMPLATE.format(
                    problem=problem,
                    kb_section=memory.kb_for_advisor(),
                )
                description = "final assembly (fallback prompt)"

            assembly_text, assembly_usage = run_solver_task(
                solver_prompt, assembly_id, assembly_round,
            )
            update_kb_from_solver_report(assembly_text, assembly_id)
            _store_solver_output(
                assembly_text, assembly_usage, assembly_id,
                assembly_round, description,
                kind="assembly",
            )


# ─── Stage 3: Verify + Refine ─────────────────────────────────────────────────

VERIFY_PROMPT_TEMPLATE = """\
I need you to check the following solution very carefully and let me know if you find any gaps, classifying them as either major or minor.
You should also carefully check that all bibliographic references are valid.

# Original Problem
{original_problem}

# Claim Being Verified
{claim}

# Solution
{solution}

# Instructions
Verify the solution against the **Claim Being Verified**, not the Original Problem. The Claim may equal the Original Problem verbatim (a full solution) or be a deliberately weakened, special-case, or partial version (a relaxation). Either is acceptable — judge the solution on the Claim it actually makes.

A **major gap** is a critical error in the argument for the Claim Being Verified that cannot easily be fixed; if there is a major gap, the solver should likely try another approach.

A **minor gap** is a fixable mistake, omission, unclear justification, typo-level mathematical issue, or bibliographic/reference problem that can likely be repaired without changing the main strategy of the solution.

Do not penalise the solution for failing to establish more than the Claim asks for. Classify bibliographic/reference problems as minor if they are easy to correct, and major if the proof relies essentially on an invalid or unavailable reference and the issue cannot easily be repaired.

# Mandatory proof-obligation and quantitative audits

In addition to checking the solution for ordinary mathematical errors, audit the dependency structure of the proof.

For every nontrivial statement used to prove the Claim Being Verified — including lemmas, propositions, estimates, reductions, identities, cited theorems, deferred claims, and "standard" facts — determine whether it is:

1. proved in the solution;
2. assumed without proof;
3. cited from a valid source whose hypotheses match the current setting;
4. deferred to a later result that actually proves it;
5. proved only under stronger or different hypotheses;
6. essentially equivalent to the Claim Being Verified;
7. insufficient to imply the step for which it is used.

If the proof relies on a statement that is unproved, assumed, not discharged, circular/equivalent to the target, or valid only under unavailable hypotheses, classify this as a major gap unless it is genuinely peripheral and easily repairable.

If the Claim Being Verified contains quantitative content — such as explicit constants, rates, error bounds, asymptotic notation, thresholds, sample complexity, probability estimates, convergence rates, dimension dependence, or parameter regimes — perform a quantitative-dependence audit:

- Extract the exact quantitative conclusion claimed.
- List all relevant parameters.
- Identify the strongest quantitative estimates actually proved.
- Check that the final claimed dependence follows algebraically from those estimates.
- Do not allow O(·), Ω(·), Θ(·), ≲, ≳, "constant", "sufficiently large", "sufficiently small", "absorbing constants", or "standard estimates" to hide dependence on parameters relevant to the Claim.
- Check difficult parameter regimes, such as large dimension, small error tolerance, parameters near boundary values, denominators close to zero, or cases near the claimed threshold.
- If the proof proves a weaker/different quantitative statement, or only assumes the key estimate with the desired dependence, list this as a major gap.

When writing <PROBLEM_SOLVED>, do not merely restate the Claim Being Verified. State only what the solution actually establishes after accounting for unproved assumptions, extra hypotheses, missing estimates, and weaker quantitative dependencies. If the proof only establishes the result conditionally on an unproved lemma or estimate, reflect that condition and also list the unproved obligation as a gap.

You must also emit:

- <PROBLEM_SOLVED>: a fully self-contained statement of the result the solution actually proves, drawn from the solution text itself (not copied from the framing above). Define every symbol, quantifier, hypothesis, and notational convention inline. A reader who has never seen the Original Problem, the Claim Being Verified, the solution, or this conversation must be able to read <PROBLEM_SOLVED> alone and understand the precise claim that has been established. Do NOT write phrases like "the problem above", "the claim", "as defined earlier", "the given graph", or otherwise refer to anything outside the tag's contents. If the solution establishes the Original Problem exactly, copy the Original Problem verbatim into this tag.
- <IS_RELAXATION>: 'true' if <PROBLEM_SOLVED> is a relaxation, weakening, special case, or partial version of the Original Problem; 'false' if and only if <PROBLEM_SOLVED> matches the Original Problem exactly (same hypotheses, same quantifiers, same conclusion). Decide this by comparing <PROBLEM_SOLVED> against the Original Problem above.

If the solution has no major or minor gaps, set <CORRECT>true</CORRECT> and leave <MAJOR_GAPS></MAJOR_GAPS> and <MINOR_GAPS></MINOR_GAPS> empty.
If there are any major or minor gaps, set <CORRECT>false</CORRECT> and list them concisely in the appropriate tag.

<CORRECT>one of 'true' or 'false'</CORRECT>
<MAJOR_GAPS>
- Brief explanation of major_gap_1
- ...
</MAJOR_GAPS>
<MINOR_GAPS>
- Brief explanation of minor_gap_1
- ...
</MINOR_GAPS>
<PROBLEM_SOLVED>fully self-contained statement of the claim the solution actually proves — see instructions above</PROBLEM_SOLVED>
<IS_RELAXATION>one of 'true' or 'false'</IS_RELAXATION>
""".strip()


def Run_Verify(solution, stage_label, *, original_problem, claim):
    # ── V4: citation audit + verification in one web-search-enabled call ──────
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from verifier_v2.scorer_v4 import run_verify_v4

    # Inject the harness's own run_response so every v4 verification call
    # goes through the same retry / cost-logging / queued-timeout machinery
    # as the rest of the pipeline. Pass `stage_label` as the stage_name so
    # `[stage_label] in_progress after Ns` log lines distinguish concurrent
    # verifications (vs. all of them sharing the generic "[run_verify_v4]"
    # prefix that call_api used).
    correct, major_gaps, minor_gaps, citation_audit, _flagged, _salvageable, patches_text, final_verdict, verdict_class, output_text = run_verify_v4(
        solution=solution,
        problem=original_problem,
        claim=claim,
        reasoning=VERIFY_REASONING,
        run_response_fn=run_response,
        stage_name=stage_label,
        verbosity=VERIFY_VERBOSITY,
        max_output_tokens=VERIFY_MAX_TOKENS,
    )

    correct_text          = "true" if correct else "false"
    major_gaps_text       = "\n".join(f"- {g}" for g in major_gaps) if major_gaps else ""
    minor_gaps_text_clean = "\n".join(f"- {g}" for g in minor_gaps) if minor_gaps else ""
    minor_gaps_text       = minor_gaps_text_clean  # will have patches appended below

    # Append patches to minor_gaps_text so the refine prompt gets specific fix instructions
    if patches_text and patches_text.strip():
        minor_gaps_text = (
            (minor_gaps_text + "\n\n" if minor_gaps_text else "") +
            "PATCHES REQUIRED FOR CORRECTNESS:\n" + patches_text
        )

    problem_solved_m = re.search(r"<PROBLEM_SOLVED>(.*?)</PROBLEM_SOLVED>", output_text, re.DOTALL)
    is_relaxation_m  = re.search(r"<IS_RELAXATION>(.*?)</IS_RELAXATION>",  output_text, re.DOTALL)
    problem_solved_text = problem_solved_m.group(1).strip() if problem_solved_m else claim
    is_relaxation_text  = is_relaxation_m.group(1).strip()  if is_relaxation_m  else "false"
    is_relaxation_bool  = is_relaxation_text.lower() == "true"

    print(f"[V4] VERDICT: {verdict_class}  (correct={correct_text})  MAJOR: {len(major_gaps)}  MINOR: {len(minor_gaps)}")
    print(f"[V4] FINAL_VERDICT text: {final_verdict[:120]}")
    print(f"[V4] CITATION_AUDIT:\n{citation_audit[:400]}")

    usage = {"model": "gpt-5.5-pro-v4", "cost_usd": 0.0, "input_tokens": 0,
             "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0,
             "elapsed_seconds": 0, "stage": stage_label, "response_id": "v4"}

    memory.log_verifier_record({
        "timestamp":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stage_label":       stage_label,
        "original_problem":  original_problem,
        "claim_verified":    claim,
        "solution_verified": solution,
        "verifier_prompt":   "[verifier_v4 combined citation+verification]",
        "verifier_response": output_text,
        "citation_audit":    citation_audit,
        "parsed": {
            "correct":        correct_text,
            "verdict_class":  verdict_class,
            "final_verdict":  final_verdict,
            "major_gaps":     major_gaps_text,
            "minor_gaps":     minor_gaps_text,
            "problem_solved": problem_solved_text,
            "is_relaxation":  is_relaxation_bool,
        },
        "usage": usage,
    })

    return correct_text, major_gaps_text, minor_gaps_text, usage, output_text, problem_solved_text, is_relaxation_bool, verdict_class


REFINE_PROMPT_TEMPLATE = """\
You previously submitted a solution which you will find below. Unfortunately, a referee found some issues with your solution that you will need to address carefully and rigorously.
Use the prior solution and the critique below as inputs to your reasoning, but the artifact you produce must be a brand-new, self-contained solution that stands on its own.

# Original Problem
{original_problem}

# Claim You Are Establishing
{claim}

Your refined solution must rigorously establish the **Claim You Are Establishing** above. The Claim may equal the Original Problem verbatim (in which case prove the original) or be a deliberately weakened / partial version (in which case prove that weaker claim — do NOT silently aim at the Original Problem). State the exact claim being proved up front and then prove it.

# Prior solution (for your reference only — do not include or quote it in your output)
{solution}

# Critique (for your reference only — do not include or quote it in your output)
{gaps}

# Output requirements (read carefully — your output will be evaluated as a standalone document)
Write a complete, self-contained solution to the Claim You Are Establishing. The reader will see only your output — they will NOT see the prior solution, the critique, or any of this conversation.

- Do NOT mention the referee, the critique, the prior solution, this revision process, or any "previous version".
- Do NOT use phrases like "as the referee noted", "fixing the gap", "the issue raised was", "in the previous attempt", "as before", "as corrected", or similar.
- Do NOT reference fixes, corrections, or changes relative to anything else — just present the argument as if writing it for the first time.
- State all definitions, hypotheses, and intermediate claims explicitly. Every step must be justified within the document itself.
- If the Claim You Are Establishing is a relaxation or partial result rather than the Original Problem, state the exact claim you prove up front and then prove it.
- Output ONLY the standalone solution. No preamble, no meta-commentary, no change log.
""".strip()


# ─── Minor polish (one-shot, EXPOSITION ONLY items only) ─────────────────────
#
# Fired when verify says verdict=Correct but listed minor gaps tagged
# "EXPOSITION ONLY". One light pass that addresses ONLY the cosmetic items
# without disturbing the proof's structure or method. Then re-verify;
# accept if still Correct, otherwise roll back to the pre-polish proof.

MINOR_REFINE_PROMPT_TEMPLATE = """\
You previously submitted a proof which a careful referee has ACCEPTED as essentially correct. The referee did note a few minor *expository* issues — things like notation, organization, missing citations for textbook facts — but emphasized these do NOT affect the rigor of the proof. Your task is a light polish to address those expository issues only.

# Original Problem
{original_problem}

# Claim Established (do NOT change this)
{claim}

# Current Accepted Proof
{solution}

# Expository Issues to Address (EXPOSITION ONLY items only)
{exposition_gaps}

# Polish Rules (read carefully)
- PRESERVE the proof's overall structure, the sequence of steps, the choice of method, the lemmas used, and every mathematical argument. Do NOT rewrite proofs of lemmas, do NOT replace estimates, do NOT change the strategy.
- Address the listed expository issues by clarifying notation, fixing minor presentation, or adding missing citations for textbook results. Light touch only.
- Do NOT introduce new lemmas, new constants, or new arguments. Do NOT remove existing arguments unless they are pure redundancy.
- Do NOT mention the referee, the critique, "the previous version", or this revision process. The output is read by someone who has never seen the unpolished version.
- If a listed issue would require non-trivial mathematical work to fully address (rather than cosmetic clarification), leave it as-is — DO NOT invent a fix.

# Output
Output ONLY the polished proof, self-contained. No preamble, no meta-commentary, no change log.
""".strip()


def _extract_exposition_only_minor_gaps(minor_gaps_text):
    """Return the subset of minor-gap lines tagged 'EXPOSITION ONLY' as a
    newline-joined string. Returns '' if none — caller treats '' as a signal
    to skip the polish step.
    """
    if not minor_gaps_text:
        return ""
    keep = []
    for line in minor_gaps_text.splitlines():
        if "EXPOSITION ONLY" in line.upper():
            keep.append(line)
    return "\n".join(keep)


def _maybe_minor_polish(now_solution, minor_gaps_text, problem_solved, is_relaxation,
                        *, task_id, stage_tag, already_done):
    """One-shot light polish + re-verify, with rollback on regression.

    Triggers iff (a) we haven't polished yet this call, AND (b) ``minor_gaps_text``
    contains at least one line tagged 'EXPOSITION ONLY'. After polish, re-verifies
    with the standard verifier:
      - if verdict_class == 'correct' (with or without leftover minor gaps): keep
        polished text and the verifier's updated problem_solved / is_relaxation
        / minor_gaps_text.
      - otherwise: roll back to the original solution / metadata.

    Returns (solution, problem_solved, is_relaxation, minor_gaps_text, done_flag).
    ``done_flag`` is True after one attempt (success OR rollback), so the caller
    sets ``_minor_polish_done = True`` regardless of outcome.
    """
    if already_done:
        return (now_solution, problem_solved, is_relaxation, minor_gaps_text, True)

    exposition_gaps = _extract_exposition_only_minor_gaps(minor_gaps_text)
    if not exposition_gaps:
        return (now_solution, problem_solved, is_relaxation, minor_gaps_text, True)

    print(f"[verify_{task_id}] verdict=Correct with EXPOSITION ONLY minor gap(s) — "
          f"running one minor polish ({stage_tag})")

    polish_prompt = MINOR_REFINE_PROMPT_TEMPLATE.format(
        original_problem=problem,
        claim=problem_solved,
        solution=now_solution,
        exposition_gaps=exposition_gaps,
    )
    try:
        polished_text, polish_usage = run_response(
            polish_prompt,
            stage_name=f"minor_polish_{task_id}_{stage_tag}",
            reasoning_effort=REFINE_REASONING,
            verbosity=REFINE_VERBOSITY,
            max_output_tokens=REFINE_MAX_TOKENS,
            web_search=True,
        )
    except Exception as exc:
        print(f"[verify_{task_id}] minor polish call errored: {exc} — rolling back")
        return (now_solution, problem_solved, is_relaxation, minor_gaps_text, True)

    memory.log_conversation({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type":      "minor_polish",
        "task_id":   task_id,
        "stage_tag": stage_tag,
        "prompt":    polish_prompt,
        "response":  polished_text,
        "usage":     polish_usage,
    })

    # Re-verify the polished version.
    (correct_text2, major_gaps_text2, minor_gaps_text2, v_usage2, v_full2,
     ps2, ir2, vc2) = Run_Verify(
        polished_text, f"verify_{task_id}_polish_{stage_tag}",
        original_problem=problem, claim=problem_solved,
    )
    memory.log_verify({
        "task_id": task_id, "round": f"polish_{stage_tag}",
        "correct_text": correct_text2,
        "verdict_class": vc2,
        "major_gaps_text": major_gaps_text2,
        "minor_gaps_text": minor_gaps_text2,
        "problem_solved": ps2, "is_relaxation": ir2,
        "usage": v_usage2,
        "kind": "post_minor_polish",
    })

    if vc2 == "correct":
        print(f"[verify_{task_id}] minor polish accepted (verdict still Correct)")
        return (polished_text, ps2, ir2, minor_gaps_text2, True)

    print(f"[verify_{task_id}] minor polish produced verdict_class={vc2!r} — rolling back to pre-polish proof")
    return (now_solution, problem_solved, is_relaxation, minor_gaps_text, True)


def verify_refine_stage(i, plan):
    sol_entry = memory.get_task_output(i)
    if sol_entry is None:
        raise KeyError(f"verify_refine_stage: no task output recorded for {i!r}")
    now_solution   = sol_entry["solution"]
    # Pick the claim presented to the verifier based on the advisor's pre-flight
    # intent for this writeup:
    #   - solves_original_problem=True  → verify against the canonical original
    #     (verbatim). This prevents any drift in the writeup's own restatement
    #     from reframing the verification target as a weaker problem.
    #   - solves_original_problem=False (or non-writeup outputs reaching this
    #     stage) → verify against the writeup's stated claim, so partial
    #     progress is judged on what it actually claims to prove.
    # The verifier always sees the canonical Original Problem too, so it can
    # compare and emit a correct <IS_RELAXATION> regardless of which framing
    # was picked. After round 0 the verifier's own <PROBLEM_SOLVED> becomes
    # the claim for the next round — it describes the turn that actually
    # survived verification.
    advisor_solves_original = bool(sol_entry.get("advisor_solves_original_problem", False))
    if advisor_solves_original:
        problem_solved = problem
    else:
        problem_solved = sol_entry["self_declared_problem_solved"]
    is_relaxation  = sol_entry["self_declared_is_relaxation"]
    if_final_true  = "None"
    _minor_polish_done = False   # one-shot EXPOSITION ONLY polish per call

    memory.log_refine({"task_id": i, "round": 0, "refined_solution": now_solution})

    for o in range(VERIFY_ROUNDS):
        print(f"\n{'#'*80}\n[verify_{i}] Round {o}\n{'#'*80}")

        v_prompt = VERIFY_PROMPT_TEMPLATE.format(
            original_problem=problem, claim=problem_solved, solution=now_solution,
        )
        (correct_text, major_gaps_text, minor_gaps_text, v_usage, v_full,
         verifier_problem_solved, verifier_is_relaxation, verdict_class) = Run_Verify(
            now_solution, f"verify_{i}_round_{o}",
            original_problem=problem, claim=problem_solved,
        )
        # Pin metadata to the verifier's report on the turn it actually judged.
        problem_solved = verifier_problem_solved
        is_relaxation  = verifier_is_relaxation
        memory.log_verify({
            "task_id": i, "round": o,
            "correct_text": correct_text,
            "verdict_class": verdict_class,
            "major_gaps_text": major_gaps_text, "minor_gaps_text": minor_gaps_text,
            "problem_solved": problem_solved, "is_relaxation": is_relaxation,
            "usage": v_usage,
        })
        memory.log_conversation({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type":      "verify",
            "task_id":   i,
            "round":     o,
            "correct":   correct_text,
            "prompt":    v_prompt,
            "response":  v_full,
            "usage":     v_usage,
        })

        if verdict_class not in {"correct", "correct_after_minor", "incorrect"}:
            raise ValueError(f"Unexpected verdict_class: {verdict_class!r}")

        if verdict_class == "correct":
            # Verifier accepts the proof as-is (no gaps, or only cosmetic ones).
            # Before accepting, optionally do ONE light polish for EXPOSITION
            # ONLY minor gaps and re-verify; roll back if regression.
            (now_solution, problem_solved, is_relaxation,
             minor_gaps_text, _minor_polish_done) = _maybe_minor_polish(
                now_solution, minor_gaps_text, problem_solved, is_relaxation,
                task_id=i, stage_tag=f"r{o}",
                already_done=_minor_polish_done,
            )
            if_final_true = "true"
            # ANNOTATE_TEX: generate annotated .tex when solution is accepted
            if ANNOTATE_TEX:
                try:
                    import sys as _sys, os as _os
                    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
                    from verifier_v2.annotator import generate_verified_tex
                    annotated = generate_verified_tex(
                        original_tex=now_solution,
                        precheck_issues=[],
                        score=10,
                        major_gaps=[],
                        minor_gaps=[g for g in minor_gaps_text.splitlines() if g.strip().startswith("-")],
                    )
                    ann_path = OUTPUT_DIR / f"annotated_{i}.tex"
                    ann_path.write_text(annotated, encoding="utf-8")
                    print(f"[annotate] wrote {ann_path}")
                except Exception as ann_err:
                    print(f"[annotate] error: {ann_err}")
            break

        # verdict_class in {"correct_after_minor", "incorrect"}: run refine.
        # Major and minor gaps both go through the same refine loop — the
        # refiner receives the verifier's full critique (major first, minor
        # second; patches are already concatenated into minor_gaps_text by
        # Run_Verify). The refine loop is bounded by VERIFY_ROUNDS; if the
        # gaps survive all rounds, the final pass below records the result
        # as if_final_true="false" (or "nearly true" if only minor gaps
        # remain).
        gap_sections = []
        if major_gaps_text.strip():
            gap_sections.append("MAJOR GAPS (fundamental issues — these likely "
                                "require substantial rework to close):\n"
                                + major_gaps_text)
        if minor_gaps_text.strip():
            gap_sections.append("MINOR GAPS / PATCHES (smaller issues, often "
                                "with concrete fixes):\n" + minor_gaps_text)
        gaps_for_refine = ("\n\n".join(gap_sections)
                           if gap_sections
                           else "(verifier flagged the proof but listed no specific gaps)")
        if verdict_class == "incorrect":
            print(f"[verify_{i}] verdict=Incorrect → entering refine with "
                  f"{len(major_gaps_text.splitlines())} major-gap line(s) + "
                  f"{len(minor_gaps_text.splitlines())} minor-gap line(s)")
        refine_prompt = REFINE_PROMPT_TEMPLATE.format(
            original_problem=problem, claim=problem_solved,
            solution=now_solution, gaps=gaps_for_refine,
        )
        output_text, r_usage = run_response(
            refine_prompt,
            stage_name=f"refine_{i}_round_{o}",
            reasoning_effort=REFINE_REASONING,
            verbosity=REFINE_VERBOSITY,
            max_output_tokens=REFINE_MAX_TOKENS,
            web_search=True,
        )
        print(f"{'#'*80}\n{output_text}")
        now_solution = output_text
        memory.log_refine({
            "task_id": i, "round": o + 1, "refined_solution": now_solution, "usage": r_usage,
        })
        memory.log_conversation({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type":      "refine",
            "task_id":   i,
            "round":     o,
            "prompt":    refine_prompt,
            "response":  output_text,
            "usage":     r_usage,
        })

    Final_Solution = now_solution

    if if_final_true == "None":
        v_prompt = VERIFY_PROMPT_TEMPLATE.format(
            original_problem=problem, claim=problem_solved, solution=Final_Solution,
        )
        (correct_text, major_gaps_text, minor_gaps_text, v_usage, v_full,
         verifier_problem_solved, verifier_is_relaxation, verdict_class) = Run_Verify(
            Final_Solution, f"verify_{i}_final",
            original_problem=problem, claim=problem_solved,
        )
        problem_solved = verifier_problem_solved
        is_relaxation  = verifier_is_relaxation
        memory.log_verify({
            "task_id": i, "round": VERIFY_ROUNDS,
            "correct_text": correct_text,
            "verdict_class": verdict_class,
            "major_gaps_text": major_gaps_text, "minor_gaps_text": minor_gaps_text,
            "problem_solved": problem_solved, "is_relaxation": is_relaxation,
            "usage": v_usage,
        })
        memory.log_conversation({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type":      "verify",
            "task_id":   i,
            "round":     VERIFY_ROUNDS,
            "is_final":  True,
            "correct":   correct_text,
            "prompt":    v_prompt,
            "response":  v_full,
            "usage":     v_usage,
        })
        if verdict_class == "correct":
            # Same one-shot EXPOSITION ONLY polish path as the in-loop branch.
            # In practice this fires here ONLY when the loop never hit Correct
            # (so _minor_polish_done is still False); if the loop already
            # polished and broke out, control would not reach this final pass.
            (Final_Solution, problem_solved, is_relaxation,
             minor_gaps_text, _minor_polish_done) = _maybe_minor_polish(
                Final_Solution, minor_gaps_text, problem_solved, is_relaxation,
                task_id=i, stage_tag="final",
                already_done=_minor_polish_done,
            )
            if_final_true = "true"
            # ANNOTATE_TEX: generate annotated .tex when final solution is accepted
            if ANNOTATE_TEX:
                try:
                    import sys as _sys, os as _os
                    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
                    from verifier_v2.annotator import generate_verified_tex
                    annotated = generate_verified_tex(
                        original_tex=Final_Solution,
                        precheck_issues=[],
                        score=10,
                        major_gaps=[],
                        minor_gaps=[g for g in minor_gaps_text.splitlines() if g.strip().startswith("-")],
                    )
                    ann_path = OUTPUT_DIR / f"annotated_{i}.tex"
                    ann_path.write_text(annotated, encoding="utf-8")
                    print(f"[annotate] wrote {ann_path}")
                except Exception as ann_err:
                    print(f"[annotate] error: {ann_err}")
        elif verdict_class == "incorrect":
            # Refine budget exhausted and major gaps still remain. Record as
            # if_final_true="false" and let downstream (Stage 3.5 finalize)
            # decide what to do with the partial artifact.
            if_final_true = "false"
            print(f"[verify_{i}] Final pass: verdict=Incorrect after {VERIFY_ROUNDS} "
                  f"refine round(s) — recording if_final_true='false'")
        elif verdict_class == "correct_after_minor":
            # Loop ran out of refine budget but verifier still reports only
            # minor gaps left → mark as "nearly true" so finalize Track A can
            # prefer this over fully unverified attempts (see find_full_proof_seed).
            if_final_true = "nearly true"
            print(f"[verify_{i}] Final pass: verdict=Correct after minor fixes — if_final_true='nearly true'")
        else:
            raise ValueError(f"Unexpected verdict_class: {verdict_class!r}")

    return memory.add_final_solution(
        task_id        = i,
        if_final_true  = if_final_true,
        final_solution = Final_Solution,
        problem_solved = problem_solved,
        is_relaxation  = is_relaxation,
    )


# ─── Stage 4: Benchmark documentation ────────────────────────────────────────

BENCHMARK_STRATEGY_PROMPT = """\
The following solution to a mathematical problem has been verified as correct (or as a valid partial result/relaxation).
Write a brief description (3-5 sentences) of the core strategy used, suitable as a one-paragraph summary for a benchmark dataset.

# Problem
{problem}

# Solution
{solution}

Output only the strategy description paragraph, no preamble.
""".strip()


def write_benchmark(i, plan, final_entry):
    """Build a benchmark entry dict for a verified solution."""
    solution_text  = final_entry["Final_Solution"]
    problem_solved = final_entry["problem_solved"]
    is_relaxation  = final_entry.get("is_relaxation", False)

    print(f"\n{'='*80}\n[benchmark] Building benchmark entry for solution_{i}\n{'='*80}")

    strategy_prompt = BENCHMARK_STRATEGY_PROMPT.format(problem=problem_solved, solution=solution_text)
    strategy_text, strat_usage = run_response(
        strategy_prompt,
        stage_name=f"benchmark_strategy_{i}",
        reasoning_effort=normalize_effort("medium"),
        verbosity="medium",
        max_output_tokens=2_000,
        web_search=False,
        model=BENCHMARK_MODEL,
    )
    print(f"[benchmark] strategy summary:\n{strategy_text}")

    return {
        "original_problem_file": str(PROBLEM_PATH),
        "original_problem":      problem,
        "problem_solved":        problem_solved,
        "is_relaxation":         is_relaxation,
        "solution_idx":          i,
        "plan_used": {
            "rank":           plan.get("rank"),
            "title":          plan.get("title"),
            "plan":           plan.get("plan"),
            "key_references": plan.get("key_references", []),
        },
        "strategy_summary":   strategy_text.strip(),
        "solution":           solution_text,
        "verified":           final_entry["if_final_true"] == "true",
        "timestamp":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─── Stage 5: LaTeX typesetting ──────────────────────────────────────────────

TYPESET_PROMPT_TEMPLATE = """\
You are a mathematical typesetter. Convert the solution below into a clean, self-contained LaTeX document.

# Document Title
{title}

# Original Problem
{original_problem}
{claim_block}
# Does the Solution Solve the Original Problem in Full?
{solves_status}

# Solution
{solution}

# Requirements
- Use the article class: \\documentclass{{amsart}}
- Include standard AMS packages: amsmath, amssymb, amsthm
- Define theorem/lemma/proof environments as needed
- The document must compile with pdflatex without any external dependencies
- Preserve all mathematical content exactly — do not add, remove, or restate any claims
- Use proper LaTeX conventions: \\begin{{proof}} ... \\end{{proof}}, \\begin{{theorem}} ... etc.
- Set \\title to the exact string given under **Document Title** above (it has already been LaTeX-escaped — use it verbatim, do NOT re-escape, do NOT substitute the problem statement). Leave \\author{{}} blank, then call \\maketitle.
- Render the **Original Problem** as the headline theorem the solution targets.
- Immediately after the headline theorem statement and BEFORE its proof, include exactly ONE short natural-English sentence (a single sentence, one or two clauses) that plainly tells the reader whether the solution proves the original problem in full. Base it on the value under **Does the Solution Solve the Original Problem in Full?**. Do NOT mention any internal flag name (e.g. "is_relaxation") verbatim — phrase it in normal mathematical prose. When the answer is "No", state in that sentence that the solution instead establishes a relaxation / partial result.
- If a **Claim Established** block is present below, the solution does NOT prove the original \
problem verbatim — it proves the relaxation / paraphrase shown in that block. Render the \
established claim prominently as its own theorem (or as a remark immediately after the \
original-problem statement) so the reader can clearly see what was actually proved versus \
what was originally asked. Do not silently merge the two.
- If no **Claim Established** block is shown, the solution proves the original problem as stated.
- Output ONLY the complete .tex file content, starting with \\documentclass and ending with \\end{{document}}
- Do not wrap it in a markdown code block — output raw LaTeX only
""".strip()


_LATEX_TITLE_ESCAPES = {
    "\\": r"\textbackslash{}",
    "_":  r"\_",
    "%":  r"\%",
    "$":  r"\$",
    "&":  r"\&",
    "#":  r"\#",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\textasciicircum{}",
}


def _latex_escape_title(text):
    """Escape LaTeX special characters so the string is safe inside \\title{...}."""
    return "".join(_LATEX_TITLE_ESCAPES.get(c, c) for c in (text or ""))


def _build_claim_block(original_problem, problem_solved):
    """Render the optional 'Claim Established' section for the typeset prompt.

    Returns "" when the claim equals the original problem (after whitespace
    normalisation), so the typesetter doesn't see two near-duplicate blocks.
    """
    def _norm(s):
        return " ".join((s or "").split())
    if not problem_solved or _norm(problem_solved) == _norm(original_problem):
        return "\n"
    return (
        "\n# Claim Established (what the solution actually proves — may be a "
        "relaxation or paraphrase of the original)\n"
        f"{problem_solved}\n"
    )


def run_typeset(solution_text, problem_solved, original_problem, title, is_relaxation):
    """Stage 5: typeset a verified solution to a self-contained LaTeX document.

    ``title`` is used verbatim (after LaTeX-escaping) as the document title — we
    pass the problem-file stem so the title reflects which problem this is, not
    the problem statement itself. ``is_relaxation`` drives the one-line
    "solves the original?" sentence that the typesetter inserts right after the
    headline theorem; it does not mention the flag name in prose.

    Both the original problem (verbatim from PROBLEM_PATH) and the agent-reported
    ``problem_solved`` are surfaced. When ``problem_solved`` differs from the
    original, the typesetter renders both so the reader can see the relaxation
    or paraphrase explicitly; when they match, the second block is suppressed.
    """
    print(f"\n{'='*80}\n[Stage 5] LaTeX typesetting\n{'='*80}")

    prompt = TYPESET_PROMPT_TEMPLATE.format(
        title=_latex_escape_title(title),
        original_problem=original_problem,
        claim_block=_build_claim_block(original_problem, problem_solved),
        solves_status=("No" if is_relaxation else "Yes"),
        solution=solution_text,
    )
    latex_text, usage = run_response(
        prompt,
        stage_name="typeset",
        reasoning_effort=None,
        verbosity="medium",
        max_output_tokens=16_000,
        web_search=False,
        model=TYPESET_MODEL,
    )
    print(f"[typeset] done ({len(latex_text)} chars)")

    # Strip accidental markdown fences if the model added them anyway
    latex_text = re.sub(r"^```(?:latex|tex)?\s*", "", latex_text.strip(), flags=re.IGNORECASE)
    latex_text = re.sub(r"\s*```$", "", latex_text.strip())

    LATEX_FILE.write_text(latex_text, encoding="utf-8")
    print(f"[typeset] saved to {LATEX_FILE.name}")
    _log_usage(usage)
    return latex_text


# ─── Main pipeline ────────────────────────────────────────────────────────────

print(f"\n{'='*80}")
print(f"MODEL:          {MODEL}")
print(f"ADVISOR_BUDGET: {ADVISOR_BUDGET}")
print(f"VERIFY_ROUNDS:  {VERIFY_ROUNDS}")
print(f"{'='*80}\n")


# ── Stage 0: Literature research (search + per-paper deep-read) ──────────────
#
# One web_search-enabled LLM call enumerates papers likely to contain useful
# theorems/lemmas/techniques. Each cited paper's PDF is downloaded, full text
# extracted, then a dedicated reader agent (parallel, no web_search) extracts
# overall summary + theorems/lemmas (with proof sketches) + proof techniques
# + other useful info. Saved per-paper to literature_research.jsonl. The
# output feeds Stage 1 ONLY — it does NOT enter the shared KB. (Stage 1.5
# deep-read still runs separately and DOES inject into KB.)

if LIT_ENABLED:
    try:
        literature_records = run_literature_research(
            problem                 = problem,
            past_notes_section      = _format_past_notes_for_prompt(_load_solver_history()),
            run_response            = run_response,
            output_file             = LITERATURE_FILE,
            cache_dir               = PAPER_CACHE_DIR,
            max_parallel            = LIT_PARALLEL,
            search_reasoning        = LIT_SEARCH_REASONING or "medium",
            search_max_tokens       = LIT_SEARCH_MAX_TOKENS,
            read_reasoning          = LIT_READ_REASONING   or "xhigh",
            read_max_tokens         = LIT_READ_MAX_TOKENS,
        )
    except Exception as exc:
        print(f"[lit_research] failed (non-fatal — continuing without literature): {exc}")
        traceback.print_exc()
        literature_records = []
else:
    print("[lit_research] disabled (LIT_ENABLED=false) — skipping Stage 0")
    literature_records = []


# ── Stage 1: Advisor directions (synthesise Stage 0 literature) ──────────────

directions = run_advisor_directions(literature_records)


# ── Stage 1.5: Literature deep-read (optional, separate module) ──────────────
#
# Pulls full text of the top ≤DEEP_READ_MAX_PAPERS references and extracts up to
# DEEP_READ_LEMMAS_PER_PAPER theorem/lemma statements + proof sketches per paper
# directly into the shared KB as `proven_result_add` events tagged with
# source_plan="literature_<arxiv_id>". Toggle off via DEEP_READ_ENABLED=false.

if DEEP_READ_ENABLED:
    try:
        run_deep_read(
            directions          = directions,
            problem             = problem,
            run_response        = run_response,
            apply_kb_updates    = _apply_advisor_kb_updates,
            output_file         = IMPORTED_PAPERS_FILE,
            cache_dir           = PAPER_CACHE_DIR,
            n_papers            = DEEP_READ_MAX_PAPERS,
            n_lemmas_per_paper  = DEEP_READ_LEMMAS_PER_PAPER,
            triage_reasoning    = DEEP_READ_TRIAGE_REASONING or "medium",
            triage_max_tokens   = DEEP_READ_TRIAGE_MAX_TOKENS,
            extract_reasoning   = DEEP_READ_EXTRACT_REASONING or "xhigh",
            extract_max_tokens  = DEEP_READ_EXTRACT_MAX_TOKENS,
            max_parallel        = DEEP_READ_PARALLEL,
            max_paper_chars     = DEEP_READ_PAPER_MAX_CHARS,
        )
    except Exception as exc:
        print(f"[deep_read] failed (non-fatal — continuing without imported lemmas): {exc}")
        traceback.print_exc()
else:
    print("[deep_read] disabled (DEEP_READ_ENABLED=false) — skipping Stage 1.5")


# ── Stage 2 + 2.9: Orchestrated Solve + Assembly ─────────────────────────────
#
# State for both stages lives in the GlobalMemory instance. The replay at
# memory construction has already loaded any prior task outputs and final
# solutions; nothing to hydrate here.

# Skip Stage 2 + 2.9 if the loop is recorded as complete AND the assembly
# task output is on disk.
_resume = memory.stage2_resume_state(ADVISOR_BUDGET)
if _resume["loop_complete"] and memory.has_task_output("assembly_final"):
    print("[pipeline] Stage 2 + 2.9 already done, skipping to Stage 3")
else:
    orchestrated_solve_loop_v2(directions)


# ── Stage 3: Verify + Refine (assembly + write-ups) ─────────────────────────
#
# Unified verification: run verify_refine_stage on every task output that has
# not yet been verified (assembly_final and any writeup_* entries produced
# during Stage 2).

print(f"\n{'='*80}\n[Stage 3] Verify + Refine\n{'='*80}")

_verify_targets = [
    tid for tid in memory.all_task_outputs()
    if not memory.has_final_solution(tid)
    and (tid == "assembly_final" or tid.startswith("writeup_"))
]

if not _verify_targets:
    print("[Stage 3] All targets already verified — nothing to do.")
else:
    for sol_idx in _verify_targets:
        try:
            print(f"\n[Stage 3] Verifying {sol_idx}")
            verify_refine_stage(sol_idx, {"title": str(sol_idx)})
            final_e = memory.get_final_solution(sol_idx)
            if final_e:
                _update_kb_verification(
                    statement      = final_e["problem_solved"],
                    verified       = _is_kb_verified(final_e["if_final_true"]),
                    solution_text  = final_e["Final_Solution"],
                    solution_ref   = f"final_solutions.jsonl task_id={sol_idx}",
                    problem_solved = final_e.get("problem_solved"),
                    is_relaxation  = final_e.get("is_relaxation"),
                )
        except Exception as exc:
            print(f"[Stage 3] verify_refine error for {sol_idx}: {exc}")
            traceback.print_exc()


# ── Stage 3.5: Finalize (optional, separate module) ──────────────────────────
#
# Two-track final-output stage. When enabled, replaces legacy Stage 5 typeset.
#   Track A: a non-relaxation proof attempt exists → polish + typeset.
#            permission to relax quantitative bounds slightly to close gaps.
#   Track B: no non-relaxation candidate exists. Produce an honest research
#            progress report instead of a claimed proof.

_finalize_track               = None
_finalize_polished_text       = None
_finalize_latex_text          = None
_finalize_seed_problem_solved = None
_finalize_seed_priority       = None

if FINALIZE_ENABLED and not LATEX_FILE.exists():
    try:
        seed_entry, _finalize_seed_priority = find_full_proof_seed(memory)

        if seed_entry is not None:
            _finalize_track = "A"
            seed_text = seed_entry.get("solution") or seed_entry.get("full_text") or ""
            _finalize_seed_problem_solved = seed_entry.get("problem_solved") or problem
            seed_tid = seed_entry.get("task_id", "")
            print(f"[finalize] Track A: seed_priority={_finalize_seed_priority}, "
                  f"task_id={seed_tid}")
            refs = [
                (label, text)
                for (label, text) in collect_verified_partials(memory)
                if not label.startswith(seed_tid + ":")
            ]
            _finalize_polished_text, _finalize_latex_text, _, _ = (
                finalize_full_proof(
                    problem               = problem,
                    seed_solution         = seed_text,
                    seed_problem_solved   = _finalize_seed_problem_solved,
                    references            = refs,
                    run_response          = run_response,
                    polish_reasoning      = FINALIZE_POLISH_REASONING or "xhigh",
                    polish_max_tokens     = FINALIZE_POLISH_MAX_TOKENS,
                    typeset_reasoning     = FINALIZE_TYPESET_REASONING or "xhigh",
                    typeset_max_tokens    = FINALIZE_TYPESET_MAX_TOKENS,
                    log_conversation      = memory.log_conversation,
                )
            )
        else:
            _finalize_track = "B"
            partials = collect_verified_partials(memory)
            print(f"[finalize] Track B: no non-relaxation seed found "
                  f"(partials={len(partials)})")
            _finalize_polished_text, _finalize_latex_text, _, _ = (
                finalize_progress_report(
                    problem            = problem,
                    verified_partials  = partials,
                    failed_attempts    = memory.all_failed_attempts(),
                    bottlenecks        = memory.all_bottlenecks(),
                    strategic_notes    = memory.all_advisor_notes(),
                    run_response       = run_response,
                    report_reasoning   = FINALIZE_POLISH_REASONING or "xhigh",
                    report_max_tokens  = FINALIZE_POLISH_MAX_TOKENS,
                    typeset_reasoning  = FINALIZE_TYPESET_REASONING or "xhigh",
                    typeset_max_tokens = FINALIZE_TYPESET_MAX_TOKENS,
                    log_conversation   = memory.log_conversation,
                )
            )

        if _finalize_latex_text:
            cleaned = re.sub(r"^```(?:latex|tex)?\s*", "",
                             _finalize_latex_text.strip(), flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned.strip())
            LATEX_FILE.write_text(cleaned, encoding="utf-8")
            print(f"[finalize] saved to {LATEX_FILE.name} (track={_finalize_track})")
    except Exception as _exc:
        print(f"[finalize] FAILED (will fall back to legacy Stage 5 below): {_exc}")
        traceback.print_exc()
        _finalize_polished_text = None
        _finalize_latex_text    = None
elif FINALIZE_ENABLED and LATEX_FILE.exists():
    print(f"[finalize] [RESUME] {LATEX_FILE.name} already exists — skipping finalize.")
else:
    print("[finalize] disabled (FINALIZE_ENABLED=false) — using legacy Stage 5 typeset.")


# ── Stage 4: Benchmark documentation ──────────────────────────────────────────

# Identify best verified entry as a baseline. When Track A finalize ran,
# benchmark.json's solution field is overridden with the polished text.
best_entry = None
best_idx   = None
for k, e in memory.all_final_solutions().items():
    if e.get("if_final_true") == "true":
        if best_entry is None or not e.get("is_relaxation", True):
            best_entry = e
            best_idx   = k

if BENCHMARK_FILE.exists():
    print(f"[RESUME] Benchmark already written: {BENCHMARK_FILE.name}")
else:
    bench_source = None
    if _finalize_polished_text and _finalize_track == "A":
        # Use finalize's polished proof as the canonical solution text.
        bench_source = dict(best_entry) if best_entry else {
            "if_final_true":  "true",
            "is_relaxation":  False,
            "problem_solved": _finalize_seed_problem_solved or problem,
        }
        bench_source["Final_Solution"] = _finalize_polished_text
        bench_idx = best_idx or "finalize_track_A"
    elif best_entry:
        bench_source = best_entry
        bench_idx = best_idx
    if bench_source:
        benchmark_entries = [write_benchmark(bench_idx, {"title": str(bench_idx)}, bench_source)]
        with open(BENCHMARK_FILE, "w", encoding="utf-8") as f:
            json.dump(benchmark_entries, f, ensure_ascii=False, indent=2)
        print(f"[benchmark] saved 1 entry to {BENCHMARK_FILE.name}")
    else:
        print("[benchmark] No verified solution found — benchmark.json not written.")


# ── Stage 5: LaTeX typesetting (legacy fallback) ─────────────────────────────
#
# Skipped when finalize already wrote LATEX_FILE. Kept for runs with
# FINALIZE_ENABLED=false or finalize-failure recovery.

if LATEX_FILE.exists():
    print(f"[RESUME/finalize] LaTeX already written: {LATEX_FILE.name}")
else:
    if best_entry:
        run_typeset(
            best_entry["Final_Solution"],
            best_entry["problem_solved"],
            problem,
            PROBLEM_PATH.stem,
            bool(best_entry.get("is_relaxation", False)),
        )
    else:
        print("[typeset] No verified solution to typeset — skipping.")


# ── Final status ──────────────────────────────────────────────────────────────

if _finalize_track == "A":
    _priority_note = f", seed={_finalize_seed_priority}" if _finalize_seed_priority else ""
    msg = f"Track A finalize complete (full-proof polish{_priority_note}). See solution.tex and benchmark.json."
elif _finalize_track == "B":
    msg = "Track B finalize complete (progress report; no verified full-problem proof). See solution.tex."
elif memory.has_any_verified_solution():
    msg = "Verified solution found. See benchmark.json."
else:
    msg = "No solution passed verification in this run."

STATUS_FILE.write_text(msg + "\n", encoding="utf-8")
print(f"\n[done] {msg}")
