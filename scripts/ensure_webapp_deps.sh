#!/usr/bin/env bash
# Install webapp runtime deps into a project-local directory (no sudo needed).
# Sourced by start_server.sh and start_dev.sh.
set -euo pipefail

DEPS_DIR="${RMA_DEPS_DIR:-${ROOT}/.deps}"
PYTHON="${PYTHON:-python3}"

mkdir -p "$DEPS_DIR"

if [[ ! -d "$DEPS_DIR/google/auth" ]]; then
    echo "[deps] Installing google-auth into ${DEPS_DIR}..."
    "$PYTHON" -m pip install --target "$DEPS_DIR" 'google-auth>=2.0' -q
fi

export PYTHONPATH="${DEPS_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

# Vertex AI defaults — project is read from ADC quota_project_id if unset.
export GOOGLE_CLOUD_REGION="${GOOGLE_CLOUD_REGION:-global}"
