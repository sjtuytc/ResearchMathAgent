#!/usr/bin/env bash
# setup_server.sh — one-shot setup + launch for ResearchMathAgent.
#
# Installs runtime dependencies, starts all backend services, and opens a
# public tunnel so the UI is reachable from outside the cluster.
#
# Usage:
#   bash setup_server.sh            # dev mode  (serveo.net, port 8001)
#   bash setup_server.sh --prod     # prod mode (ngrok,      port 8000)
#   bash setup_server.sh --stop     # kill everything and exit
#
# Environment overrides (all optional):
#   PYTHON                   path to Python 3.12 binary
#   RMA_MODE                 dev | prod (default: dev)
#   RMA_DEV_SUBDOMAIN        serveo subdomain (default: rma-dev)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"

# ── Argument parsing ──────────────────────────────────────────────────────────
MODE="${RMA_MODE:-dev}"
STOP_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --prod)   MODE=prod ;;
        --dev)    MODE=dev  ;;
        --stop)   STOP_ONLY=true ;;
        *)        echo "Unknown arg: $arg  (valid: --dev --prod --stop)"; exit 1 ;;
    esac
done

# ── Port assignments ──────────────────────────────────────────────────────────
if [[ "$MODE" == "prod" ]]; then
    PROXY_PORT=8000; SOLVE_PORT=8010; FILTER_PORT=8013
    TUNNEL_CMD="ngrok"
    PUBLIC_URL="https://${NGROK_DOMAIN:-<your-ngrok-domain>}"
    UVICORN_EXTRA=""           # no --reload in prod
else
    PROXY_PORT=8001; SOLVE_PORT=8011; FILTER_PORT=8012
    TUNNEL_CMD="serveo"
    PUBLIC_URL="https://${RMA_DEV_SUBDOMAIN:-rma-dev}.serveousercontent.com"
    UVICORN_EXTRA="--reload --reload-delay 0.5"
fi

# ── Python binary ─────────────────────────────────────────────────────────────
PYTHON="${PYTHON:-/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12}"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3.12 2>/dev/null || command -v python3 2>/dev/null)"
fi
if [[ -z "$PYTHON" ]]; then
    echo "[setup] ERROR: Python 3.12 not found. Set PYTHON=/path/to/python3.12."
    exit 1
fi
echo "[setup] Python: $PYTHON  ($(${PYTHON} --version 2>&1))"

# ── Helper: kill a port ───────────────────────────────────────────────────────
kill_port() {
    local port="$1"
    local pids
    pids=$(lsof -ti:"${port}" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        echo "[setup]   killing port ${port} (PIDs: ${pids})"
        kill -TERM $pids 2>/dev/null || true
        sleep 0.5
    fi
}

# ── Stop mode ─────────────────────────────────────────────────────────────────
echo "[setup] Stopping any existing processes on ports ${PROXY_PORT}, ${SOLVE_PORT}, ${FILTER_PORT}…"
for port in "$PROXY_PORT" "$SOLVE_PORT" "$FILTER_PORT"; do
    kill_port "$port"
done

if $STOP_ONLY; then
    echo "[setup] Done (--stop)."
    exit 0
fi

sleep 1

# ── Step 1: runtime deps dir ──────────────────────────────────────────────────
DEPS_DIR="${ROOT}/.deps"
mkdir -p "$DEPS_DIR"
PYPATH="${DEPS_DIR}:${HOME}/.local/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"

# Source local secrets if present (ANTHROPIC_API_KEY etc.)
if [[ -f "${ROOT}/.env.local" ]]; then
    set -a; . "${ROOT}/.env.local"; set +a
fi

# ── Step 2: launch solve app ──────────────────────────────────────────────────
echo "[setup] Starting solve app on 127.0.0.1:${SOLVE_PORT}…"
( while true; do
    PYTHONPATH="${PYPATH}" \
    "$PYTHON" -m uvicorn webapp.server:app \
        --host 127.0.0.1 \
        --port "${SOLVE_PORT}" \
        ${UVICORN_EXTRA} 2>&1 || true
    echo "[solve $(date '+%H:%M:%S')] restarting in 3s…"
    sleep 3
done ) >> "${LOG_DIR}/solve_${MODE}.log" 2>&1 &
SOLVE_PID=$!
echo "[setup]   solve PID ${SOLVE_PID}  →  log: logs/solve_${MODE}.log"

# ── Step 4: launch filter app ────────────────────────────────────────────────
echo "[setup] Starting filter app on 127.0.0.1:${FILTER_PORT}…"
( cd "${ROOT}/webapp_filter" && while true; do
    PYTHONPATH="${PYPATH}" \
    "$PYTHON" -m uvicorn server:app \
        --host 127.0.0.1 \
        --port "${FILTER_PORT}" \
        ${UVICORN_EXTRA} 2>&1 || true
    echo "[filter $(date '+%H:%M:%S')] restarting in 3s…"
    sleep 3
done ) >> "${LOG_DIR}/filter_${MODE}.log" 2>&1 &
FILTER_PID=$!
echo "[setup]   filter PID ${FILTER_PID}  →  log: logs/filter_${MODE}.log"

# Give backends a moment to bind
sleep 2

# ── Step 5: launch proxy ──────────────────────────────────────────────────────
echo "[setup] Starting proxy on 0.0.0.0:${PROXY_PORT}…"
( while true; do
    PYTHONPATH="${PYPATH}" \
    RMAC_SOLVE_ORIGIN="http://127.0.0.1:${SOLVE_PORT}" \
    RMAC_FILTER_ORIGIN="http://127.0.0.1:${FILTER_PORT}" \
    "$PYTHON" -m uvicorn proxy_server:app \
        --host 0.0.0.0 \
        --port "${PROXY_PORT}" \
        --reload \
        --reload-include "proxy_server.py" \
        --reload-delay 0.5 2>&1 || true
    echo "[proxy $(date '+%H:%M:%S')] restarting in 3s…"
    sleep 3
done ) >> "${LOG_DIR}/proxy_${MODE}.log" 2>&1 &
PROXY_PID=$!
echo "[setup]   proxy PID ${PROXY_PID}  →  log: logs/proxy_${MODE}.log"

sleep 2

# ── Step 6: open tunnel ───────────────────────────────────────────────────────
if [[ "$TUNNEL_CMD" == "serveo" ]]; then
    SUBDOMAIN="${RMA_DEV_SUBDOMAIN:-rma-dev}"
    SSH_KEY="${HOME}/.ssh/serveo_key"
    SSH_OPTS="-o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=no"
    if [[ ! -f "$SSH_KEY" ]]; then
        echo "[setup] WARNING: ${SSH_KEY} not found — generating a new key."
        ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -q
    fi
    echo "[setup] Opening serveo.net tunnel (subdomain: ${SUBDOMAIN})…"
    ( while true; do
        ssh -i "$SSH_KEY" $SSH_OPTS \
            -R "${SUBDOMAIN}:80:localhost:${PROXY_PORT}" \
            serveo.net 2>&1 || true
        echo "[tunnel $(date '+%H:%M:%S')] dropped, reconnecting in 5s…"
        sleep 5
    done ) >> "${LOG_DIR}/tunnel_${MODE}.log" 2>&1 &
    TUNNEL_PID=$!

elif [[ "$TUNNEL_CMD" == "ngrok" ]]; then
    NGROK="/projects/bhov/zzhao18/software/bin/ngrok"
    if [[ ! -x "$NGROK" ]]; then
        NGROK="$(command -v ngrok 2>/dev/null || true)"
    fi
    if [[ -z "$NGROK" ]]; then
        echo "[setup] WARNING: ngrok not found — skipping tunnel. Expose port ${PROXY_PORT} manually."
        TUNNEL_PID=""
    else
        DOMAIN="${NGROK_DOMAIN:?set NGROK_DOMAIN to your ngrok reserved domain (e.g. in .env.local)}"
        echo "[setup] Opening ngrok tunnel (domain: ${DOMAIN})…"
        ( while true; do
            "$NGROK" http --domain="${DOMAIN}" "${PROXY_PORT}" 2>&1 || true
            echo "[ngrok $(date '+%H:%M:%S')] dropped, reconnecting in 5s…"
            sleep 5
        done ) >> "${LOG_DIR}/tunnel_${MODE}.log" 2>&1 &
        TUNNEL_PID=$!
    fi
fi

echo "[setup]   tunnel PID ${TUNNEL_PID:-none}  →  log: logs/tunnel_${MODE}.log"

# ── Step 7: write PID file ────────────────────────────────────────────────────
PID_FILE="${ROOT}/logs/setup_${MODE}.pids"
{
    echo "SOLVE_PID=${SOLVE_PID}"
    echo "FILTER_PID=${FILTER_PID}"
    echo "PROXY_PID=${PROXY_PID}"
    echo "TUNNEL_PID=${TUNNEL_PID:-}"
    echo "MODE=${MODE}"
    echo "PROXY_PORT=${PROXY_PORT}"
} > "$PID_FILE"
echo "[setup]   PIDs written to ${PID_FILE}"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ResearchMathAgent — ${MODE^^} server started"
printf "║  Public URL:  %-48s║\n"  "${PUBLIC_URL}/rmac/solve/"
printf "║  Local:       %-48s║\n"  "http://localhost:${PROXY_PORT}/rmac/solve/"
echo "║                                                              ║"
echo "║  Logs:  tail -f logs/solve_${MODE}.log                         "
echo "║         tail -f logs/proxy_${MODE}.log                         "
echo "║         tail -f logs/tunnel_${MODE}.log                        "
echo "║                                                              ║"
echo "║  Stop:  bash setup_server.sh --stop                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Optional: wait and keep alive ─────────────────────────────────────────────
# If run interactively (not sourced), wait so Ctrl-C cleanly stops everything.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]] && [[ -t 0 ]]; then
    trap 'echo ""; echo "[setup] Ctrl-C — stopping all processes…"; kill ${SOLVE_PID} ${FILTER_PID} ${PROXY_PID} ${TUNNEL_PID:-} 2>/dev/null || true; exit 0' INT TERM
    echo "[setup] Running in foreground — press Ctrl-C to stop all services."
    wait "${SOLVE_PID}" "${FILTER_PID}" "${PROXY_PID}"
fi
