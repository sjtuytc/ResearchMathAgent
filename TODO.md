# TODO / Engineering Roadmap

Internal planning notes for the next iteration of this repository. Not part of the public-facing documentation.

## Goal

- Build a reliable math-agent pipeline: `problem -> reasoning -> complete initial solution -> verification -> refined final artifact`.
- Keep all outputs reproducible and auditable (inputs, prompts, initial solutions, verifier feedback, final files).
- Support iterative research outputs without losing prior artifacts.
- Enforce benchmark fairness: solver runs must not read existing files in `final_solutions/`, `output_solutions/`, `baselines/`, or public First Proof official-solution pages.

Current strength: strong proof artifacts and benchmark focus.
Current gap: the default `rma-skeleton` backend is deterministic and profile-guided; it now rejects short proof sketches, but it still needs stronger model/literature-backed proof generation, proof-correctness verification, schemas, run registry, and checkpoint/resume support. Claude backends are available through the Anthropic API and local Claude Code, but benchmark-quality solving still depends on stronger prompts, retrieval discipline, and verifier/refiner depth.

## Reusable Patterns to Port (inspired by PoggioAI_MSc)

1. **Tiered execution profiles**
   - Example: `budget / standard / pro`.
   - Why: explicit control over model cost, runtime, and quality level.

2. **Config + setup commands**
   - Example: `rma setup`, `rma config set ...`.
   - Why: avoid hidden environment bugs before expensive runs.

3. **Artifact contracts between stages**
   - Each stage must output structured files (e.g., `claims.json`, `proof.tex`, `checks.json`).
   - Why: prevents silent degradation and makes failures diagnosable.

4. **Run registry and resumability**
   - Save each run under experiment/model folders with metadata and logs.
   - Why: enables compare/retry/resume rather than restarting from scratch.

5. **Campaign mode for multi-problem programs**
   - Orchestrate multi-stage plans across several questions.
   - Why: math-agent work often spans related tasks, not one-off prompts.

## vNext Architecture

Recommended staged graph:

1. **Problem Parsing**
   - Normalize problem statement, assumptions, notation.

2. **Strategy Proposer**
   - Generate candidate proof strategies and required lemmas.

3. **Proof Constructor**
   - Produce a complete initial solution in LaTeX + machine-readable skeleton.

4. **Verifier**
   - Multi-pass checks: logical consistency, missing assumptions, symbol mismatch.

5. **Refiner**
   - Patch weak steps and regenerate only failed proof sections.

6. **Writer/Packager**
   - Produce final `proof.tex`, `proof.pdf`, and run report.

Each node should emit both human-readable and machine-readable artifacts.

## Proposed Folder Layout

```text
ResearchMathAgent/
  rma/                     # rma command entry
  config/                  # default configs and tiers
  agents/                  # pipeline nodes (parser, prover, verifier, ...)
  pipelines/               # graph orchestration
  schemas/                 # artifact contracts (json schema / pydantic)
  output_solutions/         # experiment/model solution outputs
  problems/                # benchmark tasks
  final_solutions/         # finalized publishable outputs; blocked from solver context
  tests/                   # unit + integration tests
```

## Implemented CLI Surface

```bash
# run one problem
rma solve q6
rma solve q6 --tier standard
rma solve q6 --exp-name proofs_v1_june13 --model-name rma-skeleton

# run individual stages
rma parse q6
rma propose q6
rma verify q6
rma refine q6

# run all First Proof problems
rma solve --all
```

## Proposed CLI Surface

```bash
# run from custom task file without solution leakage
rma solve --task-file tasks/q6_strict.txt --tier pro

# inspect and resume
rma runs
rma status <run_id>
rma resume <run_id>

# compare two runs
rma diff <run_id_a> <run_id_b>
```

## Quality Gates (Math-Specific)

Before a run is marked complete:

- **Gate A**: all theorem/lemma references resolve.
- **Gate B**: assumptions are explicit and non-contradictory.
- **Gate C**: symbolic notation is consistent globally.
- **Gate D**: proof contains no unsupported claims.
- **Gate E**: output compiles to TeX/PDF without errors.

## Migration Plan

### Phase 1 (complete)
- Add `rma parse`, `rma propose`, `rma verify`, `rma refine`.
- Make `rma solve` orchestrate parser/proposer/verifier/refiner rounds.
- Render TeX/PDF in the solution folder by default.

### Phase 2 (core capability)
- Improve model-backed proposer/refiner quality beyond the current Anthropic API and Claude Code adapters.
- Add provider configuration files for model defaults, token budgets, retries, and cost controls.
- Strengthen verifier from heuristic mathematical-completeness gates to line-by-line proof checking with theorem/citation retrieval and hypothesis verification.
- Add JSON schemas or typed artifact contracts.
- Add resumable checkpoints.
- Add run registry/status/resume commands.

### Phase 3 (advanced)
- Add campaign mode for multi-problem execution.
- Add optional multi-model counsel for difficult proof branches.
- Add run-to-run regression tests on selected benchmark questions.

## Open Questions

1. Should CLI + checkpointing be prioritized before multi-model features?
2. Should generated `output_solutions/<exp-name>_<model-name>/` artifacts be committed partially (metadata only) or fully ignored?
3. Which benchmark questions should be used as golden regression cases first?
