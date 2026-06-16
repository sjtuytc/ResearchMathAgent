#!/usr/bin/env bash
# Start everything: prod server + ngrok + dev server + serveo dev tunnel.
# Run this once after login; everything stays alive and auto-restarts.
#
# Usage:
#   bash start_all.sh          # start all four processes in background
#   bash start_all.sh --status # show what's currently running
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"

NGROK=/projects/bhov/zzhao18/software/bin/ngrok

if [[ "${1:-}" == "--status" ]]; then
    echo "=== Process status ==="
    echo -n "  Prod server (port 8000):  "; lsof -ti:8000 &>/dev/null && echo "RUNNING (PID $(lsof -ti:8000))" || echo "stopped"
    echo -n "  Dev  server (port 8001):  "; lsof -ti:8001 &>/dev/null && echo "RUNNING (PID $(lsof -ti:8001))" || echo "stopped"
    echo -n "  ngrok (prod tunnel):      "; pgrep -f "ngrok http" &>/dev/null && echo "RUNNING" || echo "stopped"
    echo -n "  serveo (dev tunnel):      "; pgrep -f "serveo.net" &>/dev/null && echo "RUNNING" || echo "stopped"
    echo ""
    echo "  Prod URL: https://zipfile-legume-gaining.ngrok-free.dev"
    DEV_URL=$(grep -oP 'https://[^\s\x1b]+serveo[^\s\x1b]+' "${LOG_DIR}/serveo.log" 2>/dev/null | tail -1 || echo "(see logs/serveo.log)")
    echo "  Dev  URL: ${DEV_URL}"
    exit 0
fi

echo "=== Starting ResearchMathAgent stack ==="

# Kill anything already on these ports to avoid conflicts
for PORT in 8000 8001; do
    PIDS=$(lsof -ti:${PORT} 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
        echo "  Clearing port ${PORT} (PIDs: ${PIDS})..."
        kill -TERM $PIDS 2>/dev/null || true
        sleep 1
    fi
done

# Kill stale tunnel processes
pkill -f "ngrok http" 2>/dev/null || true
pkill -f "serveo.net" 2>/dev/null || true
sleep 1

# 1. Production server (no --reload)
echo "  [1/4] Starting production server (port 8000)..."
nohup bash "${ROOT}/start_server.sh" > "${LOG_DIR}/prod.log" 2>&1 &
PROD_PID=$!
echo "        PID ${PROD_PID} → logs/prod.log"

sleep 2

# 2. ngrok tunnel for prod
echo "  [2/4] Starting ngrok tunnel..."
nohup bash "${ROOT}/start_ngrok.sh" > "${LOG_DIR}/ngrok.log" 2>&1 &
NGROK_PID=$!
echo "        PID ${NGROK_PID} → logs/ngrok.log"

# 3. Dev server (--reload)
echo "  [3/4] Starting dev server (port 8001)..."
nohup bash "${ROOT}/start_dev.sh" > "${LOG_DIR}/dev.log" 2>&1 &
DEV_PID=$!
echo "        PID ${DEV_PID} → logs/dev.log"

# 4. serveo.net tunnel for dev
echo "  [4/4] Starting serveo dev tunnel..."
nohup bash "${ROOT}/start_dev_tunnel.sh" > "${LOG_DIR}/serveo.log" 2>&1 &
SERVEO_PID=$!
echo "        PID ${SERVEO_PID} → logs/serveo.log"

sleep 4

echo ""
echo "=== Stack is up ==="
echo "  Prod: https://zipfile-legume-gaining.ngrok-free.dev  (stable, deploy.sh to update)"
sleep 3
DEV_URL=$(grep -oP 'https://[^\s\x1b]+serveo[^\s\x1b]+' "${LOG_DIR}/serveo.log" 2>/dev/null | tail -1 || echo "(starting… check logs/serveo.log)")
echo "  Dev:  ${DEV_URL}  (live-reload, shows changes immediately)"
echo ""
echo "  To deploy dev → prod:  bash deploy.sh"
echo "  To check status:       bash start_all.sh --status"
echo "  Tail logs:             tail -f logs/prod.log logs/dev.log logs/ngrok.log logs/serveo.log"
