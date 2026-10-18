#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
REPOSITORY_ROOT="$(git rev-parse --show-toplevel)"

image_tag="${1:-staging-$(date -u +%Y%m%d%H%M%S)}"

if ! git -C "$REPOSITORY_ROOT" diff --quiet -- backend src .dockerignore; then
  printf '%s\n' 'Commit backend, src, and .dockerignore changes before building so the source archive is reproducible.' >&2
  exit 1
fi

mapfile -t build_context < <(terraform output -json | node -e '
  let input = "";
  process.stdin.on("data", (chunk) => { input += chunk; });
  process.stdin.on("end", () => {
    const output = JSON.parse(input);
    console.log(output.image_builder_project_name.value);
    console.log(output.image_builder_source_bucket.value);
    console.log(output.image_builder_source_key.value);
    console.log(output.staging.value.ecr_repository);
  });
')

project_name="${build_context[0]}"
source_bucket="${build_context[1]}"
source_key="${build_context[2]}"
ecr_repository="${build_context[3]}"
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
  --environment-variables-override "name=IMAGE_TAG,value=$image_tag,type=PLAINTEXT" \
  --query 'build.id' \
  --output text)"

printf 'Build started: %s\n' "$build_id"

while :; do
  status="$(aws codebuild batch-get-builds \
    --profile supplyforge-dev \
    --region ap-southeast-1 \
    --ids "$build_id" \
    --query 'builds[0].buildStatus' \
    --output text)"

  case "$status" in
    SUCCEEDED)
      printf 'Image pushed: %s:%s\n' "$ecr_repository" "$image_tag"
      exit 0
      ;;
    FAILED|FAULT|STOPPED|TIMED_OUT)
      printf 'Image build ended with status %s. Review /aws/codebuild/sf-staging-image-builder.\n' "$status" >&2
      exit 1
      ;;
  esac

  sleep 10
done
