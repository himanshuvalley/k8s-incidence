const express = require("express");
const path = require("path");
const { createProxyMiddleware } = require("http-proxy-middleware");

const app = express();
const PORT = process.env.PORT || 3000;
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:4000";
const SERVICE = "portal-web";

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

app.use(express.static(path.join(__dirname, "public")));

app.use(
  "/api",
  createProxyMiddleware({
    target: BACKEND_URL,
    changeOrigin: true,
    pathRewrite: { "^/api": "" },
    on: {
      proxyReq: (_proxyReq, req) => {
        log("info", "Proxying request to portal-api", {
          method: req.method,
          path: req.originalUrl,
          target: BACKEND_URL,
        });
      },
      proxyRes: (proxyRes, req) => {
        log("info", "Proxy response from portal-api", {
          method: req.method,
          path: req.originalUrl,
          status: proxyRes.statusCode,
        });
      },
      error: (err, req) => {
        log("error", "Proxy error", {
          method: req.method,
          path: req.originalUrl,
          error: err.message,
        });
      },
    },
  })
);

app.get("/health", (_req, res) => {
  res.json({ status: "ok", tier: "web", service: SERVICE });
});

app.listen(PORT, () => {
  log("info", "Web server started", { port: PORT, backend: BACKEND_URL, tier: "presentation" });
});
