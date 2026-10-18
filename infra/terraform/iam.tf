data "aws_iam_policy_document" "ecs_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "eventbridge_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eventbridge_sqs" {
  name               = "sf-staging-eventbridge-sqs-role"
  assume_role_policy = data.aws_iam_policy_document.eventbridge_assume_role.json
}

data "aws_iam_policy_document" "eventbridge_sqs" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.work["ingestion_events"].arn]
  }
}

resource "aws_iam_role_policy" "eventbridge_sqs" {
  name   = "send-ingestion-events"
  role   = aws_iam_role.eventbridge_sqs.id
  policy = data.aws_iam_policy_document.eventbridge_sqs.json
}

resource "aws_iam_role" "execution" {
  name               = "sf-staging-ecs-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

resource "aws_iam_role_policy_attachment" "execution_base" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    sid     = "ReadRuntimeSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.django.arn,
      aws_db_instance.mysql.master_user_secret[0].secret_arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-runtime-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "api" {
  name               = "sf-staging-api-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

resource "aws_iam_role" "worker" {
  name               = "sf-staging-worker-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

data "aws_iam_policy_document" "api_runtime" {
  statement {
    sid = "RawUploadObjects"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:PutObject",
    ]
    resources = [
      aws_s3_bucket.data["raw"].arn,
      "${aws_s3_bucket.data["raw"].arn}/*",
    ]
  }

  statement {
    sid = "ReadLakeOutputs"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.data["lake"].arn,
      "${aws_s3_bucket.data["lake"].arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "api_runtime" {
  name   = "s3-runtime-access"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api_runtime.json
}

data "aws_iam_policy_document" "worker_runtime" {
  statement {
    sid = "ReadRawAndWriteLake"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:PutObject",
    ]
    resources = [
      aws_s3_bucket.data["raw"].arn,
      "${aws_s3_bucket.data["raw"].arn}/*",
      aws_s3_bucket.data["lake"].arn,
      "${aws_s3_bucket.data["lake"].arn}/*",
      aws_s3_bucket.data["ml"].arn,
      "${aws_s3_bucket.data["ml"].arn}/*",
    ]
  }

  statement {
    sid = "ConsumeIngestionEvents"
    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]
    resources = [aws_sqs_queue.work["ingestion_events"].arn]
  }
}

resource "aws_iam_role_policy" "worker_runtime" {
  name   = "data-lake-and-queue-access"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_runtime.json
}

resource "random_password" "django" {
  length  = 64
  special = true
}

resource "aws_secretsmanager_secret" "django" {
  name                    = "sf/staging/django-secret-key"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "django" {
  secret_id     = aws_secretsmanager_secret.django.id
  secret_string = random_password.django.result
}
