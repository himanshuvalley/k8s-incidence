# Retail Hub — Docker Compose on VM

Run the full **retail-hub-platform** stack on any VM with Docker (no Kubernetes).

## What runs

| Service | Internal port | Notes |
|---------|---------------|-------|
| **web** | **3000** (exposed) | UI — open in browser |
| gateway | 8080 | BFF fan-out to 5 MS |
| orders | 5001 | PostgreSQL — slow query |
| users | 5002 | MongoDB |
| inventory | 5003 | Redis |
| analytics | 5004 | MongoDB — slow query |
| payments | 5005 | PostgreSQL + Redis |
| postgres | 5432 | internal |
| mongodb | 27017 | internal |
| redis | 6379 | internal |

---

## Prerequisites (VM)

```bash
docker --version
docker compose version
```

Install if missing (Ubuntu example):

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
# log out and back in
```

---

## Start

```bash
# ACR login (images already pushed)
az acr login --name incidence

cd retail-hub-platform

docker compose pull
docker compose up -d
```

No local build needed — uses pre-pushed images from `incidence.azurecr.io`.

Check status:

```bash
docker compose ps
docker compose logs -f web
```

---

## Open UI

```bash
# From VM
curl http://localhost:3000/health

# From your laptop (replace VM_IP)
http://<VM_IP>:3000
```

If port 3000 is blocked, open firewall:

```bash
sudo ufw allow 3000/tcp
```

---

## Test

```bash
curl http://localhost:3000/health
curl http://localhost:3000/api/dashboard
```

Dashboard loads ~3–3.5s (orders + analytics slow queries by design).

---

## Stop / cleanup

```bash
docker compose down          # stop containers
docker compose down -v       # stop + delete DB volumes
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Build fails | Run from `retail-hub-platform/` folder (build context = `.`) |
| Mongo not ready | Wait 30s, `docker compose logs mongodb` |
| Web 502 | `docker compose logs gateway` — wait for all MS to start |
| Can't reach from outside | Open VM security group / `ufw` for port 3000 |

---

## Files

- `docker-compose.yml` — full stack definition
- No application code changes — uses existing `services/*/Dockerfile`
