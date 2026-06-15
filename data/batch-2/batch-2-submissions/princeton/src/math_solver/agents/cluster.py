"""Cluster Agent — groups extractor candidate tuples by technique family."""
from __future__ import annotations

import re

from ..gemini import call_gemini

_PROMPT_TEMPLATE = """\
## CLUSTER AGENT

### Purpose
Group candidate conjecture tuples by technique family and pick
the two most-distinct representatives.

### Inputs

**1. The Problem:**
```
{problem}
```

**2. Candidate proofs with conjectures** (N items, each a conjecture
tuple of 1-3 statements plus a rigorous proof of *The Problem*
assuming those conjectures):
```
{candidates}
```

### Process
1. Assign each candidate a class letter. Same letter = same
   *technique family* (the underlying mathematical approach;
   differences in parameters, notation, or variable names do not
   count as different families). Read both the tuple statements
   and the implication proof — the proof often reveals the family
   more clearly than the conjectures alone.
2. For each class, pick the candidate whose implication proof is
   most carefully argued. Break ties on clarity of the tuple statements.
3. Within that chosen candidate, identify the **load-bearing**
   conjecture: the single conjecture in the tuple that does the
   substantive work in the implication proof (the others are
   typically routine prerequisites or technical glue). Conjectures
   inside a candidate are numbered 1, 2, 3 in the order they appear
   in the candidate's tuple. If a candidate has only one conjecture,
   the load-bearing index is 1.
4. Rank classes by mutual distinctness. Report the top two.

### Disciplines
- Err toward more clusters when uncertain.
- Do not assess mathematical correctness — that is the gauntlet's job.

### Output Format

CLUSTER ASSIGNMENTS:
- Candidate 1: <letter>
- Candidate 2: <letter>
...

REPRESENTATIVES:
- Class A: candidate <N>, load-bearing = conjecture <M> — <one-line framing summary>
- Class B: candidate <N>, load-bearing = conjecture <M> — <one-line framing summary>
...

TOP TWO:
1. Class <X> — candidate <N>, load-bearing = conjecture <M>
2. Class <Y> — candidate <N>, load-bearing = conjecture <M>
"""


async def run_cluster(
    *,
    problem: str,
    candidates: list[str],
    notebook_id: str,
    run_id: str,
    store=None,
) -> str:
    """Run the cluster agent. `candidates` is a list of extractor outputs (raw),
    each containing a conjecture tuple + implication proof. Returns the cluster
    agent's raw response."""
    joined = "\n\n---\n\n".join(
        f"[Candidate {i + 1}]\n{c}" for i, c in enumerate(candidates)
    )
    prompt = _PROMPT_TEMPLATE.format(problem=problem, candidates=joined)
    call = await call_gemini(
        prompt,
        run_id=run_id,
        notebook_id=notebook_id,
        agent="cluster",
        inputs={"n_candidates": len(candidates)},
        store=store,
    )
    return call.output


def parse_top_two_indices(cluster_output: str) -> list[int]:
    """Parse the cluster agent's TOP TWO section, returning 0-indexed candidate
    positions (i.e. "candidate 5" → 4). Returns at most 2 indices; may return
    fewer if the cluster only found 1 class. Tolerant of minor wording shifts.

    Retained for callers that only need the candidate index. New callers
    should use parse_top_two_pairs to also recover the load-bearing
    conjecture index."""
    return [p[0] for p in parse_top_two_pairs(cluster_output)]


def parse_top_two_pairs(cluster_output: str) -> list[tuple[int, int]]:
    """Parse the cluster agent's TOP TWO section, returning a list of
    (ext_idx, conj_idx) pairs, both 0-indexed. `ext_idx` is the candidate
    position; `conj_idx` is the load-bearing conjecture within that
    candidate's tuple. Missing or unparseable load-bearing fields default
    to conj_idx = 0 (the first conjecture). Returns at most 2 pairs."""
    m = re.search(r"TOP\s+TWO\s*:?\s*\n(.*?)(?:\n\s*\n|\Z)", cluster_output,
                  re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    block = m.group(1)
    pairs: list[tuple[int, int]] = []
    for line in block.splitlines():
        cm = re.search(r"candidate\s+(\d+)", line, re.IGNORECASE)
        if not cm:
            continue
        ext_idx = int(cm.group(1)) - 1
        lm = re.search(r"load[-\s]bearing\s*=?\s*conjecture\s+(\d+)",
                       line, re.IGNORECASE)
        conj_idx = (int(lm.group(1)) - 1) if lm else 0
        if conj_idx < 0:
            conj_idx = 0
        pairs.append((ext_idx, conj_idx))
        if len(pairs) >= 2:
            break
    return pairs
