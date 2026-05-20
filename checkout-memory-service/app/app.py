from flask import Flask, jsonify, request
import time

app = Flask(__name__)
memory_holder = []

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

@app.route("/simulate/memory-pressure")
def memory_pressure():
    mb = int(request.args.get("mb", 500))
    delay = float(request.args.get("delay", 0.1))

    allocated = 0
    while allocated < mb:
        memory_holder.append(bytearray(10 * 1024 * 1024))
        allocated += 10
        time.sleep(delay)

    return jsonify({"allocated_mb": allocated})

@app.route("/")
def root():
    return jsonify({
        "service": "checkout-memory-service",
        "trigger": "/simulate/memory-pressure?mb=500&delay=0.1"
    })

app.run(host="0.0.0.0", port=8080)
