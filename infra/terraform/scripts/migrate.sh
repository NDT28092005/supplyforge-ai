#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Reading remote state is relatively slow. Fetch all non-secret task settings
# once, rather than holding four separate state-lock reads before run-task.
mapfile -t task_context < <(terraform output -json | node -e '
  let input = "";
  process.stdin.on("data", (chunk) => { input += chunk; });
  process.stdin.on("end", () => {
    const output = JSON.parse(input);
    console.log(output.ecs_cluster_name.value);
    console.log(output.api_task_definition_arn.value);
    console.log(output.private_app_subnet_ids.value.join(","));
    console.log(output.api_security_group_id.value);
  });
')

cluster="${task_context[0]}"
task_definition="${task_context[1]}"
subnets="${task_context[2]}"
security_group="${task_context[3]}"

task_arn="$(aws ecs run-task \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --cluster "$cluster" \
  --launch-type FARGATE \
  --task-definition "$task_definition" \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$security_group],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"api","command":["python","manage.py","migrate","--noinput"]}]}' \
  --query 'tasks[0].taskArn' \
  --output text)"

if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
  printf '%s\n' 'ECS did not start the migration task. Inspect the RunTask response in CloudTrail.' >&2
  exit 1
fi

printf 'Waiting for migration task: %s\n' "$task_arn"
aws ecs wait tasks-stopped \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --cluster "$cluster" \
  --tasks "$task_arn"

exit_code="$(aws ecs describe-tasks \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --cluster "$cluster" \
  --tasks "$task_arn" \
  --query 'tasks[0].containers[?name==`api`].exitCode | [0]' \
  --output text)"

if [[ "$exit_code" != "0" ]]; then
  printf 'Migration failed with exit code %s. Review /ecs/sf-staging/api in CloudWatch.\n' "$exit_code" >&2
  exit 1
fi

printf '%s\n' 'Migration completed successfully.'
