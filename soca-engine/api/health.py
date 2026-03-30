import os
import platform
import time
import psutil
from fastapi import APIRouter
from core.output_publisher import get_redis
from api.jobs import _workers
import config

router = APIRouter(tags=["health"])
_start_time = time.monotonic()


@router.get("/health")
def health():
    redis_ok = get_redis() is not None
    publisher = config.PUBLISHER_TYPE  # "redis" | "pubsub"
    resp = {
        "status":         "ok",
        "edge_name":      config.EDGE_NAME,
        "publisher_type": publisher,
        "active_jobs":    sum(1 for w in _workers.values() if w.is_alive()),
        "uptime_seconds": int(time.monotonic() - _start_time),
    }
    if publisher == "pubsub":
        project = config.PUBSUB_PROJECT_ID
        topic   = config.PUBSUB_TOPIC
        resp["pubsub"] = {
            "project_id": project,
            "topic":      topic,
            "configured": bool(project and topic),
        }
    else:
        resp["redis"] = "connected" if redis_ok else "unavailable"
    return resp


@router.get("/cpu")
def cpu_info():
    freq = psutil.cpu_freq()
    return {
        "model":        platform.processor() or platform.machine(),
        "architecture": platform.machine(),
        "cores_physical": psutil.cpu_count(logical=False),
        "cores_logical":  psutil.cpu_count(logical=True),
        "freq_mhz": {
            "current": round(freq.current, 1) if freq else None,
            "min":     round(freq.min, 1) if freq else None,
            "max":     round(freq.max, 1) if freq else None,
        },
        "percent_per_core": psutil.cpu_percent(interval=0.5, percpu=True),
        "percent_total":    psutil.cpu_percent(interval=0),
    }


@router.get("/system")
def system_info():
    disk = psutil.disk_usage(config.SNAPSHOTS_DIR if os.path.isdir(config.SNAPSHOTS_DIR) else "/")
    mem = psutil.virtual_memory()

    # Collect network interfaces with at least one IPv4 address
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    net_io = psutil.net_io_counters(pernic=True)
    interfaces = []
    for name, addr_list in addrs.items():
        ipv4 = next((a.address for a in addr_list if a.family.name == "AF_INET"), None)
        if not ipv4:
            continue
        st = stats.get(name)
        io = net_io.get(name)
        interfaces.append({
            "name":       name,
            "ip":         ipv4,
            "is_up":      st.isup if st else False,
            "speed_mbps": st.speed if st else 0,
            "sent_mb":    round(io.bytes_sent / 1024 / 1024, 1) if io else 0,
            "recv_mb":    round(io.bytes_recv / 1024 / 1024, 1) if io else 0,
        })

    return {
        "cpu": {
            "percent": psutil.cpu_percent(interval=0.5),
            "count": psutil.cpu_count(),
        },
        "memory": {
            "total_mb":  round(mem.total / 1024 / 1024),
            "used_mb":   round(mem.used / 1024 / 1024),
            "percent":   mem.percent,
        },
        "storage": {
            "total_gb":  round(disk.total / 1024 / 1024 / 1024, 1),
            "used_gb":   round(disk.used / 1024 / 1024 / 1024, 1),
            "free_gb":   round(disk.free / 1024 / 1024 / 1024, 1),
            "percent":   disk.percent,
        },
        "network": interfaces,
    }


@router.get("/models")
def list_models():
    models_dir = config.MODELS_DIR
    if not os.path.isdir(models_dir):
        return {"models": []}
    models = [
        {"name": f, "path": os.path.join(models_dir, f)}
        for f in os.listdir(models_dir)
        if f.endswith((".pt", ".mlpackage", ".onnx"))
    ]
    return {"models": models}
