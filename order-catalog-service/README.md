# Order Catalog Service

Production-style Node.js service (users, products, orders) with MongoDB — for distributed tracing demos.

## Deployed resources

| Resource | Name |
|----------|------|
| App Deployment | `order-catalog-service` |
| App Service (LB) | `order-catalog-service` :3000 |
| MongoDB | `order-catalog-service-mongodb` |
| ACR pull secret | `order-catalog-service-acr-secret` (auto-created) |
| Image | `incidence.azurecr.io/order-catalog-service:1.0.0` |

---

## Build & push

```bash
az acr login --name incidence

cd order-catalog-service
chmod +x build-images.sh
./build-images.sh
docker push incidence.azurecr.io/order-catalog-service:1.0.0
```

---

## Deploy (new namespace — secret auto-created)

```bash
helm upgrade --install order-catalog-service . \
  --namespace commerce-events \
  --create-namespace \
  --set imageCredentials.username=<acr-user> \
  --set imageCredentials.password=<acr-pass>
```

Helm creates `order-catalog-service-acr-secret` in the same namespace automatically.

---

## Deploy (reuse existing secret in prod)

If `acr-registry-secret` already exists from another release:

```bash
helm upgrade --install order-catalog-service . \
  --namespace prod \
  --set imageCredentials.create=false \
  --set imageCredentials.secretName=acr-registry-secret
```

---

## URL

```bash
kubectl get svc -n commerce-events order-catalog-service
```

```bash
curl http://<EXTERNAL-IP>:3000/api/health
curl http://<EXTERNAL-IP>:3000/api/dashboard
```

---

## Uninstall

```bash
helm uninstall order-catalog-service -n commerce-events
kubectl delete pvc order-catalog-service-mongodb -n commerce-events
```
