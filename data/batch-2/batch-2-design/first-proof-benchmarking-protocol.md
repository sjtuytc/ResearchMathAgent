# First Proof Benchmarking Protocol

## Overview

Multiple submitters each provide code that processes a common input file. Each submitter specifies their own hardware requirements. First Proof provides the input data, runs each submitter's code on the requested hardware, and collects results.

First Proof's per-submitter work is: clone a repo, run a script. The input file stays on First Proof's local machine and is copied to a temporary cloud instance only at run time. The instance is destroyed after results are retrieved.

See [README.md](README.md) for the repository structure, technical submission requirements, and how to test locally. Requirements about the nature of the latex solution which is submitted (length of outputs, etc) are described in the Specification for Submissions document provided by First Proof.

## Definitions

| Term | Meaning |
|------|---------|
| First Proof | Owns the AWS account, provides the input data, runs the infrastructure. Has full visibility into all stages of execution. |
| Submitter | Provides code and a hardware spec. Receives only the final output. |
| Input file | A JSON file (~1 MB) that First Proof provides. Common schema across all submitters. |
| Results | Output files (~10s of MB) that the submitter's code writes to /data/output/. |

## What First Proof Provides

1. **Input file.** `input/input.json` — the common set of LaTeX math problems that every submission processes. See [README.md](README.md) for the format.

2. **Run infrastructure.** An AWS account, ephemeral EC2 instances, and the run script ([`run.sh`](run.sh)) that automates the full lifecycle. First Proof's own AWS configuration (account credentials, SSH key pairs, security groups) lives in a gitignored `run-config.env` file; see [`run-config.env.example`](run-config.env.example) for the required fields.

3. **Approved instance types.** The list of EC2 instance types that submissions may request, published in [`allowed-instances.txt`](allowed-instances.txt). First Proof will finalize this list by May 1, 2026.

4. **Secrets handling.** When a submitter provides API keys (see below), First Proof places them at `secrets/<submitter-id>.env` and injects them as environment variables at container launch via `docker run --env-file`.

## What Each Submitter Provides

Each submitter delivers:

1. An invitation to a private GitHub repository containing the submission code. See [README.md](README.md) for the required file structure.

2. A `hardware.json` file (in the repository) specifying:

| Field | Required | Meaning |
|-------|----------|---------|
| instance_type | yes | AWS EC2 instance type. Must be on the approved list (see Security below). Proposals must be submitted by April 30, 2026 for approval. |
| env_vars | when secrets are needed | Set to `true` if the code requires environment variables from a secrets file. |
| ami | no | AMI ID. If omitted, the script uses the default (Ubuntu 24.04 LTS). |
| storage_gb | no | Size of the EBS root volume in GB (gp3). If omitted, defaults to 100. Submitters needing larger model weights, datasets, or scratch space should set this explicitly. |
| rationale | yes | Why this hardware is needed. |

3. Comprehensive logging. The code must write a detailed log of all tokens produced and consumed at each step: model inputs, model outputs, intermediate reasoning/thinking, and any other significant state transitions. This log must be written to `/data/output/` as a structured file (JSON, JSONL, or plaintext) and will be retrieved by First Proof alongside the results.

4. If `env_vars` is `true`: a `secrets.env` file containing the submitter's API keys, delivered to First Proof through a secure out-of-band channel (encrypted message, one-time link, in-person).

## How a Run Works

First Proof launches a fresh EC2 instance of the requested type, uploads the submitter's code and the input file, builds the Docker image, and runs the container. The container sees:

- `/data/input/input.json` — the input file (read-only)
- `/data/output/` — the directory where the submitter's code writes results

After the container exits (or is killed by the timeout), First Proof checks for output, retrieves result files and logs, records run metadata, and terminates the instance.

The full implementation is in [`run.sh`](run.sh).

### Run Metadata

Each run produces `results/<submitter-id>/run-metadata.json`:

```json
{
  "submitter_id": "alice",
  "timestamp_utc": "2026-04-09T14:32:00Z",
  "git_commit": "a1b2c3d4...",
  "instance_type": "g5.xlarge",
  "instance_id": "i-0abc1234def56789",
  "storage_gb": 100,
  "exit_code": 0,
  "runtime_seconds": 1847,
  "timeout_minutes": 1440,
  "output_files": 10,
  "failed": false
}
```

## Visibility

**First Proof**

- Complete source code (via repo access).
- The Dockerfile and every dependency.
- All stdout/stderr from the container.
- All files written to /data/output/.
- Hardware used, runtime, exit code, git commit.

**Submitter**

- This protocol and the [README](README.md).
- The contents of /data/output/, delivered by First Proof on its own timeline (see Turnaround below).

## Security

**Input file.** Lives on First Proof's local machine. Copied to the instance via SCP at run time, mounted read-only into the container, destroyed when the instance is terminated.

**Ephemeral instances.** Each run uses a fresh EC2 instance. The instance is terminated after results are retrieved. No data persists in the cloud between runs.

**Network.** Outbound HTTPS is allowed (for LLM API calls to publicly available models and unauthenticated access to public websites, including web search). Inbound is limited to SSH from First Proof's IP.

**API keys.** Injected as environment variables at container launch. Stored only on First Proof's local machine.

**Timeout.** The container execution is limited to 24 hours of wall-clock time. The timeout clock begins when the Docker container starts executing, not when First Proof initiates instance provisioning. AWS capacity delays (which may take up to 2 business days) do not count against this budget. The instance is always terminated when the script exits, regardless of whether the timeout was reached.

**Code review.** Before running any submitter's code on First Proof's AWS account, a member of the First Proof team performs a lightweight review of the Dockerfile and src/ directory. The review confirms that the code is structurally sound, that declared dependencies match what the code imports, and that the hardware request is consistent with the stated rationale. This review is not an audit and does not require reading every line of source code — it should take no more than 15–30 minutes per submission. No run is scheduled until the review is complete.

**Instance type allowlist.** Submissions may only request instance types from the approved list in [`allowed-instances.txt`](allowed-instances.txt). Requests for unlisted types are rejected and returned to the submitter for revision. First Proof may update this list; submitters will be notified of any changes.

## Turnaround and Communication

**Turnaround commitment.** First Proof commits to delivering results by June 10, 2026. A submission is considered valid when: (1) the GitHub repository is accessible, (2) hardware.json is well-formed and the requested instance type is on the approved list, (3) any required secrets have been received, and (4) the lightweight code review has passed.

**Validation feedback.** If any of the validity conditions above are not met, First Proof will notify the submitter within 3 business days with a specific description of what needs to be corrected. The turnaround clock starts only after all conditions are satisfied.

**Run failures.** If a run fails (non-zero exit code, timeout, or empty output), First Proof will notify the submitter promptly with the exit code, runtime, and any available stdout/stderr so the submitter can diagnose and fix their code. First Proof is not responsible for debugging submitter code but will provide all available logs.

**AWS instance availability.** AWS may return an InsufficientInstanceCapacity error for the requested instance type, particularly for GPU instances which are in high demand. This is not an error in the submission. If this occurs, First Proof will retry in an alternate Availability Zone within the same region, and if still unavailable, will retry in an alternate region. If capacity cannot be obtained within 2 business days, First Proof will notify the submitter. This situation is outside First Proof's control but First Proof will make best efforts to resolve it before the June 10, 2026 deadline.
