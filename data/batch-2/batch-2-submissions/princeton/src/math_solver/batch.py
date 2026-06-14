"""Batch driver for the First Proof submission format.

Spec (Second Batch): the deployed system is given **one JSON file** containing
the ten benchmark problems (each in complete, compilable LaTeX) plus API keys,
must "process all the problems in parallel" and produce results "within 24
hours", and must emit **one JSON file** containing ten solutions, each "a
separate, properly compilable LaTeX document". It must also log tokens per call
(input / output / reasoning) and report the totals on completion.

This module is the glue that meets those I/O requirements without touching the
battle-tested single-problem pipeline:

* Each problem is run as its own OS subprocess (``python -m math_solver.main
  run``). One process per problem ⇒ true parallelism and per-problem fault
  isolation; each process has its own Gemini concurrency budget
  (``GEMINI_CONCURRENCY``).
* When all runs finish (or the wall-clock deadline hits), the best proof from
  each run is typeset into an Overleaf-clean LaTeX document
  (``latex_export.typeset_and_verify``) and packaged into the output JSON.
* Token totals are rolled up across every run's ``agent_calls`` table — which
  already records input / output / reasoning (``tokens_think``) tokens for every
  call, including the LaTeX typesetting calls.

Input JSON schema (tolerant loader; canonical form shown):

    {"problems": [{"id": "P1", "statement": "<full LaTeX document>"}, ...]}

Also accepted: a bare list of strings, a bare list of objects, or an object
keyed by id. First Proof will publish exact deployment details in their repo; if
their schema differs, adjust ``load_problems`` only.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import GEMINI_MODEL, RUNS_DIR
from .state import RunStore, new_run_id

console = Console()

SOLVED_THRESHOLD = 7.0   # internal grader score at/above which we call it "solved"


# ── Input loading ─────────────────────────────────────────────────────────────


@dataclass
class Problem:
    id: str
    statement: str          # full, compilable LaTeX document of the problem


def _coerce_problem(idx: int, item) -> Problem:
    """Turn one heterogeneous JSON entry into a Problem."""
    if isinstance(item, str):
        return Problem(id=f"P{idx + 1}", statement=item)
    if isinstance(item, dict):
        # Accept several common key spellings for the statement.
        statement = None
        for key in ("statement", "problem", "latex", "tex", "body", "text", "content"):
            if isinstance(item.get(key), str) and item[key].strip():
                statement = item[key]
                break
        if statement is None:
            raise ValueError(
                f"Problem {idx} has no recognizable statement field "
                f"(looked for statement/problem/latex/tex/body/text/content): "
                f"keys={list(item)}"
            )
        pid = str(item.get("id") or item.get("name") or item.get("key") or f"P{idx + 1}")
        return Problem(id=pid, statement=statement)
    raise ValueError(f"Problem {idx} is neither a string nor an object: {type(item)}")


def load_problems(path: Path) -> list[Problem]:
    """Load benchmark problems from the input JSON, tolerant of several shapes."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    if isinstance(data, dict):
        if isinstance(data.get("problems"), list):
            items = data["problems"]
        else:
            # Object keyed by problem id -> statement (or -> object).
            items = []
            for k, v in data.items():
                if isinstance(v, dict):
                    v.setdefault("id", k)
                    items.append(v)
                else:
                    items.append({"id": k, "statement": v})
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"Top-level JSON must be a list or object, got {type(data)}")

    problems = [_coerce_problem(i, it) for i, it in enumerate(items)]
    if not problems:
        raise ValueError("No problems found in input JSON.")
    return problems


# ── Per-problem run ───────────────────────────────────────────────────────────


@dataclass
class RunOutcome:
    problem: Problem
    run_id: str
    returncode: int | None = None
    timed_out: bool = False
    error: str = ""
    # filled in during collection
    solved: bool = False
    score: float = 0.0
    proof_text: str = ""
    status: str = ""


async def _launch_run(problem: Problem, *, width: int, depth: int, search: bool,
                      batch_dir: Path,
                      additional_materials_path: Path | None = None,
                      ) -> tuple[RunOutcome, asyncio.subprocess.Process]:
    """Write the problem to a file and spawn a single-problem run subprocess.

    If ``additional_materials_path`` is supplied (per-problem seed bundle —
    e.g. assembled paper-hunter findings or prior best proof + critique),
    it is threaded to the child as ``--additional-materials <path>`` so
    the solver/grader/notebook stack sees it on every stage via
    ``state.vetted_facts_text()``. Mirror of the rework launcher's
    additional-materials channel; same semantics, different trigger.
    """
    run_id = new_run_id()
    pfile = batch_dir / f"{run_id}_problem.txt"
    pfile.write_text(problem.statement, encoding="utf-8")
    log_path = batch_dir / f"{run_id}.log"
    log_fh = open(log_path, "wb")

    # Budget = W*D outer + headroom for ~1 conjecture stage (R=2 inner * W)
    # + gauntlet overhead. 2*W*D is conservative and bounds runaway cost.
    total_budget = max(2 * width * depth, width + 1)
    cmd = [
        sys.executable, "-m", "math_solver.main", "run", str(pfile),
        "--run-id", run_id, "-W", str(width), "-D", str(depth),
        "--total-budget", str(total_budget),
        "--search" if search else "--no-search",
        "--no-child-spawn",                      # keep batch parallelism flat
        "--label", f"FirstProof {problem.id}",
    ]
    if additional_materials_path is not None:
        cmd.extend(["--additional-materials", str(additional_materials_path)])
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=log_fh, stderr=asyncio.subprocess.STDOUT,
    )
    am_note = f" [seed: {additional_materials_path.name}]" if additional_materials_path else ""
    console.log(f"[cyan]Launched {problem.id} → run {run_id} (pid {proc.pid}){am_note}[/cyan]")
    return RunOutcome(problem=problem, run_id=run_id), proc


async def _prefetch_oai_for_bs_clean(run_id: str) -> None:
    """Ensure every BS-clean parent record has an OpenAI score.

    The orchestrator's OAI gate fires only when the gauntlet
    *confirms* a 7/7 — and the empirical rate of those is low. So
    many BS-clean parents (gauntlet 5 or 6, BS-detector clean) end
    up with rec.openai_score = None, which excludes them from the
    ship-time ranking under the BS-clean + sum(gauntlet, openai)
    rule. This helper walks the parent records, fires a fresh
    `openai_grader.grade_proof` call on every BS-clean parent whose
    openai_score is None, and writes the scores back to the run.db
    via the RunStore. asyncio.gather for parallelism (no rate-limit
    concern at Tier 3).

    Best-effort: any per-proof failure (key error, parse failure,
    timeout) leaves that record's openai_score as None; ranking
    falls back to bs_clean+score for those.
    """
    from .state import RunStore
    from .agents.grader import _extract_critique_only, _proof_only

    store = RunStore(run_id)
    try:
        state = store.load_run_state()
        if state is None:
            return
        problem_text = getattr(state, "problem", "") or ""
        targets = [
            (i, rec) for i, rec in enumerate(state.all_solutions)
            if rec.stage_type == "parent"
            and rec.bs_clean is True
            and rec.openai_score is None
        ]
        if not targets:
            return
        console.log(
            f"[cyan]OAI prefetch {run_id}: {len(targets)} BS-clean parent(s) "
            f"need a fresh OAI grade[/cyan]"
        )

        # Resolve the openai_grader on demand (same scripts-path probe
        # as _run_grader3_for_outcome below).
        import sys as _sys
        from pathlib import Path as _Path
        for _c in (_Path(__file__).resolve().parents[2] / "scripts",
                   _Path("/app/scripts")):
            if (_c / "openai_grader.py").exists() and str(_c) not in _sys.path:
                _sys.path.insert(0, str(_c))
                break
        from openai_grader import grade_proof as _oai_grade  # type: ignore

        async def _one(rec):
            proof_clean = await _proof_only(rec.output)
            try:
                oai = await _oai_grade(problem=problem_text, proof=proof_clean)
                if oai.score is not None and oai.score >= 0:
                    return oai.score, await _extract_critique_only(oai.output)
            except Exception:
                pass
            return None, None

        results = await asyncio.gather(*[_one(rec) for _, rec in targets])
        n_ok = 0
        for (_, rec), (score, feedback) in zip(targets, results):
            if score is None:
                continue
            rec.openai_score = score
            if feedback:
                rec.openai_feedback = feedback
            n_ok += 1
        store.save_run_state(state)
        console.log(
            f"[cyan]OAI prefetch {run_id}: graded {n_ok}/{len(targets)}[/cyan]"
        )
    finally:
        store.close()


def _collect_run(outcome: RunOutcome) -> RunOutcome:
    """Load a finished run's state and extract its best proof + solved flag."""
    from .orchestrator import _extract_part3

    store = RunStore(outcome.run_id)
    try:
        state = store.load_run_state()
    finally:
        store.close()

    if state is None:
        outcome.status = "NO_STATE"
        outcome.error = outcome.error or "run produced no state (likely crashed early)"
        return outcome

    outcome.status = state.status.value
    top = state.top_solutions(n=1)
    if top:
        best = top[0]
        outcome.score = best.score
        outcome.proof_text = _extract_part3(best.output) or best.output
        outcome.solved = best.score >= SOLVED_THRESHOLD
    return outcome


def _run_token_stats(run_id: str) -> dict:
    """Token totals for one run, read straight from its agent_calls table."""
    store = RunStore(run_id)
    try:
        cur = store._conn.execute(
            "SELECT SUM(tokens_in), SUM(tokens_out), SUM(tokens_think) "
            "FROM agent_calls WHERE run_id=?",
            (run_id,),
        )
        row = cur.fetchone() or (0, 0, 0)
    finally:
        store.close()
    tin, tout, tthink = (row[0] or 0), (row[1] or 0), (row[2] or 0)
    return {"input": tin, "output": tout, "reasoning": tthink,
            "total": tin + tout + tthink}


# ── Driver ────────────────────────────────────────────────────────────────────


async def run_batch(
    input_json: Path,
    output_json: Path,
    *,
    width: int,
    depth: int,
    search: bool = False,
    timeout_hours: float = 24.0,
    max_repairs: int = 3,
    write_tex: bool = True,
) -> dict:
    """Run all problems in parallel, typeset results, write the solutions JSON.

    Returns the assembled result dict (also written to ``output_json``).
    """
    from .latex_export import (typeset_and_verify, minimal_unsolved_document,
                               pdflatex_available)

    problems = load_problems(input_json)
    console.rule(f"[bold]First Proof batch — {len(problems)} problems")
    console.log(f"Model: {GEMINI_MODEL}  |  W={width} D={depth}  search={'on' if search else 'off'}")
    if not pdflatex_available():
        console.log("[yellow]pdflatex not found — LaTeX output will not be compile-verified.[/yellow]")

    batch_dir = RUNS_DIR / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    console.log(f"Batch working dir: {batch_dir}")

    t0 = time.time()

    # 1. Launch every problem as its own parallel subprocess.
    outcomes: list[RunOutcome] = []
    procs: list[asyncio.subprocess.Process] = []
    for p in problems:
        outcome, proc = await _launch_run(p, width=width, depth=depth,
                                          search=search, batch_dir=batch_dir)
        outcomes.append(outcome)
        procs.append(proc)

    # 2. Wait for all of them, bounded by the wall-clock deadline.
    deadline = timeout_hours * 3600.0
    try:
        await asyncio.wait_for(
            asyncio.gather(*(p.wait() for p in procs)), timeout=deadline,
        )
    except asyncio.TimeoutError:
        console.log(f"[red]Deadline of {timeout_hours}h reached — terminating unfinished runs.[/red]")
        for outcome, proc in zip(outcomes, procs):
            if proc.returncode is None:
                outcome.timed_out = True
                outcome.error = f"exceeded {timeout_hours}h deadline"
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
        await asyncio.gather(*(p.wait() for p in procs), return_exceptions=True)

    for outcome, proc in zip(outcomes, procs):
        outcome.returncode = proc.returncode

    # 3. Collect each run's best proof.
    for outcome in outcomes:
        if not outcome.timed_out:
            _collect_run(outcome)

    # 4. Typeset every result to Overleaf-clean LaTeX (parallel, logged per run).
    async def _typeset(outcome: RunOutcome) -> dict:
        store = RunStore(outcome.run_id)
        try:
            if outcome.proof_text.strip():
                ts = await typeset_and_verify(
                    outcome.problem.statement, outcome.proof_text,
                    run_id=outcome.run_id, store=store,
                    solved=outcome.solved, score=outcome.score,
                    max_repairs=max_repairs,
                )
                latex, compiles, pages, note = ts.latex, ts.compiles, ts.pages, ts.note
            else:
                msg = outcome.error or "No proof was produced."
                latex = minimal_unsolved_document(msg)
                compiles, pages, note = pdflatex_available(), None, "fallback unsolved document"
        finally:
            store.close()

        tokens = _run_token_stats(outcome.run_id)
        return {
            "id": outcome.problem.id,
            "solved": outcome.solved,
            "score": round(outcome.score, 2),
            "latex": latex,
            "compiles": compiles,
            "pages": pages,
            "tokens": tokens,
            "run_id": outcome.run_id,
            "status": outcome.status or ("TIMEOUT" if outcome.timed_out else "UNKNOWN"),
            "notes": "; ".join(x for x in (outcome.error, note) if x),
        }

    solutions = await asyncio.gather(*(_typeset(o) for o in outcomes))

    # 5. Global token rollup across all runs.
    totals = {"input": 0, "output": 0, "reasoning": 0, "total": 0}
    for sol in solutions:
        for k in totals:
            totals[k] += sol["tokens"][k]

    wall = time.time() - t0
    result = {
        "metadata": {
            "spec": "First Proof — Second Batch",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": GEMINI_MODEL,
            "num_problems": len(problems),
            "num_solved": sum(1 for s in solutions if s["solved"]),
            "wall_time_seconds": round(wall, 1),
            "width": width,
            "depth": depth,
            "search": search,
            "token_totals": totals,
        },
        "solutions": solutions,
    }

    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    if write_tex:
        tex_dir = output_json.with_suffix("")
        tex_dir = tex_dir.parent / f"{tex_dir.name}_tex"
        tex_dir.mkdir(parents=True, exist_ok=True)
        for sol in solutions:
            (tex_dir / f"{sol['id']}.tex").write_text(sol["latex"], encoding="utf-8")
        console.log(f"Individual .tex files written to {tex_dir}")

    _print_summary(result)
    console.log(f"[green]Wrote {output_json}[/green]")
    return result


def _print_summary(result: dict) -> None:
    meta = result["metadata"]
    table = Table(title="First Proof batch — summary")
    table.add_column("Problem")
    table.add_column("Solved")
    table.add_column("Score", justify="right")
    table.add_column("Compiles")
    table.add_column("Pages", justify="right")
    table.add_column("Total tokens", justify="right")
    for sol in result["solutions"]:
        table.add_row(
            sol["id"],
            "[green]yes[/green]" if sol["solved"] else "no",
            f"{sol['score']:.1f}",
            "yes" if sol["compiles"] else "[red]no[/red]",
            str(sol["pages"]) if sol["pages"] is not None else "—",
            f"{sol['tokens']['total']:,}",
        )
    console.print(table)

    tot = meta["token_totals"]
    roll = Table(title="Token totals (all calls, all problems)")
    roll.add_column("Metric")
    roll.add_column("Value", justify="right")
    roll.add_row("Problems solved", f"{meta['num_solved']}/{meta['num_problems']}")
    roll.add_row("Wall time", f"{meta['wall_time_seconds']:.0f}s")
    roll.add_row("Input tokens", f"{tot['input']:,}")
    roll.add_row("Output tokens", f"{tot['output']:,}")
    roll.add_row("Reasoning tokens", f"{tot['reasoning']:,}")
    roll.add_row("Total tokens", f"{tot['total']:,}")
    console.print(roll)


# ── First Proof Batch-2 container entrypoint ──────────────────────────────────
# Contract (First Proof's run.sh): the container reads /data/input/input.json
# (read-only) and writes results to /data/output/. We write each <id>.tex
# incrementally (so a 24h hard-kill still leaves completed solutions rather than
# an empty dir, which run.sh flags as FAILED), plus a structured token log and a
# summary solutions.json. Bounded problem-level concurrency keeps RAM within a
# small instance (t3.medium = 4 GiB).


def _append_run_token_log(run_id: str, problem_id: str, path: Path) -> None:
    """Append one run's per-call token records to the JSONL token log.

    Satisfies the protocol's "detailed log of all tokens produced and consumed at
    each step" — per call: agent, stage, input/output/reasoning token counts,
    duration, and the model output text. (Gemini returns reasoning token COUNTS,
    not thinking text; input prompts are summarized by token count + agent/stage.)
    """
    store = RunStore(run_id)
    try:
        cur = store._conn.execute(
            "SELECT call_id, agent, inputs, output, tokens_in, tokens_out, "
            "tokens_think, duration_ms, created_at FROM agent_calls "
            "WHERE run_id=? ORDER BY created_at",
            (run_id,),
        )
        rows = cur.fetchall()
    finally:
        store.close()
    with open(path, "a", encoding="utf-8") as fh:
        for call_id, agent, inputs_json, output, tin, tout, tthink, dur, created in rows:
            try:
                stage = json.loads(inputs_json).get("stage")
            except Exception:
                stage = None
            tin, tout, tthink = (tin or 0), (tout or 0), (tthink or 0)
            rec = {
                "problem_id": problem_id, "run_id": run_id, "call_id": call_id,
                "agent": agent, "stage": stage,
                "tokens": {"input": tin, "output": tout, "reasoning": tthink,
                           "total": tin + tout + tthink},
                "duration_ms": dur or 0, "created_at": created,
                "output_text": (output or "")[:40000],
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


async def _launch_rework_run(
    problem: Problem,
    *,
    additional_materials_path: Path,
    batch_dir: Path,
    width: int = 6,
    depth: int = 6,
    search: bool = False,
) -> tuple[RunOutcome, asyncio.subprocess.Process]:
    """Spawn a rework subprocess with grader3 feedback as additional_materials.

    Mirrors _launch_run but uses a stronger budget (W=6 D=6 default) and
    threads the citation-verifier feedback through --additional-materials
    so the rework solver knows which prior citations failed verification.
    """
    run_id = new_run_id()
    pfile = batch_dir / f"{run_id}_problem.txt"
    pfile.write_text(problem.statement, encoding="utf-8")
    log_path = batch_dir / f"{run_id}.log"
    log_fh = open(log_path, "wb")

    total_budget = max(2 * width * depth, width + 1)
    cmd = [
        sys.executable, "-m", "math_solver.main", "run", str(pfile),
        "--run-id", run_id, "-W", str(width), "-D", str(depth),
        "--total-budget", str(total_budget),
        "--search" if search else "--no-search",
        "--no-child-spawn",
        "--additional-materials", str(additional_materials_path),
        "--label", f"FirstProof {problem.id} rework",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=log_fh, stderr=asyncio.subprocess.STDOUT,
    )
    console.log(f"[cyan]Launched {problem.id} REWORK → run {run_id} (pid {proc.pid}) "
                f"W={width} D={depth}[/cyan]")
    return RunOutcome(problem=problem, run_id=run_id), proc


def _build_rework_additional_materials(outcome: RunOutcome, g3_verdict: dict,
                                        output_dir: Path) -> Path | None:
    """Assemble grader3 feedback + original proof into one file for the
    rework solver to consume via --additional-materials. Returns the
    file path, or None if grader3 didn't produce usable feedback.

    Cut-and-paste only: nothing this function writes is composed prose;
    every byte is either a structural label or content lifted verbatim
    from grader3's LLM-produced outputs and the original proof.
    """
    report_path = g3_verdict.get("report")
    if not report_path:
        return None
    rp = Path(report_path)
    feedback_dir = rp.parent  # <output_dir>/<id>_grader3/
    bundle = output_dir / f"{outcome.problem.id}_rework_additional_materials.txt"
    parts: list[str] = []
    parts.append("[Grader 3 — Citation Verification Aggregate Report]\n")
    if rp.exists():
        parts.append(rp.read_text(encoding="utf-8"))
    # Append every per-proof feedback.md found under the grader3 output dir.
    for fp in sorted(feedback_dir.glob("proof_*/verify/feedback.md")):
        parts.append(f"\n\n[Per-proof feedback — {fp.parent.parent.name}]\n")
        parts.append(fp.read_text(encoding="utf-8"))
    # Append the original (pre-rework) proof so the rework solver can see
    # what to improve on.
    parts.append(f"\n\n[Original proof under review — run {outcome.run_id}]\n")
    parts.append(outcome.proof_text or "(no proof text recovered)")
    bundle.write_text("\n".join(parts), encoding="utf-8")
    return bundle


async def _run_grader3_for_outcome(
    outcome: RunOutcome,
    output_dir: Path,
    *,
    time_budget_secs: float,
) -> dict:
    """Fire Grader 3 on a just-finished solver run. Returns a verdict dict.

    Never raises: any exception is caught, logged, and surfaced as an
    UNKNOWN verdict so the autonomous batch loop is not interrupted by
    a verifier hiccup (FirstProof requires fully-autonomous operation).

    No score threshold (2026-05-28): even weak proofs benefit from
    literature-grounded critique. The rework loop's strictly-better
    guard ensures we never ship something worse than the original.
    """
    if time_budget_secs < 5 * 60:  # need at least 5 min to attempt
        return {"verdict": "SKIPPED",
                "reason": f"insufficient time (have {time_budget_secs:.0f}s)",
                "n_pass": 0}

    try:
        # grader3 lives in scripts/ (sibling to src/), not inside the
        # math_solver package, so it isn't on the import path by default.
        # Probe known candidate locations and add the first that contains
        # grader3.py. Falls back through:
        #   - dev checkout: <repo>/scripts/  (parents[2] of installed-ish layout)
        #   - AWS container: /app/scripts/   (deploy/Dockerfile COPY target)
        #   - PYTHONPATH-supplied: already importable, no probe needed.
        import sys as _sys
        from pathlib import Path as _Path
        _candidates = [
            _Path(__file__).resolve().parents[2] / "scripts",
            _Path("/app/scripts"),
        ]
        _scripts = None
        for _c in _candidates:
            if (_c / "grader3.py").exists():
                _scripts = str(_c)
                break
        if _scripts and _scripts not in _sys.path:
            _sys.path.insert(0, _scripts)
        import grader3 as _g3  # type: ignore

        # Compose critiques for each top-K proof (Sanjeev 2026-05-28).
        # Grader A = Gemini gauntlet aggregator critique, already on
        # rec.grader_feedback (stripped by harvest-time strip helpers).
        # Grader B = OpenAI gpt-5.5-pro critique. Cached on
        # rec.openai_feedback when the orchestrator's OAI gate fired
        # earlier (gauntlet-confirmed-7 only); for other top-K proofs,
        # call OpenAI fresh in parallel here.
        state = _g3.load_state(outcome.run_id)
        eligible = _g3.eligible_proofs(state, top_n=2)
        # Identify proofs that need a fresh OAI call.
        from openai_grader import grade_proof as _oai_grade  # type: ignore
        from .agents.grader import _extract_critique_only as _strip
        problem_text = state.get("problem", "")

        async def _proof_only_local(text: str) -> str:
            from .agents.grader import _proof_only
            return await _proof_only(text)

        async def _fetch_b_critique_for(p: dict) -> str:
            existing = p.get("openai_feedback")
            if existing:
                return existing  # already stripped at harvest
            proof_clean = await _proof_only_local(p.get("output", ""))
            try:
                oai = await _oai_grade(problem=problem_text, proof=proof_clean)
                if oai.score is not None and oai.score >= 0:
                    return await _strip(oai.output)
                return f"(OpenAI grader unavailable: error={oai.error})"
            except Exception as exc:
                return f"(OpenAI grader call failed: {type(exc).__name__}: {exc})"

        b_critiques = await asyncio.gather(*(_fetch_b_critique_for(p) for p in eligible))
        critiques = {}
        for p, b in zip(eligible, b_critiques):
            key = (p.get("stage"), p.get("solver_index"))
            a = p.get("grader_feedback") or "(not provided)"
            critiques[key] = {"grader_a": a, "grader_b": b}

        g3_out = output_dir / f"{outcome.problem.id}_grader3"
        result = await asyncio.wait_for(
            _g3.run_grader3(
                run_id=outcome.run_id,
                out_dir=g3_out,
                top_n=2,             # cap: only the top 2 candidate proofs per problem
                concurrency=4,
                auto_rework=False,   # rework wiring is a separate concern
                rework_budget=0,
                critiques=critiques,
            ),
            timeout=time_budget_secs,
        )
        return {
            "verdict": "RAN",
            "n_eligible": result.get("n_eligible", 0),
            "n_pass": result.get("n_pass", 0),
            "report": result.get("report"),
            "best_so_far": result.get("best_so_far"),
        }
    except asyncio.TimeoutError:
        return {"verdict": "TIMEOUT",
                "reason": f"grader3 exceeded {time_budget_secs:.0f}s budget"}
    except Exception as exc:
        return {"verdict": "UNKNOWN",
                "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


async def run_firstproof(
    input_path: Path,
    output_dir: Path,
    *,
    width: int,
    depth: int,
    search: bool = False,
    timeout_hours: float = 23.0,
    max_parallel: int = 10,
    max_repairs: int = 3,
) -> dict:
    """First Proof Batch-2 entrypoint: /data/input/input.json -> /data/output/.

    Writes each ``<id>.tex`` as soon as that problem finishes (incremental, so a
    timeout leaves partial-but-valid output), a structured ``token_log.jsonl``,
    and a summary ``solutions.json``. Problem-level concurrency is capped at
    ``max_parallel`` (default 10 = solve all problems at once for a 10-problem
    submission; lower to throttle if RAM constrains).
    """
    from .latex_export import (typeset_and_verify, minimal_unsolved_document,
                               pdflatex_available)

    problems = load_problems(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    token_log = output_dir / "token_log.jsonl"
    token_log.write_text("", encoding="utf-8")  # init/truncate

    console.rule(f"[bold]First Proof Batch 2 — {len(problems)} problems")
    console.log(f"Model: {GEMINI_MODEL}  |  W={width} D={depth}  max_parallel={max_parallel}  "
                f"deadline={timeout_hours}h  search={'on' if search else 'off'}")
    if not pdflatex_available():
        console.log("[yellow]pdflatex not found — LaTeX output not compile-verified.[/yellow]")

    batch_dir = RUNS_DIR / f"firstproof_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    deadline_at = t0 + timeout_hours * 3600.0
    # Lower max_parallel (-var max_parallel=N, or FIRSTPROOF_MAX_PARALLEL=N)
    # if the AWS container shows RAM pressure under all-10-at-once.
    sem = asyncio.Semaphore(max(1, max_parallel))
    log_lock = asyncio.Lock()

    async def handle(problem: Problem) -> dict:
        async with sem:
            # Optional per-problem seed bundle: <input_dir>/seeds/<id>_seed.md
            # or <input_dir>/seeds/<id>_seed.txt. If present, threaded to the
            # main-run launcher as --additional-materials. Convention mirrors
            # the rework path: caller assembles the bundle out-of-band, this
            # function just picks it up.
            seed_dir = input_path.parent / "seeds"
            seed_path: Path | None = None
            for ext in (".md", ".txt"):
                candidate = seed_dir / f"{problem.id}_seed{ext}"
                if candidate.exists():
                    seed_path = candidate
                    break
            outcome, proc = await _launch_run(problem, width=width, depth=depth,
                                              search=search, batch_dir=batch_dir,
                                              additional_materials_path=seed_path)
            remaining = deadline_at - time.time()
            try:
                await asyncio.wait_for(proc.wait(), timeout=max(remaining, 1.0))
            except asyncio.TimeoutError:
                outcome.timed_out = True
                outcome.error = f"exceeded {timeout_hours}h deadline"
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                await asyncio.gather(proc.wait(), return_exceptions=True)
            outcome.returncode = proc.returncode
            if not outcome.timed_out:
                # Prefetch OpenAI scores on every BS-clean parent that
                # lacks one. This populates rec.openai_score so
                # state.top_solutions can apply the BS-clean + sum
                # ranking (Sanjeev 2026-05-28 PM rule 1(b)) without
                # excluding candidates that simply hadn't been seen
                # by the in-loop OAI gate. Async, parallel; non-fatal.
                try:
                    await _prefetch_oai_for_bs_clean(outcome.run_id)
                except Exception as _prefetch_err:
                    console.log(
                        f"[red]OAI prefetch for {outcome.run_id} failed: "
                        f"{_prefetch_err} — ship-time ranking falls back to "
                        f"bs_clean+score on parents that were already graded[/red]"
                    )
                _collect_run(outcome)

            store = RunStore(outcome.run_id)
            try:
                if outcome.proof_text.strip():
                    ts = await typeset_and_verify(
                        problem.statement, outcome.proof_text,
                        run_id=outcome.run_id, store=store,
                        solved=outcome.solved, score=outcome.score,
                        max_repairs=max_repairs,
                    )
                    latex, compiles, pages, note = ts.latex, ts.compiles, ts.pages, ts.note
                else:
                    latex = minimal_unsolved_document(outcome.error or "No proof was produced.")
                    compiles, pages, note = pdflatex_available(), None, "fallback unsolved document"
            finally:
                store.close()

            # Incremental deliverable: write the .tex as soon as it's ready.
            # This is the best-so-far provisional answer for this problem;
            # any subsequent grader3 / rework iteration only OVERWRITES
            # if it produces a better proof.
            (output_dir / f"{problem.id}.tex").write_text(latex, encoding="utf-8")
            async with log_lock:
                _append_run_token_log(outcome.run_id, problem.id, token_log)

            tokens = _run_token_stats(outcome.run_id)
            console.log(f"[green]{problem.id}.tex[/green] (solver) solved={outcome.solved} "
                        f"score={outcome.score:.1f} compiles={compiles} pages={pages} "
                        f"tokens={tokens['total']:,}")

            # ── Grader 3 auto-fire ────────────────────────────────────
            # Citation-hypothesis verifier runs after the solver completes
            # and BEFORE this problem's slot is released. Time-budgeted to
            # 25% of the remaining wallclock (capped at 25 min) so it never
            # eats too much of the batch budget. Failures are non-fatal.
            remaining_for_g3 = deadline_at - time.time()
            g3_budget = min(25 * 60, max(0.0, remaining_for_g3 * 0.25))
            g3_verdict = await _run_grader3_for_outcome(
                outcome, output_dir, time_budget_secs=g3_budget,
            )
            console.log(f"[cyan]{problem.id} grader3:[/cyan] verdict="
                        f"{g3_verdict.get('verdict')} "
                        f"n_pass={g3_verdict.get('n_pass')} "
                        f"reason={g3_verdict.get('reason') or g3_verdict.get('error') or ''}")

            # ── Rework loop (one iteration) ───────────────────────────
            # If grader3 didn't produce >=2 PASS proofs and there's still
            # significant wallclock left, launch a W=6 D=6 rework with
            # the grader3 feedback as additional_materials. If rework
            # produces a strictly better proof, OVERWRITE the .tex.
            # Otherwise the original best-so-far .tex (written above) stays.
            rework_info: dict = {"launched": False}
            n_pass = g3_verdict.get("n_pass") or 0
            min_rework_budget_secs = 30 * 60   # need >=30 min to attempt
            remaining_for_rework = deadline_at - time.time()
            if (n_pass < 2
                and g3_verdict.get("verdict") == "RAN"
                and remaining_for_rework > min_rework_budget_secs):
                addl_path = _build_rework_additional_materials(
                    outcome, g3_verdict, output_dir)
                if addl_path is not None:
                    rw_outcome, rw_proc = await _launch_rework_run(
                        problem, additional_materials_path=addl_path,
                        batch_dir=batch_dir,
                    )
                    rw_remaining = deadline_at - time.time()
                    try:
                        await asyncio.wait_for(
                            rw_proc.wait(), timeout=max(rw_remaining, 1.0))
                        rw_outcome.returncode = rw_proc.returncode
                        _collect_run(rw_outcome)
                    except asyncio.TimeoutError:
                        rw_outcome.timed_out = True
                        try:
                            rw_proc.terminate()
                        except ProcessLookupError:
                            pass
                        await asyncio.gather(rw_proc.wait(), return_exceptions=True)

                    rework_info = {
                        "launched": True,
                        "run_id": rw_outcome.run_id,
                        "score": round(rw_outcome.score, 2),
                        "solved": rw_outcome.solved,
                        "timed_out": rw_outcome.timed_out,
                    }
                    # Strictly-better check: rework wins only if its score
                    # is higher than the original. Tied scores keep the
                    # original (less risk).
                    if (not rw_outcome.timed_out
                        and rw_outcome.proof_text.strip()
                        and rw_outcome.score > outcome.score):
                        console.log(
                            f"[bold green]{problem.id}: REWORK IMPROVED "
                            f"score {outcome.score:.1f} -> {rw_outcome.score:.1f}; "
                            f"overwriting .tex[/bold green]")
                        store2 = RunStore(rw_outcome.run_id)
                        try:
                            ts2 = await typeset_and_verify(
                                problem.statement, rw_outcome.proof_text,
                                run_id=rw_outcome.run_id, store=store2,
                                solved=rw_outcome.solved, score=rw_outcome.score,
                                max_repairs=max_repairs,
                            )
                            (output_dir / f"{problem.id}.tex").write_text(
                                ts2.latex, encoding="utf-8")
                            latex, compiles, pages, note = (
                                ts2.latex, ts2.compiles, ts2.pages, ts2.note)
                            # Adopt the rework's outcome as the canonical
                            # answer for this problem.
                            outcome = rw_outcome
                            tokens = _run_token_stats(outcome.run_id)
                        finally:
                            store2.close()
                        async with log_lock:
                            _append_run_token_log(
                                outcome.run_id, problem.id, token_log)
                    else:
                        console.log(
                            f"[yellow]{problem.id}: rework did NOT improve "
                            f"({outcome.score:.1f} vs {rw_outcome.score:.1f}); "
                            f"keeping original .tex[/yellow]")

            return {
                "id": problem.id, "solved": outcome.solved, "score": round(outcome.score, 2),
                "latex": latex, "compiles": compiles, "pages": pages, "tokens": tokens,
                "run_id": outcome.run_id,
                "status": outcome.status or ("TIMEOUT" if outcome.timed_out else "UNKNOWN"),
                "notes": "; ".join(x for x in (outcome.error, note) if x),
                "grader3": g3_verdict,
                "rework": rework_info,
            }

    solutions = list(await asyncio.gather(*(handle(p) for p in problems)))

    totals = {"input": 0, "output": 0, "reasoning": 0, "total": 0}
    for sol in solutions:
        for k in totals:
            totals[k] += sol["tokens"][k]

    wall = time.time() - t0
    result = {
        "metadata": {
            "spec": "First Proof — Batch 2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": GEMINI_MODEL,
            "num_problems": len(problems),
            "num_solved": sum(1 for s in solutions if s["solved"]),
            "wall_time_seconds": round(wall, 1),
            "width": width, "depth": depth, "max_parallel": max_parallel,
            "search": search, "token_totals": totals,
        },
        "solutions": solutions,
    }
    (output_dir / "solutions.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    _print_summary(result)
    console.log(f"[green]Wrote {output_dir}/ — {len(problems)} .tex + token_log.jsonl + solutions.json[/green]")
    return result
