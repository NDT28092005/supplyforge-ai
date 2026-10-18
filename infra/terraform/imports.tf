# Declarative imports keep the first staging adoption reviewable in `plan` and
# avoid imperative console adoption. Keeping these blocks is harmless after a
# resource is already present in remote state.
import {
  to = aws_vpc.main
  id = "vpc-0d8e024f40a06a8db"
}

import {
  to = aws_internet_gateway.main
  id = "igw-08f9f69633a4a40e8"
}

import {
  to = aws_subnet.public["a"]
  id = "subnet-08157f0e00d1e71a3"
}

import {
  to = aws_subnet.public["b"]
  id = "subnet-0e766306ba705c8a0"
}

import {
  to = aws_subnet.private_app["a"]
  id = "subnet-0e51921619c41fb36"
}

import {
  to = aws_subnet.private_app["b"]
  id = "subnet-0e15e7ed9102fca4d"
}

import {
  to = aws_subnet.private_data["a"]
  id = "subnet-05ee878d8329c887c"
}

import {
  to = aws_subnet.private_data["b"]
  id = "subnet-04e764726adec8c8d"
}

import {
  to = aws_route_table.public
  id = "rtb-0ea187825cd278bd7"
}

import {
  to = aws_route_table.private_app["a"]
  id = "rtb-0670f6304c22f75af"
}

import {
  to = aws_route_table.private_app["b"]
  id = "rtb-09d962e65d3eea287"
}

import {
  to = aws_route_table.private_data["a"]
  id = "rtb-0b49bbbaeb7cce291"
}

import {
  to = aws_route_table.private_data["b"]
  id = "rtb-0d112dd02a6437139"
}

import {
  to = aws_route.public_internet
  id = "rtb-0ea187825cd278bd7_0.0.0.0/0"
}

import {
  to = aws_route_table_association.public["a"]
  id = "subnet-08157f0e00d1e71a3/rtb-0ea187825cd278bd7"
}

import {
  to = aws_route_table_association.public["b"]
  id = "subnet-0e766306ba705c8a0/rtb-0ea187825cd278bd7"
}

import {
  to = aws_route_table_association.private_app["a"]
  id = "subnet-0e51921619c41fb36/rtb-0670f6304c22f75af"
}

import {
  to = aws_route_table_association.private_app["b"]
  id = "subnet-0e15e7ed9102fca4d/rtb-09d962e65d3eea287"
}

import {
  to = aws_route_table_association.private_data["a"]
  id = "subnet-05ee878d8329c887c/rtb-0b49bbbaeb7cce291"
}

import {
  to = aws_route_table_association.private_data["b"]
  id = "subnet-04e764726adec8c8d/rtb-0d112dd02a6437139"
}

import {
  to = aws_vpc_endpoint.s3
  id = "vpce-0b708d98280b055e2"
}

import {
  to = aws_s3_bucket.data["raw"]
  id = "supplyforce-410244642625-dev-raw"
}

import {
  to = aws_s3_bucket.data["lake"]
  id = "supplyforce-410244642625-dev-lake"
}

import {
  to = aws_s3_bucket.data["ml"]
  id = "supplyforce-410244642625-dev-ml"
}

import {
  to = aws_ecr_repository.backend
  id = "supplyforge/backend"
}

import {
  to = aws_sqs_queue.dlq["ingestion"]
  id = "https://sqs.ap-southeast-1.amazonaws.com/410244642625/sf-dev-ingestion-dlq"
}

import {
  to = aws_sqs_queue.dlq["transform"]
  id = "https://sqs.ap-southeast-1.amazonaws.com/410244642625/sf-dev-transform-dlq"
}

import {
  to = aws_sqs_queue.dlq["analytics"]
  id = "https://sqs.ap-southeast-1.amazonaws.com/410244642625/sf--dev-analytics-dlq"
}

import {
  to = aws_sqs_queue.dlq["ml"]
  id = "https://sqs.ap-southeast-1.amazonaws.com/410244642625/sf-dev-ml-dlq"
}

import {
  to = aws_sqs_queue.work["ingestion_events"]
  id = "https://sqs.ap-southeast-1.amazonaws.com/410244642625/sf-dev-ingestion-events"
}

import {
  to = aws_sqs_queue.work["transform"]
  id = "https://sqs.ap-southeast-1.amazonaws.com/410244642625/sf-dev-transform"
}

import {
  to = aws_sqs_queue.work["analytics"]
  id = "https://sqs.ap-southeast-1.amazonaws.com/410244642625/sf-dev-analytics"
}

import {
  to = aws_sqs_queue.work["ml"]
  id = "https://sqs.ap-southeast-1.amazonaws.com/410244642625/sf-dev-ml"
}

import {
  to = aws_cloudwatch_event_rule.raw_object_created
  id = "sf-dev-raw-upload"
}

import {
  to = aws_cloudwatch_event_target.raw_object_created
  id = "sf-dev-raw-upload/b33f72d9-02e5-4bd0-82f1-998a5a53e49f"
}

import {
  to = aws_ecs_cluster.main
  id = "sf-staging"
}

import {
  to = aws_elasticache_subnet_group.redis
  id = "sf-dev-redis-sg"
}
