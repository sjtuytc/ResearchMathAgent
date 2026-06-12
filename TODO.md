# TODO / Engineering Roadmap

Internal planning notes for the next iteration of this repository. Not part of the public-facing documentation.

## Goal

- Build a reliable math-agent pipeline: `problem -> reasoning -> proof draft -> verification -> final artifact`.
- Keep all outputs reproducible and auditable (inputs, prompts, intermediate drafts, final files).
- Support iterative research runs without losing prior artifacts.

Current strength: strong proof artifacts and benchmark focus.
Current gap: no unified executable pipeline interface yet (CLI/config/run registry/checkpointing).

## Reusable Patterns to Port (inspired by PoggioAI_MSc)

1. **Single entry CLI**
   - Example target: `afm run "Solve Q6 with strict verification"`.
   - Why: one stable entrypoint drastically lowers operational friction.

2. **Tiered execution profiles**
   - Example: `budget / standard / pro`.
   - Why: explicit control over model cost, runtime, and quality level.

3. **Config + setup + doctor commands**
   - Example: `afm setup`, `afm doctor`, `afm config set ...`.
   - Why: avoid hidden environment bugs before expensive runs.

4. **Artifact contracts between stages**
   - Each stage must output structured files (e.g., `claims.json`, `proof.tex`, `checks.json`).
   - Why: prevents silent degradation and makes failures diagnosable.

5. **Run registry and resumability**
   - Save each run under timestamped folders with metadata and logs.
   - Why: enables compare/retry/resume rather than restarting from scratch.

6. **Campaign mode for multi-problem programs**
   - Orchestrate multi-stage plans across several questions.
   - Why: math-agent work often spans related tasks, not one-off prompts.

## vNext Architecture

Recommended staged graph:

1. **Problem Parsing**
   - Normalize problem statement, assumptions, notation.

2. **Strategy Proposer**
   - Generate candidate proof strategies and required lemmas.

3. **Proof Constructor**
   - Produce structured proof draft in LaTeX + machine-readable skeleton.

4. **Verifier**
   - Multi-pass checks: logical consistency, missing assumptions, symbol mismatch.

5. **Refiner**
   - Patch weak steps and regenerate only failed proof sections.

6. **Writer/Packager**
   - Produce final `proof.tex`, `proof.pdf`, and run report.

Each node should emit both human-readable and machine-readable artifacts.

## Proposed Folder Layout

```text
AgentForMath/
  cli/                     # afm command entry
  config/                  # default configs and tiers
  agents/                  # pipeline nodes (parser, prover, verifier, ...)
  pipelines/               # graph orchestration
  schemas/                 # artifact contracts (json schema / pydantic)
  runs/                    # timestamped run outputs and logs
  problems/                # benchmark tasks
  final_solutions/         # finalized publishable outputs
  tests/                   # unit + integration tests
```

## Suggested CLI Surface

```bash
# one-time setup
afm setup
afm doctor

# run one problem
afm run --problem q6 --tier standard

# run from custom task file
afm run --task-file tasks/q6_strict.txt --tier pro

# inspect and resume
afm runs
afm status <run_id>
afm resume <run_id>

# compare two runs
afm diff <run_id_a> <run_id_b>
```

## Quality Gates (Math-Specific)

Before a run is marked complete:

- **Gate A**: all theorem/lemma references resolve.
- **Gate B**: assumptions are explicit and non-contradictory.
- **Gate C**: symbolic notation is consistent globally.
- **Gate D**: proof contains no placeholder claims.
- **Gate E**: output compiles to TeX/PDF without errors.

## Migration Plan

### Phase 1 (immediate, low risk)
- Add CLI skeleton (`afm run`, `afm doctor`).
- Add `config/default.yaml` and tier presets.
- Standardize run output directory schema.

### Phase 2 (core capability)
- Implement node-based pipeline (`parser -> prover -> verifier -> refiner`).
- Add artifact contracts and failure reporting.
- Add resumable checkpoints.

### Phase 3 (advanced)
- Add campaign mode for multi-problem execution.
- Add optional multi-model counsel for difficult proof branches.
- Add run-to-run regression tests on selected benchmark questions.

## Open Questions

1. Should CLI + checkpointing be prioritized before multi-model features?
2. Should `runs/` be committed partially (metadata only) or fully ignored?
3. Which benchmark questions should be used as golden regression cases first?
