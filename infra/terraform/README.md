# SupplyForge AWS Foundation Check

This Terraform directory is deliberately read-only. It discovers and verifies
the AWS development foundation that was created manually; it has no
`resource` blocks and it does not create paid AWS services.

It references the existing VPC, private subnets, security groups, S3 buckets,
ECR repository, SQS queues/DLQs, and ECS task roles. Local state is ignored by
Git. A remote state bucket will be added only when deployment work begins.

## Prerequisites

- Terraform 1.16 or newer available in `PATH`.
- AWS CLI logged in through the `supplyforge-dev` IAM Identity Center profile.
- Permission to read the development AWS account in `ap-southeast-1`.

## Safe verification

```bash
export PATH="$HOME/.local/bin:$PATH"
aws sso login --profile supplyforge-dev
cd infra/terraform
terraform init
terraform fmt -check
terraform validate
terraform plan
```

`terraform init` downloads the AWS provider locally. `terraform plan` only
reads AWS. Because this stack has no `resource` blocks, it cannot create,
modify, or destroy AWS infrastructure. On the first run Terraform may show
only `Changes to Outputs` because the local state is empty; that is not an AWS
resource change and data-only plans may not print a `Plan: 0 to add` summary.

## Important

- Do not add credentials, access keys, `.tfvars`, or Terraform state to Git.
- Do not run `terraform apply` as a deployment step. This stack is a baseline
  check only.
- The configured analytics DLQ is `sf--dev-analytics-dlq` with two hyphens,
  matching the current AWS queue name exactly.
