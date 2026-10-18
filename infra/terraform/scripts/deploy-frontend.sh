#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
REPOSITORY_ROOT="$(git rev-parse --show-toplevel)"

if ! git -C "$REPOSITORY_ROOT" diff --quiet -- frontend buildspec.frontend.yml; then
  printf '%s\n' 'Commit frontend and buildspec.frontend.yml changes before deploying so the source archive is reproducible.' >&2
  exit 1
fi

# The frontend is independent from ECS/RDS. Provision it only when absent;
# ordinary asset releases must not refresh or wake the hibernated runtime.
frontend_url_json="$(terraform output -json frontend_url 2>/dev/null || printf 'null')"
if [[ "$frontend_url_json" == "null" ]]; then
  terraform apply -auto-approve -var='enable_frontend_hosting=true'
fi

mapfile -t build_context < <(terraform output -json | node -e '
  let input = "";
  process.stdin.on("data", (chunk) => { input += chunk; });
  process.stdin.on("end", () => {
    const output = JSON.parse(input);
    console.log(output.frontend_builder_project_name.value);
    console.log(output.image_builder_source_bucket.value);
    console.log(output.frontend_builder_source_key.value);
    console.log(output.frontend_url.value);
  });
')

project_name="${build_context[0]}"
source_bucket="${build_context[1]}"
source_key="${build_context[2]}"
frontend_url="${build_context[3]}"
archive_path="$(mktemp --suffix=.zip)"
trap 'rm -f "$archive_path"' EXIT

git -C "$REPOSITORY_ROOT" archive --format=zip --output "$archive_path" HEAD
aws s3 cp "$archive_path" "s3://${source_bucket}/${source_key}" \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --sse AES256 >/dev/null

build_id="$(aws codebuild start-build \
  --profile supplyforge-dev \
  --region ap-southeast-1 \
  --project-name "$project_name" \
  --query 'build.id' \
  --output text)"

printf 'Frontend build started: %s\n' "$build_id"

while :; do
  status="$(aws codebuild batch-get-builds \
    --profile supplyforge-dev \
    --region ap-southeast-1 \
    --ids "$build_id" \
    --query 'builds[0].buildStatus' \
    --output text)"

  case "$status" in
    SUCCEEDED)
      printf 'Frontend deployed: %s\n' "$frontend_url"
      exit 0
      ;;
    FAILED|FAULT|STOPPED|TIMED_OUT)
      printf 'Frontend build ended with status %s. Review /aws/codebuild/sf-staging-frontend-builder.\n' "$status" >&2
      exit 1
      ;;
  esac

  sleep 10
done
