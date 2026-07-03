const express = require("express");
const { MongoClient } = require("mongodb");
const { log } = require("./common/logger");

const app = express();
const PORT = process.env.PORT || 5002;
const SERVICE = "retail-hub-users";

const MONGO_URI =
  process.env.MONGO_URI || "mongodb://retailhub:changeme@localhost:27017/retailhub?authSource=admin";

let db;

async function initDb() {
  const client = new MongoClient(MONGO_URI);
  await client.connect();
  db = client.db(process.env.MONGO_DATABASE || "retailhub");
  const count = await db.collection("users").countDocuments();
  if (count === 0) {
    await db.collection("users").insertMany([
      { name: "Alice Chen", role: "admin", active: true, region: "us-east" },
      { name: "Bob Singh", role: "operator", active: true, region: "eu-west" },
      { name: "Carol Diaz", role: "viewer", active: true, region: "ap-south" },
      { name: "Dan Miller", role: "operator", active: false, region: "us-west" },
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

app.get("/users/active", async (_req, res) => {
  const start = Date.now();
  try {
    const users = await db.collection("users").find({ active: true }).limit(50).toArray();
    const latencyMs = Date.now() - start;
    log(SERVICE, "info", "Active users fetched", { count: users.length, latencyMs });
    res.json({
      service: SERVICE,
      database: "mongodb",
      slowQuery: false,
      query: "find({ active: true })",
      latencyMs,
      data: { count: users.length, users },
    });
  } catch (err) {
    log(SERVICE, "error", "users query failed", { error: err.message });
    res.status(500).json({ error: "users query failed" });
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
