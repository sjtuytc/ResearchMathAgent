# First Proof — Batch 2

This repository contains everything a submitter needs to understand and prepare a submission for the First Proof benchmarking run.

First Proof provides a common input file of LaTeX math problems. Each submitter provides code that processes these problems inside a Docker container on AWS. First Proof runs the code, collects the output, and delivers results.

See [first-proof-benchmarking-protocol.md](first-proof-benchmarking-protocol.md) for the full protocol: security model, turnaround commitments, and responsibilities.

## Repository structure

```
├── input/input.json                     # Common input file (LaTeX problems)
├── run.sh                               # First Proof's run script
├── run-config.env.example               # Template for AWS configuration
├── allowed-instances.txt                # Approved EC2 instance types
├── first-proof-benchmarking-protocol.md # Full benchmarking protocol
├── submissions/
│   └── test-dummy/                      # Reference submission (working example)
├── secrets/                             # Submitter API keys (gitignored)
└── results/                             # Run output per submitter (gitignored)
```

`run.sh` is the script First Proof uses to launch an EC2 instance, build and run your Docker container, collect results, and terminate the instance. It is included so submitters can see exactly how their code will be executed.

## What a submission must contain

Each submitter provides a private GitHub repository with the following:

```
├── Dockerfile
├── hardware.json
├── README.md
├── src/
│   └── (your code)
└── (any other files your Dockerfile needs)
```

First Proof clones the repository into `submissions/<submitter-id>/` and runs it from there.

### Dockerfile

Your Dockerfile must produce an image whose `CMD` processes the input and writes output. The container will be launched with:

```bash
docker run --rm \
  -v input.json:/data/input/input.json:ro \
  -v output-dir:/data/output \
  --env-file secrets.env \    # only if env_vars is set
  your-image
```

Your code must:
- Read input from `/data/input/input.json`
- Write all output files to `/data/output/`

### hardware.json

Specifies the EC2 instance type and timeout for your run:

```json
{
  "instance_type": "t3.micro",
  "env_vars": true,
  "rationale": "Brief explanation of why this hardware is needed."
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `instance_type` | yes | EC2 instance type. Must be on the approved list in `allowed-instances.txt`. |
| `env_vars` | when needed | Set to `true` if your code requires environment variables from a secrets file. |
| `ami` | no | Custom AMI ID. Omit to use the default (Ubuntu 24.04 LTS). |
| `storage_gb` | no | Size of the EBS root volume in GB (gp3). Defaults to 100 if omitted. Increase if you need to download large model weights, datasets, or scratch space. |
| `rationale` | yes | Why this instance type is needed. |

### README.md

Submitters must include a README describing their submission: what approach or model it uses, what secrets it requires (if any), and any other context that would help First Proof understand the code during the review step described in the protocol.

### Secrets

If your code needs API keys or other credentials, set `"env_vars": true` in `hardware.json` and deliver a `secrets.env` file to First Proof through a secure out-of-band channel (encrypted message, one-time link, etc.). The file should contain one `KEY=value` pair per line. Values are injected into the container as environment variables at runtime.

## Input format

`input/input.json` contains an array of LaTeX math problems:

```json
{
  "problems": [
    {
      "id": "prob-001",
      "latex": "\\documentclass{article}\n\\usepackage{amsmath}\n\\begin{document}\n\\textbf{Problem 1.} ...\n\\end{document}"
    }
  ]
}
```

Each entry has an `id` (string) and `latex` (a complete, compilable LaTeX document).

## Testing locally

You can validate your submission locally before delivering it:

```bash
# Build your image
docker build -t my-submission .

# Run against the input file from this repo
docker run --rm \
  -v $(pwd)/input/input.json:/data/input/input.json:ro \
  -v $(pwd)/my-output:/data/output \
  --env-file my-secrets.env \
  my-submission

# Check that output files appear
ls my-output/
```

## Reference submission

`submissions/test-dummy/` is a complete working example. It reads each problem, sends it to an LLM via OpenRouter, and writes `.tex` files to `/data/output/`. See its README for details. Use it as a reference for the expected structure.

## Approved instance types

See `allowed-instances.txt` for the current list. Requests for unlisted instance types will be returned for revision. First Proof may update this list; submitters will be notified of changes.
