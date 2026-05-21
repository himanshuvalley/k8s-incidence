from flask import Flask, jsonify, request
import os
import time

app = Flask(__name__)

DATA_DIR = "/data/storage"
os.makedirs(DATA_DIR, exist_ok=True)


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "service": "document-storage-service"
    })


@app.route("/storage/status")
def storage_status():
    stat = os.statvfs(DATA_DIR)

    total_bytes = stat.f_blocks * stat.f_frsize
    free_bytes = stat.f_bavail * stat.f_frsize
    used_bytes = total_bytes - free_bytes

    return jsonify({
        "mount_path": DATA_DIR,
        "total_mb": round(total_bytes / 1024 / 1024, 2),
        "used_mb": round(used_bytes / 1024 / 1024, 2),
        "free_mb": round(free_bytes / 1024 / 1024, 2),
        "used_percent": round((used_bytes / total_bytes) * 100, 2)
    })


@app.route("/simulate/storage-fill")
def storage_fill():
    target_mb = int(request.args.get("mb", 900))
    step_mb = int(request.args.get("step", 25))
    delay = float(request.args.get("delay", 10))

    written_mb = 0
    file_path = os.path.join(DATA_DIR, f"storage-fill-{int(time.time())}.bin")

    with open(file_path, "ab") as f:
        while written_mb < target_mb:
            chunk = os.urandom(step_mb * 1024 * 1024)
            f.write(chunk)
            f.flush()
            os.fsync(f.fileno())

            written_mb += step_mb

            print(
                f"Written {written_mb} MB / {target_mb} MB to {file_path}",
                flush=True
            )

            time.sleep(delay)

    return jsonify({
        "status": "storage fill completed",
        "written_mb": written_mb,
        "file_path": file_path,
        "step_mb": step_mb,
        "delay_seconds": delay
    })


@app.route("/simulate/cleanup")
def cleanup():
    deleted_files = 0
    deleted_mb = 0

    for file_name in os.listdir(DATA_DIR):
        file_path = os.path.join(DATA_DIR, file_name)

        if os.path.isfile(file_path):
            size_mb = os.path.getsize(file_path) / 1024 / 1024
            os.remove(file_path)
            deleted_files += 1
            deleted_mb += size_mb

    return jsonify({
        "status": "cleanup completed",
        "deleted_files": deleted_files,
        "deleted_mb": round(deleted_mb, 2)
    })


@app.route("/")
def root():
    return jsonify({
        "service": "document-storage-service",
        "endpoints": {
            "health": "/health",
            "storage_status": "/storage/status",
            "slow_storage_fill": "/simulate/storage-fill?mb=900&step=25&delay=10",
            "cleanup": "/simulate/cleanup"
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
