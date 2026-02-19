#!/usr/bin/env bash
# Build a Lambda-deployable ZIP from blog-backend source.
#
# Use this when you need to deploy manually outside of CDK (e.g. hotfix).
# CDK bundling (blog-infra/lib/backend-stack.ts) handles packaging automatically
# during `cdk deploy` — you only need this script for standalone deploys.
#
# Output: lambda.zip in the blog-backend root
# Deploy: aws lambda update-function-code \
#           --function-name botthef-admin-api \
#           --zip-file fileb://lambda.zip \
#           --region us-west-2

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
BUILD_DIR="$ROOT/build"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[build]${NC} $*"; }
warning() { echo -e "${YELLOW}[build]${NC} $*"; }

# ── 1. Clean ──────────────────────────────────────────────────────────────────
info "Cleaning build directory..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# ── 2. Install prod dependencies ──────────────────────────────────────────────
# --python-platform and --python-version ensure Linux x86_64 wheels are fetched
# regardless of the build host (e.g. Apple Silicon). Lambda runs on x86_64 Linux.
info "Installing Python dependencies into $BUILD_DIR ..."
uv pip install \
  --target "$BUILD_DIR" \
  --python-platform x86_64-unknown-linux-gnu \
  --python-version 3.12 \
  fastapi \
  mangum \
  boto3 \
  "python-jose[cryptography]" \
  pydantic

# ── 3. Copy source ────────────────────────────────────────────────────────────
info "Copying source (admin + shared)..."
cp -r "$ROOT/src/admin"  "$BUILD_DIR/"
cp -r "$ROOT/src/shared" "$BUILD_DIR/"

# ── 4. Zip ────────────────────────────────────────────────────────────────────
ZIP="$ROOT/lambda.zip"
rm -f "$ZIP"
info "Creating lambda.zip..."
(cd "$BUILD_DIR" && zip -r "$ZIP" . -x "*.pyc" -x "*/__pycache__/*" > /dev/null)

SIZE=$(du -h "$ZIP" | cut -f1)
info "Done → lambda.zip ($SIZE)"
info ""
info "Deploy with:"
info "  aws lambda update-function-code \\"
info "    --function-name botthef-admin-api \\"
info "    --zip-file fileb://lambda.zip \\"
info "    --region us-west-2"
