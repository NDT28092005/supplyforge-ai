variable "aws_region" {
  description = "AWS region containing the SupplyForge development foundation."
  type        = string
  default     = "ap-southeast-1"
}

variable "aws_profile" {
  description = "Local AWS CLI SSO profile. Credentials are never stored in Terraform."
  type        = string
  default     = "supplyforge-dev"
}

variable "vpc_name" {
  description = "Name tag of the existing development VPC."
  type        = string
  default     = "sf-dev-vpc"
}

variable "subnet_names" {
  description = "Existing private application and data subnet Name tags."
  type        = set(string)
  default = [
    "sf-dev-private-app-a",
    "sf-dev-private-app-b",
    "sf-dev-private-data-a",
    "sf-dev-private-data-b",
  ]
}

variable "security_group_names" {
  description = "Existing development security group names."
  type        = set(string)
  default = [
    "sf-dev-alb-sg",
    "sf-dev-api-sg",
    "sf-dev-rds-sg",
    "sf-dev-redis-sg",
    "sf-dev-worker-sg",
  ]
}

variable "bucket_names" {
  description = "Existing immutable raw, lake and ML S3 buckets."
  type        = map(string)
  default = {
    raw  = "supplyforce-410244642625-dev-raw"
    lake = "supplyforce-410244642625-dev-lake"
    ml   = "supplyforce-410244642625-dev-ml"
  }
}

variable "ecr_repository_name" {
  description = "Existing SupplyForge backend ECR repository."
  type        = string
  default     = "supplyforge/backend"
}

variable "queue_names" {
  description = "Existing work queues and DLQs. The analytics DLQ name intentionally mirrors AWS exactly."
  type        = map(string)
  default = {
    ingestion_events = "sf-dev-ingestion-events"
    ingestion_dlq    = "sf-dev-ingestion-dlq"
    transform        = "sf-dev-transform"
    transform_dlq    = "sf-dev-transform-dlq"
    analytics        = "sf-dev-analytics"
    analytics_dlq    = "sf--dev-analytics-dlq"
    ml               = "sf-dev-ml"
    ml_dlq           = "sf-dev-ml-dlq"
  }
}

variable "iam_role_names" {
  description = "Existing ECS task role names."
  type        = map(string)
  default = {
    execution = "sf-dev-ecs-execution-role"
    api       = "sf-dev-api-task-role"
    worker    = "sf-dev-worker-task-role"
  }
}
