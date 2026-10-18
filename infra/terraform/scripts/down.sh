#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

frontend_hosting_enabled=false
if terraform state list | grep -Fxq 'aws_cloudfront_distribution.frontend[0]'; then
  frontend_hosting_enabled=true
fi

# Scale only the services first. Targeting these two resources avoids
# recreating hibernated NAT/Redis just to turn the services off again.
terraform apply -auto-approve \
  -target=aws_ecs_service.api \
  -target=aws_ecs_service.worker \
  -var='api_desired_count=0' \
  -var='worker_desired_count=0'

aws ecs wait services-stable \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --cluster sf-staging \
  --services sf-staging-api sf-staging-worker

aws rds stop-db-instance \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --db-instance-identifier sf-staging-mysql >/dev/null 2>&1 || true

aws rds wait db-instance-stopped \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --db-instance-identifier sf-staging-mysql

# Cost-safe defaults remove NAT and Redis after all task writers and RDS stop.
terraform apply -auto-approve \
  -var='enable_nat_gateways=false' \
  -var='redis_enabled=false' \
  -var="enable_frontend_hosting=$frontend_hosting_enabled" \
  -var='api_desired_count=0' \
  -var='worker_desired_count=0'

printf '%s\n' 'Runtime hibernated: ECS is zero, RDS is stopped, and NAT/Redis were removed.'
printf '%s\n' 'S3, ECR, Terraform state, and RDS storage are preserved.'
