# Deploy Any Application to AKS — Step-by-Step Guide

Use this guide when someone gives you **application source code** and you need to deploy it on **Azure Kubernetes Service (AKS)**.

Example: you receive a Node.js / Python / Java app folder with source code — no Docker, no Kubernetes files.

---

## Overview — kya kya banana padega

```text
Application code (given to you)
        ↓
   1. Dockerfile          ← image ka recipe
        ↓
   2. docker build        ← local image
        ↓
   3. ACR login + push     ← image cloud pe
        ↓
   4. K8s YAML files       ← Deployment, Service, Secret
        ↓
   5. kubectl apply        ← cluster pe deploy
        ↓
   App running on AKS ✅
```

---

## Prerequisites

| Tool | Check |
|------|-------|
| Docker | `docker --version` |
| kubectl | `kubectl version --client` |
| Helm (optional) | `helm version` |
| Azure CLI | `az --version` |
| AKS cluster access | `kubectl get nodes` |

You also need:

- **ACR name** — e.g. `xxx.azurecr.io` (replace `xxx` with your registry name)
- **ACR username + password** (or admin credentials from Azure portal)
- **Namespace** — e.g. `my-app-namespace`

---

## Step 1 — Understand the application

Before writing Dockerfile, check:

| Question | Where to look |
|----------|---------------|
| Language? | `package.json`, `requirements.txt`, `pom.xml`, `go.mod` |
| Start command? | `"scripts": { "start": "..." }` in package.json |
| Port? | `.env.example`, README, or code (`PORT`, `app.listen`) |
| Needs database? | `.env`, `docker-compose.yml` |
| Health endpoint? | `/health`, `/api/health` — needed for K8s probes |

**Example (Node.js app):**

- Start: `npm start` → `node src/index.js`
- Port: `3000`
- Health: `GET /api/health`

---

## Step 2 — Add Dockerfile

Create `Dockerfile` **inside the app folder** (or next to it). Do **not** modify application logic — only add this file.

### Node.js example

```dockerfile
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY src ./src

EXPOSE 3000

CMD ["npm", "start"]
```

### Python (Flask) example

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8080

CMD ["python", "app.py"]
```

### Test locally (optional)

```bash
cd /path/to/app
docker build -t my-app:local .
docker run -p 3000:3000 my-app:local
curl http://localhost:3000/api/health
```

---

## Step 3 — Azure Container Registry (ACR)

### 3a — Create ACR (agar pehle se nahi hai)

Skip this section if you already have an ACR (e.g. `xxx.azurecr.io`).

#### Variables set karo

Replace values with your own:

```bash
RESOURCE_GROUP=my-app-rg
LOCATION=centralindia          # ap-south-1 jaisa — Azure region
ACR_NAME=mycompanyacr          # globally unique, lowercase, no hyphen sometimes required
AKS_NAME=my-aks-cluster        # optional — agar AKS bhi naya bana rahe ho
```

> **ACR name rules:** 5–50 chars, alphanumeric only, **globally unique** across Azure.

#### Create resource group (if needed)

```bash
az login

az group create \
  --name ${RESOURCE_GROUP} \
  --location ${LOCATION}
```

#### Create ACR

**Basic tier** — dev/demo ke liye kaafi:

```bash
az acr create \
  --resource-group ${RESOURCE_GROUP} \
  --name ${ACR_NAME} \
  --sku Basic \
  --admin-enabled true
```

| SKU | Use case |
|-----|----------|
| **Basic** | Dev, demo, small teams |
| Standard | Production (more storage) |
| Premium | Geo-replication, private link |

Verify:

```bash
az acr show --name ${ACR_NAME} --query loginServer -o tsv
# Output: xxx.azurecr.io
```

#### AKS ko ACR se attach karo (important)

Taaki cluster bina extra secret ke bhi pull kar sake (optional but recommended):

```bash
az aks update \
  --resource-group ${RESOURCE_GROUP} \
  --name ${AKS_NAME} \
  --attach-acr ${ACR_NAME}
```

> Agar AKS alag resource group mein hai, same subscription mein hona chahiye.

**Alternative** — manual pull secret (guide Step 6) — attach na karo to bhi chalega.

#### ACR admin credentials lo (image pull secret ke liye)

```bash
az acr credential show --name ${ACR_NAME}
```

Output:

```json
{
  "username": "xxx",
  "passwords": [{ "value": "..." }]
}
```

Save karo — Step 6 mein `kubectl create secret` ke liye chahiye.

#### Quick checklist — naya ACR

```bash
# 1. Resource group
az group create --name my-app-rg --location centralindia

# 2. ACR
az acr create --resource-group my-app-rg --name mycompanyacr --sku Basic --admin-enabled true

# 3. Login server confirm
az acr show --name mycompanyacr --query loginServer -o tsv

# 4. Credentials
az acr credential show --name mycompanyacr

# 5. (Optional) Attach to AKS
az aks update --resource-group my-app-rg --name my-aks-cluster --attach-acr mycompanyacr
```

---

### 3b — ACR login (push image se pehle)

Replace `xxx` with your ACR name.

```bash
az login
az acr login --name xxx
```

Get credentials again (if needed):

```bash
az acr credential show --name xxx
```

---

## Step 4 — Build and push image to ACR

Pick an image name and tag. Use a **production-style name** (no `test`, no `demo`).

```bash
REGISTRY=xxx.azurecr.io
APP=my-app-service
TAG=1.0.0

cd /path/to/app

docker build -t ${REGISTRY}/${APP}:${TAG} .
docker push ${REGISTRY}/${APP}:${TAG}
```

Verify image exists:

```bash
az acr repository list --name xxx
az acr repository show-tags --name xxx --repository my-app-service
```

---

## Step 5 — Create namespace

```bash
kubectl create namespace my-app-namespace
```

---

## Step 6 — ACR pull secret

Kubernetes needs credentials to pull private images from ACR.

```bash
kubectl create secret docker-registry acr-pull-secret \
  --namespace my-app-namespace \
  --docker-server=xxx.azurecr.io \
  --docker-username=<acr-username> \
  --docker-password=<acr-password> \
  --docker-email=devops@example.com
```

Verify:

```bash
kubectl get secret acr-pull-secret -n my-app-namespace
```

> **Note:** If another app in the same namespace already has `acr-pull-secret`, reuse it — do not create duplicate.

---

## Step 7 — Deployment YAML

Create `k8s/deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app-service
  namespace: my-app-namespace
  labels:
    app: my-app-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-app-service
  template:
    metadata:
      labels:
        app: my-app-service
    spec:
      imagePullSecrets:
        - name: acr-pull-secret
      containers:
        - name: server
          image: xxx.azurecr.io/my-app-service:1.0.0
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 3000
          env:
            - name: PORT
              value: "3000"
            # Add more env vars if app needs DB, secrets, etc.
            # - name: MONGODB_URI
            #   value: "mongodb://my-mongodb:27017/mydb"
          readinessProbe:
            httpGet:
              path: /api/health
              port: 3000
            initialDelaySeconds: 10
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /api/health
              port: 3000
            initialDelaySeconds: 30
            periodSeconds: 10
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
```

Apply:

```bash
kubectl apply -f k8s/deployment.yaml
```

Check:

```bash
kubectl get pods -n my-app-namespace
kubectl logs -n my-app-namespace -l app=my-app-service -f
```

---

## Step 8 — Service YAML

### Option A — LoadBalancer (external URL, public IP)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app-service
  namespace: my-app-namespace
  labels:
    app: my-app-service
spec:
  type: LoadBalancer
  selector:
    app: my-app-service
  ports:
    - name: http
      port: 3000
      targetPort: http
```

### Option B — ClusterIP (internal only)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app-service
  namespace: my-app-namespace
spec:
  type: ClusterIP
  selector:
    app: my-app-service
  ports:
    - port: 3000
      targetPort: http
```

Apply:

```bash
kubectl apply -f k8s/service.yaml
```

Get URL:

```bash
# LoadBalancer
kubectl get svc my-app-service -n my-app-namespace

# ClusterIP — port-forward for local test
kubectl port-forward -n my-app-namespace svc/my-app-service 8080:3000
curl http://localhost:8080/api/health
```

---

## Step 9 — Deploy with database (if app needs MongoDB/Postgres)

If `docker-compose.yml` only runs a database locally, deploy DB separately in K8s.

### MongoDB (simple, no auth — dev/demo)

```yaml
# k8s/mongodb.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-mongodb
  namespace: my-app-namespace
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-mongodb
  template:
    metadata:
      labels:
        app: my-mongodb
    spec:
      containers:
        - name: mongodb
          image: mongo:7
          ports:
            - containerPort: 27017
---
apiVersion: v1
kind: Service
metadata:
  name: my-mongodb
  namespace: my-app-namespace
spec:
  selector:
    app: my-mongodb
  ports:
    - port: 27017
      targetPort: 27017
```

In app Deployment env:

```yaml
- name: MONGODB_URI
  value: "mongodb://my-mongodb.my-app-namespace.svc.cluster.local:27017/mydb"
```

Or shorter (same namespace):

```yaml
- name: MONGODB_URI
  value: "mongodb://my-mongodb:27017/mydb"
```

Apply order:

```bash
kubectl apply -f k8s/mongodb.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

---

## Step 10 — Full folder structure (recommended)

When you receive code, organize like this:

```text
my-app-service/
├── app/                    ← original source code (unchanged)
│   ├── src/
│   ├── package.json
│   └── Dockerfile
├── k8s/                    ← OR use Helm chart
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── mongodb.yaml        ← if needed
│   └── acr-secret.yaml     ← optional (prefer kubectl create secret)
├── build-images.sh
└── README.md
```

### build-images.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${REGISTRY:-xxx.azurecr.io}"
APP="${APP:-my-app-service}"
TAG="${TAG:-1.0.0}"
APP_DIR="$(cd "$(dirname "$0")/app" && pwd)"

docker build -t "${REGISTRY}/${APP}:${TAG}" "${APP_DIR}"
echo "Push: docker push ${REGISTRY}/${APP}:${TAG}"
```

---

## Step 11 — One-shot deploy checklist

```bash
# 1. Build & push
az acr login --name xxx
./build-images.sh
docker push xxx.azurecr.io/my-app-service:1.0.0

# 2. Namespace + secret
kubectl create namespace my-app-namespace
kubectl create secret docker-registry acr-pull-secret \
  --namespace my-app-namespace \
  --docker-server=xxx.azurecr.io \
  --docker-username=<user> \
  --docker-password=<pass>

# 3. Deploy
kubectl apply -f k8s/

# 4. Verify
kubectl get pods,svc -n my-app-namespace
kubectl logs -n my-app-namespace -l app=my-app-service
curl http://<EXTERNAL-IP>:3000/api/health
```

---

## Step 12 — Helm (optional, for repeat deploys)

For production teams, wrap YAML in a Helm chart (like `order-catalog-service/` in this repo).

```bash
helm upgrade --install my-app-service ./my-app-service \
  --namespace my-app-namespace \
  --create-namespace \
  --set imageCredentials.username=<acr-user> \
  --set imageCredentials.password=<acr-pass>
```

Helm benefits:

- One command upgrade
- Values file for image tag, replicas, env
- Auto-create ACR secret with `imageCredentials.create: true`

---

## Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `ImagePullBackOff` | Image not in ACR or wrong secret | Push image; check `acr-pull-secret` exists in namespace |
| `401 Unauthorized` on pull | Missing/wrong ACR secret | Recreate secret with correct credentials |
| `CrashLoopBackOff` | App crash on start | `kubectl logs` — check env vars, DB connection |
| `ErrImagePull` | Wrong image name/tag | Match deployment image with `az acr repository show-tags` |
| Probe failures | Wrong health path/port | Match readiness path to app (`/health` vs `/api/health`) |
| Secret ownership conflict (Helm) | Same secret name, different release | Use unique secret name per app or `create: false` to reuse |

---

## Naming rules (production)

| ✅ Good | ❌ Avoid |
|---------|----------|
| `my-app-service` | `test-api` |
| `order-catalog-service` | `demo-app` |
| `document-platform` (namespace) | `test-namespace` |
| `commerce-events` (namespace) | `temp` |

---

## Real example from this repo

| App | Folder | What was done |
|-----|--------|---------------|
| Order Catalog | `order-catalog-service/` | App + Dockerfile + Helm + MongoDB + LoadBalancer |
| Document Storage | `document-storage-service/` | Python Flask + PVC + ClusterIP |
| Retail Hub | `retail-hub-platform/` | 7 microservices + PG + Mongo + Redis |

Follow the same pattern for any new code you receive.

---

## Quick reference — files you must create

| # | File | Purpose |
|---|------|---------|
| 1 | `Dockerfile` | Build container image |
| 2 | `deployment.yaml` | Run app pods |
| 3 | `service.yaml` | Expose app (ClusterIP / LoadBalancer) |
| 4 | ACR secret | Pull private image |
| 5 | DB yaml (if needed) | MongoDB / Postgres in cluster |

**Application source code — change mat karo.** Sirf Dockerfile + K8s/Helm files add karo.
