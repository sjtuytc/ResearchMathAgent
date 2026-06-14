"""CLI entry point — math-solver run / resume / list / status."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .config import GEMINI_API_KEY, GEMINI_MODEL
from .models import SearchMode
from .orchestrator import Orchestrator
from .state import RunStore, find_incomplete_runs, new_run_id

console = Console()


@click.group()
def cli():
    """Research Math Solver — autonomous pipeline for firstproof-level problems."""
    pass


@cli.command()
@click.argument("problem_file", type=click.Path(exists=True, path_type=Path))
@click.option("--run-id", default=None, help="Resume an existing run ID.")
@click.option("--width", "-W", default=None, type=int,
              help="Number of parallel solver calls per stage (default: WIDTH env var or 3).")
@click.option("--depth", "-D", default=None, type=int,
              help="Maximum number of stages (default: DEPTH env var or 10).")
@click.option("--search/--no-search", default=True, show_default=True,
              help="Enable arxiv search. Disable for parametric-only problems or debugging.")
@click.option("--search-before", default=None,
              help="If set (YYYY-MM-DD), arxiv search drops papers submitted on/after this date. "
                   "Use to prevent the source paper from leaking into retrieval when stress-testing "
                   "the pipeline on a known recent arxiv result.")
@click.option("--seed-run", default=None,
              help="Seed from an existing run: loads solutions + notebook by default.")
@click.option("--seed-stage", default=None, type=int,
              help="If set, load solutions only from this stage of the seed run.")
@click.option("--seed-min-score", default=3.0, type=float, show_default=True,
              help="Minimum score threshold when loading seed solutions.")
@click.option("--no-seed-notebook", is_flag=True, default=False,
              help="Skip seeding the notebook even when --seed-run is provided.")
@click.option("--label", default=None,
              help="Human-readable label written to README.md in the run directory.")
@click.option("--inject-pdf", "inject_pdfs", multiple=True,
              type=click.Path(exists=True, path_type=Path),
              help="Manually supply a PDF to attach to all agent calls (repeatable).")
@click.option("--max-stages", default=None, type=int,
              help="Stop after this many stages (for human-notebook mode).")
@click.option("--notebook-file", default=None, type=click.Path(path_type=Path),
              help="Use this file as the notebook instead of the AI notebook agent.")
@click.option("--seed-notebook-file", default=None, type=click.Path(exists=True, path_type=Path),
              help="Seed the AI notebook agent with content from this file (AI still updates it each stage).")
@click.option("--solver-brief", "solver_brief_file", default=None,
              type=click.Path(exists=True, path_type=Path),
              help="File with adversarial gap analysis / hints shown ONLY to solvers "
                   "(not to graders or BS detectors). Injected as an extra prev-attempt "
                   "entry visible from stage 1 onward. Graders and BS detectors in the "
                   "final gauntlet remain blind to this content.")
@click.option("--additional-materials", "additional_materials_file", default=None,
              type=click.Path(exists=True, path_type=Path),
              help="File whose content goes into the solver's labeled "
                   "**Additional Materials:** field on every call. Curated external "
                   "content (literature findings, gauntlet briefs). Solver-only "
                   "channel; graders and BS detectors do not see it.")
@click.option("--allow-child-spawn/--no-child-spawn", default=True, show_default=True,
              help="If the Conjecture Extractor yields exactly 1 conjecture mid-run, "
                   "terminate cleanly and spawn a detached supervisor that runs a child "
                   "pipeline on the conjecture, then launches a successor parent run "
                   "seeded with the child's results. The successor inherits this flag "
                   "and may itself spawn another child if it gets stuck again. The "
                   "supervisor forces --no-child-spawn on the CHILD subprocess so no "
                   "grandchildren are ever created (this is the only depth restriction).")
@click.option("--total-budget", default=None, type=int,
              help="Required. Hard cap on solver-cell consumption for this lineage "
                   "(parent + any child/successor spawns). The run schedules stages "
                   "while (cells_used + W) <= total_budget, then stops. One cell = "
                   "one solver call. Conjecture-stage rounds also consume from this "
                   "pool. --depth is a sanity ceiling on the stage count.")
@click.option("--lineage-parent-id", default=None,
              help="(internal) Set by supervisor when launching a successor parent run. "
                   "Records the original parent's run_id for lineage tracking.")
@click.option("--lineage-role", default=None,
              type=click.Choice(["parent", "child", "successor"]),
              help="(internal) Lineage role for record-keeping. Set by supervisor.")
def run(problem_file: Path, run_id: str | None, width: int | None,
        depth: int | None, search: bool, search_before: str | None,
        seed_run: str | None,
        seed_stage: int | None, seed_min_score: float,
        no_seed_notebook: bool, label: str | None,
        inject_pdfs: tuple[Path, ...],
        max_stages: int | None, notebook_file: Path | None,
        seed_notebook_file: Path | None,
        solver_brief_file: Path | None,
        additional_materials_file: Path | None,
        allow_child_spawn: bool, total_budget: int | None,
        lineage_parent_id: str | None, lineage_role: str | None):
    """
    Run the orchestrator on a problem.

    PROBLEM_FILE is a plain-text file containing the problem statement.
    Use --seed-run RUN_ID to bootstrap stage-1 context from a previous run's
    top solutions, enabling faster iteration on pipeline design.
    """
    _check_api_key()

    problem = problem_file.read_text(encoding="utf-8").strip()
    if not problem:
        console.print("[red]Problem file is empty.[/red]")
        sys.exit(1)

    if run_id is None:
        run_id = new_run_id()
        console.print(f"[bold]New run:[/bold] {run_id}")
    else:
        console.print(f"[bold]Resuming run:[/bold] {run_id}")

    import math_solver.config as cfg
    w = width or cfg.WIDTH
    d = depth or cfg.DEPTH
    console.print(f"[dim]Width={w}  Depth={d}  Search={'on' if search else 'off'}[/dim]")

    seed_outputs: list[str] = []
    seed_notebook: str | None = None
    if seed_run:
        seed_outputs = _load_seed_solutions(seed_run, min_score=seed_min_score,
                                            stage=seed_stage)
        stage_str = f" stage {seed_stage}" if seed_stage else ""
        console.print(f"[dim]Seeding from run {seed_run}{stage_str}: "
                      f"{len(seed_outputs)} solutions loaded.[/dim]")
        if not no_seed_notebook:
            seed_notebook = _load_seed_notebook(seed_run)
            if seed_notebook:
                console.print(f"[dim]Notebook seeded from run {seed_run}.[/dim]")
    if seed_notebook_file and not seed_notebook:
        seed_notebook = seed_notebook_file.read_text(encoding="utf-8")
        console.print(f"[dim]Notebook seeded from file {seed_notebook_file.name}.[/dim]")

    # Validate budget / spawn settings.
    # --total-budget is now consumption-driven: a hard cap on the lineage's
    # solver-cell consumption. The run schedules stages while
    # cells_used + W <= total_budget. --depth is a sanity ceiling.
    if total_budget is None:
        console.print(
            "[red]--total-budget is required. It is the total solver-cell cap "
            "for this lineage. The run schedules stages while "
            "cells_used + W <= total_budget; --depth is a sanity ceiling on "
            "the stage count.[/red]"
        )
        sys.exit(1)
    if total_budget < w:
        console.print(
            f"[red]--total-budget {total_budget} is less than W={w}, so no "
            f"stage can run. Aborting.[/red]"
        )
        sys.exit(1)
    if total_budget < w * d:
        console.print(
            f"[yellow]--total-budget {total_budget} is less than W×D = {w*d}; "
            f"the run will stop at the budget cap before reaching the depth "
            f"sanity ceiling (D={d}).[/yellow]"
        )

    store = RunStore(run_id)
    if label:
        readme = store.run_dir / "README.md"
        lineage_note = ""
        if lineage_parent_id:
            lineage_note = (
                f"**Lineage parent:** {lineage_parent_id}  \n"
                f"**Lineage role:** {lineage_role or 'unspecified'}  \n"
            )
        readme.write_text(
            f"# {label}\n\n"
            f"**Problem file:** {problem_file.name}  \n"
            f"**Run ID:** {run_id}  \n"
            f"**Width:** {w}  **Depth:** {d}  \n"
            f"{lineage_note}"
            f"**Allow child spawn:** {allow_child_spawn}  \n"
            f"**Total budget:** {total_budget if total_budget is not None else 'unset'}  \n\n"
            f"## Problem\n\n{problem}\n",
            encoding="utf-8",
        )
    search_before_dt: datetime | None = None
    if search_before:
        try:
            search_before_dt = datetime.strptime(search_before, "%Y-%m-%d")
        except ValueError:
            console.print(f"[red]--search-before must be YYYY-MM-DD; got {search_before!r}[/red]")
            sys.exit(1)
        console.print(f"[dim]Arxiv search restricted to papers submitted before {search_before}.[/dim]")

    orch = Orchestrator(
        run_id=run_id, problem=problem, store=store,
        allow_child_spawn=allow_child_spawn,
        total_budget=total_budget,
        lineage_parent_id=lineage_parent_id,
        lineage_role=lineage_role,
        problem_file=problem_file,
        search_before=search_before_dt,
        additional_materials_file=additional_materials_file,
    )
    search_mode = SearchMode.ENABLED if search else SearchMode.DISABLED

    injected = list(inject_pdfs) if inject_pdfs else None
    if injected:
        console.print(f"[dim]Injecting {len(injected)} PDF(s): "
                      f"{', '.join(p.name for p in injected)}[/dim]")

    if notebook_file:
        console.print(f"[dim]Human-notebook mode: reading from {notebook_file}[/dim]")
    if max_stages:
        console.print(f"[dim]Max stages: {max_stages}[/dim]")

    solver_brief: str | None = None
    if solver_brief_file:
        solver_brief = solver_brief_file.read_text(encoding="utf-8")
        console.print(f"[dim]Solver brief loaded from {solver_brief_file.name} "
                      f"({len(solver_brief)} chars) — solver-only channel.[/dim]")

    additional_materials: str | None = None
    if additional_materials_file:
        additional_materials = additional_materials_file.read_text(encoding="utf-8")
        console.print(f"[dim]Additional Materials loaded from "
                      f"{additional_materials_file.name} "
                      f"({len(additional_materials)} chars) — solver-only channel.[/dim]")

    asyncio.run(orch.run(width=w, depth=d, search_mode=search_mode,
                         seed_outputs=seed_outputs, seed_notebook=seed_notebook,
                         injected_pdf_paths=injected,
                         max_stages=max_stages,
                         notebook_file=notebook_file,
                         solver_brief=solver_brief,
                         additional_materials=additional_materials))
    store.close()


@cli.command(name="run-batch")
@click.argument("input_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", "output_json", default="solutions.json",
              type=click.Path(path_type=Path), show_default=True,
              help="Path for the output JSON (ten LaTeX solutions + token totals).")
@click.option("--width", "-W", default=None, type=int,
              help="Solvers per stage for each problem (default: WIDTH env var or 3).")
@click.option("--depth", "-D", default=None, type=int,
              help="Max stages per problem (default: DEPTH env var or 10).")
@click.option("--search/--no-search", default=False, show_default=True,
              help="Enable arxiv retrieval per problem (off by default; retrieval "
                   "is currently dormant and needs network access).")
@click.option("--timeout-hours", default=24.0, type=float, show_default=True,
              help="Wall-clock deadline for the whole batch (spec: within 24 hours).")
@click.option("--latex-repairs", default=3, type=int, show_default=True,
              help="Max pdflatex error-feedback repair passes per solution.")
def run_batch_cmd(input_json: Path, output_json: Path, width: int | None,
                  depth: int | None, search: bool, timeout_hours: float,
                  latex_repairs: int):
    """Run the full benchmark: one JSON of problems in, one JSON of LaTeX solutions out.

    INPUT_JSON contains the benchmark problems (each in complete, compilable
    LaTeX). Every problem is solved in parallel; each solution is typeset into an
    Overleaf-clean LaTeX document and packaged with per-call token totals. This
    is the entry point used by the AWS deployment.
    """
    _check_api_key()
    from .batch import run_batch
    import math_solver.config as cfg
    w = width or cfg.WIDTH
    d = depth or cfg.DEPTH
    asyncio.run(run_batch(
        input_json, output_json, width=w, depth=d, search=search,
        timeout_hours=timeout_hours, max_repairs=latex_repairs,
    ))


@cli.command()
@click.option("--input", "input_path", default="/data/input/input.json",
              type=click.Path(path_type=Path), show_default=True,
              help="Input JSON (First Proof mounts it read-only here).")
@click.option("--output-dir", "output_dir", default="/data/output",
              type=click.Path(path_type=Path), show_default=True,
              help="Directory for output files (First Proof retrieves everything here).")
@click.option("--width", "-W", default=None, type=int,
              help="Solvers per stage per problem (default: WIDTH env var or 4).")
@click.option("--depth", "-D", default=None, type=int,
              help="Max stages per problem (default: DEPTH env var or 4).")
@click.option("--max-parallel", default=None, type=int,
              help="Max problems solved concurrently (default: FIRSTPROOF_MAX_PARALLEL or 10, "
                   "which is sufficient for any plausible input on r7i.2xlarge / 64 GiB).")
@click.option("--timeout-hours", default=23.0, type=float, show_default=True,
              help="Internal deadline; keep < 24h so output is written before First Proof's hard kill.")
@click.option("--search/--no-search", default=False, show_default=True,
              help="In-solver arxiv retrieval per problem. OFF by default — "
                   "vanilla arxiv search proved unhelpful; literature comes via "
                   "grader3's SerpAPI fetch (post-solve), not in-solver search.")
@click.option("--latex-repairs", default=3, type=int, show_default=True,
              help="Max pdflatex error-feedback repair passes per solution.")
def firstproof(input_path: Path, output_dir: Path, width: int | None,
               depth: int | None, max_parallel: int | None, timeout_hours: float,
               search: bool, latex_repairs: int):
    """First Proof Batch-2 container entrypoint.

    Reads /data/input/input.json and writes per-problem <id>.tex (incrementally),
    a token_log.jsonl, and a solutions.json to /data/output/. GEMINI_API_KEY is
    read from the environment (First Proof injects it via the secrets file). This
    is the Docker image's CMD.
    """
    _check_api_key()
    import os
    from .batch import run_firstproof
    w = width or int(os.environ.get("WIDTH", "4"))
    d = depth or int(os.environ.get("DEPTH", "4"))
    mp = max_parallel or int(os.environ.get("FIRSTPROOF_MAX_PARALLEL", "10"))
    asyncio.run(run_firstproof(
        input_path, output_dir, width=w, depth=d, search=search,
        timeout_hours=timeout_hours, max_parallel=mp, max_repairs=latex_repairs,
    ))


@cli.command()
def list_runs():
    """List all runs and their status."""
    from .config import RUNS_DIR
    if not RUNS_DIR.exists():
        console.print("No runs directory found.")
        return

    table = Table(title="Runs")
    table.add_column("Run ID")
    table.add_column("Status")
    table.add_column("Rounds")
    table.add_column("Best Score")
    table.add_column("Papers")

    for d in sorted(RUNS_DIR.iterdir()):
        if not d.is_dir():
            continue
        store = RunStore(d.name)
        state = store.load_run_state()
        store.close()
        if state:
            nb = state.root_notebook
            table.add_row(
                d.name,
                state.status.value,
                str(state.total_rounds),
                f"{nb.best_score:.2f}" if nb else "—",
                str(len(state.papers)),
            )

    console.print(table)


@cli.command()
@click.argument("run_id")
def status(run_id: str):
    """Print detailed status for a run."""
    store = RunStore(run_id)
    state = store.load_run_state()
    if state is None:
        console.print(f"[red]Run {run_id} not found.[/red]")
        store.close()
        return

    console.print(f"[bold]Run:[/bold] {run_id}")
    console.print(f"[bold]Status:[/bold] {state.status.value}")
    console.print(f"[bold]Rounds:[/bold] {state.total_rounds}")
    console.print(f"[bold]Papers:[/bold] {len(state.papers)}")

    nb = state.root_notebook
    if nb:
        console.print(f"[bold]Best score:[/bold] {nb.best_score:.2f}")
        console.print(f"[bold]Conjectures:[/bold] {len(nb.conjectures)}")
        open_c = [c for c in nb.conjectures if c.status == "OPEN"]
        console.print(f"  Open: {len(open_c)}")

    tel = store.telemetry_summary()
    if tel:
        console.print("[bold]Telemetry:[/bold]")
        for event, count in sorted(tel.items()):
            console.print(f"  {event}: {count}")

    store.close()


@cli.command()
def check_incomplete():
    """Warn about runs that are neither DONE nor FAILED."""
    incomplete = find_incomplete_runs()
    if not incomplete:
        console.print("[green]No incomplete runs.[/green]")
    else:
        console.print(f"[yellow]Incomplete runs ({len(incomplete)}):[/yellow]")
        for rid in incomplete:
            console.print(f"  {rid}")
        console.print("Resume with: math-solver run PROBLEM_FILE --run-id <id>")


def _load_seed_notebook(seed_run_id: str) -> str | None:
    """Load the final notebook content from a previous run."""
    seed_store = RunStore(seed_run_id)
    state = seed_store.load_run_state()
    seed_store.close()
    if state is None or state.root_notebook is None:
        console.print(f"[yellow]No notebook found in seed run {seed_run_id}.[/yellow]")
        return None
    return state.root_notebook.content


def _load_seed_solutions(
    seed_run_id: str,
    min_score: float = 3.0,
    stage: int | None = None,
) -> list[str]:
    """Load Part 3 texts from a previous run's solutions above min_score.

    If stage is given, load only from that stage.
    If stage is None (default), auto-select the *last* stage only — early-stage
    proofs are untrustworthy and should not pollute the seed context.
    """
    from .orchestrator import _extract_part3
    from .models import SolutionRecord

    seed_store = RunStore(seed_run_id)
    state = seed_store.load_run_state()
    seed_store.close()
    if state is None:
        console.print(f"[red]Seed run {seed_run_id} not found.[/red]")
        return []

    # Auto-select last stage when no explicit stage is given
    if stage is None and state.all_solutions:
        stage = max(s.stage for s in state.all_solutions)
        console.print(f"[dim]Auto-selecting last stage ({stage}) for seed.[/dim]")

    eligible = [
        s for s in state.all_solutions
        if s.score >= min_score and (stage is None or s.stage == stage)
    ]
    if not eligible:
        label = f"stage {stage}" if stage else "any stage"
        console.print(f"[yellow]No solutions above score {min_score} at {label} "
                      f"in seed run {seed_run_id}.[/yellow]")
        return []

    # Deduplicate by (stage, solver_index), keep highest-scored record per solver
    best: dict[tuple[int, int], SolutionRecord] = {}
    for sol in eligible:
        key = (sol.stage, sol.solver_index)
        if key not in best or sol.score > best[key].score:
            best[key] = sol

    ranked = sorted(best.values(), key=lambda s: s.score, reverse=True)
    return [_extract_part3(sol.output) or sol.output for sol in ranked]


def _check_api_key() -> None:
    if not GEMINI_API_KEY:
        console.print(
            "[red]GEMINI_API_KEY is not set. "
            "Export it as an environment variable before running.[/red]"
        )
        sys.exit(1)
    console.print(f"[dim]Model: {GEMINI_MODEL}[/dim]")


if __name__ == "__main__":
    cli()
