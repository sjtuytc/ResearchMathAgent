# modeltesting

Parallel OpenAI-API variant of the First Proof `batch2_design` harness. Reads
`input/input.json` (same schema as batch2), fans the problems out concurrently
to the OpenAI Chat Completions API, and writes one wrapped `.tex` per problem
plus a `run-summary.json`.

Default model: **`gpt-4.1-nano`** — currently the cheapest broadly-available
OpenAI text model (~$0.10 / 1M input tokens, $0.40 / 1M output). Override via
`OPENAI_MODEL` env var.

## Local run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your real OPENAI_API_KEY in .env
set -a; source .env; set +a
# Write output under $SCRATCH, never a relative dir inside this bisynced repo
# (rclone snapshots the working tree mid-run; gitignore does not protect it).
INPUT_PATH=input/input.json OUTPUT_DIR="$SCRATCH/fp-benchmark/modeltesting" python src/run.py
```

## Docker run (matches batch2_design submitter contract)

```bash
docker build -t modeltesting .
docker run --rm \
  --env-file .env \
  -v "$PWD/input/input.json:/data/input/input.json:ro" \
  -v "$PWD/results:/data/output" \
  modeltesting
```

## Configuration (env vars)

| Var | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | Standard OpenAI key |
| `OPENAI_MODEL` | `gpt-4.1-nano` | Any chat-completions model id |
| `CONCURRENCY` | `10` | Max in-flight API calls |
| `PER_CALL_TIMEOUT` | `120` | Per-request timeout (s) |
| `MAX_RETRIES` | `5` | Exponential-backoff retries on rate-limit / timeout |
| `INPUT_PATH` | `/data/input/input.json` | Input JSON path |
| `OUTPUT_DIR` | `/data/output` | Output directory |

## Output

For each `problems[i]` in the input, writes `<id>.tex` to the output dir — the
original LaTeX with the model's response appended as a `verbatim` block before
`\end{document}`. A `run-summary.json` captures totals, failures, and wall time.

## Relationship to batch2_design

Same I/O contract (`/data/input/input.json`, `/data/output/`). The difference
is parallelism: batch2's reference `test-dummy` submitter walks problems
serially with a 10s sleep between them; this runner dispatches them
concurrently with a semaphore.
