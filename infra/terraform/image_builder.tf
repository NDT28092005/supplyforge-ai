data "aws_iam_policy_document" "codebuild_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_s3_bucket" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  bucket = "supplyforce-${data.aws_caller_identity.current.account_id}-${var.environment}-builds"
}

resource "aws_s3_bucket_public_access_block" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  bucket                  = aws_s3_bucket.image_builder[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  bucket = aws_s3_bucket.image_builder[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  bucket = aws_s3_bucket.image_builder[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  bucket = aws_s3_bucket.image_builder[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  bucket = aws_s3_bucket.image_builder[0].id

  rule {
    id     = "expire-build-sources"
    status = "Enabled"

    filter {}

    expiration {
      days = 14
    }

    noncurrent_version_expiration {
      noncurrent_days = 3
    }
  }
}

resource "aws_iam_role" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  name               = "${local.name_prefix}-image-builder-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

data "aws_iam_policy_document" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  statement {
    sid       = "EcrAuthentication"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "PushBackendImage"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.backend.arn]
  }

  statement {
    sid = "WriteBuildLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.image_builder[0].arn}:*"]
  }

  statement {
    sid       = "ReadBuildSource"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.image_builder[0].arn}/*"]
  }

  statement {
    sid       = "ReadBuildSourceVersioning"
    actions   = ["s3:GetBucketVersioning"]
    resources = [aws_s3_bucket.image_builder[0].arn]
  }
}

resource "aws_iam_role_policy" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  name   = "push-backend-image"
  role   = aws_iam_role.image_builder[0].id
  policy = data.aws_iam_policy_document.image_builder[0].json
}

resource "aws_cloudwatch_log_group" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  name              = "/aws/codebuild/${local.name_prefix}-image-builder"
  retention_in_days = 7
}

resource "aws_codebuild_project" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  name          = "${local.name_prefix}-image-builder"
  description   = "Builds the public SupplyForge repository and pushes a backend image to ECR on demand."
  service_role  = aws_iam_role.image_builder[0].arn
  build_timeout = 30

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "IMAGE_TAG"
      value = var.image_builder_default_tag
    }

    environment_variable {
      name  = "ECR_REPOSITORY_URL"
      value = aws_ecr_repository.backend.repository_url
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.image_builder[0].name
      stream_name = "build"
      status      = "ENABLED"
    }
  }

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.image_builder[0].id}/${var.image_builder_source_key}"
    buildspec = "buildspec.backend.yml"

  }
}
