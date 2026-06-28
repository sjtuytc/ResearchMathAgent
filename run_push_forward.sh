#!/usr/bin/env bash
# Run push-forward outside the uvicorn process (immune to --reload kills).
# Usage: ./run_push_forward.sh [q1 q2 ...] [--force] [--dataset first_proof_1]
cd "$(dirname "$0")"
PYTHON=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
export PYTHONPATH="${HOME}/.local/lib/python3.12/site-packages"
exec "$PYTHON" -u -m webapp.push_forward_cli "$@"
