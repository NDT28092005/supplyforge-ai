import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = (__ENV.BASE_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');
const TARGET_RPS = Math.max(1, Number(__ENV.TARGET_RPS || 20));
const PREALLOCATED_VUS = Math.max(1, Number(__ENV.PREALLOCATED_VUS || 30));
const MAX_VUS = Math.max(PREALLOCATED_VUS, Number(__ENV.MAX_VUS || 150));

// Prevent accidental load against a shared environment. Override only after an
// explicit review of the target and test window.
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(BASE_URL)
    && __ENV.ALLOW_NON_LOCAL !== 'true') {
  throw new Error(
    'BASE_URL must be localhost/127.0.0.1. Set ALLOW_NON_LOCAL=true only for an approved isolated environment.',
  );
}

export const options = {
  scenarios: {
    business_read_flow: {
      executor: 'ramping-arrival-rate',
      startRate: 1,
      timeUnit: '1s',
      preAllocatedVUs: PREALLOCATED_VUS,
      maxVUs: MAX_VUS,
      gracefulStop: '20s',
      stages: [
        { target: Math.max(1, Math.ceil(TARGET_RPS * 0.25)), duration: '30s' },
        { target: Math.max(1, Math.ceil(TARGET_RPS * 0.60)), duration: '1m' },
        { target: TARGET_RPS, duration: '2m' },
        { target: TARGET_RPS, duration: '2m' },
        { target: 0, duration: '30s' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<800', 'p(99)<1500'],
    checks: ['rate>0.99'],
  },
};

function jsonHeaders(token) {
  return {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
  };
}

export function setup() {
  if (__ENV.SF_TOKEN) {
    return { token: __ENV.SF_TOKEN };
  }

  if (!__ENV.SF_EMAIL || !__ENV.SF_PASSWORD) {
    throw new Error('Set SF_TOKEN, or both SF_EMAIL and SF_PASSWORD for the local test account.');
  }

  const response = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: __ENV.SF_EMAIL, password: __ENV.SF_PASSWORD }),
    { headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, tags: { endpoint: 'login' } },
  );
  const loginOk = check(response, {
    'login returned 200': (res) => res.status === 200,
    'login returned access token': (res) => Boolean(res.json('access_token')),
  });
  if (!loginOk) {
    throw new Error(`Could not authenticate load-test user (HTTP ${response.status}).`);
  }
  return { token: response.json('access_token') };
}

function get(path, token, endpoint) {
  const response = http.get(`${BASE_URL}${path}`, {
    ...jsonHeaders(token),
    tags: { endpoint },
  });
  check(response, {
    [`${endpoint}: status is 200`]: (res) => res.status === 200,
    [`${endpoint}: JSON response`]: (res) => (res.headers['Content-Type'] || '').includes('application/json'),
  });
}

export default function (data) {
  // Read-only paths only: this test never uploads, refreshes a cache, retries
  // a job, changes a decision, or calls a model pipeline.
  get('/api/v2/query/dashboard-summary', data.token, 'dashboard_summary');
  get('/api/v1/risk/assessments/list?limit=50&offset=0', data.token, 'risk_assessment_list');
  get('/api/v2/jobs/?active_only=true', data.token, 'active_jobs');
  sleep(Math.random() * 0.4 + 0.1);
}
