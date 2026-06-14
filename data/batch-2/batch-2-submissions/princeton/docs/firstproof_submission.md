# First Proof — Second Batch submission

How `momus-firstproof` is packaged to meet the Second-Batch specification
(spec dated 2026-04-15). This doc covers the **I/O contract**, **how to run**
(local + Docker), **what the spec requires vs. what we provide**, and the
**open items** (notably the AWS layer, built in a second pass).

## Spec → implementation map

| Spec requirement | Where it's handled |
|---|---|
| Input = one JSON of ten problems (each compilable LaTeX) | `batch.load_problems` (tolerant loader) |
| Process all problems **in parallel** | `batch.run_batch` — one OS subprocess per problem |
| Results **within 24h** | `--timeout-hours` (default 24); unfinished runs are terminated and reported |
| Output = one JSON, ten solutions, each a **compilable LaTeX document** (article, 12pt, default margins, ≤12 pp) | `latex_export.typeset_and_verify` + `batch.run_batch` |
| Compiles cleanly on Overleaf | LLM typeset → local `pdflatex` compile-check → error-feedback repair loop → condense-if-over-12-pp |
| Log tokens per call (input / output / **reasoning**) + totals on completion | already logged to `agent_calls` (`tokens_in/out/think`); rolled up in the output JSON `metadata.token_totals` |
| Report a problem could not be solved | `solved=false` per solution; the LaTeX doc states the limitation honestly |
| Public models only | uses the Gemini API — see "Model" below |
| Fully automated AWS deploy (API keys + JSON only) | `deploy/deploy.sh` + `deploy/terraform/` — Terraform + single EC2 (see `deploy/README.md`) |

## Input JSON schema

Canonical form (also accepts a bare list of strings, a bare list of objects, or
an object keyed by id — see `load_problems`):

```json
{
  "problems": [
    {"id": "P1", "statement": "\\documentclass[12pt]{article}...\\end{document}"},
    {"id": "P2", "statement": "..."}
  ]
}
```

Each `statement` is the problem's own complete, compilable LaTeX document, exactly
as First Proof supplies it. Example: `deploy/sample_problems.json`.

> First Proof will publish exact deployment details (including their precise JSON
> schema and the one representative problem+solution) in their own repo. If their
> schema differs, **adjust `load_problems` only** — nothing downstream cares.

## Output JSON schema

```json
{
  "metadata": {
    "spec": "First Proof — Second Batch",
    "model": "gemini-3.1-pro-preview",
    "num_problems": 10,
    "num_solved": 4,
    "wall_time_seconds": 53210.0,
    "token_totals": {"input": ..., "output": ..., "reasoning": ..., "total": ...}
  },
  "solutions": [
    {
      "id": "P1",
      "solved": true,
      "score": 7.0,
      "latex": "\\documentclass[12pt]{article}...\\end{document}",
      "compiles": true,
      "pages": 8,
      "tokens": {"input": ..., "output": ..., "reasoning": ..., "total": ...},
      "run_id": "ab12cd34ef56",
      "status": "DONE",
      "notes": ""
    }
  ]
}
```

The spec's core requirement is `solutions[i].latex`: a standalone compilable
document. Individual `.tex` files are also written next to the JSON
(`<output>_tex/<id>.tex`) for convenience.

## Run it

### Locally (needs Python 3.11 + `pdflatex` + `GEMINI_API_KEY`)

```bash
pip install -e .
export GEMINI_API_KEY=...
math-solver run-batch deploy/sample_problems.json -o solutions.json \
  --width 4 --depth 4 --timeout-hours 24
```

Useful flags: `--no-search` (default; arxiv retrieval is dormant), `-W/-D`
(width/depth per problem), `--latex-repairs N`, `--timeout-hours H`.
`GEMINI_CONCURRENCY` (env) caps in-flight Gemini calls **per problem** — total
in-flight ≈ `GEMINI_CONCURRENCY × num_problems`; lower it if the API rate-limits.

### Docker (bundles TeX Live, so compile-checking always works)

```bash
docker build -f deploy/Dockerfile -t momus-firstproof .
docker run --rm -e GEMINI_API_KEY=$GEMINI_API_KEY \
  -v "$PWD/data:/data" momus-firstproof \
  /data/problems.json -o /data/solutions.json
```

## Model

The pipeline calls `gemini-3.1-pro-preview` (override with `GEMINI_MODEL`). The
spec requires "publicly available models" only. The Gemini API is publicly
available, but **"preview" tier is worth a deliberate confirmation** before
submission — either confirm preview models satisfy the editorial board's
"publicly available" bar, or pin a GA Gemini model via `GEMINI_MODEL`.

## What's new for the submission (2026-05-22)

Added without touching the battle-tested research prompts:

- `src/math_solver/batch.py` — batch driver (JSON in → JSON out, parallel runs).
- `src/math_solver/latex_export.py` — LaTeX typesetter + `pdflatex` compile/repair.
- `run-batch` CLI command.
- `GEMINI_CONCURRENCY` env knob in `gemini.py`.
- `deploy/Dockerfile`, `.dockerignore`, `deploy/sample_problems.json`.
- New agent prompt: `prompts/11_latex_typesetter.md` (⚠ not yet variance-tested).

## AWS deployment (built)

`deploy/deploy.sh` + `deploy/terraform/` implement the spec's "fully automated …
only API keys and a JSON file" deploy on a single EC2 instance (the workload is
API-bound, so one box running all problems in parallel is enough). Flow:
`deploy.sh` packages the repo, stores the API key in SSM SecureString (kept out
of TF state), and `terraform apply` creates an S3 bucket + IAM + EC2 that builds
the image, runs `run-batch --timeout-hours 24`, uploads `solutions.json` to S3,
and self-terminates. See `deploy/README.md`.

## Open items

1. **Nothing run end-to-end on a live API key / real AWS account yet.** The
   pure-Python pieces are verified against real `pdflatex`; the LLM paths and the
   Terraform/EC2 flow still need a real dry run (`terraform plan` + a small batch).
2. **Typesetter prompt is unproven** — needs testing on real solver outputs and
   variance-checking across problems before relying on it.
3. **`solved` threshold** is the internal grader score ≥ 7.0; revisit against the
   spec's grading categories if needed.
4. **Model/public-model confirmation** (above).
5. **Rate limits:** 10 parallel problems × `GEMINI_CONCURRENCY` calls each may hit
   Gemini quota; tune `GEMINI_CONCURRENCY` for the deployment account.
6. **Terraform assumes a default VPC** in the region (no `subnet_id` var yet).
