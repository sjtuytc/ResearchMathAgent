# VF promotion — design note

**Date:** 2026-05-20
**Status:** Design captured; not yet implemented.
**Open prerequisite:** literature-agent prompt review (see end).

## Background

The pipeline currently has **no automated path for promoting an Open
Conjecture to a Verified Fact.** Discovery trail:

- `notebook_v2_prompt.txt:32` — the notebook agent is explicitly
  forbidden from creating, modifying, or removing VF entries
  ("IMMUTABLE. Only the pipeline's external vetting process can assign
  VF status").
- No code path in `src/math_solver/` or `scripts/` creates VF entries
  programmatically. The supervisor's `extract_child_best_output`
  (`src/math_solver/supervisor.py:119`) bundles child outputs and
  passes the child's notebook **verbatim** to the successor — no
  transformation, no promotion.
- The only mechanism that introduces VFs is `--seed-notebook-file`:
  a hand-edited file fed at run launch. Commits `1692b3d` and
  `0e8bf75` (Sanjeev Arora, 2026-05-18) created the only such file
  used in recent history (`problems/nelson_q2_seed_notebook_run3b6a.txt`).

So "external vetting" reduces to: a previous Claude session reads the
prior run's notebook, surfaces a VF candidate, the human approves, the
session writes a seed-notebook commit. The human's approval is bounded
by the agent's pre-filtering, which is itself reading the prior
(possibly polluted) notebook.

## The motivating failure: K_1 contamination

1. Run `02d59be97325` (canonical Nelson Q2, 2026-05-17): correct
   proof, dual-gate confirmed.
2. Between this and the May-18 hardening pass, the BS detector's
   Hypothesis Auditor (then newly added) flagged the single-row
   condition for K_1 as defining a superset of the mirabolic
   congruence subgroup; the notebook absorbed the "fix" as a research
   hypothesis.
3. Run `3b6a236e1989` (May-18, hardening): "Confirmed but partly
   wrong" per the handoff. Its end-to-end proof relied on the
   non-canonical K_1 with an extra top-block constraint.
4. A Claude session surfaced C_V ≠ 0 as a VF candidate from
   `3b6a236e1989`'s confirmed proof; Sanjeev approved; commit
   `1692b3d` baked the wrong-K_1 framework into VF-1.
5. Run `dcfbcef8abd8` and downstream hardening runs inherited the
   corrupted VF-1.
6. On 2026-05-19, an external grader independently flagged the K_1
   redefinition as a fallacy; cross-check against the published gold
   (`papers/firstpfQ2.pdf`) confirmed the standard K_1 is the
   single-row condition.

The contaminating step was **(4)**: an internal-evidence-only
promotion of an internally-confirmed lemma. Neither the Claude
session nor the human had sufficient signal to override the
pipeline's confirmation.

## Design constraint for Challenge 2

VF promotion requires **external evidence**, not just internal
dual-gate confirmation. Three sources of external evidence are in
scope:

| Source | Available when | Strength | Weakness |
|---|---|---|---|
| Literature (published paper / arXiv) | result is known | Strong against pipeline self-confirmation | Doesn't help when the result is novel |
| Gold solution (e.g., FirstProof writeup) | gold exists for that problem | Direct verification | Opportunistic; not all problems have gold |
| Cross-provider confirmation (OpenAI + Gemini + Claude all confirm) | always | General; defense in depth | Doesn't catch shared-bias failures across providers |

## Decision (Sanjeev, 2026-05-20)

**Allow VF promotion from the literature agents**, with the
additional requirement that **two independent runs** must reach the
same conclusion before the lemma is promoted.

Implications:

- The literature agent (or a new VF-promotion auditor agent that
  consumes it) is the gatekeeper. It produces a citation handle
  pointing to a paper that states the result, with enough context to
  verify the citation.
- "Two independent runs" — likely means two separate `math_solver`
  runs on the same problem, each producing a `CLOSED (proved —
  pending vetting)` OC that the literature agent can match to the
  same external citation. Open question: what counts as "independent"
  — different seed? different solver/grader model? both?
- Cross-provider confirmation is **not** part of this decision but
  is a complementary lever for the same goal. Can be added later.

## Open implementation items (priority order)

1. **Review the literature agents' prompts** (`literature.py`,
   `paper_hunter.py`, `paper_guide.py`). They currently exist to
   *fetch* relevant literature for solvers; their behavior for the
   new "VF auditor" role is undefined. Prompt review pending.
2. **Define the VF promotion protocol concretely**: where does the
   auditor run, what inputs does it see, what output format does it
   produce, what triggers a promotion attempt (end-of-run? cron?
   manual invocation?).
3. **Define "two independent runs"** rigorously. Same problem,
   different seed? Different RNG? Different model provider?
4. **Wire the auditor into the pipeline**: it must be able to write
   the new VF entry into a seed notebook or directly into a run's
   state. Today the notebook agent is forbidden; we'd add a separate
   privileged path for the auditor.
5. **Audit trail**: every VF entry should record the citation handle
   and the IDs of the two runs whose OCs it consolidates, so the
   provenance is checkable later.

## Don't conflate

- "Promote OC to VF" (this design) is about what gets written to the
  notebook between runs.
- "Update VF live in a running notebook" remains forbidden — the
  notebook agent still cannot touch VF entries during a run.
- This design does **not** open the gate on autonomous, unattended
  VF creation during a run. It opens it for **between-run
  promotion** with two independent confirmations + literature.
