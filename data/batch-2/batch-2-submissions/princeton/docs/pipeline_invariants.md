# Pipeline invariants — do not break

Operational rules that took experimental discovery to find and silent
bugs to fix. Future agents editing prompts, the orchestrator, or any
agent code should preserve every invariant here. If a change *appears*
to violate one, that's the moment to surface and consult before
shipping — these were not designed in advance; they emerged from
diagnosing wrong outputs.

Last touched: 2026-05-28.

---

## 1. Strip-on-harvest: agent outputs are cleaned at the agent's return

Every battle-tested agent prompt asks the model to (a) reason internally
("Council deliberation," "Grading forum," `<internal_monologue>`, etc.)
then (b) emit a structured final output (PROOF_START sentinel, Part 2
headers, Areas-for-Improvement / Scaffolding-Questions sections).

**The reasoning portion must never reach a downstream live agent.** It
is verbose, opinionated, often praises the proof being graded, and
biases the next-stage solver/grader/extractor that consumes it.

### The rule

Strip at **harvest time** (the agent runner's return statement), not at
each downstream consumer site. Downstream consumers should be able to
trust that what they receive is already clean.

Currently-implemented harvest-time strippers (do not remove without a
replacement):

| Agent | Function | Strips to |
|---|---|---|
| `agents/extractor.run_conjecture_extractor` | local `_strip_part1` | Part 2 (Completed Proof with Conjectures) onward; drops Part 1 Grading Log |
| `agents/grader._parse_grader_async` | local `_extract_critique_only` | Areas for Improvement + Scaffolding Questions; drops Council deliberation, numerical-grade prose, Strengths, Coroner's Report praise. Score is preserved separately in `.score`. |
| `agents/solver.run_solver` (de facto, via consumers) | downstream `_proof_only` (grader.py) | Part 3 / PROOF_START block. Solver's raw `call.output` is left intact; every downstream consumer (grader, BS detector, bundle, notebook) calls `_proof_only` itself. |

Downstream "safety net" strippers also remain in place
(`_extract_grader_critique`, `_extract_part2` in orchestrator.py) and
should not be removed — they are idempotent and protect against future
slips.

### Why this matters

Concrete examples of past failure modes from skipping strip:

- The conjecture-extractor's `.raw` field carried Part 1 Grading Log
  into (a) the cluster agent, (b) the next stage's notebook injection,
  and (c) Mode A child run `additional_materials`. None of these
  stripped. Polluted notebook prose biased downstream solvers (caught
  2026-05-28).
- The grader's full output (with Strengths praise and "SCORE: 7/7"
  Coroner's Report) was being piped into next-stage solver bundles via
  a regex that silently failed to match. Praise reinforces wrong ideas;
  the score-prose biases the next-stage solver into believing its
  predecessor's proof was good (caught 2026-05-28 — same regex bug had
  been live in `_extract_grader_critique` since the function was
  written).

### Implementation pattern for extraction

Three-tier fallback chain (see `_proof_only`, `flash_extract_score`,
`flash_extract_proof` for prior art):

1. **Tier 1 — regex / marker.** Cheap, fast, no LLM call. Match the
   structured marker the prompt asks for. Be defensive about
   variants (e.g. `**Areas for Improvement:**` vs `**Areas for
   Improvement**` — the colon variant is more common; allow `:?`).
2. **Tier 2 — Gemini Flash with structured output.** When Tier 1
   fails (model deviated from the expected format), call Flash with a
   tight prompt and JSON schema constraining the response to the
   exact sections needed. Robust to LLM drift; ~$0.001/call.
3. **Tier 3 — full text fallback.** When Tier 2 also fails, return
   the original unmodified text. Never silently return empty — that
   would break downstream consumers expecting non-empty feedback.

`_extract_critique_only` and `_strip_part1` currently implement Tier 1
+ Tier 3 only. TODO #8 in `docs/firstproof_may29_todos.md` is to add
Tier 2 (Flash) — would raise the 12% miss rate observed on real
grader outputs to ~2%.

### When editing a prompt

If you change an agent's emitted output format (renaming a section,
adding new headers, restructuring Part 1/Part 2), update the strip
helper in lockstep. Verify offline by running the helper against
recent run.db outputs from that agent:

```
python -c "
import sys, sqlite3
sys.path.insert(0, 'src')
from math_solver.agents.grader import _extract_critique_only  # or whichever
conn = sqlite3.connect('runs/<rid>/run.db')
for (out,) in conn.execute(\"SELECT output FROM agent_calls WHERE agent LIKE 'grader%' LIMIT 20\"):
    stripped = _extract_critique_only(out)
    print('OK' if stripped != out else 'FALLBACK')
"
```

---

## 2. OpenAI cross-model exit gate — do not remove without a replacement

`orchestrator.py` calls `openai_grader.grade_proof` after the Gemini
gauntlet confirms a 7/7. The run only exits early if OpenAI also
scores ≥7. Kill switch: env var `OPENAI_GATE_DISABLED=1`.

### Why this exists

The Gemini gauntlet (3 draws + aggregator, all must score ≥7) protects
against stochastic per-call noise. It does **not** protect against the
grader having a consistent per-model blind spot — 4 Gemini calls can
all lock in the same overgenerous read of a proof structure.

Empirical motivation (2026-05-28 cross-verifier studies, 7 runs spanning
Q2/Q5/Q7/Q8/Q9):

- **OpenAI study:** 28 Gemini-gauntlet-confirmed-7/7 proofs.
  OpenAI rated them with mean Δ = −3.29, range −5.0 to −1.0. **Zero
  cases of OpenAI ≥ 7**, even on the best-case problem (Q7, where
  OpenAI averaged 6/7).
- **Grader 3 retrospective:** 54 Gemini-≥6 proofs (subset of the same
  runs). Verdicts: REWORK / REWRITE / UNVERIFIABLE. **Zero PASS
  verdicts on any Gemini-7.**

So `gauntlet → OpenAI` is the strict-AND. On fail, the parent record's
score is overwritten to `min(gauntlet, openai)` and the parent's
feedback is replaced with OpenAI's critique. Next stage's solvers see
OpenAI's critique via `ensemble_feedback`.

### If you're tempted to weaken this

Don't, unless you have:
- A new cross-verifier study showing OpenAI's calibration improved (or
  another grader replaces it),
- AND a measured impact on shipped-proof quality (the FP `.tex`
  shipped after the change should be no worse than before by some
  external standard).

The kill switch is for emergency use (OpenAI API outage during the FP
submission window), not for "the gate is annoying me." If a future
agent thinks "the gate blocks too many exits," that's the gate doing
its job per existing empirical data.

---

## 3. Bundle displays effective score (post-gate), not initial grader score

`_format_stage_bundle` (orchestrator.py) reads the parent record's
score from `state.all_solutions`, not the initial grader's
`grader_results[i].score`. This matters because:

1. The gauntlet aggregator overwrites the parent record's score in
   place when it disagrees with the initial 7.
2. The OpenAI gate also overwrites in place when it disagrees with
   the gauntlet.

If the bundle uses `grade.score` (the initial grader's value), next-
stage solvers see misleading inflated 7/7s for proofs that both
downstream gates demoted. Fixed 2026-05-28.

When adding new gates or scoring steps, preserve this invariant:
**whatever score a future agent sees in the bundle must be the score
the pipeline currently believes**, not the score from the first grader
call.

---

## 4. Prompts are battle-tested — diff-sized patches only

Restated from `CLAUDE.md` for emphasis: `agents/*.py` prompts and
`agents/notebook_v2_prompt.txt` are baseline. Wholesale rewrites are
forbidden. Only diff-sized patches justified by specific failure
transcripts.

If a strip helper breaks because a prompt was edited, the right fix
is to either (a) update the strip helper in lockstep, or (b) revert
the prompt edit. Do not revert the strip discipline.

---

## 5. R rounds (conjecture extractor) — currently 2

`CONJECTURE_ROUNDS = 2` (overridable via env var). Each round runs
W solvers attacking active conjectures (2/3 prove + 1/3 disprove,
distributed across surviving conjectures); a single grader 7/7
resolves a conjecture.

The conjecture stage fires only when (a) `no_progress_count >= 2`
AND (b) the W parallel extractors produced at least one structured
conjecture that survived the cluster agent's top-2 selection. As of
2026-05-28, the conjecture stage had fired in exactly 1 run out of
172 in the run database — the machinery is almost untested in
practice. Treat behavior changes here as exploratory.

The R-round inner loop currently does NOT run the gauntlet or the
OpenAI gate on its single grader calls — invariant #2 above does
NOT apply inside the conjecture stage. Worth revisiting once the
machinery has more data.

---

## 6. Run database (run.db) preserves full raw — strip helpers must not mutate it

The `agent_calls` table records `call.output` as written by
`call_gemini` and its peers, BEFORE any strip helper runs. This is
intentional: for debugging and post-hoc analysis, the full Council
deliberation / Part 1 / Strengths praise / score prose must remain
inspectable.

Strip helpers mutate the in-memory `AgentCall.output` or the
structured `.feedback`/`.raw` fields of the agent result object
*after* the gemini call has been logged. Future code that adds new
agents or wraps existing ones must preserve this distinction:
- Persist full raw to run.db (status quo via `call_gemini`).
- Return cleaned-text to the orchestrator and downstream agents.

Do not "save the cleaned version to run.db for tidiness" — you'll
delete forensic information needed for the next round of
this-debugging.
