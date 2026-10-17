output "foundation" {
  description = "Identifiers for the existing AWS development foundation. No resource is managed by this stack."
  value = {
    account_id = data.aws_caller_identity.current.account_id
    region     = var.aws_region
    vpc_id     = data.aws_vpc.foundation.id
    subnet_ids = {
      for name, subnet in data.aws_subnet.foundation : name => subnet.id
    }
    security_group_ids = {
      for name, security_group in data.aws_security_group.foundation : name => security_group.id
    }
    bucket_arns = {
      for name, bucket in data.aws_s3_bucket.foundation : name => bucket.arn
    }
    ecr_repository_url = data.aws_ecr_repository.backend.repository_url
    queue_urls = {
      for name, queue in data.aws_sqs_queue.foundation : name => queue.url
    }
    iam_role_arns = {
      for name, role in data.aws_iam_role.foundation : name => role.arn
    }
  }
}
