#!/usr/bin/env bash
# Production server watchdog.
# Starts proxy + solve + filter as independent processes, each auto-restarting.
#
# Use deploy.sh to apply code changes to production.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"

# Kill anything on our ports
for PORT in 8000 8010 8013; do
    PIDS=$(lsof -ti:${PORT} 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
        echo "  Clearing port ${PORT} (PIDs: $PIDS)…"
        kill -TERM $PIDS 2>/dev/null || true
        sleep 0.5
    fi
done

cleanup() {
    echo ""
    echo "[prod] Stopping all prod processes…"
    kill $PROXY_PID $SOLVE_PID $FILTER_PID 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

echo "[prod] Starting PROD solve app (port 8010)…"
bash "${ROOT}/start_solve_server.sh" > "${LOG_DIR}/solve_prod.log" 2>&1 &
SOLVE_PID=$!

echo "[prod] Starting PROD filter app (port 8013)…"
bash "${ROOT}/start_filter_server.sh" > "${LOG_DIR}/filter_prod.log" 2>&1 &
FILTER_PID=$!

sleep 2

echo "[prod] Starting PROD proxy (port 8000)…"
bash "${ROOT}/start_proxy_server.sh" > "${LOG_DIR}/proxy_prod.log" 2>&1 &
PROXY_PID=$!

echo "[prod] All production processes started."
echo "  Logs: tail -f logs/proxy_prod.log logs/solve_prod.log logs/filter_prod.log"
echo "  Run deploy.sh to apply code changes to production."

wait $PROXY_PID $SOLVE_PID $FILTER_PID
