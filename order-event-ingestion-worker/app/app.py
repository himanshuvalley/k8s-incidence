import os
import time
import json
import uuid
import signal
import logging
import threading
from datetime import datetime

import boto3
import pymysql
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from flask import Flask, jsonify, request
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# =========================
# Environment
# =========================
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "orders")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

ES_HOST = os.getenv("ES_HOST")
ES_PORT = int(os.getenv("ES_PORT", "9200"))
ES_INDEX = os.getenv("ES_INDEX", "order-events")
ES_USERNAME = os.getenv("ES_USERNAME", "")
ES_PASSWORD = os.getenv("ES_PASSWORD", "")
ES_USE_SSL = os.getenv("ES_USE_SSL", "false").lower() == "true"

WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").lower() == "true"
WORKER_POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "5"))
WORKER_BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", "5"))

DEPENDENCY_WAIT_SECONDS = int(os.getenv("DEPENDENCY_WAIT_SECONDS", "300"))
DEPENDENCY_WAIT_INTERVAL = int(os.getenv("DEPENDENCY_WAIT_INTERVAL", "5"))

SERVICE_NAME = os.getenv("SERVICE_NAME", "order-event-ingestion-worker")
RELEASE_VERSION = os.getenv("RELEASE_VERSION", "1.0.0")
STARTUP_FAILURE = os.getenv("STARTUP_FAILURE", "false").lower() == "true"

# =========================
# Metrics
# =========================
sqs_messages_received_total = Counter(
    "ingestion_sqs_messages_received_total",
    "Total SQS messages received"
)
sqs_messages_processed_total = Counter(
    "ingestion_sqs_messages_processed_total",
    "Total SQS messages successfully processed"
)
sqs_messages_failed_total = Counter(
    "ingestion_sqs_messages_failed_total",
    "Total SQS messages failed processing"
)
rds_write_success_total = Counter(
    "ingestion_rds_write_success_total",
    "Successful RDS writes"
)
rds_write_failure_total = Counter(
    "ingestion_rds_write_failure_total",
    "Failed RDS writes"
)
es_index_success_total = Counter(
    "ingestion_es_index_success_total",
    "Successful Elasticsearch index operations"
)
es_index_failure_total = Counter(
    "ingestion_es_index_failure_total",
    "Failed Elasticsearch index operations"
)
rds_pressure_connections = Gauge(
    "ingestion_rds_pressure_connections",
    "RDS pressure connections currently held"
)
es_pressure_active = Gauge(
    "ingestion_es_pressure_active",
    "Elasticsearch pressure simulation active (1=yes)"
)
worker_running = Gauge(
    "ingestion_worker_running",
    "Worker loop running status"
)

# =========================
# Clients & state
# =========================
sqs = boto3.client("sqs", region_name=AWS_REGION)

held_rds_connections = []
held_rds_lock = threading.Lock()
stop_event = threading.Event()
es_write_blocked = threading.Event()
es_pressure_stop = threading.Event()


def build_es_client():
    scheme = "https" if ES_USE_SSL else "http"
    hosts = [{"host": ES_HOST, "port": ES_PORT, "scheme": scheme}]

    kwargs = {
        "hosts": hosts,
        "request_timeout": 10,
        "max_retries": 1,
        "retry_on_timeout": False,
    }

    if ES_USERNAME and ES_PASSWORD:
        kwargs["basic_auth"] = (ES_USERNAME, ES_PASSWORD)

    return Elasticsearch(**kwargs)


es_client = None
dependencies_ready = False
dependencies_lock = threading.Lock()


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
        autocommit=True
    )


def get_pressure_db_connection():
    """Long-lived connections for RDS exhaustion simulation."""
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
        autocommit=True
    )


def init_rds():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS order_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                order_id VARCHAR(100) NOT NULL,
                event_type VARCHAR(100) NOT NULL,
                payload JSON NULL,
                release_version VARCHAR(50),
                indexed_to_es TINYINT(1) DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    conn.close()
    logging.info("RDS schema check completed")


def init_es(client=None):
    global es_client
    es_client = client or build_es_client()

    if not es_client.ping():
        raise RuntimeError(f"Elasticsearch unreachable at {ES_HOST}:{ES_PORT}")

    if not es_client.indices.exists(index=ES_INDEX):
        es_client.indices.create(
            index=ES_INDEX,
            body={
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "properties": {
                        "order_id": {"type": "keyword"},
                        "event_type": {"type": "keyword"},
                        "release_version": {"type": "keyword"},
                        "created_at": {"type": "date"},
                        "payload": {"type": "object", "enabled": True}
                    }
                }
            }
        )
        logging.info("Elasticsearch index created: %s", ES_INDEX)
    else:
        logging.info("Elasticsearch index exists: %s", ES_INDEX)


def wait_for_elasticsearch():
    deadline = time.time() + DEPENDENCY_WAIT_SECONDS
    attempt = 0

    while time.time() < deadline and not stop_event.is_set():
        attempt += 1
        try:
            client = build_es_client()
            if client.ping():
                logging.info(
                    "Elasticsearch reachable at %s:%s after %s attempts",
                    ES_HOST, ES_PORT, attempt
                )
                return client
        except Exception as e:
            logging.warning(
                "Waiting for Elasticsearch at %s:%s (attempt %s): %s",
                ES_HOST, ES_PORT, attempt, e
            )
        time.sleep(DEPENDENCY_WAIT_INTERVAL)

    raise RuntimeError(
        f"Elasticsearch not ready at {ES_HOST}:{ES_PORT} "
        f"after {DEPENDENCY_WAIT_SECONDS}s"
    )


def wait_for_rds():
    deadline = time.time() + DEPENDENCY_WAIT_SECONDS
    attempt = 0

    while time.time() < deadline and not stop_event.is_set():
        attempt += 1
        try:
            conn = get_db_connection()
            conn.close()
            logging.info("RDS reachable at %s after %s attempts", DB_HOST, attempt)
            return
        except Exception as e:
            logging.warning(
                "Waiting for RDS at %s (attempt %s): %s",
                DB_HOST, attempt, e
            )
        time.sleep(DEPENDENCY_WAIT_INTERVAL)

    raise RuntimeError(
        f"RDS not ready at {DB_HOST} after {DEPENDENCY_WAIT_SECONDS}s"
    )


def bootstrap_dependencies():
    global dependencies_ready

    while not stop_event.is_set():
        try:
            logging.info("Bootstrapping dependencies...")
            wait_for_rds()
            init_rds()

            client = wait_for_elasticsearch()
            init_es(client)

            with dependencies_lock:
                dependencies_ready = True

            if WORKER_ENABLED:
                threading.Thread(target=worker_loop, daemon=True).start()
                logging.info("SQS ingestion worker started")

            logging.info("All dependencies ready, worker is operational")
            return

        except Exception as e:
            logging.warning("Bootstrap retry in %ss: %s", DEPENDENCY_WAIT_INTERVAL, e)
            with dependencies_lock:
                dependencies_ready = False
            time.sleep(DEPENDENCY_WAIT_INTERVAL)


def write_order_to_rds(order_id, event_type, payload):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO order_events
                (order_id, event_type, payload, release_version)
                VALUES (%s, %s, %s, %s)
                """,
                (order_id, event_type, json.dumps(payload), RELEASE_VERSION)
            )
        rds_write_success_total.inc()
        return True
    except Exception as e:
        rds_write_failure_total.inc()
        logging.error("RDS write failed order_id=%s error=%s", order_id, e)
        return False
    finally:
        if conn:
            conn.close()


def index_order_to_es(order_id, event_type, payload):
    if es_client is None:
        es_index_failure_total.inc()
        logging.error("Elasticsearch client not initialized order_id=%s", order_id)
        return False

    if es_write_blocked.is_set():
        es_index_failure_total.inc()
        logging.error(
            "Elasticsearch write blocked (simulated ES pressure) order_id=%s",
            order_id
        )
        return False

    doc = {
        "order_id": order_id,
        "event_type": event_type,
        "release_version": RELEASE_VERSION,
        "created_at": datetime.utcnow().isoformat(),
        "payload": payload
    }

    try:
        es_client.index(
            index=ES_INDEX,
            id=f"{order_id}-{uuid.uuid4().hex[:8]}",
            document=doc
        )
        es_index_success_total.inc()
        return True
    except Exception as e:
        es_index_failure_total.inc()
        logging.error("Elasticsearch index failed order_id=%s error=%s", order_id, e)
        return False


def process_message(message):
    body = json.loads(message.get("Body", "{}"))
    order_id = body.get("order_id", str(uuid.uuid4()))
    event_type = body.get("event_type", "ORDER_CREATED")

    logging.info("Processing order_id=%s event_type=%s", order_id, event_type)

    rds_ok = write_order_to_rds(order_id, event_type, body)
    es_ok = index_order_to_es(order_id, event_type, body)

    if not rds_ok or not es_ok:
        sqs_messages_failed_total.inc()
        logging.error(
            "Message not acknowledged. rds_ok=%s es_ok=%s order_id=%s",
            rds_ok, es_ok, order_id
        )
        return False

    sqs.delete_message(
        QueueUrl=SQS_QUEUE_URL,
        ReceiptHandle=message["ReceiptHandle"]
    )
    sqs_messages_processed_total.inc()
    logging.info("Message processed and deleted order_id=%s", order_id)
    return True


def worker_loop():
    worker_running.set(1)

    while not stop_event.is_set():
        try:
            response = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=WORKER_BATCH_SIZE,
                WaitTimeSeconds=5,
                VisibilityTimeout=30
            )

            messages = response.get("Messages", [])

            if not messages:
                time.sleep(WORKER_POLL_INTERVAL)
                continue

            for message in messages:
                sqs_messages_received_total.inc()
                process_message(message)

        except Exception as e:
            sqs_messages_failed_total.inc()
            logging.error("Worker loop error: %s", e)
            time.sleep(WORKER_POLL_INTERVAL)

    worker_running.set(0)


def run_es_bulk_pressure(total_docs, batch_size, delay_seconds):
    es_pressure_active.set(1)
    es_pressure_stop.clear()

    indexed = 0
    failed = 0

    logging.warning(
        "Starting ES bulk pressure: total_docs=%s batch_size=%s",
        total_docs, batch_size
    )

    while indexed < total_docs and not es_pressure_stop.is_set():
        actions = []
        for _ in range(min(batch_size, total_docs - indexed)):
            doc_id = uuid.uuid4().hex
            actions.append({
                "_index": ES_INDEX,
                "_id": f"pressure-{doc_id}",
                "_source": {
                    "order_id": f"PRESSURE-{doc_id[:10]}",
                    "event_type": "ES_PRESSURE",
                    "release_version": RELEASE_VERSION,
                    "created_at": datetime.utcnow().isoformat(),
                    "payload": {
                        "pressure": True,
                        "blob": "x" * 4096
                    }
                }
            })

        try:
            success, errors = bulk(es_client, actions, raise_on_error=False)
            indexed += success
            failed += len(errors) if errors else 0
            logging.warning(
                "ES bulk pressure progress indexed=%s/%s failed=%s",
                indexed, total_docs, failed
            )
        except Exception as e:
            failed += len(actions)
            logging.error("ES bulk pressure batch failed: %s", e)

        time.sleep(delay_seconds)

    es_pressure_active.set(0)
    logging.warning(
        "ES bulk pressure finished indexed=%s failed=%s", indexed, failed
    )


# =========================
# HTTP routes
# =========================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": SERVICE_NAME,
        "release_version": RELEASE_VERSION
    })


@app.route("/ready", methods=["GET"])
def ready():
    if STARTUP_FAILURE:
        return jsonify({
            "status": "not_ready",
            "reason": "startup_failure_simulation"
        }), 503

    if not dependencies_ready or es_client is None:
        return jsonify({
            "status": "starting",
            "message": "Waiting for RDS and Elasticsearch to become ready"
        }), 503

    try:
        conn = get_db_connection()
        conn.close()
    except Exception as e:
        return jsonify({
            "status": "not_ready",
            "rds": "failed",
            "error": str(e)
        }), 503

    try:
        if not es_client.ping():
            raise RuntimeError("Elasticsearch ping failed")
    except Exception as e:
        return jsonify({
            "status": "not_ready",
            "elasticsearch": "failed",
            "error": str(e)
        }), 503

    return jsonify({
        "status": "ready",
        "rds": "connected",
        "elasticsearch": "connected",
        "release_version": RELEASE_VERSION
    })


@app.route("/metrics", methods=["GET"])
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/simulate/enqueue", methods=["POST"])
def simulate_enqueue():
    count = int(request.args.get("count", "150"))

    for i in range(count):
        payload = {
            "order_id": f"ORD-{uuid.uuid4().hex[:10]}",
            "event_type": "ORDER_CREATED",
            "amount": 100 + i,
            "created_at": datetime.utcnow().isoformat()
        }
        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(payload)
        )

    logging.info("Enqueued %s messages to SQS", count)
    return jsonify({"status": "success", "messages_enqueued": count})


@app.route("/simulate/rds-connection-pressure", methods=["GET", "POST"])
def simulate_rds_connection_pressure():
    connections = int(request.args.get("connections", "100"))
    hold_seconds = int(request.args.get("holdSeconds", "300"))
    ramp_delay = float(request.args.get("rampDelay", "0.1"))

    def hold_connection(index):
        conn = None
        try:
            conn = get_pressure_db_connection()

            with conn.cursor() as cursor:
                cursor.execute("SELECT CONNECTION_ID()")
                connection_id = cursor.fetchone()[0]

            with held_rds_lock:
                held_rds_connections.append({
                    "conn": conn,
                    "connection_id": connection_id,
                    "opened_at": time.time(),
                })
                rds_pressure_connections.set(len(held_rds_connections))

            logging.warning(
                "Holding RDS pressure connection %s/%s mysql_id=%s for %ss",
                index, connections, connection_id, hold_seconds
            )

            deadline = time.time() + hold_seconds
            while time.time() < deadline and not stop_event.is_set():
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                time.sleep(5)

            logging.warning(
                "RDS pressure connection %s mysql_id=%s hold period completed",
                index, connection_id
            )

        except Exception as e:
            logging.error("RDS pressure connection %s failed: %s", index, e)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

            with held_rds_lock:
                held_rds_connections[:] = [
                    item for item in held_rds_connections
                    if item.get("conn") is not conn
                ]
                rds_pressure_connections.set(len(held_rds_connections))

    for i in range(connections):
        threading.Thread(
            target=hold_connection,
            args=(i + 1,),
            daemon=True
        ).start()
        time.sleep(ramp_delay)

    return jsonify({
        "status": "started",
        "failure_case": "rds_connection_limit",
        "connections_requested": connections,
        "hold_seconds": hold_seconds,
        "ramp_delay_seconds": ramp_delay,
        "note": "Check /simulate/rds-pressure-status for active held connections"
    })


@app.route("/simulate/rds-pressure-status", methods=["GET"])
def rds_pressure_status():
    active = []

    with held_rds_lock:
        for item in held_rds_connections:
            active.append({
                "mysql_connection_id": item["connection_id"],
                "held_for_seconds": round(time.time() - item["opened_at"], 2)
            })
        held_count = len(held_rds_connections)

    return jsonify({
        "held_connection_count": held_count,
        "held_connections": active[:20],
        "note": "Only first 20 connections are shown"
    })


@app.route("/simulate/release-rds-pressure", methods=["GET", "POST"])
def release_rds_pressure():
    released = 0

    with held_rds_lock:
        while held_rds_connections:
            item = held_rds_connections.pop()
            try:
                item["conn"].close()
                released += 1
            except Exception:
                pass

        rds_pressure_connections.set(0)

    return jsonify({"status": "released", "released_connections": released})


@app.route("/simulate/es-index-pressure", methods=["GET", "POST"])
def simulate_es_index_pressure():
    total_docs = int(request.args.get("documents", "5000"))
    batch_size = int(request.args.get("batchSize", "200"))
    delay_seconds = float(request.args.get("delay", "0.5"))

    threading.Thread(
        target=run_es_bulk_pressure,
        args=(total_docs, batch_size, delay_seconds),
        daemon=True
    ).start()

    return jsonify({
        "status": "started",
        "failure_case": "elasticsearch_resource_pressure",
        "documents": total_docs,
        "batch_size": batch_size,
        "delay_seconds": delay_seconds,
        "note": "Also enable es-write-block for guaranteed ingestion failures"
    })


@app.route("/simulate/es-write-block", methods=["GET", "POST"])
def simulate_es_write_block():
    enabled = request.args.get("enabled", "true").lower() == "true"

    if enabled:
        es_write_blocked.set()
        es_pressure_active.set(1)
    else:
        es_write_blocked.clear()
        if not es_pressure_stop.is_set():
            es_pressure_active.set(0)

    return jsonify({
        "status": "updated",
        "failure_case": "elasticsearch_write_failure",
        "es_write_blocked": enabled
    })


@app.route("/simulate/stop-es-pressure", methods=["GET", "POST"])
def stop_es_pressure():
    es_pressure_stop.set()
    es_write_blocked.clear()
    es_pressure_active.set(0)
    return jsonify({"status": "stopped"})


def shutdown_handler(signum, frame):
    logging.info("Shutdown signal received")
    stop_event.set()
    es_pressure_stop.set()


signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)


if __name__ == "__main__":
    logging.info(
        "Starting %s release=%s startup_failure=%s",
        SERVICE_NAME, RELEASE_VERSION, STARTUP_FAILURE
    )

    if STARTUP_FAILURE:
        logging.error(
            "Release %s failed startup: database migration checksum mismatch. "
            "Application will not start.",
            RELEASE_VERSION
        )
        raise SystemExit(1)

    # Never call init_rds()/init_es() here — dependencies load in background.
    threading.Thread(
        target=bootstrap_dependencies,
        daemon=True,
        name="bootstrap-dependencies"
    ).start()

    logging.info("HTTP server starting on :8080 (waiting for ES/RDS in background)")
    app.run(host="0.0.0.0", port=8080, threaded=True)
