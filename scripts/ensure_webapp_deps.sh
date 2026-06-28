#!/usr/bin/env bash
# Install webapp runtime deps into a project-local directory (no sudo needed).
# Sourced by start_server.sh and start_dev.sh.
set -euo pipefail

DEPS_DIR="${RMA_DEPS_DIR:-${ROOT}/.deps}"
PYTHON="${PYTHON:-python3}"

mkdir -p "$DEPS_DIR"

export PYTHONPATH="${DEPS_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
