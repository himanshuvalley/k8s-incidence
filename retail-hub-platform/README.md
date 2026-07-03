# Retail Hub Platform

Production-style microservices demo with intentional slow queries for latency troubleshooting.

## Architecture

```text
                    ┌─────────────────────────────────────────────┐
                    │              retail-hub-web (:3000)           │
                    └──────────────────────┬──────────────────────┘
                                           │
                    ┌──────────────────────▼──────────────────────┐
                    │           retail-hub-gateway (:8080)          │
                    │         GET /dashboard → fan-out x5          │
                    └──┬────────┬─────────┬──────────┬───────────┬─┘
                       │        │         │          │           │
              ┌────────▼──┐ ┌───▼───┐ ┌───▼────┐ ┌──▼──────┐ ┌──▼──────┐
              │  orders   │ │ users │ │inventory│ │analytics│ │ payments│
              │ PostgreSQL│ │ Mongo │ │  Redis  │ │  Mongo  │ │ PG+Redis│
              │  SLOW ⚠️  │ │ fast  │ │  fast   │ │ SLOW ⚠️ │ │  fast   │
              └───────────┘ └───────┘ └─────────┘ └─────────┘ └─────────┘
```

## Intentional slow queries

| Service | Endpoint | Database | Slow behaviour |
|---------|----------|----------|----------------|
| **orders** | `GET /orders/summary` | PostgreSQL | `pg_sleep(2.5)` |
| **analytics** | `GET /analytics/revenue` | MongoDB | aggregate + `sleep(3s)` |
| users | `GET /users/active` | MongoDB | fast |
| inventory | `GET /inventory/stock` | Redis | fast |
| payments | `GET /payments/recent` | PG + Redis | fast |

When UI opens → calls `/api/dashboard` → gateway hits all 5 in **parallel** → total load ~3–3.5s (dominated by slowest services).

---

## Build & push (ACR)

```bash
az acr login --name incidence

cd retail-hub-platform
chmod +x build-images.sh
./build-images.sh

for svc in web gateway orders users inventory analytics payments; do
  docker push incidence.azurecr.io/retail-hub-${svc}:1.0.0
done
```

---

## Deploy

```bash
helm upgrade --install retail-hub ./retail-hub-platform \
  --namespace prod \
  --create-namespace \
  --set imageCredentials.username=<acr-user> \
  --set imageCredentials.password=<acr-pass>
```

Wait for all pods:

```bash
kubectl get pods -n prod -l app.kubernetes.io/name=retail-hub
```

Expected **10 pods**:

```text
retail-hub-web
retail-hub-gateway
retail-hub-orders / users / inventory / analytics / payments
retail-hub-postgres / mongodb / redis
```

---

## Access UI

```bash
kubectl port-forward -n prod svc/retail-hub-web 8080:3000
```

Open **http://localhost:8080** — dashboard auto-loads and shows latency per microservice. **orders** and **analytics** show as SLOW (red).

---

## Troubleshooting via logs

```bash
kubectl logs -n prod -l app.kubernetes.io/component=gateway -f
kubectl logs -n prod -l app.kubernetes.io/component=orders -f
kubectl logs -n prod -l app.kubernetes.io/component=analytics -f
```

---

## Pod naming reference

| Component | Pod / Service name |
|-----------|-------------------|
| Frontend | `retail-hub-web` |
| BFF | `retail-hub-gateway` |
| Orders MS | `retail-hub-orders` |
| Users MS | `retail-hub-users` |
| Inventory MS | `retail-hub-inventory` |
| Analytics MS | `retail-hub-analytics` |
| Payments MS | `retail-hub-payments` |
| PostgreSQL | `retail-hub-postgres` |
| MongoDB | `retail-hub-mongodb` |
| Redis | `retail-hub-redis` |

---

## Uninstall

```bash
helm uninstall retail-hub -n prod
```
