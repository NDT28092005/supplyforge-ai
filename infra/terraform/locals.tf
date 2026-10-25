locals {
  name_prefix = "sf-${var.environment}"

  tags = {
    Application = "supplyforge"
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  public_subnets = {
    a = {
      id   = var.public_subnet_ids.a
      cidr = "10.20.0.0/20"
      az   = "ap-southeast-1a"
    }
    b = {
      id   = var.public_subnet_ids.b
      cidr = "10.20.16.0/20"
      az   = "ap-southeast-1b"
    }
  }

  private_app_subnets = {
    a = {
      id   = var.private_app_subnet_ids.a
      cidr = "10.20.128.0/20"
      az   = "ap-southeast-1a"
    }
    b = {
      id   = var.private_app_subnet_ids.b
      cidr = "10.20.144.0/20"
      az   = "ap-southeast-1b"
    }
  }

  private_data_subnets = {
    a = {
      id   = var.private_data_subnet_ids.a
      cidr = "10.20.160.0/20"
      az   = "ap-southeast-1a"
    }
    b = {
      id   = var.private_data_subnet_ids.b
      cidr = "10.20.176.0/20"
      az   = "ap-southeast-1b"
    }
  }

  nat_subnet_ids = {
    a = local.public_subnets.a.id
    b = local.public_subnets.b.id
  }

  redis_endpoint = var.redis_enabled ? aws_elasticache_replication_group.redis[0].primary_endpoint_address : "127.0.0.1"

  allowed_hosts = distinct(concat(
    ["localhost", "127.0.0.1"],
    var.additional_allowed_hosts,
    var.enable_public_api ? [aws_lb.public[0].dns_name] : [],
  ))

  common_environment = [
    { name = "APP_ENV", value = var.environment },
    { name = "DJANGO_DEBUG", value = "false" },
    { name = "USE_SQLITE", value = "0" },
    { name = "MYSQL_HOST", value = var.database_enabled ? aws_db_instance.mysql[0].address : "" },
    { name = "MYSQL_PORT", value = var.database_enabled ? tostring(aws_db_instance.mysql[0].port) : "3306" },
    { name = "MYSQL_DATABASE", value = var.mysql_database },
    { name = "MYSQL_USER", value = var.mysql_username },
    { name = "REDIS_HOST", value = local.redis_endpoint },
    { name = "REDIS_PORT", value = "6379" },
    { name = "CELERY_BROKER_URL", value = "redis://${local.redis_endpoint}:6379/0" },
    { name = "CELERY_RESULT_BACKEND", value = "redis://${local.redis_endpoint}:6379/0" },
    { name = "REDIS_CACHE_URL", value = "redis://${local.redis_endpoint}:6379/1" },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_AUTH_MODE", value = "auto" },
    { name = "S3_BUCKET", value = var.bucket_names.raw },
    { name = "S3_LAKE_BUCKET", value = var.bucket_names.lake },
    { name = "S3_REGION", value = var.aws_region },
    { name = "SQS_INGESTION_QUEUE_URL", value = aws_sqs_queue.work["ingestion_events"].url },
    { name = "ALLOWED_HOSTS", value = join(",", local.allowed_hosts) },
    { name = "CORS_ALLOWED_ORIGINS", value = join(",", var.cors_allowed_origins) },
    { name = "TRUSTED_PROXY_IPS", value = var.vpc_cidr },
  ]

  runtime_secrets = concat(
    [
      {
        name      = "DJANGO_SECRET_KEY"
        valueFrom = aws_secretsmanager_secret.django.arn
      },
    ],
    var.database_enabled ? [
      {
        name      = "MYSQL_PASSWORD"
        valueFrom = "${aws_db_instance.mysql[0].master_user_secret[0].secret_arn}:password::"
      },
    ] : [],
  )
}
