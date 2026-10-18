data "aws_iam_policy_document" "frontend_bucket" {
  count = var.enable_frontend_hosting ? 1 : 0

  statement {
    sid    = "AllowCloudFrontReadOnly"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend[0].arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend[0].arn]
    }
  }
}

# This bucket contains only regenerated Angular assets. It is intentionally
# deletable, unlike the data lake buckets that retain customer data.
resource "aws_s3_bucket" "frontend" {
  count = var.enable_frontend_hosting ? 1 : 0

  bucket        = "supplyforce-${data.aws_caller_identity.current.account_id}-${var.environment}-frontend"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  count = var.enable_frontend_hosting ? 1 : 0

  bucket                  = aws_s3_bucket.frontend[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  count = var.enable_frontend_hosting ? 1 : 0

  bucket = aws_s3_bucket.frontend[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  count = var.enable_frontend_hosting ? 1 : 0

  bucket = aws_s3_bucket.frontend[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "frontend" {
  count = var.enable_frontend_hosting ? 1 : 0

  bucket = aws_s3_bucket.frontend[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "frontend" {
  count = var.enable_frontend_hosting ? 1 : 0

  bucket = aws_s3_bucket.frontend[0].id

  rule {
    id     = "remove-noncurrent-assets"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 7
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  count = var.enable_frontend_hosting ? 1 : 0

  name                              = "${local.name_prefix}-frontend-s3"
  description                       = "CloudFront-only access to the SupplyForge frontend bucket."
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "frontend" {
  count = var.enable_frontend_hosting ? 1 : 0

  enabled             = true
  is_ipv6_enabled     = true
  comment             = "SupplyForge staging frontend"
  default_root_object = "index.html"
  price_class         = var.frontend_cloudfront_price_class

  origin {
    domain_name              = aws_s3_bucket.frontend[0].bucket_regional_domain_name
    origin_id                = "frontend-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend[0].id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "frontend-s3"
    compress               = true
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = false

      cookies {
        forward = "none"
      }
    }
  }

  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  count = var.enable_frontend_hosting ? 1 : 0

  bucket = aws_s3_bucket.frontend[0].id
  policy = data.aws_iam_policy_document.frontend_bucket[0].json
}

resource "aws_iam_role" "frontend_builder" {
  count = var.enable_frontend_hosting ? 1 : 0

  name               = "${local.name_prefix}-frontend-builder-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

data "aws_iam_policy_document" "frontend_builder" {
  count = var.enable_frontend_hosting ? 1 : 0

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

  statement {
    sid = "DeployFrontendAssets"
    actions = [
      "s3:DeleteObject",
      "s3:GetBucketLocation",
      "s3:ListBucket",
      "s3:PutObject",
    ]
    resources = [
      aws_s3_bucket.frontend[0].arn,
      "${aws_s3_bucket.frontend[0].arn}/*",
    ]
  }

  statement {
    sid       = "InvalidateFrontendCache"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.frontend[0].arn]
  }

  statement {
    sid = "WriteBuildLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.frontend_builder[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "frontend_builder" {
  count = var.enable_frontend_hosting ? 1 : 0

  name   = "deploy-frontend"
  role   = aws_iam_role.frontend_builder[0].id
  policy = data.aws_iam_policy_document.frontend_builder[0].json
}

resource "aws_cloudwatch_log_group" "frontend_builder" {
  count = var.enable_frontend_hosting ? 1 : 0

  name              = "/aws/codebuild/${local.name_prefix}-frontend-builder"
  retention_in_days = 7
}

resource "aws_codebuild_project" "frontend_builder" {
  count = var.enable_frontend_hosting ? 1 : 0

  name          = "${local.name_prefix}-frontend-builder"
  description   = "Builds and deploys the SupplyForge Angular frontend on demand."
  service_role  = aws_iam_role.frontend_builder[0].arn
  build_timeout = 15

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "FRONTEND_BUCKET"
      value = aws_s3_bucket.frontend[0].id
    }

    environment_variable {
      name  = "CLOUDFRONT_DISTRIBUTION_ID"
      value = aws_cloudfront_distribution.frontend[0].id
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.frontend_builder[0].name
      stream_name = "build"
      status      = "ENABLED"
    }
  }

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.image_builder[0].id}/${var.frontend_builder_source_key}"
    buildspec = "buildspec.frontend.yml"
  }

  depends_on = [aws_s3_bucket_policy.frontend]
}
