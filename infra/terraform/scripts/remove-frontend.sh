#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# This removes CloudFront, the static assets, and the idle frontend build
# project. It never touches the three data-lake buckets, ECR, or RDS storage.
terraform apply -auto-approve -var='enable_frontend_hosting=false'

printf '%s\n' 'Frontend hosting removed. Future deploy-frontend.sh runs recreate it.'
