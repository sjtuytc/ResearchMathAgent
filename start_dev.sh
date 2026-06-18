#!/usr/bin/env bash
# DEV convenience script — starts the full dev stack in foreground.
#
# Launches three background processes:
#   - Proxy      on port 8001 (public, tunnel connects here)
#   - Solve app  on port 8011 (internal → /rmac/solve/)
#   - Filter app on port 8012 (internal → /rmac/filter/)
#
# Press Ctrl-C to stop all three.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"

# Kill anything on our ports
for PORT in 8001 8011 8012; do
    PIDS=$(lsof -ti:${PORT} 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
        echo "  Clearing port ${PORT} (PIDs: $PIDS)…"
        kill -TERM $PIDS 2>/dev/null || true
        sleep 0.5
    fi
done

cleanup() {
    echo ""
    echo "[dev] Stopping all dev processes…"
    kill $PROXY_PID $SOLVE_PID $FILTER_PID 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

echo "[dev] Starting solve app (port 8011)…"
bash "${ROOT}/start_solve_dev.sh" > "${LOG_DIR}/solve_dev.log" 2>&1 &
SOLVE_PID=$!

echo "[dev] Starting filter app (port 8012)…"
bash "${ROOT}/start_filter_dev.sh" > "${LOG_DIR}/filter_dev.log" 2>&1 &
FILTER_PID=$!

sleep 2

echo "[dev] Starting proxy (port 8001)…"
bash "${ROOT}/start_proxy_dev.sh" > "${LOG_DIR}/proxy_dev.log" 2>&1 &
PROXY_PID=$!

sleep 2

echo ""
echo "[dev] Stack ready:"
echo "  http://localhost:8001/rmac/solve/   ← solve"
echo "  http://localhost:8001/rmac/filter/  ← filter"
echo "  http://localhost:8001/              ← redirects to solve"
echo ""
echo "  Logs: tail -f logs/proxy_dev.log logs/solve_dev.log logs/filter_dev.log"
echo "  Press Ctrl-C to stop."

wait $PROXY_PID $SOLVE_PID $FILTER_PID
