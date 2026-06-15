# verifier_v2

Improved verifier pipeline for the Moonshot math harness. Implements v2_plan.md.

## Requirements

```bash
pip install openai
export OPENAI_API_KEY=sk-...
```

## Usage

### Full finalize pipeline
```python
from verifier_v2 import finalize

result = finalize(
    candidate_proof="...",
    problem="Show that ...",
    reasoning="high",          # API reasoning effort
    kb_file="failed_gaps.jsonl",  # persistent KB for failed approaches
    split_chunks=False,        # single chunk (recommended for most proofs)
)

if result["track"] == "A":
    print(result["solution_tex"])  # LaTeX output
else:
    print("Track B:", result["major_gaps"])
```

### In-loop verification (fast, citation-only pre-check)
```python
from verifier_v2 import run_prechecker, run_verify, is_accepted

precheck = run_prechecker(proof, in_loop=True)   # CitationChecker only
score, major, minor, raw = run_verify(proof, problem, precheck)
if is_accepted(score):
    proceed_to_finalize()
elif score <= 6:
    record_to_kb_and_restart()
else:
    patch_and_retry(minor)
```

### Check failed approaches (advisor injection)
```python
from verifier_v2 import get_failed_approaches
approaches = get_failed_approaches("failed_gaps.jsonl")
# Inject into advisor prompt as failed_attempts_block
```

## Architecture (v2_plan.md)

- **§0 chunker.py**: one-time chunk generation, reused throughout
- **§1 prechecker.py**: NumericalChecker (finalize only) + CitationChecker (always)
- **§2 scorer.py**: 1-10 scoring, MAJOR_GAPS, MINOR_GAPS
- **§3 gap_classifier.py**: KB recording for major gaps → advisor injection
- **§4 patcher.py**: targeted minor-gap patching (max 2 attempts per gap)
- **§5 memory.py**: LemmaDB, CitationDB, FailedGapDB (JSONL caches)
- **pipeline.py**: main finalize flow integrating all components

## Thresholds
- `VERIFY_ACCEPT_THRESHOLD=9` (env var): minimum score to accept
- Score ≥ 9: accept immediately
- Score 7-8: targeted patch + re-verify
- Score ≤ 6: Track B (do NOT restart solver from finalize)
