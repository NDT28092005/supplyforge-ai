variable "aws_region" {
  description = "AWS region containing the staging environment."
  type        = string
  default     = "ap-southeast-1"
}

variable "aws_profile" {
  description = "AWS CLI/SSO profile used by Terraform."
  type        = string
  default     = "supplyforge-dev"
}

variable "environment" {
  description = "Deployment environment. This stack is intentionally staging-only."
  type        = string
  default     = "staging"

  validation {
    condition     = var.environment == "staging"
    error_message = "Use a separate state key and stack before creating production."
  }
}

variable "vpc_id" {
  description = "Existing VPC adopted by this stack."
  type        = string
  default     = "vpc-0d8e024f40a06a8db"
}

variable "vpc_cidr" {
  description = "IPv4 CIDR of the adopted VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "internet_gateway_id" {
  description = "Existing internet gateway attached to the VPC."
  type        = string
  default     = "igw-08f9f69633a4a40e8"
}

variable "public_subnet_ids" {
  description = "Existing public subnets keyed by availability-zone suffix."
  type        = map(string)
  default = {
    a = "subnet-08157f0e00d1e71a3"
    b = "subnet-0e766306ba705c8a0"
  }
}

variable "private_app_subnet_ids" {
  description = "Private Fargate subnets keyed by availability-zone suffix."
  type        = map(string)
  default = {
    a = "subnet-0e51921619c41fb36"
    b = "subnet-0e15e7ed9102fca4d"
  }
}

variable "private_data_subnet_ids" {
  description = "Private RDS and ElastiCache subnets keyed by availability-zone suffix."
  type        = map(string)
  default = {
    a = "subnet-05ee878d8329c887c"
    b = "subnet-04e764726adec8c8d"
  }
}

variable "route_table_ids" {
  description = "Existing route table IDs that will be imported and managed."
  type = object({
    public         = string
    private_app_a  = string
    private_app_b  = string
    private_data_a = string
    private_data_b = string
  })
  default = {
    public         = "rtb-0ea187825cd278bd7"
    private_app_a  = "rtb-0670f6304c22f75af"
    private_app_b  = "rtb-09d962e65d3eea287"
    private_data_a = "rtb-0b49bbbaeb7cce291"
    private_data_b = "rtb-0d112dd02a6437139"
  }
}

variable "s3_gateway_endpoint_id" {
  description = "Existing free S3 gateway endpoint."
  type        = string
  default     = "vpce-0b708d98280b055e2"
}

variable "enable_nat_gateways" {
  description = "Create NAT gateways and private-app egress routes. Kept false by default to avoid idle NAT charges."
  type        = bool
  default     = false
}

variable "bucket_names" {
  description = "Existing immutable data lake buckets."
  type        = map(string)
  default = {
    raw  = "supplyforce-410244642625-dev-raw"
    lake = "supplyforce-410244642625-dev-lake"
    ml   = "supplyforce-410244642625-dev-ml"
  }
}

variable "ecr_repository_name" {
  description = "Existing backend ECR repository."
  type        = string
  default     = "supplyforge/backend"
}

variable "backend_image_tag" {
  description = "Immutable backend image tag already pushed to ECR."
  type        = string
  default     = "staging-003"
}

variable "enable_image_builder" {
  description = "Manage the on-demand CodeBuild project used to push backend images to ECR. Idle projects have no build charge."
  type        = bool
  default     = true
}

variable "image_builder_default_tag" {
  description = "ECR tag used unless overridden when starting a CodeBuild run."
  type        = string
  default     = "staging-002"
}

variable "image_builder_source_key" {
  description = "Versioned S3 object key used as the CodeBuild source archive."
  type        = string
  default     = "source-bundles/staging/backend.zip"
}

variable "enable_frontend_hosting" {
  description = "Manage the private S3 + CloudFront Angular frontend. Disabled by default so hosting is created only by deploy-frontend.sh."
  type        = bool
  default     = false
}

variable "frontend_builder_source_key" {
  description = "Versioned S3 object key used as the CodeBuild source archive for the Angular frontend."
  type        = string
  default     = "source-bundles/staging/frontend.zip"
}

variable "frontend_cloudfront_price_class" {
  description = "CloudFront edge coverage. PriceClass_200 includes Singapore and other Asia-Pacific edges at lower cost than global coverage."
  type        = string
  default     = "PriceClass_200"

  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.frontend_cloudfront_price_class)
    error_message = "Use PriceClass_100, PriceClass_200, or PriceClass_All."
  }
}

variable "mysql_database" {
  description = "Initial application database created by RDS."
  type        = string
  default     = "supplyforge"
}

variable "mysql_username" {
  description = "RDS application master username."
  type        = string
  default     = "supplyforge"
}

variable "mysql_instance_class" {
  description = "RDS instance class for staging."
  type        = string
  default     = "db.t3.micro"
}

variable "database_enabled" {
  description = "Create the disposable staging RDS MySQL instance. `down.sh` destroys it; `up.sh` recreates it before migrations."
  type        = bool
  default     = false
}

variable "redis_enabled" {
  description = "Create the Redis cluster. Kept false by default; enabling it recreates an empty queue and cache."
  type        = bool
  default     = false
}

variable "api_desired_count" {
  description = "Number of running API tasks. Set 0 to stop Fargate API charges."
  type        = number
  default     = 0
}

variable "worker_desired_count" {
  description = "Number of running worker tasks. Set 0 before stopping Redis/RDS/NAT."
  type        = number
  default     = 0
}

variable "enable_autoscaling" {
  description = "Enable ECS CPU target tracking after baseline service validation."
  type        = bool
  default     = false
}

variable "api_max_count" {
  description = "Maximum API tasks when autoscaling is enabled."
  type        = number
  default     = 4
}

variable "enable_public_api" {
  description = "Create public HTTPS ALB resources. Requires an ACM certificate ARN."
  type        = bool
  default     = false
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN in ap-southeast-1 for the public API hostname."
  type        = string
  default     = ""
}

variable "additional_allowed_hosts" {
  description = "Custom API DNS names accepted by Django."
  type        = list(string)
  default     = []
}

variable "cors_allowed_origins" {
  description = "Explicit browser origins allowed to call the staging API."
  type        = list(string)
  default     = ["http://localhost:4200"]
}

variable "eventbridge_target_id" {
  description = "Existing EventBridge target ID for raw object-created events."
  type        = string
  default     = "b33f72d9-02e5-4bd0-82f1-998a5a53e49f"
}

variable "monthly_budget_usd" {
  description = "Monthly staging cost budget in USD."
  type        = string
  default     = "80"
}

variable "billing_alert_email" {
  description = "Email that receives AWS Budget notifications and confirms its subscription once."
  type        = string
  default     = "ndaitung28092005@gmail.com"
}
