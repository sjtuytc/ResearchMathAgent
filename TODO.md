# TODO / Engineering Roadmap

## Goal

Build a reliable math-agent pipeline: `problem → parse → propose → verify → refine → artifact`.

Keep outputs reproducible and auditable. Enforce benchmark fairness (solver must not read `data/*/final_solutions/`, `baselines/`, or official solution pages).

## Implemented

- `rma doctor`, `rma parse`, `rma propose`, `rma verify`, `rma refine`, `rma solve`
- `rma solve --all` for all First Proof problems
- Tiered execution profiles: `--tier budget / standard / pro`
- Claude backends: Anthropic API (`ANTHROPIC_API_KEY`) and local Claude Code (`--model-provider claude-code`)
- Structured artifacts per run: `metadata.json`, `status.json`, `parsed_problem.json`, `proposals/`, `verifications/`, `refinements/`
- Verifier with heuristic mathematical-completeness gates (proof length, subclaim structure, boundary cases)

## Remaining Work

### Phase 2 — Proof quality
- Stronger proposer/refiner prompts (retrieval-grounded, literature-aware)
- Line-by-line proof verification (currently heuristic gates only)
- Hypothesis audit: check every named theorem's preconditions are met

### Phase 3 — Infrastructure
- Resumable runs: skip already-completed problems in `rma solve --all`
- Run comparison: diff two experiment folders side-by-side

## Open Questions

1. Which benchmark questions should be golden regression cases?
2. Should `outputs/` artifacts be committed to git or gitignored?
