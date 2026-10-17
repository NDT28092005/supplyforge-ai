# This stack is intentionally read-only. It verifies the AWS foundation before
# paid services or deployment resources are introduced in a later stack.
data "aws_caller_identity" "current" {}

data "aws_vpc" "foundation" {
  filter {
    name   = "tag:Name"
    values = [var.vpc_name]
  }
}

data "aws_subnet" "foundation" {
  for_each = var.subnet_names

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.foundation.id]
  }

  filter {
    name   = "tag:Name"
    values = [each.value]
  }
}

data "aws_security_group" "foundation" {
  for_each = var.security_group_names

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.foundation.id]
  }

  filter {
    name   = "group-name"
    values = [each.value]
  }
}

data "aws_s3_bucket" "foundation" {
  for_each = var.bucket_names
  bucket   = each.value
}

data "aws_ecr_repository" "backend" {
  name = var.ecr_repository_name
}

data "aws_sqs_queue" "foundation" {
  for_each = var.queue_names
  name     = each.value
}

data "aws_iam_role" "foundation" {
  for_each = var.iam_role_names
  name     = each.value
}
