'use strict';

/**
 * Single source of truth for expected API response times.
 * Used by /api/timing-reference and included in slow endpoint responses.
 */
const TIMING_REFERENCE = [
  { category: 'Health', method: 'GET', path: '/api/health', status: 200, expectedMs: '< 10', artificialDelayMs: 0, dbCalls: 0, notes: 'No database' },

  { category: 'Auth', method: 'POST', path: '/api/auth/register', status: 201, expectedMs: '50–150', artificialDelayMs: 0, dbCalls: 1, dbQueries: ['User.create'], notes: 'bcrypt hash + DB insert' },
  { category: 'Auth', method: 'POST', path: '/api/auth/login', status: 200, expectedMs: '50–150', artificialDelayMs: 0, dbCalls: 1, dbQueries: ['User.findOne'], notes: 'bcrypt compare + DB lookup' },
  { category: 'Auth', method: 'GET', path: '/api/auth/me', status: 200, expectedMs: '10–50', artificialDelayMs: 0, dbCalls: 1, dbQueries: ['User.findById'], notes: 'JWT verify + DB lookup' },

  { category: 'Status codes', method: 'GET', path: '/api/status/200', status: 200, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },
  { category: 'Status codes', method: 'GET', path: '/api/status/201', status: 201, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },
  { category: 'Status codes', method: 'GET', path: '/api/status/204', status: 204, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Empty body' },
  { category: 'Status codes', method: 'GET', path: '/api/status/400', status: 400, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },
  { category: 'Status codes', method: 'GET', path: '/api/status/401', status: 401, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },
  { category: 'Status codes', method: 'GET', path: '/api/status/403', status: 403, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },
  { category: 'Status codes', method: 'GET', path: '/api/status/404', status: 404, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },
  { category: 'Status codes', method: 'GET', path: '/api/status/409', status: 409, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },
  { category: 'Status codes', method: 'GET', path: '/api/status/422', status: 422, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },
  { category: 'Status codes', method: 'GET', path: '/api/status/429', status: 429, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },
  { category: 'Status codes', method: 'GET', path: '/api/status/500', status: 500, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Controlled 500 response' },
  { category: 'Status codes', method: 'GET', path: '/api/status/503', status: 503, expectedMs: '< 5', artificialDelayMs: 0, notes: 'Instant JSON' },

  { category: 'Artificial delay', method: 'GET', path: '/api/delay/:ms', status: 200, expectedMs: '= :ms', artificialDelayMs: 'param', notes: 'Exact delay matches URL param (max 30000)' },
  { category: 'Artificial delay', method: 'GET', path: '/api/delay/random', status: 200, expectedMs: '100–3100', artificialDelayMs: 'random', notes: 'Random sleep 100–3100ms; actual value in response body' },

  { category: 'Fast DB', method: 'GET', path: '/api/users', status: 200, expectedMs: '10–50', artificialDelayMs: 0, dbCalls: 1, dbQueries: ['User.find'], notes: 'Indexed find, limit 50' },
  { category: 'Fast DB', method: 'GET', path: '/api/users/:id', status: 200, expectedMs: '5–30', artificialDelayMs: 0, dbCalls: 1, dbQueries: ['User.findById'], notes: 'Indexed findById' },
  { category: 'Fast DB', method: 'GET', path: '/api/products', status: 200, expectedMs: '10–50', artificialDelayMs: 0, dbCalls: 1, dbQueries: ['Product.find'], notes: 'Indexed find, limit 100' },
  { category: 'Fast DB', method: 'GET', path: '/api/orders', status: 200, expectedMs: '30–100', artificialDelayMs: 0, dbCalls: 3, dbQueries: ['Order.find', 'User.find (populate)', 'Product.find (populate)'], notes: 'Find orders + 2 separate populate queries' },
  { category: 'Fast DB', method: 'GET', path: '/api/users/search/by-role/:role', status: 200, expectedMs: '20–80', artificialDelayMs: 0, dbCalls: 1, dbQueries: ['User.aggregate'], notes: 'Aggregation with $match + $group' },
  { category: 'Fast DB', method: 'POST', path: '/api/users', status: 201, expectedMs: '10–50', artificialDelayMs: 0, dbCalls: 1, dbQueries: ['User.create'], notes: 'Single insert' },
  { category: 'Fast DB', method: 'POST', path: '/api/orders', status: 201, expectedMs: '20–80', artificialDelayMs: 0, dbCalls: 2, dbQueries: ['User.findById', 'Order.create'], notes: 'Validate user exists, then insert order' },

  { category: 'Slow DB', method: 'GET', path: '/api/users/slow', status: 200, expectedMs: '220–350', artificialDelayMs: 200, dbCalls: 1, dbQueries: ['User.find (regex + sort)'], notes: '200ms sleep + regex scan + sort' },
  { category: 'Slow DB', method: 'GET', path: '/api/products/slow/aggregation', status: 200, expectedMs: '320–500', artificialDelayMs: 300, dbCalls: 1, dbQueries: ['Product.aggregate ($group + $sort)'], notes: '300ms sleep + full collection $group' },
  { category: 'Slow DB', method: 'GET', path: '/api/orders/slow', status: 200, expectedMs: '170–300', artificialDelayMs: 150, dbCalls: 1, dbQueries: ['Order.aggregate ($lookup users + $lookup products)'], notes: '150ms sleep + $lookup joins across 3 collections' },
  { category: 'Slow DB', method: 'GET', path: '/api/dashboard', status: 200, expectedMs: '150–300', artificialDelayMs: 100, dbCalls: 5, dbQueries: ['User.countDocuments', 'Product.countDocuments', 'Order.find + populate', 'Product.aggregate'], notes: '3 parallel queries, then 100ms sleep, then aggregation' },

  { category: 'Errors', method: 'GET', path: '/api/crash', status: 500, expectedMs: '< 10', artificialDelayMs: 0, notes: 'Unhandled exception' },
];

function timingMeta(path, artificialDelayMs, notes) {
  const entry = TIMING_REFERENCE.find((e) => e.path === path);
  return {
    expectedMs: entry?.expectedMs,
    artificialDelayMs,
    dbCalls: entry?.dbCalls ?? 0,
    dbQueries: entry?.dbQueries,
    notes: notes || entry?.notes,
    verifyWith: 'Compare X-Response-Time header against expectedMs',
  };
}

const MULTI_DB_ENDPOINTS = TIMING_REFERENCE.filter((e) => e.dbCalls > 1);

module.exports = { TIMING_REFERENCE, MULTI_DB_ENDPOINTS, timingMeta };
