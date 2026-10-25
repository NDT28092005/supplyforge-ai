output "staging" {
  description = "Non-secret identifiers for deployment automation and verification."
  value = {
    region          = var.aws_region
    vpc_id          = aws_vpc.main.id
    ecs_cluster     = aws_ecs_cluster.main.name
    api_service     = aws_ecs_service.api.name
    worker_service  = aws_ecs_service.worker.name
    ecr_repository  = aws_ecr_repository.backend.repository_url
    rds_endpoint    = var.database_enabled ? aws_db_instance.mysql[0].address : null
    redis_endpoint  = var.redis_enabled ? aws_elasticache_replication_group.redis[0].primary_endpoint_address : null
    raw_bucket      = aws_s3_bucket.data["raw"].id
    lake_bucket     = aws_s3_bucket.data["lake"].id
    ml_bucket       = aws_s3_bucket.data["ml"].id
    ingestion_queue = aws_sqs_queue.work["ingestion_events"].url
    api_alb_dns     = var.enable_public_api ? aws_lb.public[0].dns_name : null
  }
}

output "django_secret_arn" {
  description = "ARN injected into ECS; the secret value is never output."
  value       = aws_secretsmanager_secret.django.arn
}

output "rds_master_secret_arn" {
  description = "RDS-managed JSON secret ARN. Its password value is never output."
  value       = var.database_enabled ? aws_db_instance.mysql[0].master_user_secret[0].secret_arn : null
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "api_task_definition_arn" {
  value = aws_ecs_task_definition.api.arn
}

output "image_builder_project_name" {
  description = "On-demand CodeBuild project that creates and pushes backend images."
  value       = var.enable_image_builder ? aws_codebuild_project.image_builder[0].name : null
}

output "image_builder_source_bucket" {
  description = "Private versioned bucket holding short-lived CodeBuild source archives."
  value       = var.enable_image_builder ? aws_s3_bucket.image_builder[0].id : null
}

output "image_builder_source_key" {
  description = "Object key CodeBuild reads for the backend source archive."
  value       = var.image_builder_source_key
}

output "frontend_url" {
  description = "Default HTTPS URL served by CloudFront. No custom domain or ACM certificate is required."
  value       = var.enable_frontend_hosting ? "https://${aws_cloudfront_distribution.frontend[0].domain_name}" : null
}

output "frontend_bucket" {
  description = "Private bucket containing only regenerable Angular build assets."
  value       = var.enable_frontend_hosting ? aws_s3_bucket.frontend[0].id : null
}

output "frontend_distribution_id" {
  description = "CloudFront distribution ID used by the deployment build and cache invalidation."
  value       = var.enable_frontend_hosting ? aws_cloudfront_distribution.frontend[0].id : null
}

output "frontend_builder_project_name" {
  description = "On-demand CodeBuild project that builds and publishes the Angular frontend."
  value       = var.enable_frontend_hosting ? aws_codebuild_project.frontend_builder[0].name : null
}

output "frontend_builder_source_key" {
  description = "Object key CodeBuild reads for the frontend source archive."
  value       = var.frontend_builder_source_key
}

output "private_app_subnet_ids" {
  value = values(aws_subnet.private_app)[*].id
}

output "api_security_group_id" {
  value = aws_security_group.api.id
}
