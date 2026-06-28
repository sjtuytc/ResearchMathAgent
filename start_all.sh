#!/usr/bin/env bash
# Start the full rmac stack: proxy + solve app + filter app + tunnels.
#
# Public port layout (single tunnel entry point):
#   port 8001 → proxy (dev)   →  /rmac/solve/ → 8011 (solve)
#                              →  /rmac/filter/ → 8012 (filter)
#   port 8000 → proxy (prod)  →  /rmac/solve/ → 8010 (solve)
#                              →  /rmac/filter/ → 8013 (filter)
#
# Isolation: solve and filter run as separate processes.
# If one crashes, the proxy returns 502 for that path only.
#
# Usage:
#   bash start_all.sh          # start all processes in background
#   bash start_all.sh --status # show what's currently running
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"

# Pull NGROK_DOMAIN (and other secrets) from .env.local so the public domain is
# never hardcoded in tracked files.
[ -f "${ROOT}/.env.local" ] && { set -a; . "${ROOT}/.env.local"; set +a; }
PUBLIC_DOMAIN="${NGROK_DOMAIN:-<your-ngrok-domain>}"

NGROK=/projects/bhov/zzhao18/software/bin/ngrok

if [[ "${1:-}" == "--status" ]]; then
    echo "=== Process status ==="
    echo -n "  Proxy   DEV  (port 8001):  "; lsof -ti:8001 &>/dev/null && echo "RUNNING (PID $(lsof -ti:8001))" || echo "stopped"
    echo -n "  Proxy   PROD (port 8000):  "; lsof -ti:8000 &>/dev/null && echo "RUNNING (PID $(lsof -ti:8000))" || echo "stopped"
    echo -n "  Solve   DEV  (port 8011):  "; lsof -ti:8011 &>/dev/null && echo "RUNNING (PID $(lsof -ti:8011))" || echo "stopped"
    echo -n "  Solve   PROD (port 8010):  "; lsof -ti:8010 &>/dev/null && echo "RUNNING (PID $(lsof -ti:8010))" || echo "stopped"
    echo -n "  Filter  DEV  (port 8012):  "; lsof -ti:8012 &>/dev/null && echo "RUNNING (PID $(lsof -ti:8012))" || echo "stopped"
    echo -n "  Filter  PROD (port 8013):  "; lsof -ti:8013 &>/dev/null && echo "RUNNING (PID $(lsof -ti:8013))" || echo "stopped"
    echo -n "  ngrok   (prod tunnel):     "; pgrep -f "ngrok http" &>/dev/null && echo "RUNNING" || echo "stopped"
    echo -n "  serveo  (dev  tunnel):     "; pgrep -f "serveo.net" &>/dev/null && echo "RUNNING" || echo "stopped"
    echo ""
    echo "  Prod solve:  https://${PUBLIC_DOMAIN}/rmac/solve/"
    echo "  Prod filter: https://${PUBLIC_DOMAIN}/rmac/filter/"
    DEV_URL=$(grep -oP 'https://[^\s\x1b]+serveo[^\s\x1b]+' "${LOG_DIR}/serveo.log" 2>/dev/null | tail -1 || echo "(see logs/serveo.log)")
    echo "  Dev  solve:  ${DEV_URL}/rmac/solve/"
    echo "  Dev  filter: ${DEV_URL}/rmac/filter/"
    exit 0
fi

echo "=== Starting ResearchMathAgent stack ==="

# Clear old processes on all ports
for PORT in 8000 8001 8010 8011 8012 8013; do
    PIDS=$(lsof -ti:${PORT} 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
        echo "  Clearing port ${PORT} (PIDs: ${PIDS})…"
        kill -TERM $PIDS 2>/dev/null || true
        sleep 0.5
    fi
done

pkill -f "ngrok http" 2>/dev/null || true
pkill -f "serveo.net" 2>/dev/null || true
sleep 1

# 1. Prod: solve app (internal)
echo "  [1/7] Starting PROD solve app (port 8010)…"
nohup bash "${ROOT}/start_solve_server.sh" > "${LOG_DIR}/solve_prod.log" 2>&1 &
echo "        → logs/solve_prod.log"
sleep 1

# 2. Prod: filter app (internal)
echo "  [2/7] Starting PROD filter app (port 8013)…"
nohup bash "${ROOT}/start_filter_server.sh" > "${LOG_DIR}/filter_prod.log" 2>&1 &
echo "        → logs/filter_prod.log"
sleep 1

# 3. Prod: proxy (public port 8000)
echo "  [3/7] Starting PROD proxy (port 8000)…"
nohup bash "${ROOT}/start_proxy_server.sh" > "${LOG_DIR}/proxy_prod.log" 2>&1 &
echo "        → logs/proxy_prod.log"
sleep 1

# 4. ngrok tunnel for prod (port 8000)
echo "  [4/7] Starting ngrok tunnel (prod)…"
nohup bash "${ROOT}/start_ngrok.sh" > "${LOG_DIR}/ngrok.log" 2>&1 &
echo "        → logs/ngrok.log"

# 5. Dev: solve app (internal)
echo "  [5/7] Starting DEV solve app (port 8011)…"
nohup bash "${ROOT}/start_solve_dev.sh" > "${LOG_DIR}/solve_dev.log" 2>&1 &
echo "        → logs/solve_dev.log"
sleep 1

# 6. Dev: filter app (internal)
echo "  [6/7] Starting DEV filter app (port 8012)…"
nohup bash "${ROOT}/start_filter_dev.sh" > "${LOG_DIR}/filter_dev.log" 2>&1 &
echo "        → logs/filter_dev.log"
sleep 1

# 7. Dev: proxy (public port 8001) + serveo tunnel
echo "  [7/7] Starting DEV proxy (port 8001) + serveo tunnel…"
nohup bash "${ROOT}/start_proxy_dev.sh" > "${LOG_DIR}/proxy_dev.log" 2>&1 &
echo "        → logs/proxy_dev.log"
nohup bash "${ROOT}/start_dev_tunnel.sh" > "${LOG_DIR}/serveo.log" 2>&1 &
echo "        → logs/serveo.log"

sleep 5

echo ""
echo "=== Stack is up ==="
echo "  Prod solve:  https://${PUBLIC_DOMAIN}/rmac/solve/"
echo "  Prod filter: https://${PUBLIC_DOMAIN}/rmac/filter/"
sleep 3
DEV_URL=$(grep -oP 'https://[^\s\x1b]+serveo[^\s\x1b]+' "${LOG_DIR}/serveo.log" 2>/dev/null | tail -1 || echo "(starting… check logs/serveo.log)")
echo "  Dev  solve:  ${DEV_URL}/rmac/solve/"
echo "  Dev  filter: ${DEV_URL}/rmac/filter/"
echo ""
echo "  To deploy dev → prod:  bash deploy.sh"
echo "  To check status:       bash start_all.sh --status"
echo "  Tail all logs:         tail -f logs/proxy_dev.log logs/solve_dev.log logs/filter_dev.log"
