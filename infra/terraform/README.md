# SupplyForge Staging IaC

Terraform is the source of truth for the SupplyForge AWS staging environment.
It adopts the VPC, subnets, NAT gateways, S3 data lake, ECR, SQS, EventBridge,
ECS cluster, and Redis that already exist. It then creates the missing secure
runtime resources: RDS MySQL, runtime roles, managed secrets, task definitions,
ECS services, CloudWatch logs, audit trail, and a monthly budget.

No AWS access key is written to this repository. Terraform and the helper
scripts use the local `supplyforge-dev` AWS IAM Identity Center profile.

## Cost Model

The default variables intentionally create **zero running Fargate tasks**.
RDS, Redis, and NAT gateways are still billable after the first apply.

| Command | Effect | Billing left running |
|---|---|---|
| `bash scripts/down.sh` | API/worker to zero, requests RDS stop, removes Redis/NAT | S3, ECR, RDS storage, logs |
| `bash scripts/deploy-frontend.sh` | Builds Angular and deploys it to private S3 + CloudFront | Static asset storage and actual CloudFront traffic only |
| `bash scripts/remove-frontend.sh` | Deletes CloudFront, static assets and its CodeBuild project | Does not touch data buckets, ECR, or RDS storage |
| `bash scripts/up.sh` | Recreates NAT if needed, starts RDS, API=1, worker=1 | All staging services |

Redis cannot be paused. `terraform apply -var='redis_enabled=false'` destroys
it and loses queued Celery jobs and cached data. RDS has `prevent_destroy` and
deletion protection; it is intentionally stopped with AWS CLI, not destroyed.

## Frontend Hosting

The Angular frontend is hosted independently of ECS on a private S3 bucket,
served only through CloudFront Origin Access Control. It uses CloudFront's
default `https://*.cloudfront.net` address, so a domain and ACM certificate
are not required. Its production API URL remains Render.

Deploy it after committing the frontend changes:

```bash
cd infra/terraform
bash scripts/deploy-frontend.sh
```

The script creates the hosting resources if needed, builds remotely through
CodeBuild, uploads only generated `dist/frontend` assets, invalidates the
CloudFront cache, and prints the HTTPS URL. It does not start ECS, RDS, Redis,
or NAT. Source archives expire after 14 days; replaced frontend asset versions
expire after 7 days.

To remove every frontend-hosting resource and its static files:

```bash
cd infra/terraform
bash scripts/remove-frontend.sh
```

CloudFront has no fixed monthly instance charge, but requests and transferred
bytes are billed. S3 bills for stored assets. Removing frontend hosting stops
those charges; it never deletes the raw/lake/ml buckets, ECR images, database
storage, Terraform state, audit trail, or their retained logs. `up.sh` and
`down.sh` preserve the current frontend state, so they do not recreate hosting
after `remove-frontend.sh`.

## First Adoption

Run these commands from the repository root. They use no console UI.

```bash
export PATH="$HOME/.local/bin:$PATH"
aws sso login --profile supplyforge-dev

cd infra/terraform/bootstrap
terraform init
terraform apply

cd ..
bash scripts/deploy.sh
```

The final command only runs `plan`. Check that it says it will **create** a
new RDS `sf-staging-mysql`, Terraform-owned task definitions/roles/security
groups, and audit/budget resources. It must not show destruction of S3 data,
Redis, VPC, subnets, NAT, or queues.

If the plan contains an unexpected destroy, stop and inspect it. Do not use
`terraform apply -auto-approve` for the first adoption.

When the plan is correct:

```bash
APPLY=1 bash scripts/deploy.sh
```

AWS Budget will send one subscription-confirmation email to
`ndaitung28092005@gmail.com`. Confirming that email is required for alerts.

## First Release

The first apply leaves ECS at zero. Create the schema once, then start services:

```bash
cd infra/terraform
bash scripts/migrate.sh
bash scripts/up.sh
```

`migrate.sh` exits non-zero if the one-off Fargate task fails. Its runtime logs
are in `/ecs/sf-staging/api`; never run the services if migration does not
finish with exit code `0`.

## Updating an Image

Build and push an immutable ECR tag, then use it in the same declarative flow:

```bash
cd infra/terraform
terraform apply -var='backend_image_tag=staging-002'
```

Terraform registers a new API/worker task-definition revision and deploys it
through ECS. Do not edit an ECS task definition in the console.

## Public API

The initial stack does not expose an internet-facing endpoint. This prevents an
accidental HTTP-only deployment. After an ACM certificate exists, use:

```bash
terraform apply \
  -var='enable_public_api=true' \
  -var='acm_certificate_arn=arn:aws:acm:ap-southeast-1:ACCOUNT:certificate/ID' \
  -var='additional_allowed_hosts=["api-staging.example.com"]' \
  -var='cors_allowed_origins=["https://app-staging.example.com"]'
```

The ALB only accepts HTTPS, forwards to private tasks on port `8080`, and its
DNS name is automatically added to Django's host allowlist.

## State and Secrets

`bootstrap/` creates `supplyforce-410244642625-tfstate`, encrypted, versioned,
and private. The main stack uses S3 native state locking. The generated Django
key is marked sensitive but exists in Terraform state, so access to that state
bucket must remain restricted to deployment administrators. RDS uses AWS
managed master-password storage; password values are never printed by outputs.

Existing manual secrets `sf/staging/backend` and
`sf/staging/mysql-password` are not referenced by the new task definition.
Leave them untouched until the Terraform-created task has passed migrations,
then remove those legacy secrets with a reviewed change rather than the UI.
