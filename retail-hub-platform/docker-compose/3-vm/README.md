# Retail Hub — 3 VM Docker Compose Setup

Split stack across 3 Azure VMs:

```text
┌─────────────────────────────────────┐
│  VM 1 — APPS (apps-vm)              │
│  web, gateway, orders, users,       │
│  inventory, analytics, payments     │
│  Port 3000 → browser                │
└──────────┬──────────────┬───────────┘
           │              │
    ┌──────▼──────┐  ┌────▼──────────────┐
    │ VM 2 MONGO  │  │ VM 3 DATA         │
    │ mongo-vm    │  │ data-vm           │
    │ :27017      │  │ postgres :5432    │
    │             │  │ redis    :6379    │
    └─────────────┘  └───────────────────┘
```

**No application code changes** — only env vars point to remote DB VMs.

---

## Folder layout

```text
docker-compose/3-vm/
├── apps-vm/          ← VM 1 (all microservices)
│   ├── docker-compose.yml
│   └── .env.example
├── mongo-vm/         ← VM 2 (MongoDB)
│   └── docker-compose.yml
└── data-vm/          ← VM 3 (Postgres + Redis)
    └── docker-compose.yml
```

---

## Step 1 — VM 3: Postgres + Redis

```bash
# On DATA VM
cd docker-compose/3-vm/data-vm
docker compose up -d
docker compose ps
```

**NSG inbound (DATA VM):**

| Port | Source | Service |
|------|--------|---------|
| 5432 | Apps VM IP only | PostgreSQL |
| 6379 | Apps VM IP only | Redis |

---

## Step 2 — VM 2: MongoDB

```bash
# On MONGO VM
cd docker-compose/3-vm/mongo-vm
docker compose up -d
docker compose ps
```

**NSG inbound (MONGO VM):**

| Port | Source | Service |
|------|--------|---------|
| 27017 | Apps VM IP only | MongoDB |

---

## Step 3 — VM 1: All microservices

```bash
# On APPS VM
cd docker-compose/3-vm/apps-vm

cp .env.example .env
# Edit .env — set private IPs:
#   MONGO_VM_IP=<VM2 private IP>
#   DATA_VM_IP=<VM3 private IP>

az acr login --name incidence
docker compose pull
docker compose up -d
docker compose ps
```

**NSG inbound (APPS VM):**

| Port | Source | Service |
|------|--------|---------|
| 3000 | Your IP / * | Web UI |

---

## Step 4 — Test connectivity (from APPS VM)

```bash
# Mongo
nc -zv $MONGO_VM_IP 27017

# Postgres
nc -zv $DATA_VM_IP 5432

# Redis
nc -zv $DATA_VM_IP 6379
```

```bash
curl http://localhost:3000/health
curl http://localhost:3000/api/dashboard
```

Browser: `http://<APPS_VM_PUBLIC_IP>:3000`

---

## .env example

```env
MONGO_VM_IP=10.0.1.12
DATA_VM_IP=10.0.1.13
```

Use **private IPs** if all 3 VMs are in the same VNet (recommended).

---

## Stop

```bash
# Each VM — in its compose folder
docker compose down
docker compose down -v   # + delete volumes (data VM / mongo VM only)
```

---

## Troubleshooting

| Issue | Check |
|-------|-------|
| orders/payments crash | `nc -zv DATA_VM_IP 5432` from apps VM |
| users/analytics crash | `nc -zv MONGO_VM_IP 27017` from apps VM |
| inventory crash | `nc -zv DATA_VM_IP 6379` from apps VM |
| Connection refused | NSG rules — allow apps VM → db VMs |
| ImagePullBackOff | `az acr login --name incidence` on apps VM |

---

## Single VM (all-in-one)

Use parent file instead:

```bash
cd retail-hub-platform
docker compose up -d
```

See `DOCKER-COMPOSE-VM.md`.
