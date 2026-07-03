const express = require("express");
const { Pool } = require("pg");

const app = express();
const PORT = process.env.PORT || 4000;
const SERVICE = "portal-api";

const pool = new Pool({
  host: process.env.DB_HOST || "localhost",
  port: parseInt(process.env.DB_PORT || "5432", 10),
  database: process.env.DB_NAME || "portal",
  user: process.env.DB_USER || "portal",
  password: process.env.DB_PASSWORD || "changeme",
});

const SEVERITIES = ["low", "medium", "high", "critical"];
const STATUSES = ["open", "in_progress", "resolved"];

function log(level, message, meta = {}) {
  console.log(
    JSON.stringify({
      timestamp: new Date().toISOString(),
      level,
      service: SERVICE,
      message,
      ...meta,
    })
  );
}

app.use(express.json());

app.use((req, res, next) => {
  const start = Date.now();
  res.on("finish", () => {
    log("info", "HTTP request completed", {
      method: req.method,
      path: req.originalUrl,
      status: res.statusCode,
      durationMs: Date.now() - start,
      clientIp: req.headers["x-forwarded-for"] || req.socket.remoteAddress,
    });
  });
  next();
});

async function initDb() {
  const client = await pool.connect();
  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS incidents (
        id SERIAL PRIMARY KEY,
        title VARCHAR(200) NOT NULL,
        description TEXT NOT NULL,
        severity VARCHAR(20) NOT NULL DEFAULT 'medium',
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
      )
    `);

    const count = await client.query("SELECT COUNT(*)::int AS total FROM incidents");
    if (count.rows[0].total === 0) {
      await client.query(
        `INSERT INTO incidents (title, description, severity, status) VALUES
         ($1, $2, $3, $4),
         ($5, $6, $7, $8),
         ($9, $10, $11, $12)`,
        [
          "Payment API latency spike",
          "Checkout response time exceeded 2s on us-east cluster.",
          "high",
          "open",
          "Database connection pool warning",
          "RDS active connections reached 85% of max limit.",
          "medium",
          "in_progress",
          "SSL certificate renewal",
          "Wildcard cert for portal domain renewed successfully.",
          "low",
          "resolved",
        ]
      );
      log("info", "Seeded demo incidents into portal-db");
    }
  } finally {
    client.release();
  }
}

async function waitForDb(maxAttempts = 30) {
  for (let i = 1; i <= maxAttempts; i++) {
    try {
      await initDb();
      log("info", "Database connected and schema ready", {
        dbHost: process.env.DB_HOST || "localhost",
        dbName: process.env.DB_NAME || "portal",
      });
      return;
    } catch (err) {
      log("warn", "Waiting for database", { attempt: i, maxAttempts, error: err.message });
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  throw new Error("Could not connect to database");
}

app.get("/health", (_req, res) => {
  res.json({ status: "ok", tier: "api", service: SERVICE });
});

app.get("/ready", async (_req, res) => {
  try {
    await pool.query("SELECT 1");
    res.json({ status: "ready", tier: "api", service: SERVICE });
  } catch (err) {
    log("error", "Readiness check failed", { error: err.message });
    res.status(503).json({ status: "not ready" });
  }
});

app.get("/incidents/stats", async (_req, res) => {
  try {
    const result = await pool.query(`
      SELECT
        COUNT(*)::int AS total,
        COUNT(*) FILTER (WHERE status = 'open')::int AS open,
        COUNT(*) FILTER (WHERE status = 'in_progress')::int AS in_progress,
        COUNT(*) FILTER (WHERE status = 'resolved')::int AS resolved,
        COUNT(*) FILTER (WHERE severity = 'critical')::int AS critical
      FROM incidents
    `);
    log("info", "Fetched incident stats", result.rows[0]);
    res.json(result.rows[0]);
  } catch (err) {
    log("error", "Failed to fetch stats", { error: err.message });
    res.status(500).json({ error: "Failed to fetch stats" });
  }
});

app.get("/incidents", async (req, res) => {
  const status = req.query.status?.trim();
  try {
    let result;
    if (status && STATUSES.includes(status)) {
      result = await pool.query(
        `SELECT id, title, description, severity, status, created_at, updated_at
         FROM incidents WHERE status = $1 ORDER BY created_at DESC`,
        [status]
      );
      log("info", "Listed incidents by status", { status, count: result.rowCount });
    } else {
      result = await pool.query(
        `SELECT id, title, description, severity, status, created_at, updated_at
         FROM incidents ORDER BY created_at DESC`
      );
      log("info", "Listed all incidents", { count: result.rowCount });
    }
    res.json(result.rows);
  } catch (err) {
    log("error", "Failed to list incidents", { error: err.message });
    res.status(500).json({ error: "Failed to fetch incidents" });
  }
});

app.post("/incidents", async (req, res) => {
  const title = req.body?.title?.trim();
  const description = req.body?.description?.trim();
  const severity = req.body?.severity?.trim()?.toLowerCase() || "medium";

  if (!title || !description) {
    log("warn", "Create incident rejected — validation failed", { title, description });
    return res.status(400).json({ error: "title and description are required" });
  }
  if (!SEVERITIES.includes(severity)) {
    log("warn", "Create incident rejected — invalid severity", { severity });
    return res.status(400).json({ error: "invalid severity" });
  }

  try {
    const result = await pool.query(
      `INSERT INTO incidents (title, description, severity, status)
       VALUES ($1, $2, $3, 'open')
       RETURNING id, title, description, severity, status, created_at, updated_at`,
      [title, description, severity]
    );
    const incident = result.rows[0];
    log("info", "Incident created", {
      incidentId: incident.id,
      title: incident.title,
      severity: incident.severity,
      status: incident.status,
    });
    res.status(201).json(incident);
  } catch (err) {
    log("error", "Failed to create incident", { error: err.message, title });
    res.status(500).json({ error: "Failed to create incident" });
  }
});

app.patch("/incidents/:id", async (req, res) => {
  const id = parseInt(req.params.id, 10);
  const status = req.body?.status?.trim()?.toLowerCase();

  if (!Number.isInteger(id) || id <= 0) {
    return res.status(400).json({ error: "invalid incident id" });
  }
  if (!status || !STATUSES.includes(status)) {
    log("warn", "Update incident rejected — invalid status", { incidentId: id, status });
    return res.status(400).json({ error: "invalid status" });
  }

  try {
    const result = await pool.query(
      `UPDATE incidents SET status = $1, updated_at = NOW()
       WHERE id = $2
       RETURNING id, title, description, severity, status, created_at, updated_at`,
      [status, id]
    );
    if (result.rowCount === 0) {
      log("warn", "Incident not found for update", { incidentId: id });
      return res.status(404).json({ error: "incident not found" });
    }
    log("info", "Incident status updated", {
      incidentId: id,
      newStatus: status,
      title: result.rows[0].title,
    });
    res.json(result.rows[0]);
  } catch (err) {
    log("error", "Failed to update incident", { incidentId: id, error: err.message });
    res.status(500).json({ error: "Failed to update incident" });
  }
});

app.delete("/incidents/:id", async (req, res) => {
  const id = parseInt(req.params.id, 10);
  if (!Number.isInteger(id) || id <= 0) {
    return res.status(400).json({ error: "invalid incident id" });
  }

  try {
    const result = await pool.query(
      "DELETE FROM incidents WHERE id = $1 RETURNING id, title",
      [id]
    );
    if (result.rowCount === 0) {
      log("warn", "Incident not found for delete", { incidentId: id });
      return res.status(404).json({ error: "incident not found" });
    }
    log("info", "Incident deleted", {
      incidentId: id,
      title: result.rows[0].title,
    });
    res.json({ deleted: true, id });
  } catch (err) {
    log("error", "Failed to delete incident", { incidentId: id, error: err.message });
    res.status(500).json({ error: "Failed to delete incident" });
  }
});

waitForDb()
  .then(() => {
    app.listen(PORT, () => {
      log("info", "API server started", { port: PORT, tier: "application" });
    });
  })
  .catch((err) => {
    log("error", "API startup failed", { error: err.message });
    process.exit(1);
  });
