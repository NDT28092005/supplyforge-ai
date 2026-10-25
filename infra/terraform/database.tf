moved {
  from = aws_db_subnet_group.mysql
  to   = aws_db_subnet_group.mysql[0]
}

moved {
  from = aws_db_instance.mysql
  to   = aws_db_instance.mysql[0]
}

resource "aws_db_subnet_group" "mysql" {
  count = var.database_enabled ? 1 : 0

  name       = "sf-staging-db-subnet"
  subnet_ids = values(aws_subnet.private_data)[*].id

  tags = {
    Name = "sf-staging-db-subnet"
  }
}

resource "aws_db_instance" "mysql" {
  count = var.database_enabled ? 1 : 0

  identifier     = "sf-staging-mysql"
  engine         = "mysql"
  engine_version = "8.0"
  instance_class = var.mysql_instance_class

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.mysql_database
  username = var.mysql_username

  # AWS rotates the master secret container; Terraform never receives the
  # password value and ECS injects only its JSON password key at runtime.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.mysql[0].name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 1
  backup_window           = "18:30-19:30"
  maintenance_window      = "sun:20:00-sun:21:00"
  copy_tags_to_snapshot   = true
  # Staging data is disposable. `down.sh` removes the database without a
  # final snapshot so stopped RDS storage never becomes an idle charge.
  deletion_protection = false
  skip_final_snapshot = true

  auto_minor_version_upgrade      = true
  apply_immediately               = true
  enabled_cloudwatch_logs_exports = ["error", "general", "slowquery"]

  lifecycle {
    # RDS selects the current patch release in the configured MySQL family.
    # Keep automatic minor upgrades enabled without Terraform attempting a downgrade.
    ignore_changes = [engine_version]
  }
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "sf-dev-redis-sg"
  subnet_ids = values(aws_subnet.private_data)[*].id
}

resource "aws_elasticache_replication_group" "redis" {
  count = var.redis_enabled ? 1 : 0

  replication_group_id       = "sf-staging-rediss"
  description                = "SupplyForge staging Redis"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = "cache.t3.micro"
  num_cache_clusters         = 1
  parameter_group_name       = "default.redis7"
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.redis.id]
  automatic_failover_enabled = false
  multi_az_enabled           = false
  at_rest_encryption_enabled = true
  transit_encryption_enabled = false
  auto_minor_version_upgrade = false
  maintenance_window         = "fri:14:30-fri:15:30"
  snapshot_retention_limit   = 0
  snapshot_window            = "17:30-18:30"
  apply_immediately          = true
}
