# Commerce Event Processor

Production-style incident scenario for AlertMend RCA testing.

## Architecture

```text
                    ┌─────────────────────────────────────┐
                    │  commerce-event-processor (K8s)   │
                    │                                     │
  SQS Queue ◄───────┤  Producer: 60 messages/minute       │
       │            │  Consumer: 1 message/sec (normal)   │
       │            └──────────┬──────────────┬───────────┘
       │                       │              │
       └───────────────────────┘              │
              (same app reads & writes)        │
                                               ▼
                                    RDS MySQL (external)
                                               +
                                    Elasticsearch (3 EC2 nodes)
```

| Component | Where | Notes |
|-----------|-------|-------|
| **SQS** | AWS | You provide queue URL |
| **RDS** | AWS RDS | You provide endpoint |
| **Elasticsearch** | 3 separate EC2 | You setup 3-node cluster |
| **Processor** | Kubernetes | Helm deploys this |

---

## Pipeline behaviour (normal)

| Setting | Value |
|---------|-------|
| SQS produce rate | **60 messages/minute** (1 per second) |
| Normal process rate | **1 message/second** (1 sec delay per message) |
| Flow | Producer → SQS → Worker → RDS + ES → delete from SQS |

Normal state: produce rate ≈ process rate → **SQS backlog stable (~0)**

---

## Three failure cases

| Case | Trigger | What breaks | SQS metric | Logs (clean) |
|------|---------|-------------|------------|--------------|
| **1** | External RDS connection pressure | RDS too many connections | Visible or NotVisible > 100 | `RDS too many connections` only |
| **2** | ES cluster pressure | ES write fails on 3-node cluster | NotVisible > 100 | `Elasticsearch cluster write failed` only |
| **3** | Slow message processing | 10 sec/message vs 60/min incoming | Visible > 100 | No crash, no 503 — backlog grows naturally |

> Case 3 mein **manual enqueue nahi** — app khud 60/min produce karta hai, slow processing se backlog badhta hai.

---

# Setup Guide

## Prerequisites

- Kubernetes cluster + Helm
- AWS CLI configured
- **3 EC2 instances** for Elasticsearch
- **RDS MySQL** instance
- **SQS queue**
- Azure Container Registry access

---

## Step 1: Elasticsearch on 3 EC2 nodes

Har EC2 pe (replace IPs with your private IPs):

### 1.1 System settings (all 3 nodes)

```bash
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262644" | sudo tee -a /etc/sysctl.conf
```

### 1.2 Install Docker (all 3 nodes)

```bash
sudo apt-get update
sudo apt-get install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker
```

### 1.3 Run Elasticsearch

**Node 1** (master, e.g. `10.0.1.10`):

```bash
docker run -d --name es-node-1 \
  -p 9200:9200 -p 9300:9300 \
  -e "node.name=es-node-1" \
  -e "cluster.name=commerce-event-es-cluster" \
  -e "discovery.seed_hosts=10.0.1.11,10.0.1.12" \
  -e "cluster.initial_master_nodes=es-node-1,es-node-2,es-node-3" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms1g -Xmx1g" \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.1
```

**Node 2** (`10.0.1.11`):

```bash
docker run -d --name es-node-2 \
  -p 9200:9200 -p 9300:9300 \
  -e "node.name=es-node-2" \
  -e "cluster.name=commerce-event-es-cluster" \
  -e "discovery.seed_hosts=10.0.1.10,10.0.1.12" \
  -e "cluster.initial_master_nodes=es-node-1,es-node-2,es-node-3" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms1g -Xmx1g" \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.1
```

**Node 3** (`10.0.1.12`):

```bash
docker run -d --name es-node-3 \
  -p 9200:9200 -p 9300:9300 \
  -e "node.name=es-node-3" \
  -e "cluster.name=commerce-event-es-cluster" \
  -e "discovery.seed_hosts=10.0.1.10,10.0.1.11" \
  -e "cluster.initial_master_nodes=es-node-1,es-node-2,es-node-3" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms1g -Xmx1g" \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.1
```

### 1.4 Verify cluster

```bash
curl http://10.0.1.10:9200/_cluster/health?pretty
```

Expected: `"status" : "green"` or `"yellow"`

> K8s pods se ES EC2 reachable hona chahiye — Security Group mein port **9200** allow karo worker node subnet se.

---

## Step 2: RDS MySQL

```sql
CREATE DATABASE IF NOT EXISTS commerce;
```

Note your RDS endpoint, username, password.

---

## Step 3: SQS Queue

```bash
aws sqs create-queue \
  --queue-name commerce-event-queue \
  --region ap-south-1

aws sqs get-queue-url \
  --queue-name commerce-event-queue \
  --region ap-south-1
```

---

## Step 4: AWS credentials secret

```bash
kubectl create secret generic aws-credentials \
  -n default \
  --from-literal=AWS_ACCESS_KEY_ID='YOUR_KEY' \
  --from-literal=AWS_SECRET_ACCESS_KEY='YOUR_SECRET'
```

---

## Step 5: Build and push image

```bash
cd commerce-event-processor/app

docker build --no-cache -t incidence.azurecr.io/commerce-event-processor:1.0.0 .
docker push incidence.azurecr.io/commerce-event-processor:1.0.0
```

---

## Step 6: Deploy with Helm

```bash
cd ..

helm upgrade --install commerce-event-processor . \
  -n default \
  --set image.repository=incidence.azurecr.io/commerce-event-processor \
  --set image.tag=1.0.0 \
  --set imageCredentials.enabled=true \
  --set imageCredentials.registry=incidence.azurecr.io \
  --set imageCredentials.username=incidence \
  --set imageCredentials.password=xxxxxx \
  --set aws.region=ap-south-1 \
  --set aws.sqsQueueUrl="https://sqs.ap-south-1.amazonaws.com/ACCOUNT_ID/commerce-event-queue" \
  --set rds.host="your-rds-endpoint.rds.amazonaws.com" \
  --set rds.password="xxxxxx" \
  --set elasticsearch.hosts="{10.0.1.10:9200,10.0.1.11:9200,10.0.1.12:9200}"
```

---

## Step 7: Verify healthy baseline

```bash
kubectl get pods -n default -l app.kubernetes.io/name=commerce-event-processor

kubectl port-forward svc/commerce-event-processor 8080:8080 -n default

curl http://localhost:8080/ready
curl http://localhost:8080/metrics | grep sync_
```

Expected ready:

```json
{
  "status": "ready",
  "producer_rate_per_minute": 60,
  "process_delay_seconds": 1
}
```

Wait 2-3 minutes — SQS should stay low (produce ≈ consume):

```bash
aws sqs get-queue-attributes \
  --queue-url "YOUR_QUEUE_URL" \
  --attribute-names All
```

---

# Test Case 1 — RDS Too Many Connections

## What happens

External RDS connection pressure → worker cannot get DB connection → messages not deleted → SQS backlog grows.

## Trigger

```bash
# Step 1: Start RDS pressure FIRST
curl "http://localhost:8080/simulate/rds-connection-pressure?connections=80&holdSeconds=600"

# Step 2: Wait and verify connections held
sleep 15
curl "http://localhost:8080/simulate/rds-pressure-status"
# held_connection_count should be 70+

# Step 3: Wait 3-5 min for producer to fill SQS while RDS blocked
```

## Expected logs (clean — only RDS errors)

```text
ERROR RDS too many connections: transaction_id=TXN-xxx error=(1040, 'Too many connections')
```

No `503`, no `startup failed`, no `CrashLoopBackOff`.

## Expected SQS

```bash
aws sqs get-queue-attributes --queue-url "YOUR_QUEUE_URL" --attribute-names All
```

| Metric | Expected |
|--------|----------|
| `ApproximateNumberOfMessages` | > 100 |
| `ApproximateNumberOfMessagesNotVisible` | may also increase |

## Alert

```text
Name:      sqsVisibleMessagesExceedingProcessingThreshold
Query:     max(aws_sqs_approximate_number_of_messages_visible_average{dimension_queue_name="commerce-event-queue"})
Condition: > 100 for 5m
```

## Recovery

```bash
curl "http://localhost:8080/simulate/release-rds-pressure"
```

---

# Test Case 2 — Elasticsearch Cluster Problem

## What happens

App floods the **3-node ES cluster** with heavy bulk indexing (large docs, high rate).
ES JVM heap and CPU spike → worker index writes timeout/reject → messages stay in SQS.

**Important:** This hits the real ES cluster — ES metrics WILL change (unlike app-only block).

## Trigger

```bash
curl "http://localhost:8080/simulate/es-cluster-pressure?enabled=true&holdSeconds=600&parallelWorkers=4&batchSize=1000&delay=0.01&blobSizeKb=64"
```

Default **600 seconds (10 min)** tak ES cluster pe 4 parallel bulk workers se heavy load chalega.
Worker ES timeout pressure ke dauran **2s** ho jata hai aur batch size **10** + visibility **300s** — isse `NotVisible` > 100 build hona chahiye.

Monitor ES pressure:

```bash
curl "http://localhost:8080/simulate/es-pressure-status"
```

Expected while running:
```json
{
  "es_pressure_active": true,
  "hold_seconds": 600,
  "elapsed_seconds": 120.5,
  "remaining_seconds": 479.5,
  "docs_indexed": 45000,
  "docs_failed": 120
}
```

Monitor ES cluster JVM/CPU on EC2 nodes:

```bash
curl "http://ES_NODE1_PUBLIC_IP:9200/_nodes/stats/jvm,process,thread_pool?pretty"
curl "http://ES_NODE1_PUBLIC_IP:9200/_cluster/health?pretty"
```

## Expected ES metrics impact

| ES Metric | Expected |
|-----------|----------|
| `jvm.mem.heap_used_percent` | **↑ 80-95%** |
| `process.cpu.percent` | **↑ High** |
| `thread_pool.write.rejected` | **↑ Increasing** |
| `cluster.health` | `yellow` or `red` |
| `indexing.index_total` rate | Very high (bulk flood) |

## Expected logs

```text
ERROR Elasticsearch cluster write failed: transaction_id=TXN-xxx error=ConnectionTimeout(...)
ERROR Elasticsearch cluster write failed: transaction_id=TXN-xxx error=RejectedExecutionException(...)
```

No RDS errors, no 503, no crash.

## Expected SQS

```bash
aws sqs get-queue-attributes --queue-url "YOUR_QUEUE_URL" --attribute-names All
```

| Metric | Expected |
|--------|----------|
| `ApproximateNumberOfMessages` | 0 or low |
| `ApproximateNumberOfMessagesNotVisible` | > 100 |

## Alert

```text
Name:      sqsInFlightMessagesExceedingProcessingThreshold
Query:     max(aws_sqs_approximate_number_of_messages_not_visible_average{dimension_queue_name="commerce-event-queue"})
Condition: > 100 for 5m
```

## Expected RCA

```text
SQS backlog increased because commerce-event-processor could not index events to Elasticsearch.
Elasticsearch cluster was under resource pressure (high JVM heap / CPU / write rejections).
```

## Recovery

```bash
curl "http://localhost:8080/simulate/es-cluster-pressure?enabled=false"
```

Wait for ES JVM/CPU to settle (~5-10 min on small EC2 nodes).

---

# Test Case 3 — Slow Message Processing (Natural SQS Backlog)

## What happens

| | Rate |
|--|------|
| Producer (built-in) | 60 messages/minute = **1/sec incoming** |
| Normal processing | 1 message/sec |
| Slow mode | **1 message per 10 sec** = 6/min |

Net accumulation in slow mode: **60 - 6 = 54 messages/minute** → backlog crosses 100 in ~**2 minutes**.

No manual enqueue. No external trigger except enabling slow mode.

## Trigger

```bash
curl "http://localhost:8080/simulate/slow-processing?enabled=true&delaySeconds=10"
```

## Expected behaviour

- Pod stays **Running** (no CrashLoopBackOff)
- Logs stay **clean** — no error spam
- SQS **Visible** messages grow steadily
- After ~2-3 min: **SQS > 100**

## Verify

```bash
# Every 30 sec check
aws sqs get-queue-attributes \
  --queue-url "YOUR_QUEUE_URL" \
  --attribute-names All

curl http://localhost:8080/ready
# process_delay_seconds: 10
```

| Metric | Expected |
|--------|----------|
| `ApproximateNumberOfMessages` | **> 100** (growing) |
| `ApproximateNumberOfMessagesNotVisible` | low (1-5) |

## Alert

```text
Name:      sqsVisibleMessagesExceedingProcessingThreshold
Query:     max(aws_sqs_approximate_number_of_messages_visible_average{dimension_queue_name="commerce-event-queue"})
Condition: > 100 for 5m
```

## Expected RCA

```text
SQS backlog increased because commerce-event-processor message processing slowed to 10 seconds per message.
Incoming rate is 60 messages/minute but processing rate dropped to 6 messages/minute.
Messages accumulated in the queue exceeding the processing threshold.
```

## Recovery

```bash
curl "http://localhost:8080/simulate/slow-processing?enabled=false"
# Back to 1 sec/message — backlog will drain over time


---

# Alert summary (all 3 cases)

| Case | Alert name | Primary metric |
|------|-----------|----------------|
| 1 — RDS connections | `sqsVisibleMessagesExceedingProcessingThreshold` | Visible > 100 |
| 2 — ES cluster | `sqsInFlightMessagesExceedingProcessingThreshold` | NotVisible > 100 |
| 3 — Slow processing | `sqsVisibleMessagesExceedingProcessingThreshold` | Visible > 100 |

**Universal (covers all 3):**

```text
Name:  sqsBacklogMessagesExceedingProcessingThreshold
Query: max(aws_sqs_approximate_number_of_messages_visible_average{dimension_queue_name="commerce-event-queue"})
     + max(aws_sqs_approximate_number_of_messages_not_visible_average{dimension_queue_name="commerce-event-queue"})
Condition: > 100 for 5m
```

---

# Cleanup

```bash
helm uninstall commerce-event-processor -n default

aws sqs delete-queue --queue-url "YOUR_QUEUE_URL"

kubectl delete secret aws-credentials -n default
```

On each ES EC2:

```bash
docker stop es-node-1 && docker rm es-node-1
```
