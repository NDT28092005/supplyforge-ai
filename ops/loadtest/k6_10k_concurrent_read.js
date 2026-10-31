import http from 'k6/http';
import { check, sleep } from 'k6';

// This profile models signed-in analysts viewing their portfolio. It is
// intentionally read-only: imports, syncs, exports and action updates are
// exercised in separate, much smaller workflow tests.
const BASE_URL = (__ENV.BASE_URL || '').replace(/\/$/, '');
const VUS = Math.max(1, Number(__ENV.VUS || 10000));
const TOKEN_FILE = __ENV.TOKEN_FILE || './tokens.example.json';
const THINK_TIME_SECONDS = Math.max(1, Number(__ENV.THINK_TIME_SECONDS || 30));
const REQUIRE_UNIQUE_TOKENS = __ENV.REQUIRE_UNIQUE_TOKENS !== 'false';
const rawTokens = open(TOKEN_FILE);

function parseTokenPool(raw) {
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    throw new Error('TOKEN_FILE must contain a JSON array of bearer tokens or { access_token } entries.');
  }
  const tokens = parsed.map((entry) => (
    typeof entry === 'string' ? entry : entry?.access_token || entry?.token
  )).filter(Boolean);
  if (!tokens.length || tokens.some((token) => token.includes('replace-with'))) {
    throw new Error('TOKEN_FILE has no usable bearer tokens. Never commit real tokens.');
  }
  return tokens;
}

const TOKENS = parseTokenPool(rawTokens);

if (!BASE_URL) {
  throw new Error('BASE_URL is required. Use an approved isolated test environment, never production.');
}
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(BASE_URL) && __ENV.ALLOW_NON_LOCAL !== 'true') {
  throw new Error('Set ALLOW_NON_LOCAL=true only after approving an isolated non-production target.');
}
if (__ENV.ALLOW_LARGE_TEST !== 'true') {
  throw new Error('Set ALLOW_LARGE_TEST=true after confirming capacity, monitoring and an approved test window.');
}
if (REQUIRE_UNIQUE_TOKENS && TOKENS.length < VUS) {
  throw new Error(`Expected at least ${VUS} unique tokens; received ${TOKENS.length}. Set REQUIRE_UNIQUE_TOKENS=false only for a session-concurrency test, not a 10,000-user claim.`);
}

export const options = {
  discardResponseBodies: true,
  scenarios: {
    concurrent_business_readers: {
      executor: 'ramping-vus',
      startVUs: 0,
      gracefulRampDown: '1m',
      gracefulStop: '1m',
      stages: [
        { target: Math.min(500, VUS), duration: '1m' },
        { target: Math.min(2000, VUS), duration: '4m' },
        { target: Math.min(5000, VUS), duration: '5m' },
        { target: VUS, duration: '10m' },
        { target: VUS, duration: '15m' },
        { target: 0, duration: '5m' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<800', 'p(99)<1500'],
    checks: ['rate>0.99'],
    'http_req_duration{endpoint:dashboard_summary}': ['p(95)<700'],
    'http_req_duration{endpoint:risk_list}': ['p(95)<800'],
    'http_req_duration{endpoint:action_queue}': ['p(95)<800'],
  },
};

function get(path, token, endpoint) {
  const response = http.get(`${BASE_URL}${path}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
    tags: { endpoint },
  });
  check(response, {
    [`${endpoint}: status is 200`]: (res) => res.status === 200,
    [`${endpoint}: JSON response`]: (res) => (res.headers['Content-Type'] || '').includes('application/json'),
  });
}

export default function () {
  // A stable VU-to-token assignment avoids sharing a session between virtual
  // users and still permits the token pool to be larger than the VU count.
  const token = TOKENS[(__VU - 1) % TOKENS.length];
  get('/api/v2/query/dashboard-summary', token, 'dashboard_summary');
  get('/api/v1/risk/assessments/list?limit=50&offset=0', token, 'risk_list');
  get('/api/v1/action-plans/?page=1&page_size=25', token, 'action_queue');
  sleep(THINK_TIME_SECONDS * (0.8 + Math.random() * 0.4));
}
