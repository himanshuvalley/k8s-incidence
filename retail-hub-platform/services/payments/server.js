const express = require("express");
const { Pool } = require("pg");
const { createClient } = require("redis");
const { log } = require("./common/logger");

const app = express();
const PORT = process.env.PORT || 5005;
const SERVICE = "retail-hub-payments";

const pool = new Pool({
  host: process.env.PG_HOST || "localhost",
  port: parseInt(process.env.PG_PORT || "5432", 10),
  database: process.env.PG_DATABASE || "retailhub",
  user: process.env.PG_USER || "retailhub",
  password: process.env.PG_PASSWORD || "changeme",
});

const REDIS_URL = process.env.REDIS_URL || "redis://localhost:6379";
let redis;

async function initDb() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS payments (
      id SERIAL PRIMARY KEY,
      method VARCHAR(50) NOT NULL,
      amount NUMERIC(10,2) NOT NULL,
      status VARCHAR(30) DEFAULT 'success',
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
  `);
  const { rows } = await pool.query("SELECT COUNT(*)::int AS c FROM payments");
  if (rows[0].c === 0) {
    await pool.query(
      `INSERT INTO payments (method, amount, status) VALUES
       ('card', 499.00, 'success'),
       ('upi', 1200.00, 'success'),
       ('netbanking', 780.50, 'success')`
    );
  }
  redis = createClient({ url: REDIS_URL });
  await redis.connect();
  await redis.set("payments:last_sync", new Date().toISOString());
}

app.get("/health", (_req, res) => res.json({ status: "ok", service: SERVICE }));
app.get("/ready", async (_req, res) => {
  try {
    await pool.query("SELECT 1");
    await redis.ping();
    res.json({ status: "ready", service: SERVICE });
  } catch {
    res.status(503).json({ status: "not ready" });
  }
});

app.get("/payments/recent", async (_req, res) => {
  const start = Date.now();
  try {
    const result = await pool.query(
      "SELECT id, method, amount, status, created_at FROM payments ORDER BY created_at DESC LIMIT 10"
    );
    const cacheHit = await redis.get("payments:last_sync");
    const latencyMs = Date.now() - start;
    res.json({
      service: SERVICE,
      database: "postgresql+redis",
      slowQuery: false,
      query: "SELECT recent payments + redis cache check",
      latencyMs,
      data: { payments: result.rows, lastSync: cacheHit },
    });
  } catch (err) {
    log(SERVICE, "error", "payments query failed", { error: err.message });
    res.status(500).json({ error: "payments query failed" });
  }
});

async function start() {
  for (let i = 1; i <= 30; i++) {
    try {
      await initDb();
      break;
    } catch (err) {
      log(SERVICE, "warn", "Waiting for dependencies", { attempt: i, error: err.message });
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  app.listen(PORT, () => log(SERVICE, "info", "Service started", { port: PORT }));
}

start();
