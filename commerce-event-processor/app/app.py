import os
import time
import json
import uuid
import signal
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import boto3
import pymysql
from elasticsearch import Elasticsearch
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
DB_NAME = os.getenv("DB_NAME", "commerce")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

ES_HOSTS = [h.strip() for h in os.getenv("ES_HOSTS", "").split(",") if h.strip()]
ES_INDEX = os.getenv("ES_INDEX", "commerce-events")
ES_USERNAME = os.getenv("ES_USERNAME", "")
ES_PASSWORD = os.getenv("ES_PASSWORD", "")

PRODUCER_ENABLED = os.getenv("PRODUCER_ENABLED", "true").lower() == "true"
PRODUCER_MESSAGES_PER_MINUTE = int(os.getenv("PRODUCER_MESSAGES_PER_MINUTE", "60"))

WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").lower() == "true"
WORKER_BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", "1"))
NORMAL_PROCESS_DELAY_SECONDS = float(os.getenv("NORMAL_PROCESS_DELAY_SECONDS", "1"))

DEPENDENCY_WAIT_SECONDS = int(os.getenv("DEPENDENCY_WAIT_SECONDS", "300"))
DEPENDENCY_WAIT_INTERVAL = int(os.getenv("DEPENDENCY_WAIT_INTERVAL", "5"))

SERVICE_NAME = os.getenv("SERVICE_NAME", "commerce-event-processor")
RELEASE_VERSION = os.getenv("RELEASE_VERSION", "1.0.0")

# =========================
# Metrics
# =========================
sqs_produced_total = Counter("sync_sqs_produced_total", "Messages produced to SQS")
sqs_received_total = Counter("sync_sqs_received_total", "Messages received from SQS")
sqs_processed_total = Counter("sync_sqs_processed_total", "Messages processed successfully")
sqs_failed_total = Counter("sync_sqs_failed_total", "Messages failed processing")
rds_write_failure_total = Counter("sync_rds_write_failure_total", "RDS write failures")
es_index_failure_total = Counter("sync_es_index_failure_total", "Elasticsearch index failures")
es_pressure_active = Gauge("sync_es_pressure_active", "Elasticsearch bulk pressure active (1=yes)")
es_pressure_docs_indexed = Counter("sync_es_pressure_docs_indexed_total", "Docs indexed during ES pressure")
rds_pressure_connections = Gauge("sync_rds_pressure_connections", "Held RDS pressure connections")
process_delay_seconds = Gauge("sync_process_delay_seconds", "Current per-message processing delay")
producer_rate_per_minute = Gauge("sync_producer_rate_per_minute", "SQS producer rate per minute")

# =========================
# State
# =========================
sqs = boto3.client("sqs", region_name=AWS_REGION)

es_client = None
dependencies_ready = False
stop_event = threading.Event()

held_rds_connections = []
held_rds_lock = threading.Lock()
pressure_run_id = 0

slow_processing_enabled = False
slow_processing_delay = 10.0
processing_lock = threading.Lock()

es_pressure_stop = threading.Event()
es_pressure_running = False
es_pressure_lock = threading.Lock()
es_pressure_started_at = 0.0
es_pressure_hold_seconds = 0
es_pressure_indexed = 0
es_pressure_failed = 0
es_pressure_loader_threads = []


def build_es_client():
    hosts = []
    for host in ES_HOSTS:
        if host.startswith("http://") or host.startswith("https://"):
            hosts.append(host)
        else:
            hosts.append(f"http://{host}")

    kwargs = {
        "hosts": hosts,
        "request_timeout": 15,
        "max_retries": 2,
        "retry_on_timeout": True,
    }
    if ES_USERNAME and ES_PASSWORD:
        kwargs["basic_auth"] = (ES_USERNAME, ES_PASSWORD)
    return Elasticsearch(**kwargs)


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
        autocommit=True,
    )


def get_pressure_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        connect_timeout=15,
        read_timeout=3600,
        write_timeout=3600,
        autocommit=True,
    )


def init_rds():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commerce_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                transaction_id VARCHAR(100) NOT NULL,
                event_type VARCHAR(100) NOT NULL,
                payload JSON NULL,
                release_version VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    conn.close()


def init_es(client=None):
    global es_client
    es_client = client or build_es_client()
    if not es_client.ping():
        raise RuntimeError("Elasticsearch cluster unreachable")

    if not es_client.indices.exists(index=ES_INDEX):
        es_client.indices.create(
            index=ES_INDEX,
            body={
                "settings": {"number_of_shards": 3, "number_of_replicas": 1},
                "mappings": {
                    "properties": {
                        "transaction_id": {"type": "keyword"},
                        "event_type": {"type": "keyword"},
                        "release_version": {"type": "keyword"},
                        "created_at": {"type": "date"},
                        "payload": {"type": "object", "enabled": True},
                    }
                },
            },
        )


def wait_for_elasticsearch():
    deadline = time.time() + DEPENDENCY_WAIT_SECONDS
    attempt = 0
    while time.time() < deadline and not stop_event.is_set():
        attempt += 1
        try:
            client = build_es_client()
            if client.ping():
                return client
        except Exception as exc:
            logging.warning("Waiting for Elasticsearch cluster attempt=%s error=%s", attempt, exc)
        time.sleep(DEPENDENCY_WAIT_INTERVAL)
    raise RuntimeError("Elasticsearch cluster not ready")


def wait_for_rds():
    deadline = time.time() + DEPENDENCY_WAIT_SECONDS
    attempt = 0
    while time.time() < deadline and not stop_event.is_set():
        attempt += 1
        try:
            conn = get_db_connection()
            conn.close()
            return
        except Exception as exc:
            logging.warning("Waiting for RDS attempt=%s error=%s", attempt, exc)
        time.sleep(DEPENDENCY_WAIT_INTERVAL)
    raise RuntimeError("RDS not ready")


def bootstrap_dependencies():
    global dependencies_ready
    while not stop_event.is_set():
        try:
            wait_for_rds()
            init_rds()
            client = wait_for_elasticsearch()
            init_es(client)
            dependencies_ready = True
            logging.info("Dependencies ready: RDS + Elasticsearch cluster")
            return
        except Exception as exc:
            dependencies_ready = False
            logging.warning("Bootstrap retry in %ss: %s", DEPENDENCY_WAIT_INTERVAL, exc)
            time.sleep(DEPENDENCY_WAIT_INTERVAL)


def current_process_delay():
    with es_pressure_lock:
        if es_pressure_running:
            return 0
    with processing_lock:
        if slow_processing_enabled:
            return slow_processing_delay
    return NORMAL_PROCESS_DELAY_SECONDS


def worker_receive_settings():
    with es_pressure_lock:
        pressure_active = es_pressure_running
    if pressure_active:
        return {
            "max_messages": min(max(WORKER_BATCH_SIZE, 10), 10),
            "visibility_timeout": 300,
            "wait_time_seconds": 0,
        }
    return {
        "max_messages": WORKER_BATCH_SIZE,
        "visibility_timeout": 60,
        "wait_time_seconds": 5,
    }


def write_transaction_to_rds(transaction_id, event_type, payload):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO commerce_events (transaction_id, event_type, payload, release_version)
                VALUES (%s, %s, %s, %s)
                """,
                (transaction_id, event_type, json.dumps(payload), RELEASE_VERSION),
            )
        return True
    except pymysql.err.OperationalError as exc:
        rds_write_failure_total.inc()
        if exc.args and exc.args[0] == 1040:
            logging.error(
                "RDS too many connections: transaction_id=%s error=%s",
                transaction_id, exc,
            )
        else:
            logging.error("RDS write failed: transaction_id=%s error=%s", transaction_id, exc)
        return False
    except Exception as exc:
        rds_write_failure_total.inc()
        logging.error("RDS write failed: transaction_id=%s error=%s", transaction_id, exc)
        return False
    finally:
        if conn:
            conn.close()


def index_transaction_to_es(transaction_id, event_type, payload):
    with es_pressure_lock:
        pressure_active = es_pressure_running

    doc = {
        "transaction_id": transaction_id,
        "event_type": event_type,
        "release_version": RELEASE_VERSION,
        "created_at": datetime.utcnow().isoformat(),
        "payload": payload,
    }

    if pressure_active:
        try:
            client = es_client.options(
                request_timeout=3,
                max_retries=0,
                retry_on_timeout=False,
            )
            client.index(
                index=ES_INDEX,
                id=f"{transaction_id}-{uuid.uuid4().hex[:8]}",
                document=doc,
            )
        except Exception as exc:
            es_index_failure_total.inc()
            logging.error(
                "Elasticsearch cluster write failed: transaction_id=%s error=%s",
                transaction_id, exc,
            )
            return False

        es_index_failure_total.inc()
        logging.error(
            "Elasticsearch cluster write failed: transaction_id=%s error=cluster_indexing_pressure_active",
            transaction_id,
        )
        return False

    try:
        es_client.index(
            index=ES_INDEX,
            id=f"{transaction_id}-{uuid.uuid4().hex[:8]}",
            document=doc,
        )
        return True
    except Exception as exc:
        es_index_failure_total.inc()
        logging.error(
            "Elasticsearch cluster write failed: transaction_id=%s error=%s",
            transaction_id, exc,
        )
        return False


def _es_write_loader(loader_id, hold_seconds, blob_size_kb):
    """Same idea as RDS hold_connection — keep sending writes to saturate ES."""
    global es_pressure_indexed, es_pressure_failed

    blob = "x" * (blob_size_kb * 1024)
    deadline = es_pressure_started_at + hold_seconds

    while time.time() < deadline and not es_pressure_stop.is_set() and not stop_event.is_set():
        doc_id = uuid.uuid4().hex
        try:
            es_client.index(
                index=ES_INDEX,
                id=f"loader-{loader_id}-{doc_id}",
                document={
                    "transaction_id": f"LOADER-{doc_id[:10]}",
                    "event_type": "ES_CLUSTER_PRESSURE",
                    "release_version": RELEASE_VERSION,
                    "created_at": datetime.utcnow().isoformat(),
                    "payload": {"loader_id": loader_id, "blob": blob},
                },
                request_timeout=60,
            )
            with es_pressure_lock:
                es_pressure_indexed += 1
            es_pressure_docs_indexed.inc()
        except Exception as exc:
            with es_pressure_lock:
                es_pressure_failed += 1
            logging.warning("ES write loader %s failed: %s", loader_id, exc)


def run_es_cluster_pressure(hold_seconds, write_loaders, blob_size_kb):
    global es_pressure_running, es_pressure_started_at, es_pressure_hold_seconds
    global es_pressure_indexed, es_pressure_failed, es_pressure_loader_threads

    with es_pressure_lock:
        es_pressure_running = True
        es_pressure_started_at = time.time()
        es_pressure_hold_seconds = hold_seconds
        es_pressure_indexed = 0
        es_pressure_failed = 0

    es_pressure_stop.clear()
    es_pressure_active.set(1)
    es_pressure_loader_threads = []

    logging.warning(
        "Starting ES cluster pressure (Case-1 style) hold_seconds=%s write_loaders=%s blob_kb=%s",
        hold_seconds, write_loaders, blob_size_kb,
    )

    for loader_id in range(1, write_loaders + 1):
        thread = threading.Thread(
            target=_es_write_loader,
            args=(loader_id, hold_seconds, blob_size_kb),
            daemon=True,
            name=f"es-write-loader-{loader_id}",
        )
        thread.start()
        es_pressure_loader_threads.append(thread)

    for thread in es_pressure_loader_threads:
        thread.join()

    es_pressure_active.set(0)
    with es_pressure_lock:
        indexed = es_pressure_indexed
        failed = es_pressure_failed
        es_pressure_running = False
    es_pressure_loader_threads = []

    logging.warning(
        "ES cluster pressure finished hold_seconds=%s indexed=%s failed=%s",
        hold_seconds, indexed, failed,
    )


def process_message(message):
    body = json.loads(message.get("Body", "{}"))
    transaction_id = body.get("transaction_id", str(uuid.uuid4()))
    event_type = body.get("event_type", "TRANSACTION_CREATED")

    with es_pressure_lock:
        pressure_active = es_pressure_running

    delay = current_process_delay()
    process_delay_seconds.set(delay)
    if delay > 0:
        time.sleep(delay)

    if pressure_active:
        rds_ok = True
    else:
        rds_ok = write_transaction_to_rds(transaction_id, event_type, body)

    es_ok = index_transaction_to_es(transaction_id, event_type, body)

    if not rds_ok or not es_ok:
        sqs_failed_total.inc()
        return False

    sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=message["ReceiptHandle"])
    sqs_processed_total.inc()
    return True


def process_messages(messages):
    if not messages:
        return

    with es_pressure_lock:
        pressure_active = es_pressure_running

    if pressure_active and len(messages) > 1:
        with ThreadPoolExecutor(max_workers=len(messages)) as executor:
            list(executor.map(process_message, messages))
        return

    for message in messages:
        process_message(message)


def producer_loop():
    interval = 60.0 / PRODUCER_MESSAGES_PER_MINUTE
    producer_rate_per_minute.set(PRODUCER_MESSAGES_PER_MINUTE)

    while not stop_event.is_set():
        if not dependencies_ready:
            time.sleep(2)
            continue

        payload = {
            "transaction_id": f"TXN-{uuid.uuid4().hex[:10]}",
            "event_type": "TRANSACTION_CREATED",
            "source": "commerce-event-processor",
            "created_at": datetime.utcnow().isoformat(),
        }
        try:
            sqs.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(payload))
            sqs_produced_total.inc()
        except Exception as exc:
            logging.error("SQS producer failed: %s", exc)
        time.sleep(interval)


def worker_loop():
    while not stop_event.is_set():
        if not dependencies_ready:
            time.sleep(2)
            continue

        try:
            receive_settings = worker_receive_settings()
            response = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=receive_settings["max_messages"],
                WaitTimeSeconds=receive_settings["wait_time_seconds"],
                VisibilityTimeout=receive_settings["visibility_timeout"],
            )
            messages = response.get("Messages", [])
            for message in messages:
                sqs_received_total.inc()
            process_messages(messages)
        except Exception as exc:
            logging.error("Worker loop error: %s", exc)
            time.sleep(2)


# =========================
# HTTP routes
# =========================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME, "release_version": RELEASE_VERSION})


@app.route("/ready", methods=["GET"])
def ready():
    if not dependencies_ready:
        return jsonify({"status": "starting"}), 503
    return jsonify({
        "status": "ready",
        "rds": "connected",
        "elasticsearch": "connected",
        "producer_rate_per_minute": PRODUCER_MESSAGES_PER_MINUTE,
        "process_delay_seconds": current_process_delay(),
    })


@app.route("/metrics", methods=["GET"])
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/simulate/rds-connection-pressure", methods=["GET", "POST"])
def simulate_rds_connection_pressure():
    global pressure_run_id

    connections = int(request.args.get("connections", "80"))
    hold_seconds = int(request.args.get("holdSeconds", "600"))
    ramp_delay = float(request.args.get("rampDelay", "0.2"))

    current_run = pressure_run_id + 1
    pressure_run_id = current_run

    def hold_connection(index, run_id):
        conn = None
        connection_id = None
        opened_at = time.time()

        try:
            conn = get_pressure_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT CONNECTION_ID()")
                connection_id = cursor.fetchone()[0]
                cursor.execute("SET SESSION wait_timeout=28800")
                cursor.execute("SET SESSION interactive_timeout=28800")

            with held_rds_lock:
                held_rds_connections.append({
                    "conn": conn,
                    "connection_id": connection_id,
                    "opened_at": opened_at,
                    "run_id": run_id,
                })
                rds_pressure_connections.set(len(held_rds_connections))

            logging.warning(
                "RDS pressure connection %s/%s mysql_id=%s holding for %ss",
                index, connections, connection_id, hold_seconds,
            )

            deadline = time.time() + hold_seconds
            while time.time() < deadline and not stop_event.is_set():
                if run_id != pressure_run_id:
                    logging.warning(
                        "RDS pressure connection mysql_id=%s stopping due to new run",
                        connection_id,
                    )
                    break
                conn.ping(reconnect=False)
                time.sleep(3)

            logging.warning(
                "RDS pressure connection mysql_id=%s hold completed after %ss",
                connection_id, round(time.time() - opened_at, 1),
            )

        except Exception as exc:
            logging.error(
                "RDS pressure connection %s mysql_id=%s failed after %ss: %s",
                index, connection_id, round(time.time() - opened_at, 1), exc,
            )
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
            args=(i + 1, current_run),
            daemon=True,
        ).start()
        time.sleep(ramp_delay)

    return jsonify({
        "status": "started",
        "failure_case": "rds_connection_limit",
        "connections_requested": connections,
        "hold_seconds": hold_seconds,
        "ramp_delay_seconds": ramp_delay,
        "run_id": current_run,
        "note": "Check /simulate/rds-pressure-status every 10s — count should stay high",
    })


@app.route("/simulate/release-rds-pressure", methods=["GET", "POST"])
def release_rds_pressure():
    global pressure_run_id

    pressure_run_id += 1
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


@app.route("/simulate/rds-pressure-status", methods=["GET"])
def rds_pressure_status():
    active = []
    with held_rds_lock:
        for item in held_rds_connections:
            active.append({
                "mysql_connection_id": item["connection_id"],
                "held_for_seconds": round(time.time() - item["opened_at"], 1),
                "run_id": item["run_id"],
            })
        count = len(held_rds_connections)

    return jsonify({
        "held_connection_count": count,
        "held_connections": active[:20],
        "note": "Count should stay 50+ for full hold period. If drops to 0 quickly, rebuild image.",
    })


@app.route("/simulate/es-cluster-pressure", methods=["GET", "POST"])
def simulate_es_cluster_pressure():
    global es_pressure_running

    enabled = request.args.get("enabled", "true").lower() == "true"
    hold_seconds = int(request.args.get("holdSeconds", "600"))
    write_loaders = int(request.args.get("writeLoaders", "20"))
    blob_size_kb = int(request.args.get("blobSizeKb", "256"))

    if not enabled:
        es_pressure_stop.set()
        es_pressure_active.set(0)
        with es_pressure_lock:
            es_pressure_running = False
        return jsonify({
            "status": "stopped",
            "failure_case": "elasticsearch_cluster_pressure",
            "es_pressure_active": False,
        })

    with es_pressure_lock:
        if es_pressure_running:
            return jsonify({
                "status": "already_running",
                "failure_case": "elasticsearch_cluster_pressure",
                "note": "ES cluster pressure already active",
            })

    threading.Thread(
        target=run_es_cluster_pressure,
        args=(hold_seconds, write_loaders, blob_size_kb),
        daemon=True,
        name="es-cluster-pressure",
    ).start()

    return jsonify({
        "status": "started",
        "failure_case": "elasticsearch_cluster_pressure",
        "hold_seconds": hold_seconds,
        "write_loaders": write_loaders,
        "blob_size_kb": blob_size_kb,
        "note": (
            "write_loaders hammer ES for cluster metrics. Worker skips delete while pressure "
            "active (like RDS case). Wait 3-5 min for SQS backlog."
        ),
    })


@app.route("/simulate/es-pressure-status", methods=["GET"])
def es_pressure_status():
    with es_pressure_lock:
        running = es_pressure_running
        started_at = es_pressure_started_at
        hold_seconds = es_pressure_hold_seconds
        indexed = es_pressure_indexed
        failed = es_pressure_failed

    elapsed = round(time.time() - started_at, 1) if started_at else 0
    remaining = max(0, round(hold_seconds - elapsed, 1)) if hold_seconds else 0

    return jsonify({
        "es_pressure_active": running,
        "hold_seconds": hold_seconds,
        "elapsed_seconds": elapsed,
        "remaining_seconds": remaining if running else 0,
        "docs_indexed": indexed,
        "docs_failed": failed,
        "note": "Should stay active for full hold_seconds unless stopped manually",
    })


@app.route("/simulate/slow-processing", methods=["GET", "POST"])
def simulate_slow_processing():
    enabled = request.args.get("enabled", "true").lower() == "true"
    delay = float(request.args.get("delaySeconds", "10"))

    with processing_lock:
        global slow_processing_enabled, slow_processing_delay
        slow_processing_enabled = enabled
        slow_processing_delay = delay
        process_delay_seconds.set(delay if enabled else NORMAL_PROCESS_DELAY_SECONDS)

    return jsonify({
        "status": "updated",
        "failure_case": "slow_message_processing",
        "slow_processing_enabled": enabled,
        "process_delay_seconds": delay if enabled else NORMAL_PROCESS_DELAY_SECONDS,
        "producer_rate_per_minute": PRODUCER_MESSAGES_PER_MINUTE,
        "note": "Producer keeps sending 60/min. Backlog grows when delay > 1 sec/msg.",
    })


@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": SERVICE_NAME,
        "cases": {
            "case_1_rds_connections": "/simulate/rds-connection-pressure?connections=80&holdSeconds=600",
            "case_2_es_cluster": "/simulate/es-cluster-pressure?enabled=true&writeLoaders=20&holdSeconds=600",
            "case_3_slow_processing": "/simulate/slow-processing?enabled=true&delaySeconds=10",
        },
    })


def shutdown_handler(signum, frame):
    stop_event.set()
    es_pressure_stop.set()


signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)


if __name__ == "__main__":
    logging.info("Starting %s release=%s", SERVICE_NAME, RELEASE_VERSION)

    threading.Thread(target=bootstrap_dependencies, daemon=True, name="bootstrap").start()

    if PRODUCER_ENABLED:
        threading.Thread(target=producer_loop, daemon=True, name="sqs-producer").start()
        logging.info("SQS producer started at %s messages/minute", PRODUCER_MESSAGES_PER_MINUTE)

    if WORKER_ENABLED:
        threading.Thread(target=worker_loop, daemon=True, name="sqs-worker").start()
        logging.info("SQS worker started normal_process_delay=%ss", NORMAL_PROCESS_DELAY_SECONDS)

    app.run(host="0.0.0.0", port=8080, threaded=True)
