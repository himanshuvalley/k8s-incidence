# Ops Portal — Three-Tier Demo

Professional three-tier Node.js demo for Kubernetes presentations.

## Architecture

```text
  Browser
     │
     ▼
 portal-web ──▶ portal-api ──▶ portal-db
 (Tier 1)        (Tier 2)       (Tier 3)
 Node.js         Node.js        PostgreSQL
 :3000           :4000          :5432
```

## Kubernetes resource names (after deploy)

| Tier | Pod prefix | Service |
|------|------------|---------|
| Web | `portal-web-*` | `portal-web` |
| API | `portal-api-*` | `portal-api` |
| DB | `portal-db-*` | `portal-db` |

---

## Step 1: Build & push to ACR

```bash
az acr login --name incidence

cd nodejs-three-tier-app

docker build -t incidence.azurecr.io/portal-web:1.0.1 ./frontend
docker push incidence.azurecr.io/portal-web:1.0.1

docker build -t incidence.azurecr.io/portal-api:1.0.1 ./backend
docker push incidence.azurecr.io/portal-api:1.0.1
```

---

## Step 2: Deploy

Remove old release if you deployed the previous version:

```bash
helm uninstall three-tier-app -n three-tier 2>/dev/null || true
```

Deploy with clean demo names:

```bash
helm upgrade --install portal ./nodejs-three-tier-app \
  --namespace alertmend-demo \
  --create-namespace \
  --set imageCredentials.username=<acr-username> \
  --set imageCredentials.password=<acr-password>
```

Verify pods:

```bash
kubectl get pods -n alertmend-demo
```

Expected:

```text
NAME                          READY   STATUS    RESTARTS   AGE
portal-api-xxxxxxxxxx-xxxxx   1/1     Running   0          1m
portal-db-xxxxxxxxxx-xxxxx    1/1     Running   0          1m
portal-web-xxxxxxxxxx-xxxxx   1/1     Running   0          1m
```

---

## Step 3: Access for demo

```bash
kubectl port-forward -n alertmend-demo svc/portal-web 8080:3000
```

Open: **http://localhost:8080**

### View backend logs (every action is logged)

```bash
kubectl logs -n prod -l app.kubernetes.io/component=api -f
```

Example log when you create an incident:
```json
{"timestamp":"...","level":"info","service":"portal-api","message":"Incident created","incidentId":4,"title":"API timeout","severity":"high","status":"open"}
```

---

## Demo verification commands

```bash
# All pods
kubectl get pods -n alertmend-demo -o wide

# Services
kubectl get svc -n alertmend-demo

# API health
kubectl port-forward -n alertmend-demo svc/portal-api 4000:4000 &
curl http://localhost:4000/health

# DB data
kubectl exec -n alertmend-demo deploy/portal-db -- \
  psql -U portal -d portal -c "SELECT * FROM messages;"
```

---

## Uninstall

```bash
helm uninstall portal -n alertmend-demo
kubectl delete namespace alertmend-demo
```
