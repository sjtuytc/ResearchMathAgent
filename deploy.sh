#!/usr/bin/env bash
# Deploy current working-tree state to production.
#
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  ⚠️  REQUIRES EXPLICIT USER PERMISSION BEFORE RUNNING                  ║
# ║                                                                          ║
# ║  Claude (AI assistant) must NOT run this script autonomously.           ║
# ║  Always test changes on the dev server (port 8001) first, then ask      ║
# ║  the user: "Ready to deploy to production?" and wait for approval.      ║
# ║                                                                          ║
# ║  Deploying broken code to production breaks the live public website.    ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# What this does:
#   1. Optionally commit + push to GitHub (if there are uncommitted changes)
#   2. Gracefully restart the production server (port 8000) so it picks up new code
#   3. Print the live prod URL
#
# Usage:
#   bash deploy.sh                  # deploy with auto-generated commit message
#   bash deploy.sh "my message"     # deploy with a specific commit message
#   bash deploy.sh --no-commit      # just restart prod, skip git

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
[ -f "${ROOT}/.env.local" ] && { set -a; . "${ROOT}/.env.local"; set +a; }
PUBLIC_DOMAIN="${NGROK_DOMAIN:-<your-ngrok-domain>}"
PROD_PORT="${RMA_PORT:-8000}"
COMMIT_MSG="${1:-}"
NO_COMMIT=false

if [[ "${COMMIT_MSG}" == "--no-commit" ]]; then
    NO_COMMIT=true
    COMMIT_MSG=""
fi

cd "$ROOT"

echo "=== ResearchMathAgent deploy ==="

# ── 1. Git commit + push ──────────────────────────────────────────────────────
if ! $NO_COMMIT; then
    CHANGED=$(git status --porcelain 2>/dev/null | wc -l)
    if [[ "$CHANGED" -gt 0 ]]; then
        if [[ -z "$COMMIT_MSG" ]]; then
            COMMIT_MSG="deploy: $(date '+%Y-%m-%d %H:%M') — auto-commit from deploy.sh"
        fi
        echo "[deploy] Committing $CHANGED changed file(s)..."
        git add -A
        git commit -m "$COMMIT_MSG

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        echo "[deploy] Pushing to origin/main..."
        git push origin main
        echo "[deploy] Pushed ✓"
    else
        echo "[deploy] Nothing to commit — code is already clean."
        git push origin main 2>/dev/null || true
    fi
fi

# ── 2. Restart all production processes ──────────────────────────────────────
# New layout: proxy (8000) + solve (8010) + filter (8013)
echo "[deploy] Restarting production processes…"
for PORT in 8000 8010 8013; do
    PIDS=$(lsof -ti:${PORT} 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
        kill -TERM $PIDS 2>/dev/null || true
        echo "[deploy]   Killed port ${PORT} (PIDs: ${PIDS})"
    fi
done
sleep 3

# Watchdog loops in start_server.sh will restart each process automatically.
# If nothing is running, give guidance.
PROXY_PID=$(lsof -ti:${PROD_PORT} 2>/dev/null || true)
if [[ -n "$PROXY_PID" ]]; then
    echo "[deploy] Proxy back on port ${PROD_PORT} (PID ${PROXY_PID}) ✓"
else
    echo "[deploy] WARNING: proxy not yet on port ${PROD_PORT}. Watchdog should restart within 3s."
    echo "[deploy] If nothing starts: run  bash start_server.sh &"
fi

echo ""
echo "=== Deploy complete ==="
echo "  Production solve:  https://${PUBLIC_DOMAIN}/rmac/solve/"
echo "  Production filter: https://${PUBLIC_DOMAIN}/rmac/filter/"
echo "  Dev:               https://rma-dev.serveo.net/rmac/solve/  (if dev tunnel is running)"
echo ""
