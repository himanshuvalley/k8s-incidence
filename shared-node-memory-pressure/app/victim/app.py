from flask import Flask, jsonify, request
import os
import time

app = Flask(__name__)

DATA_DIR = "/data/ledger"
os.makedirs(DATA_DIR, exist_ok=True)


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "service": "payment-ledger-service",
        "data_dir": DATA_DIR
    })


@app.route("/ledger/write")
def ledger_write():
    entry = request.args.get("entry", f"payment-ledger-entry-{int(time.time())}")
    file_path = os.path.join(DATA_DIR, "ledger.log")

    with open(file_path, "a") as f:
        f.write(entry + "\n")
        f.flush()
        os.fsync(f.fileno())

    return jsonify({
        "status": "written",
        "file": file_path,
        "entry": entry
    })


@app.route("/ledger/status")
def ledger_status():
    file_path = os.path.join(DATA_DIR, "ledger.log")

    exists = os.path.exists(file_path)
    size_bytes = os.path.getsize(file_path) if exists else 0

    return jsonify({
        "status": "running",
        "service": "payment-ledger-service",
        "file_exists": exists,
        "file_size_bytes": size_bytes
    })


@app.route("/")
def root():
    return jsonify({
        "service": "payment-ledger-service",
        "endpoints": {
            "health": "/health",
            "ledger_write": "/ledger/write",
            "ledger_status": "/ledger/status"
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
