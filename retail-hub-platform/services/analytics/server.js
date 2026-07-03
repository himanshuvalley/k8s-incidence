const express = require("express");
const { MongoClient } = require("mongodb");
const { log } = require("./common/logger");

const app = express();
const PORT = process.env.PORT || 5004;
const SERVICE = "retail-hub-analytics";

const MONGO_URI =
  process.env.MONGO_URI || "mongodb://retailhub:changeme@localhost:27017/retailhub?authSource=admin";

let db;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function initDb() {
  const client = new MongoClient(MONGO_URI);
  await client.connect();
  db = client.db(process.env.MONGO_DATABASE || "retailhub");
  const count = await db.collection("events").countDocuments();
  if (count === 0) {
    await db.collection("events").insertMany([
      { type: "page_view", revenue: 120, region: "us-east", ts: new Date() },
      { type: "purchase", revenue: 890, region: "eu-west", ts: new Date() },
      { type: "purchase", revenue: 2400, region: "ap-south", ts: new Date() },
      { type: "signup", revenue: 0, region: "us-west", ts: new Date() },
    ]);
  }
}

app.get("/health", (_req, res) => res.json({ status: "ok", service: SERVICE }));
app.get("/ready", async (_req, res) => {
  try {
    await db.command({ ping: 1 });
    res.json({ status: "ready", service: SERVICE });
  } catch {
    res.status(503).json({ status: "not ready" });
  }
});

app.get("/analytics/revenue", async (_req, res) => {
  const start = Date.now();
  try {
    const pipeline = [
      { $match: { type: "purchase" } },
      { $group: { _id: "$region", totalRevenue: { $sum: "$revenue" }, count: { $sum: 1 } } },
      { $sort: { totalRevenue: -1 } },
    ];
    const agg = await db.collection("events").aggregate(pipeline).toArray();

    log(SERVICE, "info", "Running slow analytics query (sleep 3s)", {
      query: "aggregate + artificial_delay",
    });
    await sleep(3000);

    const latencyMs = Date.now() - start;
    res.json({
      service: SERVICE,
      database: "mongodb",
      slowQuery: true,
      query: "aggregate(purchase) + sleep(3000ms)",
      latencyMs,
      data: { regions: agg, totalRegions: agg.length },
    });
  } catch (err) {
    log(SERVICE, "error", "analytics query failed", { error: err.message });
    res.status(500).json({ error: "analytics query failed" });
  }
});

async function start() {
  for (let i = 1; i <= 30; i++) {
    try {
      await initDb();
      break;
    } catch (err) {
      log(SERVICE, "warn", "Waiting for MongoDB", { attempt: i, error: err.message });
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  app.listen(PORT, () => log(SERVICE, "info", "Service started", { port: PORT }));
}

start();
