#!/usr/bin/env bash
set -eo pipefail

echo "======================================================"
echo "SupplyForge AI Observability Plane Validation Script"
echo "======================================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${ROOT_DIR}"

echo "[1/5] Validating Prometheus YAML Configuration & Rules..."
docker run --rm --entrypoint promtool -v "${ROOT_DIR}/ops/monitoring/prometheus:/etc/prometheus" prom/prometheus:v2.51.0 check config /etc/prometheus/prometheus.yml

echo ""
echo "[2/5] Validating Alertmanager Configuration..."
docker run --rm --entrypoint amtool -v "${ROOT_DIR}/ops/monitoring/alertmanager:/etc/alertmanager" prom/alertmanager:v0.27.0 check-config /etc/alertmanager/alertmanager.yml

echo ""
echo "[3/5] Validating Docker Compose Topology Config..."
docker compose -f ops/monitoring/docker-compose.monitoring.yml config > /dev/null

echo ""
echo "[4/5] Validating Grafana Provisioned Dashboards JSON Syntax..."
python3 -c "
import json, glob
dashboards = glob.glob('ops/monitoring/grafana/dashboards/*.json')
assert len(dashboards) >= 7, f'Expected at least 7 dashboards, found {len(dashboards)}'
for path in sorted(dashboards):
    with open(path) as f:
        data = json.load(f)
        assert 'title' in data, f'Missing title in {path}'
        assert 'panels' in data, f'Missing panels in {path}'
print(f'  SUCCESS: {len(dashboards)} Grafana JSON dashboards validated.')
"

echo ""
echo "[5/5] Running Observability Telemetry Unit Tests..."
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/supplyforge-matplotlib}"
mkdir -p "${MPLCONFIGDIR}"
if [ -f "${ROOT_DIR}/backend/.venv/bin/python" ]; then
    ${ROOT_DIR}/backend/.venv/bin/python backend/manage.py test \
        supplyforge.tests.test_metrics \
        supplyforge.tests.test_business_metrics_collector \
        --noinput
else
    python3 backend/manage.py test \
        supplyforge.tests.test_metrics \
        supplyforge.tests.test_business_metrics_collector \
        --noinput
fi

echo ""
echo "======================================================"
echo "ALL OBSERVABILITY PLANE VALIDATION CHECKS PASSED!"
echo "======================================================"
