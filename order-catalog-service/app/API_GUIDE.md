# Trace Test API — Usage Guide

Base URL: `http://localhost:3000`

Import the Postman collection from [`postman/Trace-Test-API.postman_collection.json`](postman/Trace-Test-API.postman_collection.json).

**Trace verification checklist:** [`TRACE_VERIFICATION.md`](TRACE_VERIFICATION.md) — expected durations, DB span counts, and pass/fail criteria for your tracing tool.

---

## 1. Register a user

**Endpoint:** `POST /api/auth/register`

**Request body:**
```json
{
  "name": "Alice",
  "email": "alice@example.com",
  "password": "secret123"
}
```

**Success response:** `201 Created`
```json
{
  "message": "User registered successfully",
  "data": {
    "id": "665f1a2b3c4d5e6f7a8b9c0d",
    "name": "Alice",
    "email": "alice@example.com",
    "role": "user"
  },
  "token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Common errors:**

| Status | When |
|--------|------|
| `400` | Missing `name`, `email`, or `password`, or password shorter than 6 chars |
| `409` | Email already registered |

**curl:**
```bash
curl -X POST http://localhost:3000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice","email":"alice@example.com","password":"secret123"}'
```

> **Note:** Seeded users (`user1@example.com` … `user200@example.com`) do **not** have passwords and cannot log in. Always register a new user for the auth flow.

---

## 2. Login

**Endpoint:** `POST /api/auth/login`

**Request body:**
```json
{
  "email": "alice@example.com",
  "password": "secret123"
}
```

**Success response:** `200 OK`
```json
{
  "message": "Login successful",
  "data": {
    "id": "665f1a2b3c4d5e6f7a8b9c0d",
    "name": "Alice",
    "email": "alice@example.com",
    "role": "user"
  },
  "token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Common errors:**

| Status | When |
|--------|------|
| `400` | Missing `email` or `password` |
| `401` | Wrong email or password |

**curl:**
```bash
curl -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"secret123"}'
```

---

## 3. Use the token (optional)

**Endpoint:** `GET /api/auth/me`

**Header:** `Authorization: Bearer <token>`

Returns the logged-in user's profile. Use this to verify login worked.

```bash
curl http://localhost:3000/api/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

The Postman collection auto-saves `token` and `userId` after register/login.

---

## 4. Expected response times (verify your traces)

**Three ways to check timing:**

1. **`X-Response-Time` header** — actual measured time on every response (e.g. `X-Response-Time: 312ms`)
2. **`timing` field in response body** — on slow/delay endpoints, shows expected vs actual
3. **`GET /api/timing-reference`** — full table of all endpoints and expected times

```bash
curl http://localhost:3000/api/timing-reference
```

### Complete timing reference

| Endpoint | Status | Expected time | Artificial delay | DB calls | Notes |
|----------|--------|---------------|------------------|----------|-------|
| `GET /api/health` | 200 | **< 10 ms** | 0 ms | 0 | No database |
| `POST /api/auth/register` | 201 | **50–150 ms** | 0 ms | 1 | bcrypt + DB insert |
| `POST /api/auth/login` | 200 | **50–150 ms** | 0 ms | 1 | bcrypt + DB lookup |
| `GET /api/auth/me` | 200 | **10–50 ms** | 0 ms | 1 | JWT + DB lookup |
| `GET /api/status/*` | varies | **< 5 ms** | 0 ms | 0 | Instant JSON |
| `GET /api/delay/500` | 200 | **= 500 ms** | 500 ms | 0 | Exact — matches URL param |
| `GET /api/delay/2000` | 200 | **= 2000 ms** | 2000 ms | 0 | Exact — matches URL param |
| `GET /api/delay/random` | 200 | **100–3100 ms** | random | 0 | Check `delayed` field in body |
| `GET /api/users` | 200 | **10–50 ms** | 0 ms | 1 | Fast indexed find |
| `GET /api/users/:id` | 200/404 | **5–30 ms** | 0 ms | 1 | Fast findById |
| `GET /api/products` | 200 | **10–50 ms** | 0 ms | 1 | Fast indexed find |
| `GET /api/orders` | 200 | **30–100 ms** | 0 ms | **3** | Find + 2× populate |
| `GET /api/users/slow` | 200 | **220–350 ms** | **200 ms** | 1 | + regex scan + sort |
| `GET /api/products/slow/aggregation` | 200 | **320–500 ms** | **300 ms** | 1 | + full $group aggregation |
| `GET /api/orders/slow` | 200 | **170–300 ms** | **150 ms** | 1* | + $lookup joins |
| `GET /api/dashboard` | 200 | **150–300 ms** | **100 ms** | **5** | 3 parallel + aggregation |
| `POST /api/orders` | 201 | **20–80 ms** | 0 ms | **2** | findById + create |
| `GET /api/status/500` | 500 | **< 5 ms** | 0 ms | 0 | Controlled error |
| `GET /api/crash` | 500 | **< 10 ms** | 0 ms | 0 | Unhandled exception |

> See **Section 5** for full breakdown of multi-DB endpoints.

> **How to verify:** Call an endpoint, read `X-Response-Time` header, and confirm it falls within the `Expected time` range. For delay endpoints, it should match exactly (±10 ms overhead).

### Example — slow endpoint response

```json
{
  "count": 200,
  "data": [...],
  "timing": {
    "expectedMs": "220–350",
    "artificialDelayMs": 200,
    "notes": "200ms sleep + regex scan + sort",
    "verifyWith": "Compare X-Response-Time header against expectedMs"
  }
}
```

### APIs that simulate higher response time

These endpoints are intentionally slow so you can test trace latency and MongoDB query timing.

### Artificial delay (no database)

| Endpoint | Typical time | Description |
|----------|-------------|-------------|
| `GET /api/delay/500` | **500 ms** (configurable) | Fixed delay — change `500` to any ms up to 30000 |
| `GET /api/delay/2000` | **2000 ms** | 2-second delay |
| `GET /api/delay/random` | **100–3100 ms** | Random delay each call |

### Slow MongoDB queries

| Endpoint | Typical time | Why it's slow |
|----------|-------------|---------------|
| `GET /api/users/slow` | **200 ms+** | Artificial 200 ms sleep + regex scan without index + sort |
| `GET /api/products/slow/aggregation` | **300 ms+** | Artificial 300 ms sleep + full collection `$group` aggregation |
| `GET /api/orders/slow` | **150 ms+** | Artificial 150 ms sleep + `$lookup` join across collections |
| `GET /api/dashboard` | **100 ms+** | Multiple parallel queries + serial aggregation + 100 ms sleep |

### Fast endpoints (for comparison)

| Endpoint | Typical time | Description |
|----------|-------------|-------------|
| `GET /api/health` | **< 5 ms** | No DB |
| `GET /api/users` | **< 50 ms** | Indexed find, limit 50 |
| `GET /api/products` | **< 50 ms** | Indexed find with optional filters |
| `GET /api/orders` | **< 100 ms** | Populate (a few queries, but indexed) |

Every timed response includes an `X-Response-Time` header (e.g. `X-Response-Time: 312ms`).

---

## 5. APIs with multiple database calls

Some endpoints hit MongoDB more than once. Use these to test traces where you need to see **separate spans per query**.

### Summary

| Endpoint | DB calls | Execution | Queries |
|----------|----------|-----------|---------|
| `GET /api/dashboard` | **5** | 3 parallel → sleep → 1 serial | See breakdown below |
| `GET /api/orders` | **3** | Sequential (Mongoose populate) | See breakdown below |
| `POST /api/orders` | **2** | Sequential | See breakdown below |
| `GET /api/orders/slow` | **1*** | Single aggregation | 2× `$lookup` joins inside one pipeline |

\* `GET /api/orders/slow` is **one** MongoDB round-trip, but the aggregation internally joins 3 collections via `$lookup`. Your tracer may show one span or multiple depending on instrumentation.

### `GET /api/dashboard` — 5 DB calls (best for multi-span testing)

```
Step 1 (parallel):
  ├── User.countDocuments({ active: true })     → Query 1
  ├── Product.countDocuments()                  → Query 2
  └── Order.find().populate('userId')           → Query 3 + populate sub-query

Step 2: sleep(100ms)

Step 3 (serial):
  └── Product.aggregate($group, $sort)          → Query 4
```

**Expected time:** 150–300 ms | **Artificial delay:** 100 ms

### `GET /api/orders` — 3 DB calls (populate pattern)

```
Step 1: Order.find().sort().limit(20)           → Query 1 (orders)
Step 2: User.find({ _id: { $in: [...] } })      → Query 2 (populate users)
Step 3: Product.find({ _id: { $in: [...] } })  → Query 3 (populate products)
```

**Expected time:** 30–100 ms | **Artificial delay:** 0 ms

### `POST /api/orders` — 2 DB calls (sequential write)

```
Step 1: User.findById(userId)                   → Query 1 (validate user)
Step 2: Order.create({ ... })                   → Query 2 (insert order)
```

**Expected time:** 20–80 ms | **Artificial delay:** 0 ms

### `GET /api/orders/slow` — 1 DB call with internal joins

```
Single aggregation pipeline:
  Order.aggregate([
    $lookup → users collection
    $lookup → products collection
    $unwind, $match, $project, $limit
  ])
```

**Expected time:** 170–300 ms | **Artificial delay:** 150 ms

### Single DB call endpoints (baseline for comparison)

| Endpoint | DB calls | Query |
|----------|----------|-------|
| `GET /api/users` | 1 | `User.find()` |
| `GET /api/users/:id` | 1 | `User.findById()` |
| `GET /api/users/slow` | 1 | `User.find()` with regex |
| `GET /api/products` | 1 | `Product.find()` |
| `GET /api/products/slow/aggregation` | 1 | `Product.aggregate()` |
| `GET /api/users/search/by-role/:role` | 1 | `User.aggregate()` |
| `POST /api/auth/register` | 1 | `User.create()` |
| `POST /api/auth/login` | 1 | `User.findOne()` |
| `GET /api/auth/me` | 1 | `User.findById()` |

### No database

All `/api/status/*`, `/api/delay/*`, `/api/health`, and `/api/crash` endpoints do **not** call MongoDB.

```bash
# View multi-DB endpoints programmatically
curl http://localhost:3000/api/timing-reference | jq '.multiDbEndpoints'
```

---

## 6. APIs that return 500 (server error)

| Endpoint | Status | How the error is triggered |
|----------|--------|---------------------------|
| `GET /api/status/500` | **500** | Returns a JSON error response directly (controlled) |
| `GET /api/crash` | **500** | Throws an unhandled exception (simulates real crash) |

### Other error status codes (not 500)

| Endpoint | Status | Use case |
|----------|--------|----------|
| `GET /api/status/400` | 400 | Bad request |
| `GET /api/status/401` | 401 | Unauthorized |
| `GET /api/status/403` | 403 | Forbidden |
| `GET /api/status/404` | 404 | Not found |
| `GET /api/status/409` | 409 | Conflict |
| `GET /api/status/422` | 422 | Validation error |
| `GET /api/status/429` | 429 | Rate limited |
| `GET /api/status/503` | 503 | Service unavailable |
| `GET /api/users/:id` | 404 | User ID does not exist |
| `POST /api/auth/login` | 401 | Wrong credentials |
| `POST /api/auth/register` | 409 | Duplicate email |

---

## 7. Recommended trace testing flow

1. **Register** → `POST /api/auth/register`
2. **Login** → `POST /api/auth/login` (save token)
3. **Fast baseline** → `GET /api/health`
4. **Slow delay** → `GET /api/delay/2000`
5. **Slow DB query** → `GET /api/users/slow`
6. **Multi-query** → `GET /api/dashboard` (5 DB calls)
7. **Populate pattern** → `GET /api/orders` (3 DB calls)
8. **Controlled 500** → `GET /api/status/500`
9. **Crash 500** → `GET /api/crash`

Compare traces between:
- **Single query:** `GET /api/users` (1 DB call)
- **Multi query:** `GET /api/dashboard` (5 DB calls)
- **Slow single query:** `GET /api/users/slow` (1 DB call, but slow)

---

## 8. Start the server

```bash
# In-memory MongoDB (quickest)
npm run start:memory

# Real MongoDB
docker compose up -d
npm run seed
npm run dev
```
