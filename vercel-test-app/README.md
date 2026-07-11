# Vercel Test App

Minimal static site with two serverless API routes — useful for smoke-testing Vercel deployments, DNS, and CI/CD.

## What it includes

| Path | Description |
|------|-------------|
| `/` | Static dashboard with health check UI |
| `/api/health` | Returns deployment status, region, timestamp |
| `/api/echo` | Echoes query params, method, and POST body |

No build step. Deploy as-is.

---

## Deploy to Vercel

### Option A — Vercel CLI

```bash
cd vercel-test-app
npx vercel
```

Follow the prompts. For production:

```bash
npx vercel --prod
```

### Option B — GitHub + Vercel dashboard

1. Push this repo to GitHub.
2. Go to [vercel.com/new](https://vercel.com/new).
3. Import the repository.
4. Set **Root Directory** to `vercel-test-app`.
5. Click **Deploy** (no build command or output directory needed).

---

## Local preview

Install the Vercel CLI once, then run:

```bash
cd vercel-test-app
npx vercel dev
```

Open the URL shown in the terminal (usually `http://localhost:3000`).

---

## Manual API checks

```bash
curl https://YOUR-APP.vercel.app/api/health
curl "https://YOUR-APP.vercel.app/api/echo?message=test"
curl -X POST https://YOUR-APP.vercel.app/api/echo \
  -H "Content-Type: application/json" \
  -d '{"message":"hello"}'
```
