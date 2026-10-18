#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Kept as a backwards-compatible alias for the cost-safe stop command.
exec bash "$ROOT_DIR/scripts/down.sh"
