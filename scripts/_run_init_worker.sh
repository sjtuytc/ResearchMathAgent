#!/usr/bin/env bash
# Run one init-all-tabs worker for a set of datasets, on the global Vertex endpoint.
# Usage: _run_init_worker.sh <dataset> [dataset ...]
set -uo pipefail
cd /projects/bhov/zzhao18/code/ResearchMathAgent-web
export GOOGLE_CLOUD_REGION=global
export GOOGLE_CLOUD_PROJECT=nairr-260096-569948
export PYTHONPATH="${HOME}/.local/lib/python3.12/site-packages"
PY=/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12
echo "[worker start $(date '+%F %T')] datasets: $*"
"$PY" scripts/init_all_tabs.py --datasets "$@"
echo "[worker done $(date '+%F %T')] datasets: $*"
