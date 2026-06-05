# Order Event Ingestion Worker

Production-style incident scenario for AlertMend RCA testing.

## Pipeline

```text
SQS Queue (AWS - you provide)
   ↓
order-event-ingestion-worker (K8s)
   ↓
RDS MySQL (you provide)  +  Elasticsearch (K8s - auto deployed by Helm)
```

The worker consumes order events from SQS, writes each event to **RDS**, indexes it in **Elasticsearch**, and only then deletes the message from SQS.

**Elasticsearch runs inside your Kubernetes cluster** — no separate ES setup needed. Helm deploys it automatically.

**Alert condition:** SQS visible messages > 100

---

## Three Failure Cases

| Case | Failure | How to trigger | Expected symptom |
|------|---------|----------------|------------------|
| **1** | RDS connection limit reached | `/simulate/rds-connection-pressure` | RDS writes fail, SQS backlog grows |
| **2** | Elasticsearch under pressure (JVM/CPU/memory) | `/simulate/es-index-pressure` + `/simulate/es-write-block` | ES index fails, SQS backlog grows |
| **3** | Application failed to start after new release | Redeploy with `app.startupFailure=true` | Pod CrashLoopBackOff, no processing, SQS backlog grows |

---

## Prerequisites

- Kubernetes cluster + Helm
- AWS CLI configured
- **RDS MySQL** — you provide endpoint + credentials
- **SQS Queue** — you provide queue URL
- Azure Container Registry access
- Docker (to build and push worker image)

> Elasticsearch is **not** needed externally. It deploys automatically inside K8s with this chart (`elasticsearch.deployInCluster=true` by default).

---

## Step 1: Build and Push Image

```bash
cd order-event-ingestion-worker/app

docker build --no-cache -t incidence.azurecr.io/order-event-ingestion-worker:1.0.0 .
docker push incidence.azurecr.io/order-event-ingestion-worker:1.0.0
```

> **Important:** Code change ke baad `--no-cache` se rebuild karna zaroori hai. Purani image mein `init_es()` startup pe crash karta tha — nayi image mein ye fix hai.

---

## Step 2: Create RDS Database

Connect to RDS and run:

```sql
CREATE DATABASE IF NOT EXISTS orders;
```

---

## Step 3: Create SQS Queue

```bash
aws sqs create-queue \
  --queue-name order-event-ingestion-queue \
  --region ap-south-1

aws sqs get-queue-url \
  --queue-name order-event-ingestion-queue \
  --region ap-south-1
```

Save the queue URL.

---

## Step 4: Create AWS Credentials Secret

```bash
kubectl create secret generic aws-credentials \
  -n default \
  --from-literal=AWS_ACCESS_KEY_ID='<AWS_ACCESS_KEY_ID>' \
  --from-literal=AWS_SECRET_ACCESS_KEY='<AWS_SECRET_ACCESS_KEY>'
```

---

## Step 5: Deploy (Healthy Baseline)

Elasticsearch + worker dono ek saath deploy honge:

```bash
helm upgrade --install order-event-ingestion-worker . \
  -n default \
  --set image.repository=incidence.azurecr.io/order-event-ingestion-worker \
  --set image.tag=1.0.0 \
  --set imageCredentials.enabled=true \
  --set imageCredentials.registry=incidence.azurecr.io \
  --set imageCredentials.username=incidence \
  --set imageCredentials.password=xxxxxx \
  --set app.releaseVersion=1.0.0 \
  --set app.startupFailure=false \
  --set aws.region=ap-south-1 \
  --set aws.sqsQueueUrl="https://sqs.ap-south-1.amazonaws.com/ACCOUNT_ID/order-event-ingestion-queue" \
  --set rds.host="your-rds-endpoint.rds.amazonaws.com" \
  --set rds.port="3306" \
  --set rds.database="orders" \
  --set rds.username="admin" \
  --set rds.password="xxxxxx" \
  --set elasticsearch.deployInCluster=true \
  --set elasticsearch.index="order-events"
```

> **Note:** `elasticsearch.host` set karne ki zaroorat nahi — Helm automatically worker ko in-cluster ES service se connect karega: `order-event-ingestion-worker-elasticsearch:9200`

---

## Step 6: Verify Deployment

```bash
# Worker pod
kubectl get pods -n default -l app.kubernetes.io/name=order-event-ingestion-worker

# Elasticsearch pod (auto deployed)
kubectl get pods -n default -l app.kubernetes.io/component=elasticsearch

kubectl logs deploy/order-event-ingestion-worker -n default -f
```

Expected logs:

```text
Starting order-event-ingestion-worker release=1.0.0
Waiting for Elasticsearch at order-event-ingestion-worker-elasticsearch:9200 (attempt 1)...
Elasticsearch reachable at order-event-ingestion-worker-elasticsearch:9200 after 3 attempts
RDS schema check completed
Elasticsearch index exists: order-events
All dependencies ready, worker is operational
SQS ingestion worker started
```

> **Startup order:**
> 1. ES pod start hota hai (~1-2 min)
> 2. Worker init container (busybox) ES ready hone tak wait karta hai
> 3. Worker app start hota hai — ES/RDS background mein connect hota hai, **crash nahi karta**
> 4. `/ready` tab pass hota hai jab sab connected ho

Verify Elasticsearch is healthy:

```bash
kubectl port-forward svc/order-event-ingestion-worker-elasticsearch 9200:9200 -n default

curl http://localhost:9200/_cluster/health?pretty
```

Expected:

```json
{
  "cluster_name": "order-event-ingestion-es",
  "status": "green" or "yellow"
}
```

Port forward worker:

```bash
kubectl port-forward svc/order-event-ingestion-worker 8080:8080 -n default
```

Health check:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/ready
```

Expected readiness:

```json
{
  "status": "ready",
  "rds": "connected",
  "elasticsearch": "connected",
  "release_version": "1.0.0"
}
```

---

## Step 7: Load SQS with Messages

Generate 150 messages (above the 100 alert threshold):

```bash
curl -X POST "http://localhost:8080/simulate/enqueue?count=150"
```

Verify queue:

```bash
aws sqs get-queue-attributes \
  --queue-url "https://sqs.ap-south-1.amazonaws.com/ACCOUNT_ID/order-event-ingestion-queue" \
  --attribute-names ApproximateNumberOfMessages ApproximateAgeOfOldestMessage
```

Wait until worker drains messages (queue should go down). Then enqueue again before each failure test.

---

# Test Case 1 — RDS Connection Limit

## Trigger

```bash
curl "http://localhost:8080/simulate/rds-connection-pressure?connections=100&holdSeconds=300"
```

This opens 100 RDS connections and holds them for 300 seconds.

## Verify

Check RDS:

```sql
SHOW VARIABLES LIKE 'max_connections';
SHOW STATUS LIKE 'Threads_connected';
```

Check worker logs:

```bash
kubectl logs deploy/order-event-ingestion-worker -n default -f
```

Expected:

```text
RDS write failed order_id=ORD-xxx error=(1040, 'Too many connections')
Message not acknowledged. rds_ok=False es_ok=True
```

Check SQS backlog:

```bash
aws sqs get-queue-attributes \
  --queue-url "YOUR_QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages
```

Expected: `ApproximateNumberOfMessages > 100`

## Expected RCA

```text
SQS backlog increased because order-event-ingestion-worker could not write to RDS.
RDS reached its maximum connection limit, causing write failures.
Messages were not deleted from SQS and the queue backlog grew.
```

## Recovery

```bash
curl "http://localhost:8080/simulate/release-rds-pressure"
```

---

# Test Case 2 — Elasticsearch Resource Pressure

Simulates ES cluster under stress (high JVM heap, CPU, indexing load). ES runs **inside K8s** — bulk indexing will push JVM/memory on the ES pod.

## Trigger (two steps)

**Step A** — Flood in-cluster ES with bulk indexing (raises JVM/CPU on ES pod):

```bash
curl "http://localhost:8080/simulate/es-index-pressure?documents=10000&batchSize=500&delay=0.2"
```

Monitor ES JVM/memory while pressure runs:

```bash
kubectl top pod -n default -l app.kubernetes.io/component=elasticsearch

curl http://localhost:9200/_nodes/stats/jvm,process?pretty
```

**Step B** — Block worker ES writes (simulates ingestion failures when ES is overloaded):

```bash
curl "http://localhost:8080/simulate/es-write-block?enabled=true"
```

## Verify

Check worker logs:

```text
Elasticsearch write blocked (simulated ES pressure) order_id=ORD-xxx
Message not acknowledged. rds_ok=True es_ok=False
```

Check SQS:

```bash
aws sqs get-queue-attributes \
  --queue-url "YOUR_QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateAgeOfOldestMessage
```

Expected: backlog > 100 and age increasing.

Check metrics:

```bash
curl http://localhost:8080/metrics | grep ingestion_es
```

Expected:

```text
ingestion_es_index_failure_total increasing
ingestion_sqs_messages_failed_total increasing
```

## Expected RCA

```text
SQS backlog increased because order-event-ingestion-worker could not index events to Elasticsearch.
Elasticsearch cluster was under resource pressure (high JVM/memory/CPU), causing index write failures.
Messages remained in SQS because both RDS and ES writes must succeed before acknowledgment.
```

## Recovery

```bash
curl "http://localhost:8080/simulate/es-write-block?enabled=false"
curl "http://localhost:8080/simulate/stop-es-pressure"
```

---

# Test Case 3 — Application Not Started After New Release

Simulates a bad deployment where the new release fails startup (migration error, config mismatch).

## Trigger

Redeploy with a new release version and startup failure enabled:

```bash
helm upgrade --install order-event-ingestion-worker . \
  -n default \
  --set image.repository=incidence.azurecr.io/order-event-ingestion-worker \
  --set image.tag=1.0.0 \
  --set imageCredentials.enabled=true \
  --set imageCredentials.registry=incidence.azurecr.io \
  --set imageCredentials.username=incidence \
  --set imageCredentials.password=xxxxxx \
  --set app.releaseVersion=1.0.1 \
  --set app.startupFailure=true \
  --set aws.region=ap-south-1 \
  --set aws.sqsQueueUrl="YOUR_QUEUE_URL" \
  --set rds.host="your-rds-endpoint" \
  --set rds.port="3306" \
  --set rds.database="orders" \
  --set rds.username="admin" \
  --set rds.password="xxxxxx" \
  --set elasticsearch.deployInCluster=true \
  --set elasticsearch.index="order-events"
```

## Verify

Check pod status:

```bash
kubectl get pods -n default -l app.kubernetes.io/name=order-event-ingestion-worker
```

Expected:

```text
order-event-ingestion-worker-xxxxx   0/1   CrashLoopBackOff
```

Check logs:

```bash
kubectl logs deploy/order-event-ingestion-worker -n default --previous
```

Expected:

```text
Release 1.0.1 failed startup: database migration checksum mismatch. Application will not start.
```

Enqueue messages (they will not be processed):

```bash
# Port-forward from a previous healthy pod won't work — enqueue via AWS CLI instead:
for i in $(seq 1 150); do
  aws sqs send-message \
    --queue-url "YOUR_QUEUE_URL" \
    --message-body "{\"order_id\":\"ORD-$i\",\"event_type\":\"ORDER_CREATED\"}"
done
```

Check SQS backlog:

```bash
aws sqs get-queue-attributes \
  --queue-url "YOUR_QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages
```

Expected: > 100 and not decreasing.

## Expected RCA

```text
SQS backlog increased because order-event-ingestion-worker release 1.0.1 failed to start.
The new deployment crashed on startup due to a migration/config error.
No worker was running to consume messages from SQS.
```

## Recovery

Redeploy healthy release:

```bash
helm upgrade --install order-event-ingestion-worker . \
  -n default \
  --set app.releaseVersion=1.0.0 \
  --set app.startupFailure=false \
  ... (same values as Step 5)
```

---

## Metrics Endpoint

```bash
curl http://localhost:8080/metrics
```

Key metrics:

| Metric | Description |
|--------|-------------|
| `ingestion_sqs_messages_received_total` | Messages pulled from SQS |
| `ingestion_sqs_messages_processed_total` | Successfully processed |
| `ingestion_sqs_messages_failed_total` | Failed processing |
| `ingestion_rds_write_failure_total` | RDS write failures |
| `ingestion_es_index_failure_total` | ES index failures |
| `ingestion_rds_pressure_connections` | Active RDS pressure connections |
| `ingestion_es_pressure_active` | ES pressure simulation active |

---

## Cleanup

```bash
helm uninstall order-event-ingestion-worker -n default

aws sqs delete-queue \
  --queue-url "YOUR_QUEUE_URL"

kubectl delete secret aws-credentials -n default
```

This removes both the worker **and** the in-cluster Elasticsearch deployment.

---

## Optional: Use External Elasticsearch

Agar tum apna external ES use karna chahte ho:

```bash
helm upgrade --install order-event-ingestion-worker . \
  ... \
  --set elasticsearch.deployInCluster=false \
  --set elasticsearch.host="your-external-es-host" \
  --set elasticsearch.port="9200"
```
