resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/sf-staging/api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/sf-staging/worker"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "main" {
  name = "sf-staging"

  configuration {
    execute_command_configuration {
      logging = "DEFAULT"
    }
  }

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "sf-staging-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"
      essential = true
      portMappings = [{
        containerPort = 8080
        hostPort      = 8080
        protocol      = "tcp"
        appProtocol   = "http"
      }]
      environment = local.common_environment
      secrets     = local.runtime_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
    },
  ])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "sf-staging-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "celery"
      image     = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"
      essential = true
      # A staging task currently runs all queues. Queue names still isolate
      # backlog and let the production service be split by worker class
      # without changing task routing.
      command     = ["celery", "-A", "config", "worker", "--loglevel=info", "--queues=data_worker,ml_worker,decision_worker,integration_worker,celery"]
      environment = local.common_environment
      secrets     = local.runtime_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.worker.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "celery"
        }
      }
    },
    {
      name        = "s3-events"
      image       = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"
      essential   = true
      command     = ["python", "manage.py", "consume_s3_ingestion_events"]
      environment = local.common_environment
      secrets     = local.runtime_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.worker.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "s3-events"
        }
      }
    },
  ])
}

resource "aws_lb" "public" {
  count = var.enable_public_api ? 1 : 0

  name               = "sf-staging-api"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = values(aws_subnet.public)[*].id

  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  count = var.enable_public_api ? 1 : 0

  name        = "sf-staging-api"
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    enabled             = true
    path                = "/health/live"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  count = var.enable_public_api ? 1 : 0

  load_balancer_arn = aws_lb.public[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  count = var.enable_public_api ? 1 : 0

  load_balancer_arn = aws_lb.public[0].arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.acm_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}

resource "aws_ecs_service" "api" {
  name            = "sf-staging-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = values(aws_subnet.private_app)[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = var.enable_public_api ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.api[0].arn
      container_name   = "api"
      container_port   = 8080
    }
  }

  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "worker" {
  name            = "sf-staging-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = values(aws_subnet.private_app)[*].id
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }
}

resource "aws_appautoscaling_target" "api" {
  count = var.enable_autoscaling ? 1 : 0

  max_capacity       = var.api_max_count
  min_capacity       = 0
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  count = var.enable_autoscaling ? 1 : 0

  name               = "sf-staging-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api[0].resource_id
  scalable_dimension = aws_appautoscaling_target.api[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.api[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
