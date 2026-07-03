# Trace Verification Guide

Use this document as a **checklist** when validating traces in your tracing tool (Jaeger, Tempo, Datadog, etc.).

For each API call, verify the items in the **Expected in trace** column match what you see.

**Cross-check sources:**
- `X-Response-Time` response header (actual measured time)
- `timing` field in response body (on slow/delay endpoints)
- `GET /api/timing-reference` (programmatic reference)

---

## How to read this doc

| Column | Meaning |
|--------|---------|
| **HTTP status** | Response code you should see |
| **Total duration** | Full request time (root span) |
| **DB spans** | Number of MongoDB spans expected |
| **MongoDB spans** | What each DB child span should represent |
| **Pass if** | Clear pass criteria for your trace tool |

> Durations have ±20% tolerance unless marked **exact**.

---

## 1. Per-endpoint verification

### Health & status codes (no database)

| Endpoint | HTTP status | Total duration | DB spans | Pass if |
|----------|-------------|----------------|----------|---------|
| `GET /api/health` | 200 | < 10 ms | **0** | 1 HTTP span only, no MongoDB children |
| `GET /api/status/200` | 200 | < 5 ms | **0** | Root span ~1–5 ms, status=200 |
| `GET /api/status/201` | 201 | < 5 ms | **0** | status=201 |
| `GET /api/status/204` | 204 | < 5 ms | **0** | status=204, empty body |
| `GET /api/status/400` | 400 | < 5 ms | **0** | status=400, span marked as error or 4xx |
| `GET /api/status/401` | 401 | < 5 ms | **0** | status=401 |
| `GET /api/status/403` | 403 | < 5 ms | **0** | status=403 |
| `GET /api/status/404` | 404 | < 5 ms | **0** | status=404 |
| `GET /api/status/409` | 409 | < 5 ms | **0** | status=409 |
| `GET /api/status/422` | 422 | < 5 ms | **0** | status=422 |
| `GET /api/status/429` | 429 | < 5 ms | **0** | status=429 |
| `GET /api/status/500` | 500 | < 5 ms | **0** | status=500, span marked as error |
| `GET /api/status/503` | 503 | < 5 ms | **0** | status=503 |
| `GET /api/crash` | 500 | < 10 ms | **0** | status=500, span has exception/error event |

---

### Artificial delay (no database)

| Endpoint | HTTP status | Total duration | DB spans | Pass if |
|----------|-------------|----------------|----------|---------|
| `GET /api/delay/500` | 200 | **= 500 ms (exact ±10 ms)** | **0** | Duration ≈ 500 ms, no DB spans, body has `"delayed": 500` |
| `GET /api/delay/2000` | 200 | **= 2000 ms (exact ±20 ms)** | **0** | Duration ≈ 2000 ms, no DB spans |
| `GET /api/delay/random` | 200 | **100–3100 ms** | **0** | Duration matches `delayed` field in body, no DB spans |

---

### Auth

| Endpoint | HTTP status | Total duration | DB spans | MongoDB spans | Pass if |
|----------|-------------|----------------|----------|---------------|---------|
| `POST /api/auth/register` | 201 | 50–150 ms | **1** | `insert` on `users` | 1 DB span (insert), returns token |
| `POST /api/auth/login` | 200 | 50–150 ms | **1** | `find` on `users` | 1 DB span (find), returns token |
| `GET /api/auth/me` | 200 | 10–50 ms | **1** | `find` on `users` by `_id` | 1 DB span, requires Bearer token |
| `POST /api/auth/login` (wrong password) | 401 | 50–150 ms | **1** | `find` on `users` | 1 DB span, status=401 |
| `POST /api/auth/register` (duplicate email) | 409 | 50–150 ms | **1** | `insert` fails | 1 DB span, status=409 |

---

### Fast database (single query)

| Endpoint | HTTP status | Total duration | DB spans | MongoDB spans | Pass if |
|----------|-------------|----------------|----------|---------------|---------|
| `GET /api/users` | 200 | 10–50 ms | **1** | `find` on `users` | 1 DB span, fast (< 50 ms total) |
| `GET /api/users/:id` | 200 | 5–30 ms | **1** | `find` by `_id` | 1 DB span |
| `GET /api/users/:id` (invalid) | 404 | 5–30 ms | **1** | `find` by `_id` | 1 DB span, status=404 |
| `GET /api/products` | 200 | 10–50 ms | **1** | `find` on `products` | 1 DB span |
| `GET /api/users/search/by-role/user` | 200 | 20–80 ms | **1** | `aggregate` on `users` | 1 DB span |
| `POST /api/users` | 201 | 10–50 ms | **1** | `insert` on `users` | 1 DB span |

---

### Slow database (single query + artificial sleep)

| Endpoint | HTTP status | Total duration | DB spans | Artificial delay | Pass if |
|----------|-------------|----------------|----------|------------------|---------|
| `GET /api/users/slow` | 200 | **220–350 ms** | **1** | 200 ms | Total ≥ 200 ms; 1 DB span slower than `GET /api/users` |
| `GET /api/products/slow/aggregation` | 200 | **320–500 ms** | **1** | 300 ms | Total ≥ 300 ms; 1 aggregate span on `products` |
| `GET /api/orders/slow` | 200 | **170–300 ms** | **1** | 150 ms | Total ≥ 150 ms; 1 aggregate span with `$lookup` |

**Compare:** `GET /api/users` (~20 ms) vs `GET /api/users/slow` (~250 ms) — same resource, ~10× slower trace.

---

### Multi-database endpoints

#### `GET /api/orders` — 3 DB spans

| | Expected |
|---|----------|
| **HTTP status** | 200 |
| **Total duration** | 30–100 ms |
| **DB spans** | **3** |
| **Span 1** | `find` on `orders` |
| **Span 2** | `find` on `users` (populate) |
| **Span 3** | `find` on `products` (populate) |
| **Pass if** | 3 separate MongoDB child spans under 1 HTTP span |

#### `POST /api/orders` — 2 DB spans (sequential)

| | Expected |
|---|----------|
| **HTTP status** | 201 (or 404 if bad userId) |
| **Total duration** | 20–80 ms |
| **DB spans** | **2** |
| **Span 1** | `find` on `users` (validate) |
| **Span 2** | `insert` on `orders` |
| **Pass if** | Spans are sequential (span 2 starts after span 1 ends) |

#### `GET /api/dashboard` — 5 DB spans (best multi-query test)

| | Expected |
|---|----------|
| **HTTP status** | 200 |
| **Total duration** | 150–300 ms |
| **DB spans** | **4–5** (depending on tracer populate handling) |
| **Artificial delay** | 100 ms between query batches |
| **Pass if** | Multiple MongoDB spans visible; total ≥ 150 ms |

**Expected span tree:**
```
GET /api/dashboard                    [150–300 ms]
├── mongodb: countDocuments (users)    [parallel]
├── mongodb: countDocuments (products) [parallel]
├── mongodb: find (orders)            [parallel]
├── mongodb: find (users populate)    [may be separate span]
└── mongodb: aggregate (products)     [serial, after ~100ms gap]
```

---

## 2. Scenario-based verification (run in order)

### Scenario A — Baseline (no DB)

| Step | Call | Verify in trace |
|------|------|-----------------|
| 1 | `GET /api/health` | 1 span, < 10 ms, no DB children |
| 2 | `GET /api/status/200` | 1 span, < 5 ms, status 200 |

**Pass:** Traces are flat — only HTTP spans, very short.

---

### Scenario B — Fixed delay accuracy

| Step | Call | Verify in trace |
|------|------|-----------------|
| 1 | `GET /api/delay/500` | Root span ≈ **500 ms**, 0 DB spans |
| 2 | `GET /api/delay/2000` | Root span ≈ **2000 ms**, 0 DB spans |

**Pass:** Duration matches URL param (±10 ms). Confirms your tracer captures sleep time.

---

### Scenario C — Fast vs slow query

| Step | Call | Verify in trace |
|------|------|-----------------|
| 1 | `GET /api/users` | ~20 ms, 1 DB span |
| 2 | `GET /api/users/slow` | ~250 ms, 1 DB span |

**Pass:** Same number of DB spans (1), but step 2 is **10× slower**. DB child span in step 2 is visibly longer.

---

### Scenario D — DB call count scaling

| Step | Call | DB spans | Total duration |
|------|------|----------|----------------|
| 1 | `GET /api/users` | 1 | ~20 ms |
| 2 | `GET /api/orders` | 3 | ~60 ms |
| 3 | `GET /api/dashboard` | 4–5 | ~200 ms |

**Pass:** DB span count increases 1 → 3 → 5. Total duration increases with each step.

---

### Scenario E — Delay source isolation

| Step | Call | Verify in trace |
|------|------|-----------------|
| 1 | `GET /api/delay/2000` | ~2000 ms, **0 DB spans** (all delay is sleep) |
| 2 | `GET /api/users/slow` | ~250 ms, **1 DB span** (delay is sleep + query) |

**Pass:** Step 1 has no MongoDB children. Step 2 has 1 MongoDB child. Confirms you can distinguish sleep vs DB time.

---

### Scenario F — Error handling

| Step | Call | Verify in trace |
|------|------|-----------------|
| 1 | `GET /api/status/404` | status=404, no error flag (or 4xx tag) |
| 2 | `GET /api/status/500` | status=500, marked as error |
| 3 | `GET /api/crash` | status=500, exception/stack trace in span |
| 4 | `GET /api/users/000000000000000000000000` | status=404, **1 DB span still present** |

**Pass:** 500s are flagged as errors. 404 after DB lookup still shows the DB span.

---

### Scenario G — Full user journey

| Step | Call | HTTP status | DB spans |
|------|------|-------------|----------|
| 1 | `POST /api/auth/register` | 201 | 1 |
| 2 | `POST /api/auth/login` | 200 | 1 |
| 3 | `GET /api/auth/me` | 200 | 1 |
| 4 | `GET /api/dashboard` | 200 | 4–5 |

**Pass:** 4 separate traces (or 1 trace if your tool links by session). Step 4 is the heaviest with most DB spans.

---

### Scenario H — Populate vs aggregation join

| Step | Call | DB spans | Pattern |
|------|------|----------|---------|
| 1 | `GET /api/orders` | 3 | Separate find + 2 populates |
| 2 | `GET /api/orders/slow` | 1 | Single aggregation with `$lookup` |

**Pass:** Step 1 shows 3 spans. Step 2 shows 1 span but similar or longer duration.

---

## 3. Quick verification checklist

Copy this checklist when testing:

```
[ ] GET /api/health          → < 10 ms,  0 DB spans, status 200
[ ] GET /api/delay/500       → ≈ 500 ms, 0 DB spans, status 200
[ ] GET /api/delay/2000      → ≈ 2000 ms, 0 DB spans, status 200
[ ] GET /api/users           → < 50 ms,  1 DB span,  status 200
[ ] GET /api/users/slow      → 220–350 ms, 1 DB span, status 200
[ ] GET /api/orders          → 30–100 ms, 3 DB spans, status 200
[ ] GET /api/dashboard       → 150–300 ms, 4–5 DB spans, status 200
[ ] GET /api/status/500      → < 5 ms,   0 DB spans, status 500 (error)
[ ] GET /api/crash           → < 10 ms,  0 DB spans, status 500 (exception)
[ ] POST /api/auth/register  → 50–150 ms, 1 DB span,  status 201
[ ] POST /api/auth/login     → 50–150 ms, 1 DB span,  status 200
[ ] GET /api/auth/me         → 10–50 ms,  1 DB span,  status 200
```

---

## 4. What to compare in your trace tool

| Field in trace tool | Where to get expected value |
|---------------------|----------------------------|
| **Span duration** | "Total duration" column above, or `X-Response-Time` header |
| **HTTP status code** | "HTTP status" column above |
| **Number of DB spans** | "DB spans" column above |
| **Error flag** | Should be set for 500 endpoints and `/api/crash` |

---

## 5. Common failures and what they mean

| What you see | Likely problem |
|--------------|----------------|
| Duration much shorter than expected | Tracer not capturing async/sleep time |
| No MongoDB spans on DB endpoints | MongoDB instrumentation not enabled |
| Only 1 DB span on `/api/orders` | Populate queries not instrumented separately |
| `/api/delay/500` shows < 50 ms | Delay endpoint not being hit, or trace sampled incorrectly |
| All spans same duration as parent | Child spans not being created (flat trace) |
| `/api/crash` shows status 200 | Error middleware catching but not tagging span |

---

## 6. Reference commands

```bash
# Check actual response time
curl -s -D - http://localhost:3000/api/users/slow -o /dev/null | grep X-Response-Time

# Get full timing + DB call reference
curl -s http://localhost:3000/api/timing-reference | jq .

# Get only multi-DB endpoints
curl -s http://localhost:3000/api/timing-reference | jq '.multiDbEndpoints'
```
