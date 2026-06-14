# Skill — Prompt optimization for the math_solver pipeline

Captures the procedure for revising an agent's prompt. Distilled from
the sessions on `bs_detector.py`, `grader.py`, `solver.py`,
`paper_hunter.py`, and `notebook_v2_prompt.txt` (May 2026).

## When to invoke

- A specific failure transcript (false positive, false negative, missed
  case) names a sentence or clause in the prompt to change.
- An agent's prompt was migrated mechanically and now needs a coherent
  rewrite pass.
- A new agent's prompt exists in draft form and has never been reviewed.

Do **not** invoke for: "I think this prompt looks long." Verbose ≠
broken. Every load-bearing clause was usually added in response to a
past failure; ripping it out reintroduces the failure.

## Principles

1. **Baseline first.** Read the current prompt end-to-end before
   proposing changes. The prompt is treated as battle-tested until
   proven otherwise.
2. **Diff-sized patches, not rewrites.** Each proposed change should be
   justifiable by either (a) a specific past failure transcript, or
   (b) a clarity issue the user can point at. No wholesale
   reorganization for taste reasons.
3. **Terse Sanjeev-style prose.** Short sentences. No "in order to" /
   "it is important to note" / "please be sure to" padding. One-line
   bullets for lists. Personas one sentence each. Process steps
   one-line each. Examples kept verbatim only when the example itself
   was the test case that caused a past failure.
4. **General, not problem-specific.** "We don't want to design prompts
   using a single problem. The patches have to be general." Variance
   check ≥3 runs across ≥2 problems before claiming an improvement.
5. **Preserve gory-detail clauses that the user explicitly added.**
   When the user has spelled out (a) and (b) clauses, those are sacred.
   Compress around them, not through them.
6. **System_instruction architecture.** Personas + discipline rules
   live in `system_instruction`. Run-specific inputs are labeled
   fields in the user contents (`**Problem:** ...`, `**Notebook:**
   ...`). Migrate the architecture in the same pass as the rewrite
   when feasible — both touch the same file.
7. **Surface omissions explicitly.** When proposing a terse rewrite,
   list which clauses you compressed or removed. The user audits
   those specifically. Silent omission is the worst failure mode.

## Procedure

### Phase 1 — Read

- Read the current prompt file end-to-end.
- Look at recent commits touching it (`git log --oneline -p
  <prompt-file>` or `git log --follow`). Note any clauses that were
  added in response to specific incidents — those are load-bearing.
- Look at recent agent outputs in `runs/<id>/agent_calls/` for failure
  patterns the prompt is supposed to prevent. The handoff and IPT
  entries in notebooks sometimes name specific clauses.

### Phase 2 — Propose

Write the rewrite as a single file paste, terse-style. In parallel,
write a short audit memo to the user:

- **Compressed:** list of clauses you shortened, with the original
  and the replacement.
- **Removed:** list of clauses you cut entirely, with one-line
  justification each.
- **Preserved verbatim:** list of clauses you kept word-for-word and
  why (usually: load-bearing examples or user-added (a)/(b) clauses).
- **Architecture change:** what moved to `system_instruction`, what
  stayed in user contents, what labeled-field structure the user
  message now uses.

Wait for review. Do not commit until the user signs off.

**Present the audit in human-sized chunks.** A single response stuffed with
every preserved/compressed/removed clause plus migration plan plus open
decisions is too dense to review reliably — humans miss things in that
mode. Default to one chunk at a time (e.g. "audit of the slim" first,
pause for reaction; then "migration plan"; then "open decisions"). Expand
acronyms on first use within a chunk (VF = Verified Fact, etc.) — the
prompt itself uses them, but a review conversation should not assume the
reader is holding the full vocabulary in working memory.

### Phase 3 — Review iteration

The user typically pushes back on:
- A clause you thought was redundant but was the one keeping a known
  failure mode at bay.
- Word choice / tone (Sanjeev prefers a specific terseness).
- A persona's role getting subtly altered.

Iterate the diff, not the whole rewrite. One clause at a time.

### Phase 4 — Validate

After commit:
- **Variance check.** Run the agent ≥3 times on ≥2 problems with
  the old prompt and the new prompt side by side. Compare failure
  modes — not just success/failure but *which* gaps got caught.
- **Replay if possible.** If a prior run hit the failure mode the
  rewrite was supposed to fix, replay that run with the new prompt
  and confirm the fix.
- **Single-problem patches are forbidden.** A rewrite that improves
  Q9 outcomes but regresses on Q2 is a net loss — verify across
  problems.

### Phase 5 — Snapshot

Snapshot the rewritten prompt into
`prompts_archive/<YYYY-MM-DD>_<purpose>/` with a README documenting
what changed. This is the rollback point if the rewrite turns out to
have regressed.

## Common pitfalls

- **Over-aggressive compression of personas.** Each persona's role
  description anchors its behavior. Cutting "**Veritas, the
  Inquisitor:** Gatekeeper of truth. Two phases..." down to "Veritas
  checks logic" reliably regresses the agent. Keep at least one
  sentence per persona that names its discipline.
- **Cutting examples.** The Slip Hunter's "by the equivariance of W..."
  example was added because a real failure produced exactly that
  wording. Removing it causes the failure to return. Verify against
  IPT entries before cutting any example.
- **Hand-tuning prompts on a single failing transcript.** This is the
  most common failure mode. Sanjeev: "The patches have to be general."
- **Not migrating the driver in the same pass.** If the prompt moves
  to `system_instruction` but the driver still passes it as a user
  message, nothing changes operationally. Patch both.
- **Silently removing the "if unsure, flag as gap" / "if unsure, omit
  rather than mis-state" hedges.** These are how the agent expresses
  epistemic humility. Without them, the agent invents.

## Failure modes that should *not* be addressed with a prompt patch

- Hallucinated citations → input bug (truncation, wrong scope).
- "Proof is empty" verdict on a populated proof → double-extraction
  (see `_proof_only` Flash extractor bug, 2026-05-19).
- Two BS panels giving opposite verdicts → input bug (one panel saw
  the notebook, the other didn't).
- Solver degenerates into Stack Overflow content → stochastic Gemini
  event, mitigated by SDK defaults (2026-05-20 fix).

If you're tempted to fix one of these via prompt patch, stop and
inspect `tokens_in` for the failing call first.

## Per-prompt inventory (as of 2026-05-22)

| File | Slim? | User-reviewed slim? | SI-migrated? |
|---|:-:|:-:|:-:|
| `agents/bs_detector.py` | ✓ | ✓ | ✓ |
| `agents/grader.py` | ✓ | ✓ | ✓ |
| `agents/solver.py` | ✓ | ✓ | ✓ |
| `agents/notebook.py` (prompt inlined as `_SYSTEM_INSTRUCTION`) | ✓ | in progress (2026-05-22) | ✓ |
| `agents/paper_hunter.py` | ✓ | ✓ | **✗** (handoff history was wrong) |
| `agents/extractor.py` | ✗ | ✗ | ✗ |
| `agents/triage.py` | ✗ | ✗ | ✗ |
| `agents/paper_guide.py` | ✗ | ✗ | ✗ |
| `agents/literature.py` (stub) | n/a | n/a | n/a |

**Recent diff-sized patches:**
- 2026-05-22, `agents/extractor.py` (commit `13182f4`): added the **Conjecture
  Auditor** persona (keep-minimal / make-nontrivial / not-refutable-on-small-examples)
  to catch over-strong extracted conjectures. Replay validation in
  `scratch/2026-05-22_extractor_patch/`. Variance check across ≥2 problems still pending.

**Stealth prompts (easy to miss):**
- BS-aggregator prompt embedded in `bs_detector.py` (~lines 210-260) — touched
  during driver migration but not separately reviewed.
- Grader-aggregator prompt embedded in `grader.py` (~lines 334-350) — same.
- `scratch/2026-05-20_retrieval_prototype/research_librarian_prompt.md`,
  `librarian_gauntlet_v2.py`, `citation_expand_v3.py` — new last night,
  unreviewed.
- `scratch/2026-05-21_q8_literature/librarian_gauntlet_q8.py`
  (LIBRARIAN_PROMPT + AGGREGATOR_PROMPT) — new 2026-05-21, unreviewed.
- `scratch/2026-05-21_q8_literature/book_findings_q8.py`
  (`READING_PLANNER_PROMPT`) — new 2026-05-21, ran once on Cannas,
  unreviewed. Most-likely-to-need-tightening of the new prompts.

## Recommended order for the next pass

1. **`notebook.py`** — finish the slim review (in progress 2026-05-22).
   SI migration already done in commit `ea82621`'s follow-up; only the
   user-review of the slim content remains.
2. **`READING_PLANNER_PROMPT` in `book_findings_q8.py`** — validate by
   running on a second book before committing.
3. **`paper_hunter.py`** — finish SI migration (slim is done and approved).
4. **Embedded aggregator prompts** in `bs_detector.py` and `grader.py` —
   review as standalone prompts.
5. **`extractor.py`, `triage.py`, `paper_guide.py`** — touched least, but
   feed the agents you do care about, so worth a pass before Challenge 2.

## Related memory entries

- `feedback_prompt_iteration.md` — keep Sanjeev's prompts as baseline;
  only diff-sized patches.
- `project_agent_prompt_design.md` — canonical architecture (personas
  in `system_instruction`, run-specific inputs as labeled user fields).
- `feedback_consult_on_architecture.md` — surface prompt-shape /
  API-config design choices before extending.
- `feedback_minimize_interventions.md` — "Act on execution; consult on
  design." Prompt changes are design, not execution.
- `project_math_notebook_prompt.md` — past notebook-prompt patch
  (2026-05-15, dedup-rule patch).
