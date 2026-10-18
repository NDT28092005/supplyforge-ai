#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

adopt() {
  local address="$1"
  local identifier="$2"

  if terraform state show "$address" >/dev/null 2>&1; then
    printf 'Already managed: %s\n' "$address"
    return
  fi

  printf 'Importing: %s\n' "$address"
  terraform import "$address" "$identifier"
}

# Network and egress created manually during the first staging bootstrap.
adopt aws_vpc.main vpc-0d8e024f40a06a8db
adopt aws_internet_gateway.main igw-08f9f69633a4a40e8
adopt 'aws_subnet.public["a"]' subnet-08157f0e00d1e71a3
adopt 'aws_subnet.public["b"]' subnet-0e766306ba705c8a0
adopt 'aws_subnet.private_app["a"]' subnet-0e51921619c41fb36
adopt 'aws_subnet.private_app["b"]' subnet-0e15e7ed9102fca4d
adopt 'aws_subnet.private_data["a"]' subnet-05ee878d8329c887c
adopt 'aws_subnet.private_data["b"]' subnet-04e764726adec8c8d
adopt aws_route_table.public rtb-0ea187825cd278bd7
adopt 'aws_route_table.private_app["a"]' rtb-0670f6304c22f75af
adopt 'aws_route_table.private_app["b"]' rtb-09d962e65d3eea287
adopt 'aws_route_table.private_data["a"]' rtb-0b49bbbaeb7cce291
adopt 'aws_route_table.private_data["b"]' rtb-0d112dd02a6437139
adopt aws_route.public_internet 'rtb-0ea187825cd278bd7_0.0.0.0/0'
adopt 'aws_route.private_app_nat["a"]' 'rtb-0670f6304c22f75af_0.0.0.0/0'
adopt 'aws_route.private_app_nat["b"]' 'rtb-09d962e65d3eea287_0.0.0.0/0'
adopt 'aws_route_table_association.public["a"]' subnet-08157f0e00d1e71a3/rtb-0ea187825cd278bd7
adopt 'aws_route_table_association.public["b"]' subnet-0e766306ba705c8a0/rtb-0ea187825cd278bd7
adopt 'aws_route_table_association.private_app["a"]' subnet-0e51921619c41fb36/rtb-0670f6304c22f75af
adopt 'aws_route_table_association.private_app["b"]' subnet-0e15e7ed9102fca4d/rtb-09d962e65d3eea287
adopt 'aws_route_table_association.private_data["a"]' subnet-05ee878d8329c887c/rtb-0b49bbbaeb7cce291
adopt 'aws_route_table_association.private_data["b"]' subnet-04e764726adec8c8d/rtb-0d112dd02a6437139
adopt 'aws_eip.nat["a"]' eipalloc-065991e514ab0a77c
adopt 'aws_eip.nat["b"]' eipalloc-0d142153af40c0020
adopt 'aws_nat_gateway.this["a"]' nat-0a9201ed8a0b980dd
adopt 'aws_nat_gateway.this["b"]' nat-076e351a24ada24cd
adopt aws_vpc_endpoint.s3 vpce-0b708d98280b055e2

# Existing data plane and messaging foundation.
adopt 'aws_s3_bucket.data["raw"]' supplyforce-410244642625-dev-raw
adopt 'aws_s3_bucket.data["lake"]' supplyforce-410244642625-dev-lake
adopt 'aws_s3_bucket.data["ml"]' supplyforce-410244642625-dev-ml
adopt aws_ecr_repository.backend supplyforge/backend
adopt 'aws_sqs_queue.dlq["ingestion"]' sf-dev-ingestion-dlq
adopt 'aws_sqs_queue.dlq["transform"]' sf-dev-transform-dlq
adopt 'aws_sqs_queue.dlq["analytics"]' sf--dev-analytics-dlq
adopt 'aws_sqs_queue.dlq["ml"]' sf-dev-ml-dlq
adopt 'aws_sqs_queue.work["ingestion_events"]' sf-dev-ingestion-events
adopt 'aws_sqs_queue.work["transform"]' sf-dev-transform
adopt 'aws_sqs_queue.work["analytics"]' sf-dev-analytics
adopt 'aws_sqs_queue.work["ml"]' sf-dev-ml
adopt aws_cloudwatch_event_rule.raw_object_created sf-dev-raw-upload
adopt aws_cloudwatch_event_target.raw_object_created 'sf-dev-raw-upload/b33f72d9-02e5-4bd0-82f1-998a5a53e49f'

# Existing compute/cache resources. The legacy task definition is deliberately
# not imported: Terraform registers the corrected sf-staging-api family.
adopt aws_ecs_cluster.main sf-staging
adopt aws_elasticache_subnet_group.redis sf-dev-redis-sg
adopt 'aws_elasticache_replication_group.redis[0]' sf-staging-rediss

printf '%s\n' 'Adoption completed. Run terraform plan and review only intended changes.'
