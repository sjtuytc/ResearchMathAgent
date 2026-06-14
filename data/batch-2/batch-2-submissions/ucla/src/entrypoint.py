#!/usr/bin/env python3
"""First Proof Batch 2 adapter for harness_0518_Final.

The container is launched per the Batch 2 protocol with:
  * /data/input/input.json  (read-only) — {"problems": [{"id", "latex"}, ...]}
  * /data/output/           (writable)  — one <id>.tex per problem

This script:
  1. Reads each problem from input.json.
  2. Writes its LaTeX to a temp file inside problems/.
  3. Spawns run_parallel_harness.py with PROBLEM_FILE / OUTPUT_ROOT_DIR.
  4. Copies <output_root>/selected_solution.tex to /data/output/<id>.tex.

If the harness fails to produce a selected_solution.tex for a given problem,
a fallback .tex containing the original problem plus a failure notice is
written, so /data/output/ always contains one .tex per input problem.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic

APP_DIR                 = Path(__file__).resolve().parent
HARNESS_PARALLEL_SCRIPT = APP_DIR / "run_parallel_harness.py"
PROBLEMS_DIR            = APP_DIR / "problems"

INPUT_PATH          = Path(os.environ.get("INPUT_PATH",          "/data/input/input.json"))
OUTPUT_DIR          = Path(os.environ.get("OUTPUT_DIR",          "/data/output"))
HARNESS_OUTPUT_ROOT = Path(os.environ.get("HARNESS_OUTPUT_ROOT", "/data/output/_harness_runs"))

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_id(raw: str) -> str:
    cleaned = _SAFE_ID_RE.sub("_", raw).strip("_")
    return cleaned or "problem"


def _wrap_failure_tex(problem_latex: str, message: str) -> str:
    notice = (
        "\n\n\\bigskip\n\\textbf{harness\\_0518\\_Final notice.} "
        "No proof was produced by the harness for this problem.\n\n"
        "\\begin{verbatim}\n"
        f"{message}\n"
        "\\end{verbatim}\n"
    )
    if r"\end{document}" in problem_latex:
        return problem_latex.replace(r"\end{document}", notice + r"\end{document}")
    return problem_latex + notice


def _harness_env(problem_filename: str, output_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PROBLEM_FILE"]     = problem_filename
    env["OUTPUT_ROOT_DIR"]  = str(output_root)
    env.pop("RESUME_DIR", None)
    env.pop("PROBLEM_DATA_DIR", None)
    # Defaults from harness_0518_Final/README.md quick-start.
    # Override any of these via the secrets.env file delivered out-of-band.
    env.setdefault("N_PARALLEL_RUNS",        "1")
    env.setdefault("STAGE2_DEADLINE_HOURS",  "21")
    env.setdefault("ADVISOR_BUDGET",         "10")
    env.setdefault("VERIFY_ROUNDS",          "2")
    env.setdefault("LIT_PARALLEL",           "5")
    env.setdefault("PLAN_REASONING",         "xhigh")
    env.setdefault("SOLVE_REASONING",        "xhigh")
    env.setdefault("ADVISOR_REASONING",      "xhigh")
    env.setdefault("VERIFY_REASONING",       "xhigh")
    env.setdefault("REFINE_REASONING",       "xhigh")
    env.setdefault("FINALIZE_ENABLED",       "True")
    # env.setdefault("LIT_SEARCH_MAX_TOKENS",       "32000")
    env.setdefault("LIT_READ_MAX_TOKENS",       "64000")
    return env


# ─── Cross-problem aggregation: total_usage.json + solutions.json ────────────
#
# After every per-problem harness subprocess has finished, we walk each
# problem's per-call usage.jsonl (written by harness_0518_Final._log_usage)
# and the parallel-selector verdict (when N_PARALLEL_RUNS>=2 so a selector
# actually ran), sum them into per-problem and grand totals, and write a
# single ``total_usage.json`` at the root of ``/data/output``. We also
# emit ``solutions.json`` — a single JSON file mirroring the input schema
# (``{"solutions": [{"id", "latex"}]}``) — alongside the per-problem
# ``<id>.tex`` files, so the submission satisfies the Second-Round spec's
# "JSON file containing ten solutions" requirement without losing the
# individual .tex artifacts.

_USAGE_NUMERIC_KEYS = (
    "input_tokens", "cached_input_tokens", "output_tokens",
    "reasoning_tokens", "total_tokens", "cost_usd", "elapsed_seconds",
)


def _empty_usage_totals() -> dict:
    totals = {k: 0 for k in _USAGE_NUMERIC_KEYS}
    totals["n_api_calls"] = 0
    return totals


def _accumulate_usage(acc: dict, entry: dict) -> None:
    for k in _USAGE_NUMERIC_KEYS:
        try:
            acc[k] = (acc.get(k, 0) or 0) + (entry.get(k, 0) or 0)
        except Exception:
            pass
    acc["n_api_calls"] = acc.get("n_api_calls", 0) + 1


def _read_usage_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        pass
    return out


def _aggregate_problem_usage(safe_pid: str) -> dict:
    """Sum every per-call usage entry under HARNESS_OUTPUT_ROOT/<safe_pid>/.

    Walks every ``Overall_Usage/usage.jsonl`` written by any harness subprocess
    under this problem's output root, plus the parallel-selector's usage (when
    a selector ran) recorded in ``selector_verdict.json``.
    """
    pdir = HARNESS_OUTPUT_ROOT / safe_pid
    totals = _empty_usage_totals()
    per_stage: dict[str, dict] = {}
    if not pdir.exists():
        return {"totals": totals, "per_stage": per_stage}

    for usage_file in pdir.glob("**/Overall_Usage/usage.jsonl"):
        for entry in _read_usage_jsonl(usage_file):
            _accumulate_usage(totals, entry)
            stage = entry.get("stage") or "unknown"
            stage_acc = per_stage.setdefault(stage, _empty_usage_totals())
            _accumulate_usage(stage_acc, entry)

    verdict_file = pdir / "selector_verdict.json"
    if verdict_file.exists():
        try:
            v = json.loads(verdict_file.read_text(encoding="utf-8"))
        except Exception:
            v = {}
        sel = v.get("selector_usage") if isinstance(v, dict) else None
        if isinstance(sel, dict):
            selector_entry = {
                "stage":               "parallel_selector",
                "input_tokens":        sel.get("input_tokens", 0) or 0,
                "cached_input_tokens": 0,
                "output_tokens":       sel.get("output_tokens", 0) or 0,
                "reasoning_tokens":    0,
                "total_tokens":        sel.get("total_tokens", 0) or 0,
                "cost_usd":            0,
                "elapsed_seconds":     sel.get("elapsed_seconds", 0) or 0,
            }
            _accumulate_usage(totals, selector_entry)
            per_stage.setdefault("parallel_selector", _empty_usage_totals())
            _accumulate_usage(per_stage["parallel_selector"], selector_entry)

    return {"totals": totals, "per_stage": per_stage}


def _round_usage_dict(d: dict) -> None:
    if "cost_usd" in d:
        d["cost_usd"] = round(float(d.get("cost_usd", 0.0) or 0.0), 6)
    if "elapsed_seconds" in d:
        d["elapsed_seconds"] = round(float(d.get("elapsed_seconds", 0.0) or 0.0), 3)


def _write_total_usage(jobs: list[tuple[str, str]]) -> None:
    """Aggregate token usage across all problems and write total_usage.json."""
    grand = _empty_usage_totals()
    per_problem: dict[str, dict] = {}
    for pid, _latex in jobs:
        safe_pid = _safe_id(pid)
        agg      = _aggregate_problem_usage(safe_pid)
        for k in _USAGE_NUMERIC_KEYS:
            grand[k] = (grand.get(k, 0) or 0) + (agg["totals"].get(k, 0) or 0)
        grand["n_api_calls"] = grand.get("n_api_calls", 0) + agg["totals"].get("n_api_calls", 0)
        _round_usage_dict(agg["totals"])
        for st in agg["per_stage"].values():
            _round_usage_dict(st)
        per_problem[pid] = {
            "safe_id":   safe_pid,
            "totals":    agg["totals"],
            "per_stage": agg["per_stage"],
        }
    _round_usage_dict(grand)

    report = {
        "schema_version": 1,
        "n_problems":     len(jobs),
        "grand_total":    grand,
        "per_problem":    per_problem,
    }
    out_path = OUTPUT_DIR / "total_usage.json"
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[entrypoint] wrote {out_path}  "
        f"(grand: calls={grand['n_api_calls']} "
        f"in={grand['input_tokens']} cached={grand['cached_input_tokens']} "
        f"out={grand['output_tokens']} reason={grand['reasoning_tokens']} "
        f"total={grand['total_tokens']} cost=${grand['cost_usd']:.2f})",
        flush=True,
    )


def _write_solutions_json(jobs: list[tuple[str, str]]) -> None:
    """Emit a single solutions.json mirroring the input schema.

    Reads each problem's final ``<safe_id>.tex`` from /data/output/ (which by
    this point holds either the harness's selected_solution.tex or a fallback
    failure-notice .tex), and bundles them into one JSON. Preserves the
    original ``id`` from the input file, not the sanitised filename id.
    """
    solutions = []
    for pid, original_latex in jobs:
        safe_pid = _safe_id(pid)
        tex_path = OUTPUT_DIR / f"{safe_pid}.tex"
        if tex_path.exists() and tex_path.stat().st_size > 0:
            latex = tex_path.read_text(encoding="utf-8")
        else:
            latex = _wrap_failure_tex(
                original_latex,
                "no .tex file present at solutions.json assembly time",
            )
        solutions.append({"id": pid, "latex": latex})
    out_path = OUTPUT_DIR / "solutions.json"
    out_path.write_text(
        json.dumps({"solutions": solutions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[entrypoint] wrote {out_path} ({len(solutions)} solution(s))", flush=True)


def _run_one(pid: str, latex: str) -> None:
    safe_pid     = _safe_id(pid)
    problem_file = PROBLEMS_DIR / f"_input_{safe_pid}.txt"
    output_root  = HARNESS_OUTPUT_ROOT / safe_pid

    PROBLEMS_DIR.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    problem_file.write_text(latex, encoding="utf-8")

    env = _harness_env(problem_file.name, output_root)

    print(f"[entrypoint] === {pid} (safe id: {safe_pid}) ===", flush=True)
    print(f"[entrypoint]   problem_file = {problem_file}", flush=True)
    print(f"[entrypoint]   output_root  = {output_root}", flush=True)
    started = monotonic()
    rc: int = -1
    try:
        rc = subprocess.call(
            [sys.executable, "-u", str(HARNESS_PARALLEL_SCRIPT)],
            env=env,
            cwd=str(APP_DIR),
        )
    except Exception:
        traceback.print_exc()
    elapsed = monotonic() - started
    print(f"[entrypoint]   rc={rc} elapsed={elapsed:.0f}s", flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    selected = output_root / "selected_solution.tex"
    out_path = OUTPUT_DIR / f"{safe_pid}.tex"
    if selected.exists() and selected.stat().st_size > 0:
        shutil.copyfile(selected, out_path)
        print(f"[entrypoint]   wrote {out_path} ({out_path.stat().st_size} bytes)", flush=True)
    else:
        fallback = _wrap_failure_tex(
            latex,
            f"harness exit code {rc}; no selected_solution.tex at {selected}",
        )
        out_path.write_text(fallback, encoding="utf-8")
        print(f"[entrypoint]   WARNING: no selected_solution.tex; wrote fallback to {out_path}", flush=True)


def main() -> int:
    if not INPUT_PATH.exists():
        print(f"[entrypoint] ERROR: input file {INPUT_PATH} does not exist", file=sys.stderr)
        return 2

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    problems = data.get("problems") if isinstance(data, dict) else None
    if not isinstance(problems, list):
        print("[entrypoint] ERROR: input file must contain a 'problems' array", file=sys.stderr)
        return 2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, str]] = []
    for i, prob in enumerate(problems, start=1):
        pid   = str(prob.get("id", f"prob-{i:03d}"))
        latex = prob.get("latex", "")
        if not latex:
            print(f"[entrypoint] WARNING: empty latex for {pid}; skipping", file=sys.stderr)
            continue
        jobs.append((pid, latex))

    max_workers = max(1, int(os.environ.get("PROBLEM_PARALLEL", str(len(jobs) or 1))))
    print(
        f"[entrypoint] processing {len(problems)} problems "
        f"({len(jobs)} runnable, up to {max_workers} in parallel)",
        flush=True,
    )

    def _safe_run(pid: str, latex: str) -> None:
        try:
            _run_one(pid, latex)
        except Exception:
            traceback.print_exc()
            out_path = OUTPUT_DIR / f"{_safe_id(pid)}.tex"
            out_path.write_text(
                _wrap_failure_tex(latex, "entrypoint exception (see container logs)"),
                encoding="utf-8",
            )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(_safe_run, pid, latex) for pid, latex in jobs]
        for f in as_completed(futs):
            f.result()

    # ── Cross-problem aggregation: solutions.json + total_usage.json ──────────
    # Both are emitted on a best-effort basis: a failure here must not flip
    # the run to FAILED, because the per-problem .tex outputs are already on
    # disk by this point and constitute the primary submission artifact.
    try:
        _write_solutions_json(jobs)
    except Exception:
        print("[entrypoint] WARNING: failed to write solutions.json", file=sys.stderr)
        traceback.print_exc()
    try:
        _write_total_usage(jobs)
    except Exception:
        print("[entrypoint] WARNING: failed to write total_usage.json", file=sys.stderr)
        traceback.print_exc()

    print("[entrypoint] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
