#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

terraform init

terraform fmt -check
terraform validate
terraform plan -out=tfplan

if [[ "${APPLY:-0}" == "1" ]]; then
  terraform apply tfplan
else
  printf '%s\n' 'Plan only. Re-run with APPLY=1 after reviewing the plan.'
fi
