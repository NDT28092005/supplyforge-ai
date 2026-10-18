resource "aws_s3_bucket" "data" {
  for_each = var.bucket_names

  bucket        = each.value
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  for_each = var.bucket_names

  bucket                  = aws_s3_bucket.data[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "data" {
  for_each = var.bucket_names

  bucket = aws_s3_bucket.data[each.key].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  for_each = var.bucket_names

  bucket = aws_s3_bucket.data[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "data" {
  for_each = var.bucket_names

  bucket = aws_s3_bucket.data[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  for_each = {
    raw  = aws_s3_bucket.data["raw"].id
    lake = aws_s3_bucket.data["lake"].id
  }

  bucket = each.value

  rule {
    id     = "archive-after-24-months"
    status = "Enabled"

    filter {}

    transition {
      days          = 730
      storage_class = "DEEP_ARCHIVE"
    }

    expiration {
      days = 2555
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "raw" {
  bucket = aws_s3_bucket.data["raw"].id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD", "POST", "PUT"]
    allowed_origins = var.cors_allowed_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

# EventBridge keeps S3 delivery decoupled from the client finalization call.
resource "aws_s3_bucket_notification" "raw" {
  bucket      = aws_s3_bucket.data["raw"].id
  eventbridge = true
}

resource "aws_ecr_repository" "backend" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = "arn:aws:kms:ap-southeast-1:410244642625:key/0721f478-e40a-4306-866c-68977d55ca87"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Retain the latest 30 immutable backend images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 30
        }
        action = { type = "expire" }
      },
    ]
  })
}
