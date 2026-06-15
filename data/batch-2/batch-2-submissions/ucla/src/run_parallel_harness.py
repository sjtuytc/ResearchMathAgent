#!/usr/bin/env python3
"""Parallel-harness orchestrator.

Runs ``N_PARALLEL_RUNS`` (default 3) parallel instances of
``harness_0518_Final.py`` on the same problem, each in its own
subprocess with fully isolated state — independent ``OUTPUT_ROOT_DIR``
AND independent ``PROBLEM_DATA_DIR`` so there is no shared paper cache,
no shared ``solver_history_*.jsonl``, and no leakage of mid-flight
exploration between the parallel runs.

After every run finishes, a selector LLM call sees the original problem
plus the N full proofs (read from each run's ``solution.tex``) and picks
the strongest one. The chosen proof is copied to
``selected_solution.tex`` at the top level and the verdict (selected
label, reasoning, retrieval pointer) is written to
``selector_verdict.json``.

**N=1 degenerate mode.** When ``N_PARALLEL_RUNS=1`` the orchestrator runs
a single harness, skips the selector LLM call entirely (no token spend,
no second-guessing), and copies that run's ``solution.tex`` straight to
``selected_solution.tex``. The verdict still records the single run for
auditability, with ``selector_skipped=true``.

Usage:
    PROBLEM_FILE=foo.txt OUTPUT_ROOT_DIR=./PARALLEL_OUT \
        N_PARALLEL_RUNS=3 python3 run_parallel_harness.py

Output layout:
    {OUTPUT_ROOT_DIR}/
    ├── harness_run_0/             # full harness output for run 0
    │   ├── solution.tex
    │   ├── final_status.txt
    │   ├── memory/...
    │   └── problem_data/...       # per-run paper cache + solver_history
    ├── harness_run_1/             # only present when N>=2
    ├── …
    ├── harness_stdout_0.log       # subprocess stdout+stderr
    ├── harness_stdout_1.log       # only present when N>=2
    ├── …
    ├── selector_prompt.txt        # selector input    (only when N>=2)
    ├── selector_response.txt      # selector raw LLM response  (only when N>=2)
    ├── selector_verdict.json      # verdict + retrieval pointer (always)
    ├── selected_solution.tex      # the chosen proof (always)
    └── FINAL_STATUS.txt
"""

from __future__ import annotations

import json
import os
import re
import string
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep

try:
    from openai import OpenAI
except ImportError as exc:
    raise RuntimeError(
        "Install the OpenAI Python package: python3 -m pip install openai"
    ) from exc


# ─── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR         = Path(__file__).resolve().parent
HARNESS_SCRIPT     = SCRIPT_DIR / "harness_0518_Final.py"
LOCAL_ENV_FILE     = SCRIPT_DIR / ".env"
LOCAL_API_KEY_FILE = SCRIPT_DIR / ".openai_api_key"
PROBLEMS_DIR       = SCRIPT_DIR / "problems"


# ─── Env helpers (mirrored from the harness so behaviour is identical) ────────

def _load_local_env_file(path: Path) -> None:
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


def _load_secret_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v and v.strip() else default


_load_local_env_file(LOCAL_ENV_FILE)


# ─── Config ───────────────────────────────────────────────────────────────────

# Labels available for proof IDs (A, B, C, …). Hard cap = 26 = len(uppercase).
_LABEL_ALPHABET    = string.ascii_uppercase
_MAX_PARALLEL_RUNS = len(_LABEL_ALPHABET)

N_PARALLEL_RUNS        = _env_int("N_PARALLEL_RUNS",        3)
SELECTOR_MODEL         = os.getenv("SELECTOR_MODEL",        os.getenv("MODEL", "gpt-5.5-pro"))
SELECTOR_REASONING     = os.getenv("SELECTOR_REASONING",    "xhigh")
SELECTOR_VERBOSITY     = os.getenv("SELECTOR_VERBOSITY",    "high")
SELECTOR_MAX_TOKENS    = _env_int("SELECTOR_MAX_TOKENS",    128000)
# Max selector LLM calls per orchestrator run. The first call uses the
# base prompt; subsequent calls (only made when the parser couldn't
# recover a valid <SELECTED>X</SELECTED>) append a corrective reminder.
SELECTOR_MAX_RETRIES   = _env_int("SELECTOR_MAX_RETRIES",   2)
QUEUED_TIMEOUT_SECONDS = _env_int("QUEUED_TIMEOUT_SECONDS", 30 * 60)
BACKGROUND_API         = (os.getenv("BACKGROUND", "true").strip().lower()
                          in {"true", "1", "yes"})

if N_PARALLEL_RUNS < 1:
    raise ValueError(f"N_PARALLEL_RUNS must be >= 1 (got {N_PARALLEL_RUNS})")
if N_PARALLEL_RUNS > _MAX_PARALLEL_RUNS:
    raise ValueError(
        f"N_PARALLEL_RUNS={N_PARALLEL_RUNS} exceeds the {_MAX_PARALLEL_RUNS}-label "
        f"cap (would run out of A-Z proof IDs)."
    )


# ─── Problem resolution (same lookup the harness does) ────────────────────────

def _resolve_problem_file() -> Path:
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
            return files[0]
        if len(files) > 1:
            listing = "\n".join(f"  {f.name}" for f in files)
            raise RuntimeError(
                "Multiple problems found in problems/. "
                "Set PROBLEM_FILE=<filename> to pick one:\n" + listing
            )
    raise FileNotFoundError(
        "No problem file found. Place a .txt file in problems/ "
        "or set PROBLEM_FILE=<path>."
    )


# ─── Subprocess: launch one harness instance ──────────────────────────────────

def _spawn_harness(run_idx: int, output_root: Path, problem_env_value: str) -> tuple[int, int, Path]:
    """Spawn one harness subprocess. Blocks until it exits.

    Each subprocess inherits the parent env but is given:
      - PROBLEM_FILE          : same problem as the parent
      - OUTPUT_ROOT_DIR       : per-run subdir; isolates memory/, solution.tex, …
      - PROBLEM_DATA_DIR      : per-run subdir; isolates paper cache and
                                solver_history so parallel runs cannot leak
                                exploration state to each other.

    Returns (run_idx, returncode, run_dir).
    """
    run_dir   = output_root / f"harness_run_{run_idx}"
    data_dir  = run_dir / "problem_data"
    log_path  = output_root / f"harness_stdout_{run_idx}.log"
    run_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PROBLEM_FILE"]     = problem_env_value
    env["OUTPUT_ROOT_DIR"]  = str(run_dir)
    env["PROBLEM_DATA_DIR"] = str(data_dir)
    # Clear RESUME_DIR — the orchestrator owns lifecycle; per-run resume is
    # handled implicitly by the harness reading its own OUTPUT_ROOT_DIR.
    env.pop("RESUME_DIR", None)

    started = monotonic()
    print(f"[parallel] spawning harness {run_idx} → {run_dir}")
    print(f"[parallel]   stdout/stderr → {log_path}")
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"[parallel] launch at {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        log.write(f"[parallel] PROBLEM_FILE={problem_env_value}\n")
        log.write(f"[parallel] OUTPUT_ROOT_DIR={run_dir}\n")
        log.write(f"[parallel] PROBLEM_DATA_DIR={data_dir}\n")
        log.flush()
        proc = subprocess.Popen(
            [sys.executable, "-u", str(HARNESS_SCRIPT)],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(SCRIPT_DIR),
        )
        rc = proc.wait()

    elapsed = monotonic() - started
    print(f"[parallel] harness {run_idx} exited rc={rc} in {elapsed:.0f}s")
    return run_idx, rc, run_dir


# ─── Per-run final-proof retrieval ────────────────────────────────────────────

def _read_run_proof(run_dir: Path) -> dict:
    """Collect the final artifacts for one harness run.

    Preference order for the proof text:
      1. ``solution.tex``        — canonical typeset output (always preferred).
      2. ``memory/final_solutions.jsonl`` best verified entry — fallback when
         the typeset step did not run.

    Returns a dict with: label-able fields (run_dir, source, status, proof,
    problem_solved, is_relaxation, verified, …) — consumed by both the
    selector prompt builder and the verdict writer.
    """
    record: dict = {
        "run_dir":        str(run_dir),
        "source":         None,
        "status":         "",
        "proof":          "",
        "problem_solved": "",
        "is_relaxation":  None,
        "verified":       None,
    }

    status_file = run_dir / "final_status.txt"
    if status_file.exists():
        record["status"] = status_file.read_text(encoding="utf-8").strip()

    latex_file = run_dir / "solution.tex"
    if latex_file.exists() and latex_file.stat().st_size > 0:
        record["proof"]  = latex_file.read_text(encoding="utf-8")
        record["source"] = f"{latex_file.relative_to(run_dir)}"

    # Always also pull metadata from final_solutions.jsonl (verifier-canonical
    # values) so the selector prompt can show is_relaxation / verified flags,
    # even when the proof text itself comes from solution.tex.
    fs_file = run_dir / "memory" / "final_solutions.jsonl"
    best_entry = None
    if fs_file.exists():
        for line in fs_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            v = (entry.get("if_final_true") or "").lower()
            is_relax = bool(entry.get("is_relaxation", True))
            # Priority: verified+non-relaxation > verified > anything
            key = (v == "true" and not is_relax, v == "true", 0)
            if best_entry is None:
                best_entry = (key, entry)
            elif key > best_entry[0]:
                best_entry = (key, entry)

    if best_entry is not None:
        _, entry = best_entry
        record["problem_solved"] = entry.get("problem_solved", "") or ""
        record["is_relaxation"]  = entry.get("is_relaxation", None)
        record["verified"]       = (entry.get("if_final_true") or "").lower() == "true"
        # Fallback for the proof body itself if solution.tex wasn't produced.
        if not record["proof"] and entry.get("Final_Solution"):
            record["proof"]  = entry["Final_Solution"]
            record["source"] = f"memory/final_solutions.jsonl (task_id={entry.get('task_id')})"

    return record


# ─── Selector LLM call ────────────────────────────────────────────────────────

SELECTOR_PROMPT_TEMPLATE = """\
You are a senior mathematics referee. Below are {n_runs} INDEPENDENT proof \
attempts at the same problem, each produced by a separate full-pipeline run. \
Your job is to pick the ONE proof you would actually submit to a journal — \
the most rigorous, self-consistent, and reliable of the {n_runs}.

# Problem
{problem}

# Independent Proof Attempts (labels: {labels_csv})
Each attempt is shown verbatim. They come from independent runs and may \
prove different versions of the problem (full original vs. a relaxation), \
have different levels of rigor, and rely on different citations.

{proofs_block}

# Your task
Read each proof carefully. Pick the strongest one by these criteria, in \
priority order:

1. **Mathematical rigor** — every step justified; no hand-waving; \
quantifiers explicit; constants defined; no circular reasoning.
2. **Self-consistency** — no internal contradictions; notation used \
consistently throughout; lemmas as stated are sufficient for how they're used.
3. **Reliability** — citations exist and are applied with hypotheses \
verified; standard theorems used correctly; no hallucinated references.
4. **Publication suitability** — clear exposition; sound structure; ready \
(or close to ready) for journal submission.

**Tie-breaker:** if two attempts are comparably rigorous, prefer the one \
that proves the stronger claim (the full original problem over a \
relaxation; better quantitative bounds over weaker ones).

Be specific in your reasoning. Cite concrete steps, lemmas, gaps, or \
citation issues in the proofs (e.g. "Proof A's Lemma 3 has a circular \
argument: it invokes Theorem 2 which itself depends on Lemma 3").

You do NOT need to restate the chosen proof — only identify it by label \
and justify the choice.

# Output format (must follow exactly)

<SELECTED>one of: {labels_csv}</SELECTED>
<REASONING>
A few paragraphs comparing the attempts and explaining why the selected \
one wins. Cite specific steps/lemmas/citations in each proof.
</REASONING>
""".rstrip()


def _build_proofs_block(records: list[dict]) -> str:
    """Render the proofs as labeled blocks for the selector prompt."""
    blocks = []
    for r in records:
        label = r["label"]
        status_summary = r.get("status") or "(no final_status.txt)"
        ps  = (r.get("problem_solved") or "").strip()
        rel = r.get("is_relaxation")
        ver = r.get("verified")
        meta_lines = [f"  - source: {r.get('source') or '(none)'}",
                      f"  - harness final_status: {status_summary}"]
        if ps:
            meta_lines.append(f"  - verifier-canonical problem_solved: {ps}")
        if rel is not None:
            meta_lines.append(f"  - verifier is_relaxation flag: {rel}")
        if ver is not None:
            meta_lines.append(f"  - verifier verified flag: {ver}")
        meta_block = "\n".join(meta_lines)

        body = r.get("proof", "").rstrip() or "(no proof produced by this run)"
        blocks.append(
            f"<PROOF id=\"{label}\">\n"
            f"Run metadata (provenance only — judge on the proof content itself):\n"
            f"{meta_block}\n\n"
            f"--- begin proof {label} ---\n"
            f"{body}\n"
            f"--- end proof {label} ---\n"
            f"</PROOF>"
        )
    return "\n\n".join(blocks)


def _call_selector_api(prompt: str, api_key: str, organization: str | None) -> tuple[str, dict]:
    """Submit the selector prompt and return (response_text, usage_dict).

    Mirrors the harness's run_response retry semantics:
      - background submission + polling
      - queued > QUEUED_TIMEOUT_SECONDS → cancel + resubmit
      - non-completed terminal status → sleep + resubmit
      - any SDK exception → sleep + resubmit
    """
    client_kwargs = {"api_key": api_key, "timeout": 1800, "max_retries": 0}
    if organization:
        client_kwargs["organization"] = organization
    client = OpenAI(**client_kwargs)

    print(f"[parallel/selector] model={SELECTOR_MODEL} reasoning={SELECTOR_REASONING} "
          f"verbosity={SELECTOR_VERBOSITY} max_tokens={SELECTOR_MAX_TOKENS} "
          f"background={BACKGROUND_API}")

    while True:
        response = None
        try:
            started_at = monotonic()
            kwargs = {
                "model":             SELECTOR_MODEL,
                "input":             prompt,
                "text":              {"verbosity": SELECTOR_VERBOSITY},
                "max_output_tokens": SELECTOR_MAX_TOKENS,
                "background":        BACKGROUND_API,
                "service_tier":      "priority",
                "reasoning":         {"effort": SELECTOR_REASONING},
            }
            response = client.responses.create(**kwargs)

            queued_since = None
            cancelled    = False
            while response.status in {"queued", "in_progress"}:
                if response.status == "queued":
                    if queued_since is None:
                        queued_since = monotonic()
                    elif monotonic() - queued_since > QUEUED_TIMEOUT_SECONDS:
                        print(f"[parallel/selector] job {response.id} stuck queued > "
                              f"{QUEUED_TIMEOUT_SECONDS//60} min — cancelling")
                        try:
                            client.responses.cancel(response.id)
                        except Exception as cancel_exc:
                            print(f"[parallel/selector] cancel error (ignoring): {cancel_exc}")
                        cancelled = True
                        break
                else:
                    queued_since = None
                sleep(2)
                response = client.responses.retrieve(response.id)

            if cancelled:
                continue

            if response.status == "completed":
                elapsed = monotonic() - started_at
                usage = getattr(response, "usage", None)
                usage_dict = {
                    "input_tokens":     getattr(usage, "input_tokens",  0) if usage else 0,
                    "output_tokens":    getattr(usage, "output_tokens", 0) if usage else 0,
                    "total_tokens":     getattr(usage, "total_tokens",  0) if usage else 0,
                    "elapsed_seconds":  round(elapsed, 3),
                    "response_id":      getattr(response, "id", None),
                }
                print(f"[parallel/selector] done in {elapsed:.1f}s "
                      f"tokens(in={usage_dict['input_tokens']} "
                      f"out={usage_dict['output_tokens']})")
                return response.output_text or "", usage_dict

            print(f"[parallel/selector] non-completed status: {response.status} — retrying")
            sleep(10)

        except Exception as e:
            print(f"[parallel/selector] error: {e} — retrying in 10s")
            sleep(10)


def _parse_selector_response(text: str, valid_labels: set[str]) -> tuple[str | None, str]:
    """Return (selected_label, reasoning). selected_label is uppercase, in
    ``valid_labels``, or None if absent / unrecognised."""
    sel_m    = re.search(r"<SELECTED>\s*([A-Za-z])\s*</SELECTED>", text)
    reason_m = re.search(r"<REASONING>(.*?)</REASONING>", text, re.DOTALL)
    selected = sel_m.group(1).strip().upper() if sel_m else None
    if selected not in valid_labels:
        selected = None
    reasoning = reason_m.group(1).strip() if reason_m else text.strip()
    return selected, reasoning


SELECTOR_RETRY_REMINDER_TEMPLATE = """\
NOTE FROM THE HARNESS: your previous response did not produce a valid \
<SELECTED> tag. The label inside <SELECTED>...</SELECTED> must be exactly \
ONE letter from this set: {labels_csv}.

{prev_issue}

Re-emit your COMPLETE analysis below — comparing the proofs and \
explaining your choice — and END with the two required tags exactly as \
shown. The label inside <SELECTED> must be ONE letter (no extras, no \
punctuation, no full word).

<SELECTED>one of: {labels_csv}</SELECTED>
<REASONING>
your reasoning here
</REASONING>"""


def _build_retry_reminder(prev_response: str, labels_csv: str) -> str:
    """Build the harness-side corrective note appended to the prompt on retry."""
    m = re.search(r"<SELECTED>([^<]*)</SELECTED>", prev_response)
    if m:
        raw = m.group(1).strip()
        if raw:
            prev_issue = (
                f"Your previous response had <SELECTED>{raw}</SELECTED>, "
                f"which is not a valid single-letter label from {labels_csv}."
            )
        else:
            prev_issue = "Your previous response had an empty <SELECTED></SELECTED> tag."
    else:
        prev_issue = "Your previous response did not contain any <SELECTED>...</SELECTED> tag."
    return SELECTOR_RETRY_REMINDER_TEMPLATE.format(
        prev_issue=prev_issue, labels_csv=labels_csv,
    )


def _call_selector_with_retries(
    base_prompt: str,
    valid_labels: set[str],
    labels_csv: str,
    api_key: str,
    organization: str | None,
    output_root: Path,
) -> tuple[str | None, str, str, dict, int]:
    """Call selector with up to ``SELECTOR_MAX_RETRIES`` attempts.

    Attempt 1 uses the base prompt. Attempts 2+ append a corrective hint
    that tells the model exactly what went wrong (invalid label / missing
    tag / empty tag) and re-requests the required output format.

    Returns ``(selected_label, reasoning, last_response, total_usage,
    n_attempts)``. ``selected_label`` is None iff every attempt returned
    an invalid label — caller then falls back deterministically.

    Side effects: writes ``selector_response.txt`` (the final response,
    successful or not) and — only when retries actually happened — also
    writes ``selector_attempts.txt`` with the full text of every attempt
    for post-hoc debugging.
    """
    all_responses: list[tuple[int, str, dict]] = []
    total_usage = {
        "input_tokens":    0,
        "output_tokens":   0,
        "total_tokens":    0,
        "elapsed_seconds": 0.0,
        "response_ids":    [],
    }
    selected: str | None = None
    reasoning = ""
    response_text = ""

    for attempt in range(1, SELECTOR_MAX_RETRIES + 1):
        if attempt == 1:
            prompt = base_prompt
        else:
            prompt = base_prompt + "\n\n---\n\n" + _build_retry_reminder(
                response_text, labels_csv,
            )

        response_text, usage = _call_selector_api(prompt, api_key, organization)
        all_responses.append((attempt, response_text, usage))

        for k in ("input_tokens", "output_tokens", "total_tokens"):
            total_usage[k] += usage.get(k, 0) or 0
        total_usage["elapsed_seconds"] += usage.get("elapsed_seconds", 0) or 0
        rid = usage.get("response_id")
        if rid:
            total_usage["response_ids"].append(rid)

        selected, reasoning = _parse_selector_response(response_text, valid_labels)
        if selected is not None:
            print(f"[parallel/selector] attempt {attempt}/{SELECTOR_MAX_RETRIES}: "
                  f"got valid label {selected}")
            break

        if attempt < SELECTOR_MAX_RETRIES:
            print(f"[parallel/selector] attempt {attempt}/{SELECTOR_MAX_RETRIES}: "
                  f"invalid/missing <SELECTED> — retrying with corrective hint")
        else:
            print(f"[parallel/selector] attempt {attempt}/{SELECTOR_MAX_RETRIES}: "
                  f"still invalid — giving up, caller will fall back")

    # Persist the last response (compat with the old single-attempt file name).
    (output_root / "selector_response.txt").write_text(response_text, encoding="utf-8")

    # Persist every attempt when retries actually happened — useful for
    # debugging selector misbehaviour without losing the failed attempts.
    if len(all_responses) > 1:
        with open(output_root / "selector_attempts.txt", "w", encoding="utf-8") as f:
            for n, resp, u in all_responses:
                f.write(f"{'='*80}\n")
                f.write(f"[attempt {n}/{SELECTOR_MAX_RETRIES}] "
                        f"response_id={u.get('response_id')} "
                        f"tokens(in={u.get('input_tokens')} out={u.get('output_tokens')})\n")
                f.write(f"{'='*80}\n")
                f.write(resp)
                f.write("\n\n")

    return selected, reasoning, response_text, total_usage, len(all_responses)


# ─── Verdict + final-proof writer ────────────────────────────────────────────

def _write_verdict_and_proof(
    *,
    output_root: Path,
    problem_path: Path,
    records: list[dict],
    chosen: dict,
    selector_used: bool,
    selector_reasoning: str,
    selector_usage: dict | None,
    selector_skipped_reason: str | None,
    selector_n_attempts: int = 0,
    selector_fallback_used: bool = False,
) -> tuple[Path, Path]:
    """Write selector_verdict.json and selected_solution.tex. Returns
    (verdict_path, proof_path)."""
    verdict = {
        "timestamp":               datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "problem_file":            str(problem_path),
        "n_runs":                  len(records),
        "selected_label":          chosen["label"],
        "selected_run":            chosen["run_idx"],
        "selected_proof_path":     str(Path(chosen["run_dir"]) / "solution.tex"),
        "selected_proof_source":   chosen.get("source"),
        "selected_problem_solved": chosen.get("problem_solved"),
        "selected_is_relaxation":  chosen.get("is_relaxation"),
        "selected_verified":       chosen.get("verified"),
        "selector_used":           selector_used,
        "selector_skipped_reason": selector_skipped_reason,
        "selector_model":          SELECTOR_MODEL if selector_used else None,
        "selector_reasoning":      selector_reasoning if selector_used else None,
        "selector_usage":          selector_usage if selector_used else None,
        # New: how many selector LLM calls were made (incl. retries on
        # invalid <SELECTED>), and whether we ended up using the fallback
        # because every attempt failed to produce a valid label.
        "selector_n_attempts":     selector_n_attempts if selector_used else 0,
        "selector_max_retries":    SELECTOR_MAX_RETRIES if selector_used else 0,
        "selector_fallback_used":  selector_fallback_used,
        "all_runs": [
            {
                "label":          r["label"],
                "run_idx":        r["run_idx"],
                "run_dir":        r["run_dir"],
                "returncode":     r["returncode"],
                "source":         r.get("source"),
                "proof_chars":    len(r.get("proof") or ""),
                "status":         r.get("status"),
                "problem_solved": r.get("problem_solved"),
                "is_relaxation":  r.get("is_relaxation"),
                "verified":       r.get("verified"),
            }
            for r in records
        ],
    }
    verdict_path = output_root / "selector_verdict.json"
    proof_path   = output_root / "selected_solution.tex"
    verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    proof_path.write_text(chosen["proof"], encoding="utf-8")
    return verdict_path, proof_path


# ─── Main orchestration ──────────────────────────────────────────────────────

def main() -> int:
    # 1. Resolve problem
    problem_path     = _resolve_problem_file()
    problem_text     = problem_path.read_text(encoding="utf-8").strip()
    problem_env_val  = os.getenv("PROBLEM_FILE", "").strip() or problem_path.name

    # 2. Output root
    output_root = Path(os.getenv("OUTPUT_ROOT_DIR",
                                  str(SCRIPT_DIR / "PARALLEL_OUT"))).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    verdict_file = output_root / "selector_verdict.json"
    final_proof  = output_root / "selected_solution.tex"
    status_file  = output_root / "FINAL_STATUS.txt"

    print(f"\n{'='*80}")
    print(f"[parallel] problem        : {problem_path.name}")
    print(f"[parallel] output root    : {output_root}")
    print(f"[parallel] parallel runs  : {N_PARALLEL_RUNS}"
          + ("  (single-run degenerate mode — selector will be skipped)"
             if N_PARALLEL_RUNS == 1 else ""))
    if N_PARALLEL_RUNS >= 2:
        print(f"[parallel] selector model : {SELECTOR_MODEL} ({SELECTOR_REASONING})")
    print(f"{'='*80}\n")

    # 3. Resume short-circuit
    if verdict_file.exists() and final_proof.exists():
        print(f"[parallel] [RESUME] {verdict_file.name} + {final_proof.name} already "
              f"exist — orchestrator already done. Delete them to re-run.")
        print((status_file.read_text(encoding="utf-8") if status_file.exists() else "").rstrip())
        return 0

    # 4. Spawn N parallel harness subprocesses (each fully isolated)
    spawn_started = monotonic()
    subprocess_results: list[tuple[int, int, Path]] = []
    # ThreadPoolExecutor with N workers covers both N=1 (sequential single task)
    # and N>=2 (true parallel) without a code branch.
    with ThreadPoolExecutor(max_workers=N_PARALLEL_RUNS) as ex:
        futures = {
            ex.submit(_spawn_harness, i, output_root, problem_env_val): i
            for i in range(N_PARALLEL_RUNS)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                subprocess_results.append(fut.result())
            except Exception as exc:
                print(f"[parallel] harness {idx} crashed in orchestrator: {exc}")
                subprocess_results.append((idx, -1, output_root / f"harness_run_{idx}"))

    spawn_elapsed = monotonic() - spawn_started
    print(f"\n[parallel] all {N_PARALLEL_RUNS} subprocess(es) finished in {spawn_elapsed:.0f}s")
    subprocess_results.sort(key=lambda t: t[0])

    # 5. Read per-run final proofs + metadata
    records: list[dict] = []
    for run_idx, rc, run_dir in subprocess_results:
        rec = _read_run_proof(run_dir)
        rec["label"]      = _LABEL_ALPHABET[run_idx]
        rec["run_idx"]    = run_idx
        rec["returncode"] = rc
        records.append(rec)
        proof_len = len(rec.get("proof") or "")
        print(f"[parallel] proof {rec['label']} (run {run_idx}, rc={rc}): "
              f"{proof_len} chars from {rec.get('source') or '(none)'}")

    non_empty = [r for r in records if (r.get("proof") or "").strip()]
    if not non_empty:
        msg = (f"All {N_PARALLEL_RUNS} parallel harness run(s) failed to produce a proof.\n"
               f"Inspect per-run logs at {output_root}/harness_stdout_*.log\n"
               f"and per-run output dirs at {output_root}/harness_run_*/.\n")
        status_file.write_text(msg)
        print(f"\n[parallel] {msg}")
        return 1

    # 6a. Degenerate mode (N=1): single run is the answer — skip the selector.
    if N_PARALLEL_RUNS == 1:
        chosen = records[0]
        if not (chosen.get("proof") or "").strip():
            msg = "Single-run mode produced no proof.\n"
            status_file.write_text(msg)
            print(f"\n[parallel] {msg}")
            return 1
        _write_verdict_and_proof(
            output_root=output_root,
            problem_path=problem_path,
            records=records,
            chosen=chosen,
            selector_used=False,
            selector_reasoning="",
            selector_usage=None,
            selector_skipped_reason="N_PARALLEL_RUNS=1 — single run, no selection needed",
        )
        msg = (
            f"Single-run mode (N_PARALLEL_RUNS=1) — no selection performed.\n"
            f"  • Chosen proof : {final_proof}\n"
            f"  • Source       : {chosen.get('source')}\n"
            f"  • Verdict JSON : {verdict_file}\n"
            f"  • Run dir      : {output_root}/harness_run_0\n"
        )
        status_file.write_text(msg, encoding="utf-8")
        print(f"\n[parallel] {msg}")
        return 0

    # 6b. Multi-run mode (N>=2): build selector prompt + call LLM (with
    #     retries on invalid <SELECTED>).
    labels_csv  = ", ".join(r["label"] for r in records)
    valid_labels = {r["label"] for r in records}

    prompt = SELECTOR_PROMPT_TEMPLATE.format(
        n_runs=N_PARALLEL_RUNS,
        labels_csv=labels_csv,
        problem=problem_text,
        proofs_block=_build_proofs_block(records),
    )
    (output_root / "selector_prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"[parallel] selector prompt: {len(prompt)} chars "
          f"→ {output_root}/selector_prompt.txt")
    print(f"[parallel] selector retries allowed: up to {SELECTOR_MAX_RETRIES}")

    api_key = _load_secret_file(LOCAL_API_KEY_FILE) or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Provide an API key via .openai_api_key (next to this script) "
            "or OPENAI_API_KEY in the .env file or environment."
        )
    organization = os.getenv("OPENAI_ORG_ID") or os.getenv("OPENAI_ORGANIZATION")

    selected, reasoning, _response_text, usage, n_attempts = _call_selector_with_retries(
        base_prompt=prompt,
        valid_labels=valid_labels,
        labels_csv=labels_csv,
        api_key=api_key,
        organization=organization,
        output_root=output_root,
    )

    print(f"\n[parallel/selector] final selected: {selected} after {n_attempts} attempt(s)")
    print(f"[parallel/selector] reasoning (first 600 chars):\n{reasoning[:600]}")

    # 7. Retrieve the chosen proof by label (with sensible fallbacks).
    #    Two fallback triggers:
    #      a) every retry returned an invalid <SELECTED> tag (selected is None)
    #      b) the picked run happened to produce no proof body
    by_label = {r["label"]: r for r in records}
    chosen   = by_label.get(selected) if selected else None
    fallback_used = False

    if chosen is None or not (chosen.get("proof") or "").strip():
        fallback = non_empty[0]
        reason = (
            f"selector exhausted {n_attempts} attempt(s) without a valid label"
            if selected is None
            else f"selector chose {selected!r} but that run has no proof body"
        )
        print(f"[parallel/selector] WARNING: {reason} — "
              f"falling back to {fallback['label']} (run {fallback['run_idx']})")
        chosen = fallback
        fallback_used = True

    # 8. Persist verdict + chosen proof
    _write_verdict_and_proof(
        output_root=output_root,
        problem_path=problem_path,
        records=records,
        chosen=chosen,
        selector_used=True,
        selector_reasoning=reasoning,
        selector_usage=usage,
        selector_skipped_reason=None,
        selector_n_attempts=n_attempts,
        selector_fallback_used=fallback_used,
    )
    msg = (
        f"Parallel-harness complete. Selector chose {chosen['label']} "
        f"(run {chosen['run_idx']}).\n"
        f"  • Chosen proof : {final_proof}\n"
        f"  • Source       : {chosen.get('source')}\n"
        f"  • Verdict JSON : {verdict_file}\n"
        f"  • Run dirs     : {output_root}/harness_run_*\n"
    )
    status_file.write_text(msg, encoding="utf-8")
    print(f"\n[parallel] {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
