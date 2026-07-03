const express = require("express");
const path = require("path");
const { createProxyMiddleware } = require("http-proxy-middleware");

const app = express();
const PORT = process.env.PORT || 3000;
const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8080";

app.use(express.static(path.join(__dirname, "public")));
app.use(
  "/api",
  createProxyMiddleware({
    target: GATEWAY_URL,
    changeOrigin: true,
    pathRewrite: { "^/api": "" },
  })
);

app.get("/health", (_req, res) => res.json({ status: "ok", service: "retail-hub-web" }));
app.listen(PORT, () => console.log(`retail-hub-web on :${PORT} -> ${GATEWAY_URL}`));
