from flask import Flask, jsonify, request
import time
import os

app = Flask(__name__)

memory_holder = []


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "service": "checkout-memory-service",
        "pid": os.getpid()
    })


@app.route("/simulate/memory-pressure")
def memory_pressure():
    target_mb = int(request.args.get("mb", 500))
    step_mb = int(request.args.get("step", 10))
    delay = float(request.args.get("delay", 10))

    allocated = 0

    while allocated < target_mb:
        memory_holder.append(bytearray(step_mb * 1024 * 1024))
        allocated += step_mb

        print(
            f"Memory allocated: {allocated} MB / {target_mb} MB",
            flush=True
        )

        time.sleep(delay)

    return jsonify({
        "status": "memory pressure completed",
        "allocated_mb": allocated,
        "target_mb": target_mb,
        "step_mb": step_mb,
        "delay_seconds": delay
    })


@app.route("/memory/status")
def memory_status():
    return jsonify({
        "allocated_blocks": len(memory_holder),
        "approx_allocated_mb": len(memory_holder) * 10
    })


@app.route("/")
def root():
    return jsonify({
        "service": "checkout-memory-service",
        "endpoints": {
            "health": "/health",
            "slow_memory_spike": "/simulate/memory-pressure?mb=500&step=10&delay=10",
            "memory_status": "/memory/status"
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
