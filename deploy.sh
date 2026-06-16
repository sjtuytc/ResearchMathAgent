#!/usr/bin/env bash
# Deploy current working-tree state to production.
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

# ── 2. Restart the production server ─────────────────────────────────────────
echo "[deploy] Restarting production server (port ${PROD_PORT})..."
PROD_PID=$(lsof -ti:${PROD_PORT} 2>/dev/null || true)
if [[ -n "$PROD_PID" ]]; then
    # SIGTERM → watchdog in start_server.sh catches the exit and relaunches with new code
    kill -TERM $PROD_PID 2>/dev/null || true
    sleep 2
    NEW_PID=$(lsof -ti:${PROD_PORT} 2>/dev/null || true)
    if [[ -n "$NEW_PID" ]]; then
        echo "[deploy] Production server restarted (PID ${NEW_PID}) ✓"
    else
        echo "[deploy] WARNING: prod server not yet back on port ${PROD_PORT}. Watchdog should restart it within 3s."
    fi
else
    echo "[deploy] WARNING: no process found on port ${PROD_PORT}. Start it with: bash start_server.sh &"
fi

echo ""
echo "=== Deploy complete ==="
echo "  Production: https://zipfile-legume-gaining.ngrok-free.dev"
echo "  Dev:        https://rma-dev.serveo.net  (if dev tunnel is running)"
echo ""
