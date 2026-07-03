const express = require("express");
const { createClient } = require("redis");
const { log } = require("./common/logger");

const app = express();
const PORT = process.env.PORT || 5003;
const SERVICE = "retail-hub-inventory";

const REDIS_URL = process.env.REDIS_URL || "redis://localhost:6379";
let redis;

async function initRedis() {
  redis = createClient({ url: REDIS_URL });
  redis.on("error", (err) => log(SERVICE, "error", "Redis error", { error: err.message }));
  await redis.connect();
  const exists = await redis.exists("inventory:sku-1001");
  if (!exists) {
    await redis.hSet("inventory:sku-1001", { name: "Widget Pro", stock: "842", warehouse: "WH-EAST" });
    await redis.hSet("inventory:sku-2044", { name: "Sensor Kit", stock: "156", warehouse: "WH-WEST" });
    await redis.hSet("inventory:sku-3300", { name: "Power Module", stock: "67", warehouse: "WH-EAST" });
  }
}

app.get("/health", (_req, res) => res.json({ status: "ok", service: SERVICE }));
app.get("/ready", async (_req, res) => {
  try {
    await redis.ping();
    res.json({ status: "ready", service: SERVICE });
  } catch {
    res.status(503).json({ status: "not ready" });
  }
});

app.get("/inventory/stock", async (_req, res) => {
  const start = Date.now();
  try {
    const keys = await redis.keys("inventory:*");
    const items = [];
    for (const key of keys) {
      items.push({ sku: key.replace("inventory:", ""), ...(await redis.hGetAll(key)) });
    }
    const latencyMs = Date.now() - start;
    log(SERVICE, "info", "Inventory stock fetched", { items: items.length, latencyMs });
    res.json({
      service: SERVICE,
      database: "redis",
      slowQuery: false,
      query: "HGETALL inventory:*",
      latencyMs,
      data: { items, totalSkus: items.length },
    });
  } catch (err) {
    log(SERVICE, "error", "inventory query failed", { error: err.message });
    res.status(500).json({ error: "inventory query failed" });
  }
});

async function start() {
  for (let i = 1; i <= 30; i++) {
    try {
      await initRedis();
      break;
    } catch (err) {
      log(SERVICE, "warn", "Waiting for Redis", { attempt: i, error: err.message });
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  app.listen(PORT, () => log(SERVICE, "info", "Service started", { port: PORT }));
}

start();
