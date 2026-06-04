from flask import Flask, jsonify, request
import mysql.connector
import os
import time
import threading

app = Flask(__name__)

held_connections = []
held_lock = threading.Lock()

SERVICE_NAME = "order-db-connection-pressure"

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "connection_timeout": 5,
    "autocommit": True,
    "pool_name": "order_db_pool",
    "pool_size": 10
}

# Initialize the connection pool
connection_pool = pooling.MySQLConnectionPool(**DB_CONFIG)


def get_connection():
    return connection_pool.get_connection()


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            customer_name VARCHAR(100),
            amount DECIMAL(10,2),
            status VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT INTO orders (customer_name, amount, status)
        SELECT 'Demo Customer', 1200.50, 'PROCESSING'
        WHERE NOT EXISTS (SELECT 1 FROM orders LIMIT 1)
    """)
    cursor.close()
    conn.close()


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "service": SERVICE_NAME
    })


@app.route("/db/health")
def db_health():
    try:
        start = time.time()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()

        latency_ms = round((time.time() - start) * 1000, 2)

        return jsonify({
            "status": "healthy",
            "db_status": "connected",
            "db_latency_ms": latency_ms
        })

    except Exception as e:
        return jsonify({
            "status": "failed",
            "db_status": "unavailable",
            "error": str(e)
        }), 503


@app.route("/orders")
def orders():
    try:
        start = time.time()

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT SLEEP(2)")
        cursor.fetchall()

        cursor.execute("SELECT * FROM orders LIMIT 10")
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        latency_ms = round((time.time() - start) * 1000, 2)

        return jsonify({
            "status": "success",
            "latency_ms": latency_ms,
            "orders": rows
        })

    except Exception as e:
        return jsonify({
            "status": "failed",
            "message": "Order service failed because DB connection is unavailable or max connections reached",
            "error": str(e)
        }), 503


@app.route("/simulate/rds-connection-exhaustion")
def rds_connection_exhaustion():
    connections = int(request.args.get("connections", 80))
    hold_seconds = int(request.args.get("hold", 600))
    ramp_delay = float(request.args.get("delay", 0.2))

    opened = 0
    failed = 0
    errors = []

    def hold_connection(index):
        nonlocal opened, failed

        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT CONNECTION_ID()")
            connection_id = cursor.fetchone()[0]

            with held_lock:
                held_connections.append({
                    "conn": conn,
                    "cursor": cursor,
                    "connection_id": connection_id,
                    "opened_at": time.time()
                })
                opened += 1

            print(f"Held RDS connection #{index}, mysql_connection_id={connection_id}", flush=True)

            time.sleep(hold_seconds)

        except Exception as e:
            with held_lock:
                failed += 1
                errors.append(str(e))

            print(f"Failed opening RDS connection #{index}: {e}", flush=True)

    for i in range(connections):
        t = threading.Thread(target=hold_connection, args=(i + 1,))
        t.daemon = True
        t.start()
        time.sleep(ramp_delay)

    return jsonify({
        "status": "rds_connection_exhaustion_started",
        "requested_connections": connections,
        "hold_seconds": hold_seconds,
        "ramp_delay_seconds": ramp_delay,
        "note": "Use /simulate/status to check held connection count"
    })


@app.route("/simulate/slow-orders")
def slow_orders():
    delay = int(request.args.get("delay", 20))

    try:
        start = time.time()

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(f"SELECT SLEEP({delay})")
        cursor.fetchall()

        cursor.execute("SELECT * FROM orders LIMIT 5")
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        latency_ms = round((time.time() - start) * 1000, 2)

        return jsonify({
            "status": "success",
            "message": "Slow DB-backed order request completed",
            "delay_seconds": delay,
            "latency_ms": latency_ms,
            "orders": rows
        })

    except Exception as e:
        return jsonify({
            "status": "failed",
            "message": "Slow order request failed due to DB connection issue",
            "error": str(e)
        }), 503


@app.route("/simulate/status")
def simulate_status():
    active_connections = []

    with held_lock:
        for item in held_connections:
            active_connections.append({
                "mysql_connection_id": item["connection_id"],
                "held_for_seconds": round(time.time() - item["opened_at"], 2)
            })

    return jsonify({
        "held_connection_count": len(active_connections),
        "held_connections": active_connections[:20],
        "note": "Only first 20 connections are shown"
    })


@app.route("/simulate/release-connections")
def release_connections():
    released = 0
    errors = []

    with held_lock:
        while held_connections:
            item = held_connections.pop()

            try:
                item["cursor"].close()
                item["conn"].close()
                released += 1
            except Exception as e:
                errors.append(str(e))

    return jsonify({
        "status": "released",
        "released_connections": released,
        "errors": errors[:5]
    })


@app.route("/")
def root():
    return jsonify({
        "service": SERVICE_NAME,
        "endpoints": {
            "health": "/health",
            "db_health": "/db/health",
            "orders": "/orders",
            "rds_connection_exhaustion": "/simulate/rds-connection-exhaustion?connections=80&hold=600&delay=0.2",
            "slow_orders": "/simulate/slow-orders?delay=20",
            "status": "/simulate/status",
            "release": "/simulate/release-connections"
        }
    })


try:
    init_db()
except Exception as e:
    print(f"DB init failed: {e}", flush=True)
