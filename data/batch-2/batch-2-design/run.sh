#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
# First Proof — run a single submitter's code
# Usage: ./run.sh <submitter-id>
# ─────────────────────────────────────────────

# ── Configuration ──────────────────────────────────────────
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$BASE_DIR/run-config.env"

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: Config file not found at $CONFIG_FILE"
    echo "Copy run-config.env.example to run-config.env and fill in your values."
    exit 1
fi

# shellcheck source=run-config.env.example
source "$CONFIG_FILE"

PROFILE="${AWS_PROFILE:?Set AWS_PROFILE in run-config.env}"
KEY_NAME="${KEY_NAME:?Set KEY_NAME in run-config.env}"
KEY_FILE="${KEY_FILE:?Set KEY_FILE in run-config.env}"
SECURITY_GROUP="${SECURITY_GROUP:?Set SECURITY_GROUP in run-config.env}"
DEFAULT_AMI="${DEFAULT_AMI:?Set DEFAULT_AMI in run-config.env}"

ALLOWED_INSTANCES_FILE="$BASE_DIR/allowed-instances.txt"
if [[ ! -f "$ALLOWED_INSTANCES_FILE" ]]; then
    echo "ERROR: Allowed instances file not found at $ALLOWED_INSTANCES_FILE"
    exit 1
fi
mapfile -t ALLOWED_INSTANCES < "$ALLOWED_INSTANCES_FILE"

# ── Input validation ───────────────────────
if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <submitter-id>"
    exit 1
fi

SUBMITTER_ID="$1"
REPO_DIR="$BASE_DIR/submissions/$SUBMITTER_ID"
RESULTS_DIR="$BASE_DIR/results/$SUBMITTER_ID"
INPUT_FILE="$BASE_DIR/input/input.json"
SECRETS_FILE="$BASE_DIR/secrets/${SUBMITTER_ID}.env"
HARDWARE_FILE="$REPO_DIR/hardware.json"

# ── Preflight checks ──────────────────────
echo "==> Preflight checks"

if [[ ! -d "$REPO_DIR" ]]; then
    echo "ERROR: Repo not found at $REPO_DIR"
    echo "Clone it first: git clone <url> $REPO_DIR"
    exit 1
fi

if [[ ! -f "$HARDWARE_FILE" ]]; then
    echo "ERROR: hardware.json not found at $HARDWARE_FILE"
    exit 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "ERROR: Input file not found at $INPUT_FILE"
    exit 1
fi

if [[ ! -f "$KEY_FILE" ]]; then
    echo "ERROR: SSH key not found at $KEY_FILE"
    exit 1
fi

# ── Parse hardware.json ───────────────────
INSTANCE_TYPE=$(jq -r '.instance_type' "$HARDWARE_FILE")
AMI=$(jq -r '.ami // empty' "$HARDWARE_FILE")
AMI="${AMI:-$DEFAULT_AMI}"
STORAGE_GB=$(jq -r '.storage_gb // 100' "$HARDWARE_FILE")
TIMEOUT_MINUTES=1440

if ! [[ "$STORAGE_GB" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: hardware.json storage_gb must be a positive integer (got '$STORAGE_GB')"
    exit 1
fi

echo "    Submitter:     $SUBMITTER_ID"
echo "    Instance type:  $INSTANCE_TYPE"
echo "    Storage:        ${STORAGE_GB} GB (gp3)"
echo "    Timeout:        $TIMEOUT_MINUTES minutes (24 hours)"
echo "    AMI:            $AMI"

# Validate instance type against allowlist
ALLOWED=false
for allowed in "${ALLOWED_INSTANCES[@]}"; do
    if [[ "$INSTANCE_TYPE" == "$allowed" ]]; then
        ALLOWED=true
        break
    fi
done

if [[ "$ALLOWED" != "true" ]]; then
    echo "ERROR: Instance type '$INSTANCE_TYPE' is not on the approved list."
    echo "Allowed types: ${ALLOWED_INSTANCES[*]}"
    exit 1
fi

# ── Check for secrets ─────────────────────
ENV_VARS=$(jq -r '.env_vars // empty' "$HARDWARE_FILE")
DOCKER_ENV_FILE_FLAG=""

if [[ -n "$ENV_VARS" ]]; then
    if [[ ! -f "$SECRETS_FILE" ]]; then
        echo "ERROR: hardware.json declares env_vars but no secrets file at $SECRETS_FILE"
        exit 1
    fi
    echo "    Secrets:        $SECRETS_FILE"
    DOCKER_ENV_FILE_FLAG="--env-file /home/ubuntu/secrets.env"
fi

# ── Prepare results directory ─────────────
mkdir -p "$RESULTS_DIR"
TIMESTAMP_UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ── Launch instance ───────────────────────
echo ""
echo "==> Launching EC2 instance"

SG_ID=$(aws ec2 describe-security-groups \
    --group-names "$SECURITY_GROUP" \
    --query 'SecurityGroups[0].GroupId' \
    --output text \
    --profile "$PROFILE")

INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":${STORAGE_GB},\"VolumeType\":\"gp3\"}}]" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=firstproof-${SUBMITTER_ID}},{Key=Project,Value=FirstProof}]" \
    --query 'Instances[0].InstanceId' \
    --output text \
    --profile "$PROFILE")

echo "    Instance ID:    $INSTANCE_ID"

# ── Cleanup on exit (always terminate) ────
cleanup() {
    echo ""
    echo "==> Terminating instance $INSTANCE_ID"
    aws ec2 terminate-instances \
        --instance-ids "$INSTANCE_ID" \
        --profile "$PROFILE" > /dev/null 2>&1 || true
    echo "    Instance terminated."
}
trap cleanup EXIT

# ── Wait for instance to be running ───────
echo "==> Waiting for instance to be running..."
aws ec2 wait instance-running \
    --instance-ids "$INSTANCE_ID" \
    --profile "$PROFILE"

PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text \
    --profile "$PROFILE")

echo "    Public IP:      $PUBLIC_IP"

# ── Wait for SSH to be ready ──────────────
echo "==> Waiting for SSH..."
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o LogLevel=ERROR"
for i in $(seq 1 30); do
    if ssh $SSH_OPTS -i "$KEY_FILE" ubuntu@"$PUBLIC_IP" "echo ok" > /dev/null 2>&1; then
        echo "    SSH ready."
        break
    fi
    if [[ $i -eq 30 ]]; then
        echo "ERROR: SSH not available after 30 attempts."
        exit 1
    fi
    sleep 10
done

# Helper function for SSH/SCP
remote() {
    ssh $SSH_OPTS -i "$KEY_FILE" ubuntu@"$PUBLIC_IP" "$@"
}

# ── Upload input file ─────────────────────
echo "==> Uploading input file"
scp $SSH_OPTS -i "$KEY_FILE" "$INPUT_FILE" ubuntu@"$PUBLIC_IP":/home/ubuntu/input.json

# ── Upload secrets if needed ──────────────
if [[ -n "$ENV_VARS" ]]; then
    echo "==> Uploading secrets"
    scp $SSH_OPTS -i "$KEY_FILE" "$SECRETS_FILE" ubuntu@"$PUBLIC_IP":/home/ubuntu/secrets.env
fi

# ── Upload submitter code ─────────────────
echo "==> Uploading submitter code"
# Tar the repo, upload, and extract (faster than git clone on the instance)
tar -czf /tmp/firstproof-code.tar.gz -C "$REPO_DIR" .
scp $SSH_OPTS -i "$KEY_FILE" /tmp/firstproof-code.tar.gz ubuntu@"$PUBLIC_IP":/home/ubuntu/code.tar.gz
remote "mkdir -p /home/ubuntu/code && tar -xzf /home/ubuntu/code.tar.gz -C /home/ubuntu/code"
rm -f /tmp/firstproof-code.tar.gz

# ── Install Docker on instance ────────────
echo "==> Installing Docker"
remote "sudo apt-get update -qq && sudo apt-get install -y -qq docker.io > /dev/null 2>&1"
remote "sudo usermod -aG docker ubuntu"

# ── Record git commit ─────────────────────
GIT_COMMIT=$(cd "$REPO_DIR" && git rev-parse HEAD 2>/dev/null || echo "unknown")

# ── Build and run container ───────────────
echo "==> Building Docker image"
remote "cd /home/ubuntu/code && sudo docker build -t submitter-run ."

echo "==> Running container (timeout: ${TIMEOUT_MINUTES}m)"
TIMEOUT_SECONDS=$((TIMEOUT_MINUTES * 60))
RUN_START=$(date +%s)

# Run the container:
# - Mount input read-only at /data/input/input.json
# - Mount output directory at /data/output/
# - Inject secrets if present
# - Enforce timeout
EXIT_CODE=0
remote "mkdir -p /home/ubuntu/output && \
    sudo timeout ${TIMEOUT_SECONDS} docker run \
    --rm \
    -v /home/ubuntu/input.json:/data/input/input.json:ro \
    -v /home/ubuntu/output:/data/output \
    $DOCKER_ENV_FILE_FLAG \
    submitter-run" || EXIT_CODE=$?

RUN_END=$(date +%s)
RUNTIME_SECONDS=$((RUN_END - RUN_START))

echo "    Exit code:      $EXIT_CODE"
echo "    Runtime:        ${RUNTIME_SECONDS}s"

# Exit code 124 = timeout killed the process
if [[ $EXIT_CODE -eq 124 ]]; then
    echo "    WARNING: Container was killed by timeout."
fi

# ── Check for output ──────────────────────
echo "==> Checking for output"
OUTPUT_COUNT=$(remote "ls -1 /home/ubuntu/output/ 2>/dev/null | wc -l" || echo "0")

if [[ "$OUTPUT_COUNT" -eq 0 ]]; then
    echo "    WARNING: No output files found. Run flagged as failed."
    FAILED=true
else
    echo "    Output files:   $OUTPUT_COUNT"
    FAILED=false
fi

# ── Retrieve results ──────────────────────
if [[ "$FAILED" != "true" ]]; then
    echo "==> Retrieving results"
    scp $SSH_OPTS -i "$KEY_FILE" -r ubuntu@"$PUBLIC_IP":/home/ubuntu/output/* "$RESULTS_DIR/"
fi

# ── Retrieve container logs ───────────────
echo "==> Retrieving logs"
remote "sudo docker logs \$(sudo docker ps -aq --latest) > /home/ubuntu/stdout.log 2> /home/ubuntu/stderr.log" || true
scp $SSH_OPTS -i "$KEY_FILE" ubuntu@"$PUBLIC_IP":/home/ubuntu/stdout.log "$RESULTS_DIR/stdout.log" 2>/dev/null || true
scp $SSH_OPTS -i "$KEY_FILE" ubuntu@"$PUBLIC_IP":/home/ubuntu/stderr.log "$RESULTS_DIR/stderr.log" 2>/dev/null || true

# ── Write run metadata ────────────────────
echo "==> Writing metadata"
cat > "$RESULTS_DIR/run-metadata.json" <<EOF
{
  "submitter_id": "$SUBMITTER_ID",
  "timestamp_utc": "$TIMESTAMP_UTC",
  "git_commit": "$GIT_COMMIT",
  "instance_type": "$INSTANCE_TYPE",
  "instance_id": "$INSTANCE_ID",
  "storage_gb": $STORAGE_GB,
  "exit_code": $EXIT_CODE,
  "runtime_seconds": $RUNTIME_SECONDS,
  "timeout_minutes": $TIMEOUT_MINUTES,
  "output_files": $OUTPUT_COUNT,
  "failed": $FAILED
}
EOF

echo ""
echo "==> Done."
echo "    Results:  $RESULTS_DIR/"
echo "    Metadata: $RESULTS_DIR/run-metadata.json"

if [[ "$FAILED" == "true" ]]; then
    echo "    STATUS: FAILED (no output files)"
    exit 1
else
    echo "    STATUS: SUCCESS"
fi

# Instance is terminated by the cleanup trap on exit
