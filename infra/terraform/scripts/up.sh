#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

frontend_hosting_enabled=false
if terraform state list | grep -Fxq 'aws_cloudfront_distribution.frontend[0]'; then
  frontend_hosting_enabled=true
fi

# Restore networking/cache first. RDS is started separately because Terraform
# models its configuration, while AWS owns the stopped/running runtime state.
terraform apply -auto-approve \
  -var='enable_nat_gateways=true' \
  -var='redis_enabled=true' \
  -var="enable_frontend_hosting=$frontend_hosting_enabled" \
  -var='api_desired_count=0' \
  -var='worker_desired_count=0'

aws rds start-db-instance \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --db-instance-identifier sf-staging-mysql >/dev/null 2>&1 || true

aws rds wait db-instance-available \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --db-instance-identifier sf-staging-mysql

# Apply schema changes before any long-lived API or worker task is started.
bash "$ROOT_DIR/scripts/migrate.sh"

terraform apply -auto-approve \
  -var='enable_nat_gateways=true' \
  -var='redis_enabled=true' \
  -var="enable_frontend_hosting=$frontend_hosting_enabled" \
  -var='api_desired_count=1' \
  -var='worker_desired_count=1'

printf '%s\n' 'API and worker services are running.'
