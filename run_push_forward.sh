#!/bin/bash
# Daily push-forward: discover proof gaps, resolve issues, run expert meetings.
# Triggered via the webapp API so it runs inside the server's already-configured
# Vertex AI context (ADC credentials, rate-limit pools, etc.).
#
# Cron entry (installed automatically — do not edit by hand):
#   0 9 * * * /projects/bhov/zzhao18/code/ResearchMathAgent-web/run_push_forward.sh

set -euo pipefail

SOLVE_API="http://127.0.0.1:8011"
LOG_FILE="/tmp/rma_push_forward.log"
STAMP="[$(date '+%Y-%m-%d %H:%M:%S')]"

log() { echo "${STAMP} $*" >> "$LOG_FILE"; }

log "=== push-forward starting ==="

# Verify the webapp is up before doing anything
if ! curl -sf --max-time 5 "${SOLVE_API}/api/capabilities" > /dev/null 2>&1; then
    log "ERROR: solve app not reachable at ${SOLVE_API} — is it running?"
    exit 1
fi

# Fire the push-forward. The API already gates on 'already ran today' so
# running this from cron daily is safe — it won't double-run.
RESPONSE=$(curl -sf --max-time 10 -X POST "${SOLVE_API}/api/push-forward" \
    -H "content-type: application/json" \
    -d '{}' 2>&1) || {
    log "ERROR: POST /api/push-forward failed"
    exit 1
}

log "Response: ${RESPONSE}"

# Surface the outcome
if echo "$RESPONSE" | grep -q '"started": true'; then
    JOB_ID=$(echo "$RESPONSE" | grep -oP '"job_id":\s*"\K[^"]+' || echo "unknown")
    log "Push-forward started (job ${JOB_ID}). Runs in background — check /api/push-forward/status."
elif echo "$RESPONSE" | grep -q '"started": false'; then
    REASON=$(echo "$RESPONSE" | grep -oP '"reason":\s*"\K[^"]+' || echo "unknown reason")
    log "Skipped: ${REASON}"
else
    log "Unexpected response, check manually."
fi

log "=== done ==="
