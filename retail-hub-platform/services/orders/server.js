const express = require("express");
const { Pool } = require("pg");
const { log } = require("./common/logger");

const app = express();
const PORT = process.env.PORT || 5001;
const SERVICE = "retail-hub-orders";

const pool = new Pool({
  host: process.env.PG_HOST || "localhost",
  port: parseInt(process.env.PG_PORT || "5432", 10),
  database: process.env.PG_DATABASE || "retailhub",
  user: process.env.PG_USER || "retailhub",
  password: process.env.PG_PASSWORD || "changeme",
});

async function initDb() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS orders (
      id SERIAL PRIMARY KEY,
      customer VARCHAR(100) NOT NULL,
      amount NUMERIC(10,2) NOT NULL,
      status VARCHAR(30) DEFAULT 'completed',
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
  `);
  const { rows } = await pool.query("SELECT COUNT(*)::int AS c FROM orders");
  if (rows[0].c === 0) {
    await pool.query(
      `INSERT INTO orders (customer, amount, status) VALUES
       ('Acme Corp', 2499.00, 'completed'),
       ('Globex Ltd', 890.50, 'completed'),
       ('Initech', 15200.00, 'pending'),
       ('Umbrella Co', 430.00, 'completed')`
    );
  }
}

app.get("/health", (_req, res) => res.json({ status: "ok", service: SERVICE }));
app.get("/ready", async (_req, res) => {
  try {
    await pool.query("SELECT 1");
    res.json({ status: "ready", service: SERVICE });
  } catch {
    res.status(503).json({ status: "not ready" });
  }
});

app.get("/orders/summary", async (_req, res) => {
  const start = Date.now();
  try {
    const countResult = await pool.query(
      "SELECT COUNT(*)::int AS total, COALESCE(SUM(amount),0)::float AS revenue FROM orders"
    );
    log(SERVICE, "info", "Running slow orders query (pg_sleep 2.5s)", { query: "pg_sleep(2.5)" });
    await pool.query("SELECT pg_sleep(2.5)");

    const latencyMs = Date.now() - start;
    res.json({
      service: SERVICE,
      database: "postgresql",
      slowQuery: true,
      query: "SELECT COUNT/SUM + pg_sleep(2.5)",
      latencyMs,
      data: countResult.rows[0],
    });
  } catch (err) {
    log(SERVICE, "error", "orders summary failed", { error: err.message });
    res.status(500).json({ error: "orders summary failed" });
  }
});

async function start() {
  for (let i = 1; i <= 30; i++) {
    try {
      await initDb();
      break;
    } catch (err) {
      log(SERVICE, "warn", "Waiting for PostgreSQL", { attempt: i, error: err.message });
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  app.listen(PORT, () => log(SERVICE, "info", "Service started", { port: PORT }));
}

start();
