#!/usr/bin/env bash
# Run the full integration test suite end-to-end.
#
# What this script does (in order):
#   1. Load env vars from .env.local
#   2. Start DynamoDB Local via docker compose (if not already running)
#   3. Wait for DynamoDB Local to be healthy
#   4. Create DynamoDB tables (idempotent — safe to run on existing tables)
#   5. Start the FastAPI dev server in the background
#   6. Wait for the server to be healthy
#   7. Run pytest tests/test_integration.py
#   8. Kill the dev server on exit (success or failure)
#
# Usage:
#   ./scripts/integration_test.sh            # run all integration tests
#   ./scripts/integration_test.sh -k blog    # pass extra args to pytest

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
ENV_FILE="$ROOT/.env.local"

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[integration]${NC} $*"; }
warning() { echo -e "${YELLOW}[integration]${NC} $*"; }
error()   { echo -e "${RED}[integration]${NC} $*" >&2; }

# ── 1. Load .env.local ────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  error ".env.local not found at $ENV_FILE"
  error "Create it first — see CLAUDE.md § Local Testing › Step 2"
  exit 1
fi

info "Loading $ENV_FILE"
set -o allexport
# shellcheck source=/dev/null
source "$ENV_FILE"
set +o allexport

# ── 2. Start DynamoDB Local ───────────────────────────────────────────────────
info "Starting DynamoDB Local via docker compose..."
docker compose -f "$ROOT/docker-compose.yml" up -d

# ── 3. Wait for DynamoDB Local ────────────────────────────────────────────────
info "Waiting for DynamoDB Local on $DYNAMODB_ENDPOINT ..."
RETRIES=20
until AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy \
      aws dynamodb list-tables \
        --endpoint-url "$DYNAMODB_ENDPOINT" \
        --region "${AWS_REGION:-us-west-2}" \
        --output text > /dev/null 2>&1; do
  RETRIES=$((RETRIES - 1))
  if [[ $RETRIES -le 0 ]]; then
    error "DynamoDB Local did not become ready in time."
    exit 1
  fi
  sleep 1
done
info "DynamoDB Local is ready."

# ── 4. Create tables (idempotent) ─────────────────────────────────────────────
DYNAMO_OPTS=(
  --endpoint-url "$DYNAMODB_ENDPOINT"
  --region "${AWS_REGION:-us-west-2}"
)
DYNAMO_ENV=(env AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy)

info "Creating blog table (if not exists)..."
"${DYNAMO_ENV[@]}" aws dynamodb create-table \
  "${DYNAMO_OPTS[@]}" \
  --table-name "${DYNAMODB_BLOG_TABLE:-blog}" \
  --attribute-definitions \
      AttributeName=PK,AttributeType=S \
      AttributeName=SK,AttributeType=S \
      AttributeName=date,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[
    {"IndexName":"date-index",
     "KeySchema":[{"AttributeName":"SK","KeyType":"HASH"},{"AttributeName":"date","KeyType":"RANGE"}],
     "Projection":{"ProjectionType":"ALL"}}
  ]' > /dev/null 2>&1 || warning "blog table already exists — skipping."

info "Creating playbook table (if not exists)..."
"${DYNAMO_ENV[@]}" aws dynamodb create-table \
  "${DYNAMO_OPTS[@]}" \
  --table-name "${DYNAMODB_PLAYBOOK_TABLE:-playbook}" \
  --attribute-definitions \
      AttributeName=PK,AttributeType=S \
      AttributeName=SK,AttributeType=S \
      AttributeName=status,AttributeType=S \
      AttributeName=nextReview,AttributeType=S \
      AttributeName=collection,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[
    {"IndexName":"status-review-index",
     "KeySchema":[{"AttributeName":"status","KeyType":"HASH"},{"AttributeName":"nextReview","KeyType":"RANGE"}],
     "Projection":{"ProjectionType":"ALL"}},
    {"IndexName":"playbook-collection-gsi",
     "KeySchema":[{"AttributeName":"collection","KeyType":"HASH"},{"AttributeName":"PK","KeyType":"RANGE"}],
     "Projection":{"ProjectionType":"ALL"}}
  ]' > /dev/null 2>&1 || warning "playbook table already exists — skipping."

# ── 5. Start the dev server ───────────────────────────────────────────────────
SERVER_LOG="$(mktemp /tmp/uvicorn.XXXXXX.log)"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    info "Stopping dev server (PID $SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

info "Starting FastAPI dev server..."
PYTHONPATH="$ROOT/src" uv run --directory "$ROOT" \
  uvicorn admin.handler:app --port 8001 > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

# ── 6. Wait for server health ─────────────────────────────────────────────────
info "Waiting for server on http://localhost:8001 ..."
RETRIES=20
until curl -sf http://localhost:8001/health > /dev/null 2>&1; do
  RETRIES=$((RETRIES - 1))
  if [[ $RETRIES -le 0 ]]; then
    error "Server did not become healthy. Logs:"
    cat "$SERVER_LOG"
    exit 1
  fi
  # Check server didn't crash
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    error "Server process died. Logs:"
    cat "$SERVER_LOG"
    exit 1
  fi
  sleep 1
done
info "Server is ready."

# ── 7. Run integration tests ──────────────────────────────────────────────────
info "Running integration tests..."
echo ""
PYTHONPATH="$ROOT/src" uv run --directory "$ROOT" \
  pytest tests/test_integration.py -v "$@"
