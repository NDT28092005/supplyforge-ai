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

# Cost-safe defaults remove NAT, Redis, and disposable RDS storage after all
# task writers stop. No final RDS snapshot is retained in staging.
terraform apply -auto-approve \
  -var='enable_nat_gateways=false' \
  -var='database_enabled=false' \
  -var='redis_enabled=false' \
  -var="enable_frontend_hosting=$frontend_hosting_enabled" \
  -var='api_desired_count=0' \
  -var='worker_desired_count=0'

printf '%s\n' 'Runtime removed: ECS is zero; RDS, Redis, and NAT were deleted.'
printf '%s\n' 'S3, ECR, Terraform state, and frontend hosting are preserved.'
