const express = require("express");
const { log } = require("./common/logger");

const app = express();
const PORT = process.env.PORT || 8080;
const SERVICE = "retail-hub-gateway";

const SERVICES = [
  {
    name: "orders",
    url: process.env.ORDERS_URL || "http://localhost:5001",
    path: "/orders/summary",
    slow: true,
    db: "postgresql",
  },
  {
    name: "users",
    url: process.env.USERS_URL || "http://localhost:5002",
    path: "/users/active",
    slow: false,
    db: "mongodb",
  },
  {
    name: "inventory",
    url: process.env.INVENTORY_URL || "http://localhost:5003",
    path: "/inventory/stock",
    slow: false,
    db: "redis",
  },
  {
    name: "analytics",
    url: process.env.ANALYTICS_URL || "http://localhost:5004",
    path: "/analytics/revenue",
    slow: true,
    db: "mongodb",
  },
  {
    name: "payments",
    url: process.env.PAYMENTS_URL || "http://localhost:5005",
    path: "/payments/recent",
    slow: false,
    db: "postgresql+redis",
  },
];

async function callService(svc) {
  const start = Date.now();
  try {
    const res = await fetch(`${svc.url}${svc.path}`);
    const body = await res.json();
    const latencyMs = Date.now() - start;
    log(SERVICE, "info", "Downstream call completed", {
      target: svc.name,
      latencyMs,
      status: res.status,
      slowQuery: body.slowQuery || false,
    });
    return {
      name: svc.name,
      ok: res.ok,
      latencyMs,
      slowQuery: body.slowQuery || svc.slow,
      database: svc.db,
      query: body.query || svc.path,
      data: body.data,
      error: res.ok ? null : body.error,
    };
  } catch (err) {
    const latencyMs = Date.now() - start;
    log(SERVICE, "error", "Downstream call failed", { target: svc.name, error: err.message });
    return {
      name: svc.name,
      ok: false,
      latencyMs,
      slowQuery: svc.slow,
      database: svc.db,
      query: svc.path,
      error: err.message,
    };
  }
}

app.get("/health", (_req, res) => res.json({ status: "ok", service: SERVICE }));
app.get("/ready", (_req, res) => res.json({ status: "ready", service: SERVICE }));

app.get("/dashboard", async (_req, res) => {
  const dashboardStart = Date.now();
  log(SERVICE, "info", "Dashboard load — fan-out to 5 microservices");
  const results = await Promise.all(SERVICES.map(callService));
  const totalLatencyMs = Date.now() - dashboardStart;
  const slowServices = results.filter((r) => r.latencyMs > 1000 || r.slowQuery);

  res.json({
    service: SERVICE,
    totalLatencyMs,
    slowServices: slowServices.map((s) => s.name),
    services: results,
  });
});

app.listen(PORT, () => log(SERVICE, "info", "Gateway started", { port: PORT, tier: "bff" }));
