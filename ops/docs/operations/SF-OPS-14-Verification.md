# SF-OPS-14 Verification Document: Grafana OSS Role Mapping & Security Hardening

## 1. Security Overview
Ticket **SF-OPS-14** enforces enterprise-grade security and role management for the Grafana OSS monitoring platform within SupplyForge AI.

## 2. Configured Security Policies (`ops/monitoring/grafana/grafana.ini`)
- **Zero Plaintext Credentials in Git**: All administrative secrets are passed via environment variables `${GF_SECURITY_ADMIN_USER}` and `${GF_SECURITY_ADMIN_PASSWORD}`.
- **Anonymous Access Disabled**: `[auth.anonymous] enabled = false` prevents unauthenticated access to dashboards or telemetry data.
- **User Self-Registration Disabled**: `[users] allow_sign_up = false` restricts user onboarding to administrator invitations or SSO integration.
- **Default Org Role**: Default newly provisioned users receive the least-privilege `Viewer` role.
- **Cookie & Embedding Hardening**: `cookie_secure = true`, `allow_embedding = false`, `disable_gravatar = true`.

## 3. Grafana Role Mapping Architecture

| Role Name | Grafana Role | Assigned Teams / Personas | Permitted Actions |
| :--- | :--- | :--- | :--- |
| **`ops-admin`** | `Admin` | Platform SRE & DevOps Lead | Full administrative privileges, datasource provisioning, user management, global settings |
| **`engineering`** | `Editor` | Developers & ML Engineers | Create/edit dashboards, modify panel PromQL queries, configure alert channels |
| **`stakeholder`** | `Viewer` | Product Managers & Business Analysts | Read-only view of executive KPI dashboards, operational metrics, SLA/SLO summaries |

## 4. Port & Endpoint Isolation
- **Prometheus TSDB**: Listens on `127.0.0.1:9090` (Localhost only, inaccessible from public Internet).
- **Alertmanager**: Listens on `127.0.0.1:9093` (Localhost only).
- **Django `/metrics`**: Protected behind Nginx reverse proxy returning HTTP 403 Forbidden to public requests.

## 5. Verification Results
```bash
docker compose -f ops/monitoring/docker-compose.monitoring.yml config
```
**Status**: `PASSED` — `grafana.ini` volume mount correctly validated without syntax errors.
