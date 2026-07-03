# Trace Test API

A Node.js + Express + MongoDB server built for testing distributed tracing, HTTP status codes, and slow query debugging.

## Quick start

### Option A — in-memory MongoDB (zero setup)

```bash
npm install
npm run start:memory   # auto-seeds on first run
```

### Option B — real MongoDB

```bash
docker compose up -d   # or use your own MongoDB instance
npm install
cp .env.example .env
npm run seed
npm run dev
```

Server runs at `http://localhost:3000`.

## Endpoints

### Status codes (no DB)

| Endpoint | Status |
|---|---|
| `GET /api/status/200` | 200 OK |
| `GET /api/status/201` | 201 Created |
| `GET /api/status/204` | 204 No Content |
| `GET /api/status/400` | 400 Bad Request |
| `GET /api/status/401` | 401 Unauthorized |
| `GET /api/status/403` | 403 Forbidden |
| `GET /api/status/404` | 404 Not Found |
| `GET /api/status/409` | 409 Conflict |
| `GET /api/status/422` | 422 Unprocessable |
| `GET /api/status/429` | 429 Rate Limited |
| `GET /api/status/500` | 500 Internal Error |
| `GET /api/status/503` | 503 Unavailable |

### Response time control

| Endpoint | Description |
|---|---|
| `GET /api/delay/500` | Fixed 500ms delay |
| `GET /api/delay/random` | Random 100–3100ms delay |

### MongoDB endpoints (for query tracing)

| Endpoint | What it does |
|---|---|
| `GET /api/users` | Fast indexed find |
| `GET /api/users/slow` | Slow regex scan + sort |
| `GET /api/users/:id` | Find by ID (404 if missing) |
| `POST /api/users` | Create user (201 / 409 duplicate) |
| `GET /api/users/search/by-role/:role` | Aggregation |
| `GET /api/products` | Filtered find with sort |
| `GET /api/products/slow/aggregation` | Full collection aggregation |
| `GET /api/orders` | Populate (multiple queries) |
| `GET /api/orders/slow` | `$lookup` aggregation join |
| `GET /api/dashboard` | Chained parallel + serial queries |
| `GET /api/crash` | Throws 500 error |

## Logging & timing

Every response includes an `X-Response-Time` header, and the console logs:

- `[http]` — request/response timing
- `[timing]` — per-route handler timing
- `[mongo]` — raw MongoDB queries (mongoose debug mode)

See [`TRACE_VERIFICATION.md`](TRACE_VERIFICATION.md) for expected durations and DB call counts.

## Example curl commands

```bash
# Fast health check
curl http://localhost:3000/api/health

# Status codes
curl -w "\n%{http_code}\n" http://localhost:3000/api/status/404

# Artificial delay
curl -w "\nTime: %{time_total}s\n" http://localhost:3000/api/delay/2000

# Slow MongoDB query
curl http://localhost:3000/api/users/slow

# Multi-query dashboard
curl http://localhost:3000/api/dashboard

# Create a user
curl -X POST http://localhost:3000/api/users \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice","email":"alice@example.com"}'
```
