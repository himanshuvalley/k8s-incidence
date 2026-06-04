# SQS Backlog Due to RDS Connection Limit

## Objective

This demo simulates a production scenario where:

```text
SQS Queue
   ↓
order-fulfillment-worker
   ↓
RDS MySQL
```

The worker consumes messages from SQS and writes them into RDS.

When RDS reaches its connection limit:

* Worker cannot acquire new database connections.
* Message processing fails.
* Messages are not deleted from SQS.
* SQS backlog increases.
* Alert should trigger when SQS messages exceed 100.

---

# Prerequisites

* Kubernetes Cluster
* Helm
* AWS CLI configured
* Existing RDS MySQL instance
* Azure Container Registry access

---

# Step 1: Create Database

Connect to RDS MySQL:

```sql
CREATE DATABASE orders;
```

Verify:

```sql
SHOW DATABASES;
```

Expected:

```text
orders
```

---

# Step 2: Create SQS Queue

Create queue:

```bash
aws sqs create-queue \
  --queue-name order-fulfillment-demo-queue \
  --region ap-south-1
```

Get queue URL:

```bash
aws sqs get-queue-url \
  --queue-name order-fulfillment-demo-queue \
  --region ap-south-1
```

Example output:

```text
https://sqs.ap-south-1.amazonaws.com/123456789012/order-fulfillment-demo-queue
```

Save this URL.

---

# Step 3: Create AWS Credentials Secret

Create secret in default namespace:

```bash
kubectl create secret generic aws-credentials \
  -n default \
  --from-literal=AWS_ACCESS_KEY_ID='<AWS_ACCESS_KEY_ID>' \
  --from-literal=AWS_SECRET_ACCESS_KEY='<AWS_SECRET_ACCESS_KEY>'
```

Verify:

```bash
kubectl get secret aws-credentials -n default
```

---

# Step 4: Deploy Application

Deploy using Helm:

```bash
helm upgrade --install order-fulfillment-worker . \
  -n default \
  --set image.repository=incidence.azurecr.io/order-fulfillment-worker \
  --set image.tag=1.0.0 \
  --set imageCredentials.enabled=true \
  --set imageCredentials.registry=incidence.azurecr.io \
  --set imageCredentials.username=incidence \
  --set imageCredentials.password=xxxxx \
  --set aws.region=ap-south-1 \
  --set aws.sqsQueueUrl="https://sqs.ap-south-1.amazonaws.com/xxxx/order-fulfillment-demo-queue" \
  --set rds.host="xxxx" \
  --set rds.port="3306" \
  --set rds.database="orders" \
  --set rds.username="admin" \
  --set rds.password="xxxx"
```

---

# Step 5: Verify Deployment

Check pods:

```bash
kubectl get pods -n default
```

Expected:

```text
order-fulfillment-worker-xxxxx   Running
```

Check logs:

```bash
kubectl logs deploy/order-fulfillment-worker -n default -f
```

Expected:

```text
Starting order-fulfillment-worker
RDS table check completed successfully
SQS worker started
```

Port forward:

```bash
kubectl port-forward svc/order-fulfillment-worker 8080:8080 -n default
```

Health check:

```bash
curl http://localhost:8080/health
```

Readiness check:

```bash
curl http://localhost:8080/ready
```

Expected:

```json
{
  "status":"ready",
  "rds":"connected"
}
```

---

# Step 6: Generate SQS Messages

Generate 150 messages:

```bash
curl -X POST \
"http://localhost:8080/simulate/enqueue?count=150"
```

Expected:

```json
{
  "status":"success",
  "messages_enqueued":150
}
```

---

# Step 7: Verify Queue Status

Check queue metrics:

```bash
aws sqs get-queue-attributes \
  --queue-url "https://sqs.ap-south-1.amazonaws.com/xxxx/order-fulfillment-demo-queue" \
  --attribute-names \
  ApproximateNumberOfMessages \
  ApproximateNumberOfMessagesNotVisible \
  ApproximateAgeOfOldestMessage
```

Example:

```text
ApproximateNumberOfMessages=150
ApproximateNumberOfMessagesNotVisible=5
ApproximateAgeOfOldestMessage=10
```

---

# Step 8: Simulate RDS Connection Pressure

Open and hold database connections:

```bash
curl \
"http://localhost:8080/simulate/rds-connection-pressure?connections=100&holdSeconds=300"
```

This will:

* Open 100 RDS connections.
* Hold them for 300 seconds.
* Exhaust available database connections.

---

# Step 9: Verify Connection Pressure

Connect to MySQL:

```sql
SHOW VARIABLES LIKE 'max_connections';
```

Check active connections:

```sql
SHOW STATUS LIKE 'Threads_connected';
```

Expected:

```text
max_connections     100
Threads_connected   95-100
```

---

# Step 10: Verify Application Failure

Check logs:

```bash
kubectl logs deploy/order-fulfillment-worker -n default -f
```

Expected:

```text
RDS write failed
Too many connections
connection pool exhausted
Message processing failed
```

---

# Step 11: Verify SQS Backlog Growth

Run:

```bash
aws sqs get-queue-attributes \
  --queue-url "https://sqs.ap-south-1.amazonaws.com/xxxx/order-fulfillment-demo-queue" \
  --attribute-names \
  ApproximateNumberOfMessages \
  ApproximateNumberOfMessagesNotVisible \
  ApproximateAgeOfOldestMessage
```

Expected:

```text
ApproximateNumberOfMessages > 100
ApproximateAgeOfOldestMessage increasing
```

This confirms messages are not being processed successfully.

---

# Step 12: Verify Metrics

Check metrics endpoint:

```bash
curl http://localhost:8080/metrics
```

Important metrics:

```text
worker_sqs_messages_received_total
worker_sqs_messages_processed_total
worker_sqs_messages_failed_total
worker_rds_write_success_total
worker_rds_write_failure_total
worker_rds_pressure_connections
```

Expected during incident:

```text
worker_rds_write_failure_total increasing
worker_sqs_messages_failed_total increasing
worker_rds_pressure_connections high
```

---

# Expected RCA

Root Cause:

```text
SQS backlog increased because order-fulfillment-worker could not acquire new database connections.

RDS reached its maximum connection limit, causing database writes to fail.

Messages were not acknowledged and remained in SQS, resulting in queue growth.
```

---

# Release Connection Pressure

Release held connections:

```bash
curl \
"http://localhost:8080/simulate/release-rds-pressure"
```

Or wait for:

```text
holdSeconds=300
```

to expire.

---

# Cleanup

Delete deployment:

```bash
helm uninstall order-fulfillment-worker -n default
```

Delete SQS queue:

```bash
aws sqs delete-queue \
  --queue-url "https://sqs.ap-south-1.amazonaws.com/xxxx/order-fulfillment-demo-queue"
```

Delete AWS secret:

```bash
kubectl delete secret aws-credentials -n default
```

