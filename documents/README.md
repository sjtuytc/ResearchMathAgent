# ResearchMathAgent — Documents

**Generated:** 2026-06-16 18:07 UTC

This directory contains all research documentation for the First Proof benchmark.

## Quick Navigation

- **[discussions/index.md](discussions/index.md)** — Master hub: status dashboard, thematic clusters, discussion threads
- **questions/qN/** — Per-question documentation (4 files each):
  - `overview.md` — Problem statement, background, definitions, key theorems
  - `timeline.md` — Every attempt, chronological, with outcomes
  - `progress.md` — Live status, best result, open gaps, next steps
  - `strategies.md` — Strategy space, quick checks, agent insights
- **strategy_memory.jsonl** — Raw attempt log (feeds all documents above)

## Problems

| ID | Title | Status |
|----|-------|--------|
| [q1](questions/q1/overview.md) | See overview.md | [progress](questions/q1/progress.md) |
| [q2](questions/q2/overview.md) | See overview.md | [progress](questions/q2/progress.md) |
| [q3](questions/q3/overview.md) | See overview.md | [progress](questions/q3/progress.md) |
| [q4](questions/q4/overview.md) | See overview.md | [progress](questions/q4/progress.md) |
| [q5](questions/q5/overview.md) | See overview.md | [progress](questions/q5/progress.md) |
| [q6](questions/q6/overview.md) | See overview.md | [progress](questions/q6/progress.md) |
| [q7](questions/q7/overview.md) | See overview.md | [progress](questions/q7/progress.md) |
| [q8](questions/q8/overview.md) | See overview.md | [progress](questions/q8/progress.md) |
| [q9](questions/q9/overview.md) | See overview.md | [progress](questions/q9/progress.md) |
| [q10](questions/q10/overview.md) | See overview.md | [progress](questions/q10/progress.md) |

## How Documents Are Updated

- After every `rma solve` run: `timeline.md`, `progress.md`, `strategies.md` are refreshed
- After every critic/solver agent run: `strategies.md` receives agent insights; `progress.md` gets reasoning traces
- `overview.md` is static — update it manually as understanding of the problem deepens
- `discussions/index.md` is refreshed after every daily run

## Adding Manual Notes

Edit any `.md` file directly. Agent-generated content is appended in clearly marked sections.
Manual notes above the `---` dividers are preserved across auto-updates.
