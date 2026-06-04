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
from flask import Flask, jsonify, request
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# =========================
# Environment variables
# =========================
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "orders")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").lower() == "true"
WORKER_POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "5"))
WORKER_BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", "5"))

SERVICE_NAME = os.getenv("SERVICE_NAME", "order-fulfillment-worker")
RELEASE_VERSION = os.getenv("RELEASE_VERSION", "v1.0.0")

# =========================
# Metrics
# =========================
messages_received_total = Counter(
    "worker_sqs_messages_received_total",
    "Total SQS messages received"
)

messages_processed_total = Counter(
    "worker_sqs_messages_processed_total",
    "Total SQS messages successfully processed"
)

messages_failed_total = Counter(
    "worker_sqs_messages_failed_total",
    "Total SQS messages failed"
)

rds_write_success_total = Counter(
    "worker_rds_write_success_total",
    "Total successful RDS writes"
)

rds_write_failure_total = Counter(
    "worker_rds_write_failure_total",
    "Total failed RDS writes"
)

rds_pressure_connections = Gauge(
    "worker_rds_pressure_connections",
    "Number of pressure connections currently held"
)

worker_running = Gauge(
    "worker_running",
    "Worker running status"
)

# =========================
# Clients
# =========================
sqs = boto3.client("sqs", region_name=AWS_REGION)

held_connections = []
stop_event = threading.Event()


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


def init_db():
    """
    Creates demo table if not present.
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_events (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    order_id VARCHAR(100) NOT NULL,
                    event_type VARCHAR(100) NOT NULL,
                    payload JSON NULL,
                    release_version VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.close()
        logging.info("RDS table check completed successfully")
    except Exception as e:
        logging.error(f"RDS table initialization failed: {str(e)}")


def write_order_to_rds(order_id, event_type, payload):
    """
    Real RDS write. This will fail when RDS connection limit is reached.
    """
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
                (
                    order_id,
                    event_type,
                    json.dumps(payload),
                    RELEASE_VERSION
                )
            )

        rds_write_success_total.inc()
        return True

    except Exception as e:
        rds_write_failure_total.inc()
        logging.error(
            f"RDS write failed for order_id={order_id}. Error={str(e)}"
        )
        return False

    finally:
        if conn:
            conn.close()


def process_message(message):
    body = json.loads(message.get("Body", "{}"))

    order_id = body.get("order_id", str(uuid.uuid4()))
    event_type = body.get("event_type", "ORDER_CREATED")

    logging.info(f"Processing message order_id={order_id}")

    success = write_order_to_rds(
        order_id=order_id,
        event_type=event_type,
        payload=body
    )

    if not success:
        messages_failed_total.inc()
        logging.error(
            f"Message processing failed. Message will not be deleted from SQS. order_id={order_id}"
        )
        return False

    # Delete message only after RDS write success.
    sqs.delete_message(
        QueueUrl=SQS_QUEUE_URL,
        ReceiptHandle=message["ReceiptHandle"]
    )

    messages_processed_total.inc()
    logging.info(f"Message processed and deleted from SQS. order_id={order_id}")
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
                messages_received_total.inc()
                process_message(message)

        except Exception as e:
            messages_failed_total.inc()
            logging.error(f"Worker loop error: {str(e)}")
            time.sleep(WORKER_POLL_INTERVAL)

    worker_running.set(0)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": SERVICE_NAME,
        "release_version": RELEASE_VERSION
    })


@app.route("/ready", methods=["GET"])
def ready():
    try:
        conn = get_db_connection()
        conn.close()
        return jsonify({
            "status": "ready",
            "rds": "connected"
        })
    except Exception as e:
        return jsonify({
            "status": "not_ready",
            "rds": "failed",
            "error": str(e)
        }), 503


@app.route("/metrics", methods=["GET"])
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/simulate/enqueue", methods=["POST"])
def simulate_enqueue():
    """
    Adds messages to SQS for testing backlog.
    Example:
    curl -X POST "http://localhost:8080/simulate/enqueue?count=150"
    """
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

    logging.info(f"Enqueued {count} messages to SQS")

    return jsonify({
        "status": "success",
        "messages_enqueued": count
    })


@app.route("/simulate/rds-connection-pressure", methods=["POST", "GET"])
def simulate_rds_connection_pressure():
    """
    Opens many RDS connections and holds them.
    Example:
    curl "http://localhost:8080/simulate/rds-connection-pressure?connections=100&holdSeconds=300"
    """
    connections = int(request.args.get("connections", "100"))
    hold_seconds = int(request.args.get("holdSeconds", "300"))

    def hold_connection(index):
        conn = None
        try:
            conn = get_db_connection()
            held_connections.append(conn)
            rds_pressure_connections.set(len(held_connections))

            logging.warning(
                f"Holding RDS pressure connection {index}/{connections} for {hold_seconds}s"
            )

            with conn.cursor() as cursor:
                cursor.execute(f"SELECT SLEEP({hold_seconds})")

        except Exception as e:
            logging.error(f"Failed to create pressure connection {index}: {str(e)}")

        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

            if conn in held_connections:
                held_connections.remove(conn)

            rds_pressure_connections.set(len(held_connections))

    for i in range(connections):
        thread = threading.Thread(
            target=hold_connection,
            args=(i + 1,),
            daemon=True
        )
        thread.start()
        time.sleep(0.05)

    return jsonify({
        "status": "started",
        "connections_requested": connections,
        "hold_seconds": hold_seconds
    })


@app.route("/simulate/release-rds-pressure", methods=["POST", "GET"])
def release_rds_pressure():
    released = 0

    for conn in list(held_connections):
        try:
            conn.close()
            released += 1
        except Exception:
            pass

    held_connections.clear()
    rds_pressure_connections.set(0)

    return jsonify({
        "status": "released",
        "released_connections": released
    })


def shutdown_handler(signum, frame):
    logging.info("Shutdown signal received")
    stop_event.set()


signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)


if __name__ == "__main__":
    logging.info(f"Starting {SERVICE_NAME} release={RELEASE_VERSION}")

    init_db()

    if WORKER_ENABLED:
        thread = threading.Thread(target=worker_loop, daemon=True)
        thread.start()
        logging.info("SQS worker started")

    app.run(host="0.0.0.0", port=8080)
