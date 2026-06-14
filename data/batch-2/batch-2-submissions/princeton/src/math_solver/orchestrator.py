"""
Orchestrator — simplified width×depth loop.

Each stage d (1..D):
  1. Run W solvers in parallel.
     Each solver receives: Problem + Notebook Level 1
                         + up to PREV_CTX_SIZE randomly sampled raw outputs
                           from the previous stage (independent sample per solver).
  2. Grade all W outputs (stopping-condition check only — not for selection).
  3. If any grader reports complete (7/7): done.
  4. Update notebook with all W solver outputs + grader feedback.
  5. If notebook emits search queries: two-stage arxiv→triage→PDF fetch,
     then Paper Hunter reads new papers and injects findings back to notebook.
     Search only fires when the notebook explicitly requests it.
  6. Store all W raw outputs as context for stage d+1.

Stopping: complete solution found, or depth D exhausted.
"""
from __future__ import annotations

import asyncio
import os
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console

from .agents.bs_detector import bs_detect_all_parallel
from .agents.extractor import run_conjecture_extractor
from .agents.grader import _bs_is_clean, grade_all_parallel, verify_solution
from .agents.notebook import notebook_update
from .agents.paper_hunter import run_paper_hunter
from .agents.solver import run_solver, run_solvers_parallel
from .agents.triage import run_triage
from .gemini import call_gemini
from .config import (
    ARXIV_MAX_RESULTS,
    CONJECTURE_ROUNDS,
    DEPTH,
    MAX_KEEP_PAPERS,
    MAX_TRIAGE_REFUSALS,
    PREV_CTX_SIZE,
    WIDTH,
)
from .models import (
    AgentCall,
    Conjecture,
    NotebookState,
    RunState,
    RunStatus,
    SearchMode,
    SearchQuery,
    SolutionRecord,
)
from .search import build_arxiv_query, download_pdf, search_arxiv
from .state import RunStore
from .telemetry import Telemetry

console = Console()


class Orchestrator:
    def __init__(
        self,
        run_id: str,
        problem: str,
        store: RunStore,
        *,
        allow_child_spawn: bool = False,
        total_budget: int | None = None,
        lineage_parent_id: str | None = None,
        lineage_role: str | None = None,
        problem_file: Path | None = None,
        search_before: datetime | None = None,
        additional_materials_file: Path | None = None,
    ):
        self.run_id = run_id
        self.problem = problem
        self.store = store
        self.tel = Telemetry(run_id, store)
        # ── Lineage / child-spawn controls ──────────────────────────────────
        self.allow_child_spawn = allow_child_spawn
        self.total_budget = total_budget           # remaining budget for this lineage
        self.lineage_parent_id = lineage_parent_id  # original parent's run_id, if any
        self.lineage_role = lineage_role            # "parent" | "child" | "successor"
        self.problem_file = problem_file            # path to parent problem; needed for successor
        self.search_before = search_before          # if set, arxiv search drops papers submitted on/after this date
        self.additional_materials_file = additional_materials_file  # propagated to child/successor via supervisor manifest

    # ─────────────────────────────────────────────────────────────────────────
    # Entry point
    # ─────────────────────────────────────────────────────────────────────────

    async def run(
        self,
        *,
        width: int = WIDTH,
        depth: int = DEPTH,
        search_mode: SearchMode = SearchMode.ENABLED,
        seed_outputs: list[str] | None = None,
        seed_notebook: str | None = None,   # pre-built notebook content to skip cold init
        injected_pdf_paths: list[Path] | None = None,  # manually supplied PDFs
        max_stages: int | None = None,       # stop after this many stages (None = depth)
        notebook_file: Path | None = None,   # bypass AI notebook agent; read/write from file
        solver_brief: str | None = None,     # adversarial gap analysis shown to solvers only
        additional_materials: str | None = None,  # curated external content for solver's Additional Materials field
    ) -> RunState:
        state = self.store.load_run_state()
        if state is None:
            state = RunState(run_id=self.run_id, problem=self.problem)

        # Stash on self so helpers (notably the conjecture-stage grader call)
        # can build the vetted-facts channel without re-reading the file.
        self._additional_materials_runtime: str = additional_materials or ""

        self._warn_disk(state)

        # ── Register manually injected PDFs ─────────────────────────────────
        if injected_pdf_paths:
            self._register_injected_pdfs(state, injected_pdf_paths)

        # ── Init notebook ────────────────────────────────────────────────────
        if state.status == RunStatus.INIT:
            state.root_notebook = NotebookState(notebook_id="ROOT", parent_id=None)
            # Populate paper_library with any injected PDFs registered above
            for key in state.papers:
                citation_key = f"arxiv:{key}"
                if citation_key not in state.root_notebook.paper_library:
                    state.root_notebook.paper_library.append(citation_key)

            if notebook_file is not None:
                # ── Human-notebook mode: read content from file, skip AI ─────
                state.root_notebook.content = notebook_file.read_text(encoding="utf-8")
                console.log(f"[cyan]Notebook loaded from {notebook_file}[/cyan]")
            else:
                # ── AI notebook mode ─────────────────────────────────────────
                nb_out = await notebook_update(
                    problem=self.problem,
                    paper_library=state.paper_library_text(state.root_notebook),
                    notebook_id="ROOT",
                    parent_id="ROOT",
                    current_notebook=seed_notebook if seed_notebook else "(new notebook)",
                    new_materials="(continuing from seeded run)" if seed_notebook
                                  else "(initial setup — no solver output yet)",
                    mode="UPDATE",
                    search_mode=search_mode,
                    run_id=self.run_id,
                    store=self.store,
                )
                state.root_notebook.content = nb_out.content
                if seed_notebook:
                    console.log("[dim]Notebook seeded and reformatted.[/dim]")
                if search_mode == SearchMode.ENABLED and nb_out.search_queries:
                    await self._handle_search(state, state.root_notebook,
                                              nb_out.search_queries, search_mode)

                # ── Upfront Paper Hunter pass for injected PDFs ──────────────
                injected_paths = self._pdf_paths(state, state.root_notebook)
                if injected_paths:
                    console.log(
                        f"[cyan]Running Paper Hunter on {len(injected_paths)} "
                        f"injected PDF(s) before stage 1...[/cyan]"
                    )
                    findings = await run_paper_hunter(
                        problem=self.problem,
                        notebook_full=state.root_notebook.content,
                        paper_library=state.paper_library_text(state.root_notebook),
                        hints="These papers have been manually supplied as the primary "
                              "references for this problem. Read them in full and extract "
                              "every definition, theorem, and technique that bears on the "
                              "problem statement.",
                        notebook_id="ROOT",
                        run_id=self.run_id,
                        pdf_paths=injected_paths,
                        store=self.store,
                    )
                    nb_out2 = await notebook_update(
                        problem=self.problem,
                        paper_library=state.paper_library_text(state.root_notebook),
                        notebook_id="ROOT",
                        parent_id="ROOT",
                        current_notebook=state.root_notebook.content,
                        new_materials=f"[Paper Hunter — upfront reading of injected papers]\n{findings}",
                        mode="UPDATE",
                        search_mode=SearchMode.DISABLED,
                        run_id=self.run_id,
                        store=self.store,
                    )
                    state.root_notebook.content = nb_out2.content
                    console.log("[cyan]Notebook updated with paper findings.[/cyan]")

            state.status = RunStatus.SOLVING
            self.store.save_run_state(state)

        # ── Main loop ────────────────────────────────────────────────────────
        nb = state.root_notebook
        assert nb is not None

        # Strip process logs from seeded outputs — only pass proof blocks forward
        prev_stage_outputs: list[str] = [
            _extract_part3(s) or s for s in (seed_outputs or [])
        ]
        # Inject adversarial gap analysis (solver-only channel) as an extra
        # prev-stage entry. Solvers see it via run_solver's _build_additional_materials;
        # graders and BS detectors do NOT see it. They run fresh on the new proofs.
        if solver_brief:
            prev_stage_outputs.append(
                "[ADVERSARIAL GAP ANALYSIS — read carefully; address every item]\n"
                + solver_brief.strip()
            )
            console.log("[dim]Solver brief injected as extra prev-attempt entry "
                        "(solvers-only channel).[/dim]")
        effective_depth = min(depth, max_stages) if max_stages else depth
        # Stages where stage-median grader score failed to improve over the
        # prior stage. Median (not max) because the pipeline self-corrects in
        # the width dimension — a single hallucinated high grade propagates
        # as ~3 corrupted seeds into the next stage, gets honestly graded
        # low, and pulls that stage's median back down. Rolling max
        # (nb.best_score) is permanently pinned by the bogus grade and so
        # can't be the progress signal. nb.best_score is retained for
        # operator-facing telemetry only.
        no_progress_count: int = 0
        conjecture_round: int = 0   # increments each time the extractor fires
        prev_stage_median: float | None = None

        # Consumption-driven scheduling: schedule the next stage while there
        # are budget cells available. `depth` is the sanity ceiling — the
        # outer cap that prevents runaway loops if the budget is somehow
        # unbounded or progress signals never converge. One cell = one solver
        # call; cells consumed so far = len(state.all_solutions).
        d = 0
        while True:
            cells_used = len(state.all_solutions)
            if self.total_budget is not None and cells_used + width > self.total_budget:
                console.log(
                    f"[bold cyan]Budget cap reached: cells used "
                    f"{cells_used}/{self.total_budget}; the next stage would need "
                    f"{width} more. Stopping.[/bold cyan]"
                )
                break
            if d >= effective_depth:
                console.log(
                    f"[bold cyan]Depth sanity ceiling reached (D={effective_depth}); "
                    f"stopping even though budget remains.[/bold cyan]"
                )
                break
            d += 1
            console.rule(f"[bold]Stage {d} (W={width}, cells {cells_used}/{self.total_budget})")

            # ── Skip stages already fully recorded in state ───────────────────
            completed_stages = {s.stage for s in state.all_solutions}
            if d in completed_stages:
                console.log(f"[dim]Stage {d}: already complete in state — skipping.[/dim]")
                stage_sols = [s for s in state.all_solutions if s.stage == d]
                prev_stage_outputs = [
                    _extract_part3(s.output) or s.output for s in stage_sols
                ]
                continue

            # ── Recover any already-completed calls for partial stages ────────
            cached_solvers = self.store.load_stage_calls(d, "solver_")
            cached_bs     = self.store.load_stage_calls(d, "bs_detector_")
            cached_graders = self.store.load_stage_calls(d, "grader_")
            if cached_solvers:
                console.log(f"[dim]Stage {d}: recovering {len(cached_solvers)} "
                            f"cached solver call(s).[/dim]")
            if cached_bs:
                console.log(f"[dim]Stage {d}: recovering {len(cached_bs)} "
                            f"cached BS detector call(s).[/dim]")
            if cached_graders:
                console.log(f"[dim]Stage {d}: recovering {len(cached_graders)} "
                            f"cached grader call(s).[/dim]")

            # 1. Run W solvers (or recover from cache)
            solver_calls = await run_solvers_parallel(
                problem=self.problem,
                notebook_level1=nb.content,
                prev_stage_outputs=prev_stage_outputs,
                width=width,
                prev_ctx_size=PREV_CTX_SIZE,
                stage=d,
                notebook_id="ROOT",
                run_id=self.run_id,
                cached_calls=cached_solvers or None,
                additional_materials=additional_materials or "(none)",
                pdf_paths=self._pdf_paths(state, nb),
                store=self.store,
            )

            # 2a. BS-detect first — flags feed into the grader to prevent
            #     the grader ratifying hallucinated steps
            bs_results = await bs_detect_all_parallel(
                problem=self.problem,
                solver_calls=solver_calls,
                stage=d,
                notebook_id="ROOT",
                run_id=self.run_id,
                additional_materials=state.references_text(nb),
                cached_calls=cached_bs or None,
                store=self.store,
            )

            # 2b. Grade with BS flags pre-loaded (stopping-condition check only)
            # Grader sees the vetted-facts channel only — VFs + SNTs from the
            # notebook + paper library + summarized .md references. OCs / RHs /
            # IPTs / PSes / prose stay in the BS detector's channel above.
            # See docs/grader_contamination_and_provenance.md.
            grader_results = await grade_all_parallel(
                problem=self.problem,
                solver_calls=solver_calls,
                stage=d,
                notebook_id="ROOT",
                run_id=self.run_id,
                additional_materials=state.vetted_facts_text(
                    nb, self._additional_materials_runtime
                ),
                bs_results=bs_results,
                cached_calls=cached_graders or None,
                pdf_paths=self._pdf_paths(state, nb),
                store=self.store,
            )
            scores = [g.score for g in grader_results]
            self.tel.solver_round("ROOT", d, scores)
            console.log(f"Scores: {[f'{s:.1f}' for s in scores]}")

            # Record all graded outputs for final ranking
            for call, grade in zip(solver_calls, grader_results):
                state.all_solutions.append(SolutionRecord(
                    stage=d,
                    solver_index=call.inputs.get("solver_index", 0),
                    score=grade.score,
                    output=call.output,
                    grader_feedback=grade.feedback,
                ))

            # 3. Stopping condition — ensemble exit check on any ≥5 score (parallel)
            #    ≥5: 2 draws + always-run aggregator (extended grading)
            #    7/7: 3 draws, all must pass, then aggregator (full exit check)
            ensemble_feedback: list[str] = []   # aggregator reports from failed checks
            complete_pairs = [
                (call, grade)
                for call, grade in zip(solver_calls, grader_results)
                if grade.score >= 5.0
            ]
            if complete_pairs:
                solver_indices = [c.inputs.get("solver_index", "?") for c, _ in complete_pairs]
                has_sevens = [g.is_complete for _, g in complete_pairs]
                console.log(
                    f"[yellow]Solvers {solver_indices} scored ≥5 — "
                    f"running extended grading (2 draws + aggregator each)...[/yellow]"
                )
                verify_tasks = [
                    verify_solution(
                        problem=self.problem,
                        solver_output=call.output,
                        solver_index=call.inputs.get("solver_index", 0),
                        notebook_id="ROOT",
                        run_id=self.run_id,
                        additional_materials=state.vetted_facts_text(
                            nb, self._additional_materials_runtime
                        ),
                        pdf_paths=self._pdf_paths(state, nb),
                        store=self.store,
                        n_draws=2,
                        always_aggregate=True,
                    )
                    for call, _ in complete_pairs
                ]
                verify_results = await asyncio.gather(*verify_tasks)
                for (call, _), (confirmed, conf_grades, bs_feedback) in zip(complete_pairs, verify_results):
                    si = call.inputs.get("solver_index", 0)
                    # Compute BS verdict once per solver from the gauntlet's
                    # consolidated bs aggregator feedback.
                    bs_clean_verdict = _bs_is_clean(bs_feedback)
                    # The aggregator's verdict is the authoritative score for
                    # solver si on stage d. Demote (or confirm) the initial-pass
                    # SolutionRecord with this score so top_solutions() ranks
                    # gauntlet-adjudicated proofs at their TRUE score. Without
                    # this, the initial-pass 7/7 record outranks the gauntlet's
                    # 3/7 verdict and a rejected proof surfaces as the run's
                    # top solution. Observed on Q2 run 7c5e48e8486e
                    # (2026-05-25): solver_5 stage-4 initial 7/7, gauntlet
                    # agg 3/7 — final_score reported as 7 anyway.
                    agg_result = conf_grades[-1]  # last element is the aggregator
                    for rec in reversed(state.all_solutions):
                        if (rec.stage == d and rec.solver_index == si
                                and rec.stage_type == "parent"):
                            rec.score = agg_result.score
                            rec.bs_clean = bs_clean_verdict
                            rec.grader_feedback = agg_result.feedback
                            break
                    # Mutate scores[si] too, so nb.best_score updates below
                    # see the gauntlet-adjusted value rather than the initial
                    # grader's pass.
                    if 0 <= si < len(scores):
                        scores[si] = agg_result.score
                    # Persist the per-draw + aggregator grader outputs for
                    # diagnostics, but stamp them stage_type="gauntlet_draw"
                    # so top_solutions() (which filters to "parent") doesn't
                    # surface high-scoring draws as headline solutions.
                    for cg in conf_grades:
                        state.all_solutions.append(SolutionRecord(
                            stage=d,
                            solver_index=si,
                            score=cg.score,
                            output=call.output,
                            grader_feedback=cg.feedback,
                            bs_clean=bs_clean_verdict,
                            stage_type="gauntlet_draw",
                        ))
                    if confirmed:
                        # OpenAI cross-model gate (Sanjeev 2026-05-28): a
                        # gauntlet-confirmed 7/7 only triggers exit if a
                        # different model (GPT-5.5 Pro) also rates the proof
                        # ≥7. Tonight's disagreement study showed Gemini's
                        # gauntlet locks in systematic per-model bias: 4
                        # Gemini calls all agree on a 7 that OpenAI scores
                        # at 3. Kill switch: OPENAI_GATE_DISABLED=1.
                        openai_score: float | None = None
                        openai_feedback_text: str | None = None
                        if os.environ.get("OPENAI_GATE_DISABLED") != "1":
                            try:
                                # Imported here (not at module top) to keep the
                                # scripts/ dependency optional — the gate is
                                # off-by-default in dev runs without the key.
                                import sys as _sys
                                from pathlib import Path as _Path
                                _scripts = _Path(__file__).resolve().parents[2] / "scripts"
                                if _scripts.exists() and str(_scripts) not in _sys.path:
                                    _sys.path.insert(0, str(_scripts))
                                from openai_grader import grade_proof as _oai_grade  # type: ignore
                                proof_text = await _extract_part3_async(call.output)
                                oai_result = await _oai_grade(
                                    problem=self.problem,
                                    proof=proof_text,
                                )
                                openai_score = oai_result.score
                                # Strip Council deliberation on harvest — same
                                # prompt as Gemini grader, so same Part 1 prose.
                                from .agents.grader import _extract_critique_only
                                openai_feedback_text = await _extract_critique_only(
                                    oai_result.output
                                )
                                console.log(
                                    f"[cyan]OpenAI gate (Solver {si}): "
                                    f"{openai_score}/7[/cyan]"
                                )
                            except Exception as _gate_err:
                                console.log(
                                    f"[red]OpenAI gate (Solver {si}) failed: "
                                    f"{_gate_err} — treating as gauntlet-only "
                                    f"decision (no demote, no exit-block)[/red]"
                                )
                                openai_score = None

                        if openai_score is not None and openai_score >= 7:
                            # Record on the parent for downstream consumers
                            # (Grader 3's critique-informed gap_report) even
                            # on the happy-path exit.
                            for rec in reversed(state.all_solutions):
                                if (rec.stage == d and rec.solver_index == si
                                        and rec.stage_type == "parent"):
                                    rec.openai_score = openai_score
                                    if openai_feedback_text:
                                        rec.openai_feedback = openai_feedback_text
                                    break
                            console.log(
                                f"[green]Ensemble + OpenAI confirmed 7/7 "
                                f"(Solver {si}) — solution verified, stopping.[/green]"
                            )
                            state.status = RunStatus.DONE
                            self.store.save_run_state(state)
                        elif openai_score is not None and openai_score >= 0:
                            # Do NOT demote rec.score (2026-05-28 PM): ship-time
                            # selection uses sum(rec.score, rec.openai_score)
                            # to pick the best BS-clean proof, which requires
                            # the raw gauntlet score on the record. Demoting
                            # to min() would lose the gauntlet score and the
                            # sum would double-count openai.
                            # The local scores[si] DOES still get demoted so
                            # the in-loop progress signal (stage_median for
                            # the conjecture-extractor trigger) tracks the
                            # cross-model effective score, not the inflated
                            # gauntlet.
                            eff_score = min(agg_result.score, openai_score)
                            for rec in reversed(state.all_solutions):
                                if (rec.stage == d and rec.solver_index == si
                                        and rec.stage_type == "parent"):
                                    rec.openai_score = openai_score
                                    if openai_feedback_text:
                                        rec.openai_feedback = openai_feedback_text
                                    break
                            if 0 <= si < len(scores):
                                scores[si] = eff_score
                            console.log(
                                f"[yellow]OpenAI gate (Solver {si}) blocked exit "
                                f"(gauntlet={agg_result.score}, openai={openai_score}) — "
                                f"continuing; rec.score kept at gauntlet, in-loop "
                                f"signal demoted to {eff_score}.[/yellow]"
                            )
                            ensemble_feedback.append(
                                f"[OpenAI Grader (cross-model) — Solver {si} "
                                f"stage {d}, score {openai_score}/7]\n"
                                f"{openai_feedback_text or '(no feedback text)'}"
                            )
                        else:
                            # OpenAI unavailable (kill-switch or call failure):
                            # fall back to original behavior — exit on gauntlet
                            # confirmation alone. Safer than blocking exit when
                            # we have no second-opinion signal.
                            console.log(
                                f"[green]Ensemble confirmed 7/7 (Solver {si}) — "
                                f"OpenAI gate unavailable, exiting on gauntlet "
                                f"alone.[/green]"
                            )
                            state.status = RunStatus.DONE
                            self.store.save_run_state(state)
                    else:
                        agg = conf_grades[-1]
                        console.log(f"[yellow]Solver {si} ensemble score {agg.score:.1f}/7 — "
                                    f"aggregator found issues, continuing.[/yellow]")
                        # Grader 1: Areas for Improvement + Scaffolding Questions, no score
                        grader_critique = await _extract_grader_critique(agg.feedback)
                        if grader_critique:
                            ensemble_feedback.append(
                                f"[Grader 1 — Solver {si} stage {d}]\n"
                                f"{grader_critique}"
                            )
                        # Grader 2: BS interventions as a hard-blocker grader report, no score
                        bs_interventions = _extract_bs_interventions(bs_feedback)
                        if bs_interventions:
                            ensemble_feedback.append(
                                f"[Grader 2 — Solver {si} stage {d}]\n"
                                f"{bs_interventions}"
                            )
            if state.status == RunStatus.DONE:
                # Capture stage counter and best_score before exiting the
                # loop. Without this the post-loop save emits
                # final_score=0.0 / total_rounds=0 (observed on run
                # 0b9b2ba7eaac, 2026-05-20). Also persists verify-gauntlet
                # records appended for solvers processed after the first
                # dual-gate confirmation.
                state.total_rounds = d
                nb.best_score = max(nb.best_score, max(scores) if scores else 0.0)
                self.store.save_run_state(state)
                break

            # 4. Notebook UPDATE (or write bundle for human-notebook mode)
            new_materials = await _format_stage_bundle(
                solver_calls, grader_results, d, bs_results,
                all_solutions=state.all_solutions,
            )
            if ensemble_feedback:
                new_materials += "\n\n" + "\n\n".join(ensemble_feedback)

            # Always write the stage bundle to disk for inspection / human notebook
            bundle_path = self.store.run_dir / f"stage_{d}_bundle.txt"
            bundle_path.write_text(new_materials, encoding="utf-8")
            console.log(f"[dim]Stage bundle written to {bundle_path}[/dim]")

            if notebook_file is not None:
                # Human-notebook mode: skip AI update; notebook stays as-is until
                # next invocation provides an updated --notebook-file
                console.log(
                    "[cyan]Human-notebook mode: skipping AI notebook update. "
                    "Provide updated --notebook-file on next invocation.[/cyan]"
                )
                nb.round = d
                nb.best_score = max(nb.best_score, max(scores) if scores else 0.0)
            else:
                nb_out = await notebook_update(
                    problem=self.problem,
                    paper_library=state.paper_library_text(nb),
                    notebook_id="ROOT",
                    parent_id="ROOT",
                    current_notebook=nb.content,
                    new_materials=new_materials,
                    mode="UPDATE",
                    search_mode=search_mode,
                    round=d,
                    run_id=self.run_id,
                    store=self.store,
                )
                nb.content = nb_out.content
                nb.round = d
                prev_best = nb.best_score
                nb.best_score = max(nb.best_score, max(scores) if scores else 0.0)

                # Progress gate: stage-over-stage median delta (not all-time
                # max). See no_progress_count comment near the loop top.
                # Threshold > 0.5 filters single-position wobble: with W=4
                # and integer grader scores, possible medians are spaced by
                # 0.5, so a 0.5 step is one solver moving one point at the
                # middle position — grader-noise-sized, not real progress.
                stage_median = statistics.median(scores) if scores else 0.0
                if prev_stage_median is None or stage_median > prev_stage_median + 0.5:
                    no_progress_count = 0
                else:
                    no_progress_count += 1
                prev_stage_median = stage_median

                self.tel.notebook_update(
                    "ROOT", d, nb.best_score,
                    progress=nb.best_score > prev_best,
                )

                # 4b. Conjecture Extractor — fires when stage-median has
                #     failed to improve for 2 consecutive stages. Synthesises
                #     a rigorous proof skeleton with explicit conjectures for
                #     the gaps, injected as notebook material.
                if no_progress_count >= 2:
                    conjecture_round += 1
                    console.log(
                        f"[cyan]Stage {d}: {no_progress_count} stages without improvement — "
                        f"firing {width} parallel Conjecture Extractors "
                        f"(conjecture round {conjecture_round})...[/cyan]"
                    )
                    _grader_critiques = await asyncio.gather(*[
                        _extract_grader_critique(gr.feedback) for gr in grader_results
                    ])
                    grader_reports_text = "\n\n".join(
                        f"[Solver {gr.solver_index}]\n{crit}"
                        for gr, crit in zip(grader_results, _grader_critiques)
                    )
                    # Also pass the ensemble blocker reports (Grader 2 / BS interventions)
                    # so the extractor sees what specifically prevented acceptance.
                    if ensemble_feedback:
                        grader_reports_text += (
                            "\n\n---\n\n[Acceptance blockers — steps the proof "
                            "cannot be accepted without addressing]\n"
                            + "\n\n".join(ensemble_feedback)
                        )
                    # Run W parallel extractor draws (each picks a random subset of
                    # solvers internally), then cluster to pick the two most-distinct
                    # representatives. Aggregate the two selected into a single
                    # ext_out surrogate so downstream Mode A / Mode B logic works.
                    from .agents.cluster import run_cluster, parse_top_two_pairs
                    from types import SimpleNamespace
                    # Format currently-active (OPEN) conjectures so the extractor's
                    # Auditor rule (v) can reject technique-family duplicates on
                    # round-2+ extraction. First round: none.
                    open_conjectures = [c for c in nb.conjectures if c.status == "OPEN"]
                    if open_conjectures:
                        active_tuples_text = "\n\n".join(
                            f"[{c.id}] statement: {c.statement}\n"
                            f"     negation: {c.negation}"
                            for c in open_conjectures
                        )
                    else:
                        active_tuples_text = "(none — initial extraction)"
                    ext_outs = await asyncio.gather(*[
                        run_conjecture_extractor(
                            problem=self.problem,
                            notebook_level1=nb.content,
                            solver_calls=solver_calls,
                            grader_reports=grader_reports_text,
                            active_tuples=active_tuples_text,
                            notebook_id="ROOT",
                            run_id=self.run_id,
                            store=self.store,
                        )
                        for _ in range(width)
                    ])
                    cluster_raw = await run_cluster(
                        problem=self.problem,
                        candidates=[eo.raw for eo in ext_outs],
                        notebook_id="ROOT",
                        run_id=self.run_id,
                        store=self.store,
                    )
                    top_pairs = parse_top_two_pairs(cluster_raw)
                    if not top_pairs:
                        # Parsing failed — fall back to the first two extractor draws,
                        # taking each draw's first conjecture as load-bearing.
                        top_pairs = [(i, 0) for i in range(min(2, len(ext_outs)))]
                        console.log(f"[yellow]Cluster parse empty; falling back to first {len(top_pairs)} draws (conj 0).[/yellow]")
                    # Resolve each (ext_idx, conj_idx) to the actual load-bearing
                    # Conjecture. Out-of-range conj_idx (e.g. parse error or
                    # extractor returned fewer conjectures than the cluster
                    # claimed) falls back to index 0 of that draw.
                    selected_conjectures: list[Conjecture] = []
                    selected_pairs_resolved: list[tuple[int, int]] = []
                    for ei, ci in top_pairs:
                        if ei < 0 or ei >= len(ext_outs):
                            continue
                        draw_conjs = ext_outs[ei].conjectures
                        if not draw_conjs:
                            continue
                        if ci >= len(draw_conjs):
                            ci = 0
                        selected_conjectures.append(draw_conjs[ci])
                        selected_pairs_resolved.append((ei, ci))
                    console.log(
                        f"[cyan]Cluster picked {len(selected_pairs_resolved)} "
                        f"load-bearing conjectures: "
                        f"{[(ei + 1, ci + 1) for ei, ci in selected_pairs_resolved]} "
                        f"(candidate, conjecture) of {len(ext_outs)} draws.[/cyan]"
                    )
                    ext_out = SimpleNamespace(
                        conjectures=selected_conjectures,
                        raw="\n\n---\n\n".join(
                            f"[Extractor Draw {ei + 1}, load-bearing C{ci + 1} — selected by cluster]\n{ext_outs[ei].raw}"
                            for ei, ci in selected_pairs_resolved
                        ),
                    )
                    n_conj = len(ext_out.conjectures)
                    # ── Mode A: single self-contained conjecture → spawn child lineage ──
                    child_w, child_d = 4, 4
                    parent_consumed = width * d
                    successor_cost = width * depth
                    chain_cost_needed = parent_consumed + (child_w * child_d) + successor_cost
                    mode_a_feasible = (
                        n_conj == 1
                        and self.allow_child_spawn
                        and d < effective_depth
                        and self.total_budget is not None
                        and self.total_budget >= chain_cost_needed
                    )
                    if mode_a_feasible:
                        # Save extractor result to notebook FIRST so resumed run sees it
                        nb.conjectures.extend(ext_out.conjectures)
                        nb_ext = await notebook_update(
                            problem=self.problem,
                            paper_library=state.paper_library_text(nb),
                            notebook_id="ROOT",
                            parent_id="ROOT",
                            current_notebook=nb.content,
                            new_materials=(
                                f"[Conjecture Extractor — stage {d}, conjecture round {conjecture_round}, Mode A]\n"
                                f"Pipeline stuck for {no_progress_count} stages. A single "
                                f"self-contained conjecture was extracted. This run is "
                                f"terminating cleanly; a supervisor will launch a child "
                                f"pipeline on the conjecture and then a successor parent "
                                f"run seeded with the child's results.\n\n"
                                f"{ext_out.raw}"
                            ),
                            mode="UPDATE",
                            search_mode=SearchMode.DISABLED,
                            run_id=self.run_id,
                            store=self.store,
                        )
                        nb.content = nb_ext.content
                        state.total_rounds = d
                        # Spawn supervisor (writes child problem file, launches child + successor)
                        await self._spawn_child_supervisor(
                            conjecture=ext_out.conjectures[0],
                            extractor_raw=ext_out.raw,
                            stage_when_paused=d,
                            child_w=child_w, child_d=child_d,
                            successor_w=width, successor_d=depth,
                            remaining_budget=self.total_budget - parent_consumed,
                        )
                        state.status = RunStatus.PAUSED_FOR_CHILD
                        self.store.save_run_state(state)
                        console.log(
                            f"[bold cyan]Mode A: parent {self.run_id} paused at stage {d}. "
                            f"Supervisor launched. Exiting.[/bold cyan]"
                        )
                        return state

                    # ── Mode B: run a conjecture stage on the cluster's top-2,
                    #         then inject results as notebook material ────────────
                    mode_b_reason = (
                        "more than one conjecture extracted" if n_conj != 1 else
                        "child-spawn disabled" if not self.allow_child_spawn else
                        "final stage — no remaining stages to use the conjecture"
                        if d >= effective_depth else
                        "remaining budget insufficient for child + successor"
                    )

                    # Active conjectures are the cluster's load-bearing picks
                    # (one per top class), already resolved above into
                    # ext_out.conjectures. No re-deriving from top_pairs here —
                    # the cluster's load-bearing index has already been honored.
                    active_conjectures: list[Conjecture] = list(ext_out.conjectures)

                    conjecture_stage_text = ""
                    resolved_active: list[Conjecture] = []
                    if active_conjectures:
                        console.log(
                            f"[bold magenta]Entering conjecture stage with "
                            f"k={len(active_conjectures)} active conjectures, "
                            f"R={CONJECTURE_ROUNDS} rounds...[/bold magenta]"
                        )
                        conjecture_stage_text, resolved_active = await self._run_conjecture_stage(
                            active_conjectures=active_conjectures,
                            width=width,
                            rounds=CONJECTURE_ROUNDS,
                            nb=nb,
                            state=state,
                            stage_when_fired=d,
                            conjecture_round_num=conjecture_round,
                        )

                    nb_ext = await notebook_update(
                        problem=self.problem,
                        paper_library=state.paper_library_text(nb),
                        notebook_id="ROOT",
                        parent_id="ROOT",
                        current_notebook=nb.content,
                        new_materials=(
                            f"[Conjecture Extractor — stage {d}, conjecture round {conjecture_round}, Mode B]\n"
                            f"Pipeline stuck for {no_progress_count} stages. "
                            f"({n_conj} conjecture(s) extracted across {len(ext_outs)} draws; "
                            f"Mode A not triggered: {mode_b_reason}.)\n\n"
                            f"**The conjectures below are SOFT-LEMMAs "
                            f"(verify-before-use), not replacement problems.** You MUST "
                            f"continue producing a complete proof of the PARENT PROBLEM "
                            f"(as stated at the top of this prompt). For each SOFT-LEMMA "
                            f"you invoke, you MUST cite it by its OC-N identifier and "
                            f"declare your posture explicitly:\n"
                            f"  (a) prove it inline within your proof — cite as "
                            f"`[SOFT-LEMMA OC-N: discharged]`, or\n"
                            f"  (b) cite it as a still-open gap — write "
                            f"`[SOFT-LEMMA OC-N: open — parent proof conditional]` "
                            f"in bold at the point of use.\n"
                            f"Do not invoke a SOFT-LEMMA without citing its OC-N. "
                            f"Do NOT replace the parent problem with one of the "
                            f"conjectures. Do NOT restate a conjecture as 'the problem'. "
                            f"Your output must answer the parent problem statement.\n\n"
                            f"**Conjecture-stage outcomes below carry status tags:**\n"
                            f"  - `RESOLVED — PROVED`: SOFT-LEMMA is available to invoke as above.\n"
                            f"  - `RESOLVED — DISPROVED`: the conjecture's NEGATION holds. "
                            f"DO NOT invoke this OC-N as a SOFT-LEMMA in any form. If your "
                            f"draft was leaning on it, reroute the argument around it.\n"
                            f"  - `UNRESOLVED`: treat as a SOFT-LEMMA per the (a)/(b) rule above.\n\n"
                            f"{ext_out.raw}\n\n"
                            f"{conjecture_stage_text}"
                        ),
                        mode="UPDATE",
                        search_mode=SearchMode.DISABLED,
                        run_id=self.run_id,
                        store=self.store,
                    )
                    nb.content = nb_ext.content
                    nb.conjectures.extend(ext_out.conjectures)
                    no_progress_count = 0   # reset; extractor gets one shot per rut
                    console.log(
                        f"[cyan]Conjecture Extractor: {n_conj} conjecture(s) added "
                        f"(Mode B — {mode_b_reason}).[/cyan]"
                    )
                    # TODO: after extracting conjectures, make a dedicated LLM call that
                    # takes each conjecture + its negation from ext_out and rewrites them
                    # as fully self-contained statements — all variables defined inline,
                    # no references to "the proof above" or parent problem notation.
                    # This is required before spawning a child notebook or using the
                    # conjecture as a standalone problem file. Without this step the
                    # phrasing inherits context from the parent proof and is not
                    # independently interpretable. (Sanjeev: "this is what I used to do
                    # by hand when designing the pipeline.")

                # 5. Search if notebook requests it
                if search_mode == SearchMode.ENABLED and nb_out.search_queries:
                    await self._handle_search(state, nb, nb_out.search_queries, search_mode)

                # 5b. Periodic Paper Hunter re-read on injected PDFs (every 2 stages)
                injected_paths = self._pdf_paths(state, nb)
                if injected_paths and d % 2 == 0:
                    console.log(
                        f"[cyan]Stage {d}: re-running Paper Hunter on injected PDFs "
                        f"against updated notebook...[/cyan]"
                    )
                    findings = await run_paper_hunter(
                        problem=self.problem,
                        notebook_full=nb.content,
                        paper_library=state.paper_library_text(nb),
                        hints="The notebook now records what has been tried and failed. "
                              "Hunt for techniques or results in these papers that speak "
                              "directly to the current gaps and have not yet been exploited.",
                        notebook_id="ROOT",
                        run_id=self.run_id,
                        pdf_paths=injected_paths,
                        store=self.store,
                    )
                    nb_out3 = await notebook_update(
                        problem=self.problem,
                        paper_library=state.paper_library_text(nb),
                        notebook_id="ROOT",
                        parent_id="ROOT",
                        current_notebook=nb.content,
                        new_materials=f"[Paper Hunter — stage {d} re-read]\n{findings}",
                        mode="UPDATE",
                        search_mode=SearchMode.DISABLED,
                        run_id=self.run_id,
                        store=self.store,
                    )
                    nb.content = nb_out3.content
                    console.log("[cyan]Notebook updated with new paper findings.[/cyan]")

            # 6. Prune and save Part 3 for next stage
            prev_stage_outputs = await _prune_for_next_stage(
                solver_calls, grader_results, d, state.all_solutions, bs_results
            )

            state.total_rounds = d
            self.store.save_run_state(state)

        if state.status != RunStatus.DONE:
            if max_stages and state.total_rounds < depth:
                # Paused mid-run for human notebook update — stay in SOLVING
                state.status = RunStatus.SOLVING
                console.log(
                    f"[cyan]Paused after {max_stages} stage(s). "
                    f"Update notebook and resume with --run-id {self.run_id}[/cyan]"
                )
            else:
                state.status = RunStatus.DONE
        # Save unconditionally so end-of-run state (including early-DONE
        # path) is always persisted before run_done telemetry fires.
        self.store.save_run_state(state)

        self.tel.run_done(nb.best_score, state.total_rounds)
        self.tel.print_summary()
        self._save_and_display_top_solutions(state)
        return state

    # ─────────────────────────────────────────────────────────────────────────
    # Search pipeline: notebook queries → arxiv → triage → PDF → Paper Hunter
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_search(
        self,
        state: RunState,
        nb: NotebookState,
        queries: list[SearchQuery],
        search_mode: SearchMode,
    ) -> None:
        new_paper_keys: list[str] = []
        for sq in queries:
            if sq.purpose in nb.exhausted_search_gaps:
                continue
            keys = await self._run_search_query(state, nb, sq)
            new_paper_keys.extend(keys)

        if not new_paper_keys:
            return

        # Paper Hunter reads newly fetched papers → findings
        findings = await run_paper_hunter(
            problem=self.problem,
            notebook_full=nb.content,
            paper_library=state.paper_library_text(nb),
            notebook_id="ROOT",
            run_id=self.run_id,
            pdf_paths=self._pdf_paths(state, nb),
            store=self.store,
        )

        # Inject Paper Hunter findings back into notebook
        nb_out = await notebook_update(
            problem=self.problem,
            paper_library=state.paper_library_text(nb),
            notebook_id="ROOT",
            parent_id="ROOT",
            current_notebook=nb.content,
            new_materials=f"[Paper Hunter Findings]\n{findings}",
            mode="UPDATE",
            search_mode=SearchMode.DISABLED,   # don't trigger another search loop
            run_id=self.run_id,
            store=self.store,
        )
        nb.content = nb_out.content
        console.log(f"[cyan]Search done — {len(new_paper_keys)} new papers injected.[/cyan]")

    async def _run_search_query(
        self,
        state: RunState,
        nb: NotebookState,
        sq: SearchQuery,
    ) -> list[str]:
        self.tel.search_issued(nb.notebook_id, sq.arxiv_query, sq.recency_hint)
        console.log(f"[cyan]Search:[/cyan] {sq.arxiv_query[:80]} (recency={sq.recency_hint})")

        refusal_count = 0
        for recency in (["recent", "any"] if sq.recency_hint == "recent" else ["any"]):
            if not self.store.check_disk_space():
                console.log(f"[red]Low disk ({self.store.disk_free_gb():.1f} GB) — skipping.[/red]")
                return []

            candidates = await search_arxiv(
                build_arxiv_query(sq.arxiv_query),
                max_results=ARXIV_MAX_RESULTS,
                recency=recency,  # type: ignore[arg-type]
                max_date=self.search_before,
            )

            triage = await run_triage(
                problem=self.problem,
                notebook_level1=nb.content,
                search_gap=sq.purpose,
                search_query=sq.arxiv_query,
                candidates=candidates,
                notebook_id=nb.notebook_id,
                run_id=self.run_id,
                store=self.store,
            )
            self.tel.triage_result(nb.notebook_id, len(candidates),
                                   len(triage.shortlist))

            if triage.no_relevant:
                refusal_count += 1
                if refusal_count >= MAX_TRIAGE_REFUSALS:
                    nb.exhausted_search_gaps.append(sq.purpose)
                    console.log(f"Gap exhausted: {sq.purpose[:60]}")
                    return []
                continue

            keys: list[str] = []
            for tr in triage.shortlist[:MAX_KEEP_PAPERS]:
                keys += await self._fetch_paper(state, nb, tr.arxiv_id)
            return keys

        return []

    async def _fetch_paper(
        self, state: RunState, nb: NotebookState, arxiv_id: str
    ) -> list[str]:
        if arxiv_id in state.papers:
            self.tel.paper_fetched(arxiv_id, from_cache=True)
            key = f"arxiv:{arxiv_id}"
            if key not in nb.paper_library:
                nb.paper_library.append(key)
            return [key]

        if not self.store.check_disk_space():
            console.log(f"[red]Skipping {arxiv_id} — low disk.[/red]")
            return []

        hits = await search_arxiv(f"id:{arxiv_id}", max_results=1)
        if not hits:
            return []
        paper = hits[0]

        dest = self.store.pdf_path(arxiv_id)
        if await download_pdf(arxiv_id, dest):
            paper.pdf_path = str(dest)
            paper.fetched_at = time.time()

        state.papers[arxiv_id] = paper
        key = paper.citation_key
        if key not in nb.paper_library:
            nb.paper_library.append(key)
        self.tel.paper_fetched(arxiv_id, from_cache=False)
        return [key]

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _register_injected_pdfs(
        self, state: RunState, pdf_paths: list[Path]
    ) -> None:
        """Register manually supplied PDFs in state so they flow to all agents."""
        import re
        import time as _time

        nb = state.root_notebook
        for i, pdf_path in enumerate(pdf_paths):
            key = f"inj{i}"
            if key in state.papers:
                continue  # already registered (e.g. resumed run)

            # Try to extract title/authors from a companion .tex file
            title = pdf_path.stem
            authors: list[str] = ["(manually supplied)"]
            abstract = f"Manually supplied PDF: {pdf_path.name}"
            # Only use a .tex whose stem matches the PDF — otherwise an
            # unrelated .tex sitting elsewhere in the tree poisons every
            # injected PDF's metadata with that paper's title/abstract.
            tex_candidates = [
                t for t in pdf_path.parent.glob("**/*.tex")
                if t.stem == pdf_path.stem
            ]
            for tex in tex_candidates[:3]:
                try:
                    raw = tex.read_text(encoding="utf-8", errors="ignore")
                    # title
                    tm = re.search(r"\\title\s*(?:\[.*?\])?\s*\{([^}]{5,200})\}", raw, re.DOTALL)
                    if tm:
                        title = re.sub(r"\s+", " ", tm.group(1).replace("\n", " ")).strip()
                    # authors
                    am = re.findall(r"\\author\s*\{([^}]{2,80})\}", raw)
                    if am:
                        authors = [re.sub(r"\s+", " ", a).strip() for a in am]
                    # abstract
                    abm = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", raw, re.DOTALL)
                    if abm:
                        abstract = re.sub(r"\s+", " ", abm.group(1).replace("\n", " ")).strip()[:600]
                    break
                except Exception:
                    pass

            from .models import Paper
            paper = Paper(
                arxiv_id=key,
                title=title,
                authors=authors,
                date="2025",
                abstract=abstract,
                primary_category="math",
                pdf_path=str(pdf_path.resolve()),
                fetched_at=_time.time(),
            )
            state.papers[key] = paper
            citation_key = f"arxiv:{key}"
            # Add to root notebook paper library if it exists
            if nb is not None and citation_key not in nb.paper_library:
                nb.paper_library.append(citation_key)
            console.log(
                f"[cyan]Injected PDF:[/cyan] {pdf_path.name} → [{citation_key}] {title[:60]}"
            )
        self.store.save_run_state(state)

    def _pdf_paths(self, state: RunState, nb: NotebookState) -> list[Path]:
        paths = []
        for key in nb.paper_library:
            p = state.papers.get(key.replace("arxiv:", ""))
            if p and p.pdf_path:
                path = Path(p.pdf_path)
                if path.exists():
                    paths.append(path)
        return paths

    def _save_and_display_top_solutions(self, state: RunState) -> None:
        top = state.top_solutions(n=2)
        if not top:
            console.log("No solutions recorded.")
            return

        run_dir = self.store.run_dir
        console.rule("[bold green]Top Solution(s)")
        for rank, sol in enumerate(top, 1):
            # Surface dual-gate verdict in the label so the operator can see at
            # a glance whether a top-ranked proof was BS-clean. Possible values:
            #   "BS-CLEAN"   — gauntlet ran, BS aggregator reported no gaps
            #   "BS-OPEN"    — gauntlet ran, BS aggregator flagged gaps
            #   "BS-N/A"     — solution never went through the gauntlet
            bs_tag = (
                "BS-CLEAN" if sol.bs_clean is True
                else "BS-OPEN" if sol.bs_clean is False
                else "BS-N/A"
            )
            label = (f"Rank {rank} — Stage {sol.stage}, "
                     f"Solver {sol.solver_index}, Score {sol.score:.1f}/7, {bs_tag}")
            console.print(f"\n[bold]{label}[/bold]")

            # Write to file — strip process logs (Parts 1 & 2), keep only the
            # proof after PROOF_START. Fall back to full output if sentinel
            # absent. Grader feedback intentionally omitted — full grader
            # output lives in the run DB (agent_calls table). Bundling it
            # here corrupted downstream readers (BS detector, comparator)
            # because the appended grading log uses theorem-statement words
            # that confused upstream Flash extraction.
            proof = _extract_part3(sol.output)
            # Re-prepend the PROOF_START sentinel so the saved file
            # round-trips through _extract_part3 / _proof_only cleanly
            # (the sentinel itself is consumed by .split() during extraction).
            proof_text = f"PROOF_START\n{proof}" if proof else sol.output
            path = run_dir / f"top_solution_{rank}.txt"
            path.write_text(
                f"{label}\n{'='*60}\n{proof_text}\n",
                encoding="utf-8",
            )
            console.print(f"[dim]Saved to {path}[/dim]")
            console.print(proof_text)

    def _warn_disk(self, state: RunState) -> None:
        free = self.store.disk_free_gb()
        if free < 5.0:
            console.log(f"[yellow]WARNING: {free:.1f} GB free — PDF fetch may be throttled.[/yellow]")

    # ─────────────────────────────────────────────────────────────────────────
    # Mode A: spawn child supervisor and exit
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_conjecture_stage(
        self,
        *,
        active_conjectures: list[Conjecture],
        width: int,
        rounds: int,
        nb: NotebookState,
        state: RunState,
        stage_when_fired: int,
        conjecture_round_num: int,
    ) -> tuple[str, list[Conjecture]]:
        """Run R rounds of solvers attacking the active conjectures
        (2/3 prove + 1/3 disprove, distributed across surviving conjectures).
        BS detector is skipped. Single grader (no ensemble exit); any 7/7
        marks the conjecture resolved. Resolved conjectures' solver slots
        reallocate to surviving conjectures in subsequent rounds.

        Returns (injection_text, resolved_conjectures). The injection_text is
        Mode B-style material for notebook_update. Solver outputs are
        appended to state.all_solutions so the budget tracks them.
        """
        from .agents.grader import grade_attempt

        leaderboard: dict[str, dict[str, list[tuple[str, float, str]]]] = {
            c.id: {"prove": [], "disprove": []} for c in active_conjectures
        }
        # resolved[c.id] is None until a single-grader 7/7 fires, then
        # "proved" or "disproved" depending on which mode hit it. Previously
        # this was a bool, which caused the notebook injection to ALWAYS
        # say "CLOSED (proved — pending vetting)" even when the 7/7 came
        # from a disprove attempt — silently mislabeling disproved
        # conjectures as proved in the notebook. Fixed 2026-05-27.
        resolved: dict[str, str | None] = {c.id: None for c in active_conjectures}

        total_prove_pool = (2 * width) // 3
        total_disprove_pool = width - total_prove_pool   # remainder

        for r in range(1, rounds + 1):
            surviving = [c for c in active_conjectures if resolved[c.id] is None]
            if not surviving:
                console.log("[green]All active conjectures resolved; "
                            "ending conjecture stage early.[/green]")
                break

            # Budget check before this round
            cells_used = len(state.all_solutions)
            if self.total_budget is not None and cells_used + width > self.total_budget:
                console.log(
                    f"[cyan]Budget cap reached during conjecture stage "
                    f"(cells {cells_used}/{self.total_budget}). Stopping.[/cyan]"
                )
                break

            prove_per = max(1, total_prove_pool // len(surviving))
            disprove_per = max(0, total_disprove_pool // len(surviving))
            used = (prove_per + disprove_per) * len(surviving)
            slack = width - used   # distribute extras to prove (round-robin)
            extra_prove = [0] * len(surviving)
            for i in range(max(0, slack)):
                extra_prove[i % len(surviving)] += 1

            console.rule(
                f"[bold magenta]Conjecture round {r}/{rounds}  "
                f"({len(surviving)} surviving — "
                f"{prove_per}P+{disprove_per}D per c)"
            )

            assignments: list[tuple[Conjecture, str, int]] = []
            for ci, c in enumerate(surviving):
                for i in range(prove_per + extra_prove[ci]):
                    assignments.append((c, "prove", i))
                for i in range(disprove_per):
                    assignments.append((c, "disprove", i))

            async def _run_one(c: Conjecture, mode: str, sub_idx: int, flat: int):
                problem_str = c.statement if mode == "prove" else f"Disprove: {c.statement}"
                prev = [out for out, _, _ in leaderboard[c.id][mode][:2]]
                add = (
                    f"(conjecture stage; you are attempting to "
                    f"{'PROVE' if mode == 'prove' else 'DISPROVE'} the statement "
                    f"in the Problem field. BS detector skipped this round.)"
                )
                return await run_solver(
                    problem=problem_str,
                    notebook_level1=nb.content,
                    prev_attempts=prev,
                    solver_index=flat,
                    stage=stage_when_fired,
                    notebook_id="ROOT",
                    run_id=self.run_id,
                    additional_materials=add,
                    store=self.store,
                )

            solver_calls = await asyncio.gather(*[
                _run_one(c, m, i, flat)
                for flat, (c, m, i) in enumerate(assignments)
            ])

            # Conjecture-stage grader uses the same vetted-facts channel as
            # the main-stage grader: VFs + SNTs from notebook + paper library
            # + summarized .md references. Without this, the prove/disprove
            # gauntlet operates with no literature view — observed on Q7 run
            # 9d66f0e53f8d (2026-05-24) where C2 ("closed orientable manifold
            # with finite normal subgroup in π₁ has simplicial volume zero",
            # false) was not disproved because the grader had no Witte Morris
            # / Thurston baseline. Excluding OCs/RHs/IPTs/PSes here matches
            # the contamination-discipline split (see
            # docs/grader_contamination_and_provenance.md).
            references_for_grader = state.vetted_facts_text(
                nb, self._additional_materials_runtime
            )

            async def _grade_one(call, c: Conjecture, mode: str, flat: int):
                problem_str = c.statement if mode == "prove" else f"Disprove: {c.statement}"
                return await grade_attempt(
                    problem=problem_str,
                    solver_output=call.output,
                    solver_index=flat,
                    stage=stage_when_fired,
                    notebook_id="ROOT",
                    run_id=self.run_id,
                    bs_flags="(BS detector not run — conjecture stage)",
                    additional_materials=references_for_grader,
                    store=self.store,
                )

            grades = await asyncio.gather(*[
                _grade_one(call, c, m, flat)
                for flat, (call, (c, m, _)) in enumerate(zip(solver_calls, assignments))
            ])

            for call, grade, (c, mode, _) in zip(solver_calls, grades, assignments):
                leaderboard[c.id][mode].append((call.output, grade.score, grade.feedback))
                state.all_solutions.append(SolutionRecord(
                    stage=stage_when_fired,
                    solver_index=call.inputs.get("solver_index", 0),
                    score=grade.score,
                    output=call.output,
                    grader_feedback=grade.feedback,
                    stage_type="conjecture",
                ))
                if grade.score >= 7.0 and resolved[c.id] is None:
                    # Record WHICH mode resolved it. "prove" -> "proved";
                    # "disprove" -> "disproved". This determines the OC status
                    # the notebook agent will record below.
                    resolved[c.id] = "proved" if mode == "prove" else "disproved"
                    console.log(
                        f"[bold green]Conjecture {c.id} resolved as "
                        f"{resolved[c.id].upper()} (mode={mode}, single grader 7/7).[/bold green]"
                    )

            for c in active_conjectures:
                for mode in ("prove", "disprove"):
                    leaderboard[c.id][mode] = sorted(
                        leaderboard[c.id][mode], key=lambda x: -x[1]
                    )[:2]

            self.store.save_run_state(state)

        # Build Mode B-style notebook injection
        resolved_conjs = [c for c in active_conjectures if resolved[c.id] is not None]
        lines = [
            f"[Conjecture Stage — conjecture round {conjecture_round_num}, "
            f"R={rounds} rounds attempted]",
            "",
            "## Active conjectures and their attempts",
            "",
        ]
        for c in active_conjectures:
            lines.append(f"### {c.id}: {c.statement[:600]}")
            outcome = resolved[c.id]
            if outcome == "proved":
                lines.append(
                    "**RESOLVED — PROVED** by single grader 7/7 — please record OC "
                    "status as `CLOSED (proved — pending vetting)` (not VF; soft "
                    "promotion only). This conjecture is now available as a "
                    "SOFT-LEMMA in subsequent parent-problem proofs."
                )
            elif outcome == "disproved":
                lines.append(
                    f"**RESOLVED — DISPROVED** by single grader 7/7 — please "
                    f"record OC status as `CLOSED (blocked — disproved)` and "
                    f"add a new IPT entry: \"{c.id} disproved at conjecture "
                    f"round {conjecture_round_num} by single grader 7/7 on a "
                    f"disprove attempt.\" Subsequent parent-problem proofs "
                    f"MUST NOT invoke {c.id} as a SOFT-LEMMA — the negation "
                    f"holds. Any earlier draft that depended on {c.id} needs "
                    f"its argument rerouted around this dead path."
                )
            else:
                lines.append("**UNRESOLVED** — top-2 prove + top-2 disprove attempts follow.")
            lines.append("")
            for mode in ("prove", "disprove"):
                lines.append(f"#### Top {mode} attempts ({len(leaderboard[c.id][mode])})")
                if not leaderboard[c.id][mode]:
                    lines.append("_(no attempts this round)_")
                for i, (out, score, fb) in enumerate(leaderboard[c.id][mode], 1):
                    lines.append(f"\n**{mode.title()} attempt {i} — graded {score:.1f}/7**")
                    lines.append(f"\n{out[:8000]}\n")
                    lines.append(f"\n_Grader feedback (excerpt):_ {fb[:1500]}\n")
                lines.append("")
            lines.append("")

        return "\n".join(lines), resolved_conjs

    # ─────────────────────────────────────────────────────────────────────────

    async def _spawn_child_supervisor(
        self,
        *,
        conjecture,
        extractor_raw: str,
        stage_when_paused: int,
        child_w: int,
        child_d: int,
        successor_w: int,
        successor_d: int,
        remaining_budget: int,
    ) -> None:
        """
        Self-contain the conjecture statement, write it as a standalone problem
        file, then launch a detached supervisor.py subprocess that will:
          (1) run a child pipeline on the conjecture (W=child_w, D=child_d)
          (2) extract the child's best output
          (3) launch a successor parent run seeded with parent_id + child's results

        This method writes inputs to disk and detaches; it does NOT wait. The
        parent run terminates cleanly after this returns.
        """
        run_dir = self.store.run_dir
        # ── 1. Self-contain the conjecture statement via a short LLM rewrite ──
        rewrite_prompt = (
            "You will rewrite a mathematical conjecture so that it is fully "
            "self-contained — readable as a standalone problem by someone who "
            "has not seen any parent context.\n\n"
            "Rules:\n"
            "1. Inline every variable, set, function, and notation used. Do not "
            "refer to 'the proof above', 'the problem', or any external object.\n"
            "2. If the conjecture relies on standard objects (local fields, "
            "groups, representations, etc.), state their definitions inline at "
            "the top of the problem.\n"
            "3. Preserve the mathematical content exactly — no weakening, no "
            "strengthening, no paraphrasing of the claim.\n"
            "4. End with a clear ask: 'Prove the following:' followed by the "
            "self-contained statement.\n\n"
            f"Original conjecture statement:\n{conjecture.statement}\n\n"
            f"Original conjecture negation (for context, do not include in "
            f"output):\n{conjecture.negation}\n\n"
            f"For additional context, here is the surrounding extractor output "
            f"showing how the conjecture was used in the parent proof "
            f"(use only to resolve any ambiguous notation — do not embed):\n"
            f"{extractor_raw[:4000]}\n\n"
            "Output ONLY the rewritten self-contained problem statement. "
            "No preamble, no commentary."
        )
        rewrite_call = await call_gemini(
            rewrite_prompt,
            run_id=self.run_id,
            notebook_id="ROOT",
            agent="conjecture_self_containment",
            inputs={"source_conjecture_id": conjecture.id},
            store=self.store,
        )
        child_problem_text = rewrite_call.output.strip()

        # ── 2. Write child problem + lineage manifest to disk ─────────────────
        child_problem_file = run_dir / f"child_{conjecture.id}_problem.txt"
        child_problem_file.write_text(child_problem_text, encoding="utf-8")

        if self.problem_file is None:
            console.log(
                "[red]Cannot spawn supervisor: self.problem_file is None. "
                "Supervisor needs the parent's problem file path to launch the "
                "successor run.[/red]"
            )
            return
        manifest = {
            "parent_run_id": self.run_id,
            "parent_problem_file": str(self.problem_file.resolve()),
            "child_problem_file": str(child_problem_file.resolve()),
            "child_w": child_w,
            "child_d": child_d,
            "successor_w": successor_w,
            "successor_d": successor_d,
            "remaining_budget": remaining_budget,
            "stage_when_paused": stage_when_paused,
            "conjecture_id": conjecture.id,
            # Direction the child was tasked with. Today the rewriter at
            # _spawn_child_supervisor always produces a "Prove the following"
            # form from the statement; the field is here so the supervisor's
            # verdict derivation doesn't need to keyword-scan the child
            # problem file. When the AWS parallel PROVE+NEGATE spawn lands
            # (per memory/project_aws_negation_spawn.md), this field will
            # carry "statement" or "negation" for each of the two children.
            "conjecture_target": "statement",
            # Propagate the parent's --additional-materials file (if any) so the
            # supervisor can re-attach it to the child and successor runs.
            "additional_materials_file": (
                str(self.additional_materials_file.resolve())
                if self.additional_materials_file else None
            ),
        }
        manifest_file = run_dir / "supervisor_manifest.json"
        import json
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # ── 3. Launch supervisor.py detached ──────────────────────────────────
        supervisor_log = run_dir / "supervisor.log"
        cmd = [
            sys.executable, "-m", "math_solver.supervisor",
            "--manifest", str(manifest_file.resolve()),
        ]
        log_fh = open(supervisor_log, "w")
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,   # fully detach from parent's session group
            cwd=str(Path(__file__).resolve().parents[2]),  # math_solver/ root
        )

        # ── 4. Console output ────────────────────────────────────────────────
        console.log(
            f"[bold cyan]Supervisor spawned (PID {proc.pid}).[/bold cyan]\n"
            f"  Manifest:        {manifest_file}\n"
            f"  Child problem:   {child_problem_file}\n"
            f"  Supervisor log:  {supervisor_log}\n"
            f"  Remaining budget: {remaining_budget} (child {child_w}×{child_d}, "
            f"successor {successor_w}×{successor_d})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────────────────────────────────────

def _extract_part3(text: str) -> str | None:
    """Pull the clean proof via PROOF_START sentinel. Returns None if absent.

    Sync, sentinel-only. For paths where a Flash-based fallback is warranted
    (notebook integration, stage-bundle assembly — places where a missed
    extraction would propagate internal solver/grader dialectic to downstream
    agents), use `_extract_part3_async` instead.
    """
    if "PROOF_START" in text:
        return text.split("PROOF_START", 1)[1].strip()
    return None


async def _extract_part3_async(text: str) -> str:
    """Three-tier Part 3 extractor: PROOF_START sentinel -> Flash extraction
    -> full text. Always returns a string (never None). Use at call sites
    where a missed extraction would let a solver's internal Council
    dialectic flow into downstream agent context (notebook integration,
    next-stage prev_stage_outputs, etc.). Delegates to grader._proof_only,
    which already implements the three-tier logic for the BS-detector /
    grader call paths."""
    from .agents.grader import _proof_only
    return await _proof_only(text)


def _extract_part2(text: str) -> str:
    """Strip the process log (Part 1) from any agent output, keeping Part 2 onward.
    Works for graders, BS detectors, aggregators, extractors — any agent whose
    output starts with a process log followed by a 'Part 2' section."""
    for marker in ("**Part 2", "## Part 2", "Part 2:", "---\n\n**Part 2"):
        idx = text.find(marker)
        if idx >= 0:
            return text[idx:].strip()
    return text  # no marker found — return as-is


async def _extract_grader_critique(text: str) -> str:
    """Three-tier strip: regex -> Flash -> full text. Same semantics
    as grader.py:_extract_critique_only, kept here so orchestrator
    paths (bundle composition, ensemble_feedback assembly, conjecture-
    extractor grader_reports_text) have the same robust extraction.

    Tier 1 (regex): bold-header sections. ~87% catch on initial grader
    output, 0% on aggregator output (different schema).

    Tier 2 (Flash): semantic critique extraction via flash_extract_critique.
    Catches aggregator format + prompt-format drift.

    Tier 3 (full text): defensive fallback. No regression vs prior.
    """
    import re
    parts = []
    for section in ("Areas for Improvement", "Scaffolding Questions"):
        # Allow optional colon in marker: graders emit
        # "**Areas for Improvement:**" more often than the bare form.
        m = re.search(
            rf"\*\*{section}:?\*\*(.*?)(?=\n\*\*[A-Z]|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            parts.append(f"**{section}**{m.group(1).rstrip()}")
    if parts:
        return "\n\n".join(parts)

    # Tier 2: Flash. Empty string return is a trustworthy "no critique
    # here" (aggregator praised everything). None means Flash errored
    # after retries — fall through to Tier 3.
    try:
        from .gemini import flash_extract_critique
        flash_out = await flash_extract_critique(text)
        if flash_out is not None:
            if not flash_out:
                return ""
            if len(flash_out) < len(text) * 1.1:
                return flash_out
    except Exception:
        pass

    # Tier 3: full text safety net
    return text


def _extract_bs_interventions(text: str) -> str:
    """Extract only the Required Interventions from a BS detector report.
    Omits verdicts, metaphors, escalation logs, and any framing that implies
    a score or judgment — solvers see only the actionable gap questions,
    framed as mandatory requirements."""
    import re
    m = re.search(
        r"\*\*Part 2[:\s]*Required Interventions.*?\*\*(.*?)(?=\n\*\*Part\s+\d|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        return (
            "The proof cannot be accepted without explicitly addressing the following. "
            "Each item identifies a step where the current text is insufficient:\n"
            f"{m.group(1).rstrip()}"
        )
    return ""


async def _prune_for_next_stage(
    solver_calls: list[AgentCall],
    grader_results,
    stage: int,
    all_solutions: list[SolutionRecord],
    bs_results=None,
) -> list[str]:
    """
    Keep solutions whose avg score (across all grading attempts this stage)
    is within 3 of the stage max. If fewer than 2 survive, pad with next-best
    to maintain diversity. Returns one string per kept solution: the Part 3
    proof followed by the filtered grader critique (Areas for Improvement +
    Scaffolding Questions only), plus any BS detector flags, packaged as a
    single unit so each next-stage solver sees proof and critique together.
    """
    from collections import defaultdict

    bs_map = {r.solver_index: r for r in (bs_results or [])}

    # Avg score per solver_index using all recorded grades for this stage
    scores_by_idx: dict[int, list[float]] = defaultdict(list)
    for sol in all_solutions:
        if sol.stage == stage:
            scores_by_idx[sol.solver_index].append(sol.score)

    pairs: list[tuple[float, str]] = []
    for call, grade in zip(solver_calls, grader_results):
        idx = call.inputs.get("solver_index", 0)
        recorded = scores_by_idx.get(idx, [grade.score])
        avg = sum(recorded) / len(recorded)
        proof = await _extract_part3_async(call.output)
        critique = await _extract_grader_critique(grade.feedback)
        unit = f"{proof}\n\n--- Grader Critique ---\n{critique}"
        if idx in bs_map:
            unit += (
                f"\n\n--- Potential BS that needs elaboration or removal ---\n"
                f"{_extract_part2(bs_map[idx].feedback)}"
            )
        pairs.append((avg, unit))

    if not pairs:
        return []

    max_avg = max(avg for avg, _ in pairs)
    threshold = max_avg - 3.0
    kept = [(avg, unit) for avg, unit in pairs if avg >= threshold]

    # If only 1 survived pruning, supplement with top-2 runners-up
    if len(kept) < 2:
        ranked = sorted(pairs, key=lambda x: x[0], reverse=True)
        kept_units = {unit for _, unit in kept}
        for avg, unit in ranked:
            if unit not in kept_units:
                kept.append((avg, unit))
                kept_units.add(unit)
            if len(kept) >= 3:
                break

    kept_count = len(kept)
    console.log(f"[dim]Pruning: kept {kept_count}/{len(pairs)} solutions "
                f"(threshold {threshold:.1f}, max {max_avg:.1f})[/dim]")
    return [unit for _, unit in kept]


async def _format_stage_bundle(
    solver_calls: list[AgentCall],
    grader_results,
    stage: int,
    bs_results=None,
    all_solutions=None,
) -> str:
    """Format stage outputs for the notebook. Solver: Part 3 only. Grader: critique only.

    Async so the Part-3 extractor can fall back to Flash when the
    PROOF_START sentinel is missing — prevents internal solver dialectic
    from leaking into the notebook and thus into downstream agents.

    When `all_solutions` is supplied, the displayed score per solver is
    the **effective** score from the parent record (which the gauntlet
    aggregator and OpenAI gate overwrite in-place), not the initial
    grader's score. Without this, next-stage solvers would see inflated
    initial 7/7s even when both downstream gates demoted them.
    """
    bs_map = {r.solver_index: r for r in (bs_results or [])}
    # Map solver_index -> effective parent-record score for this stage.
    eff_scores: dict = {}
    if all_solutions:
        for rec in all_solutions:
            if getattr(rec, "stage", None) == stage and getattr(rec, "stage_type", None) == "parent":
                eff_scores[rec.solver_index] = rec.score
    parts = [f"[Stage {stage} — {len(solver_calls)} solver outputs]"]
    for call, grade in zip(solver_calls, grader_results):
        idx = call.inputs.get("solver_index", "?")
        proof = await _extract_part3_async(call.output)
        critique = await _extract_grader_critique(grade.feedback)
        displayed_score = eff_scores.get(idx, grade.score)
        block = (
            f"=== Solver {idx} (score {displayed_score:.1f}/7) ===\n"
            f"{proof}\n\n"
            f"--- Grader Critique ---\n{critique}"
        )
        if idx in bs_map:
            block += (
                f"\n\n--- Potential BS that needs elaboration or removal ---\n"
                f"{bs_map[idx].feedback}"
            )
        parts.append(block)
    return "\n\n".join(parts)
