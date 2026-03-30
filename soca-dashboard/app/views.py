import json
import os
import sqlite3
import yaml
from datetime import timezone, timedelta
from pathlib import Path

_TZ_GMT7 = timezone(timedelta(hours=7))

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from .decorators import role_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

import engine_client
import mediamtx as mtx
from .models import Camera, EdgeConfig, Rule, Schedule, SiteConfig, User
import secrets
from .api_auth import require_api_key
from .purge import purge_preview as _purge_preview_helper, purge_execute as _purge_execute_helper, VALID_DAYS


def _yml_path(cfg):
    """Resolve mediamtx_yml_path to absolute, anchored to BASE_DIR."""
    p = Path(cfg.mediamtx_yml_path)
    if not p.is_absolute():
        p = (Path(settings.BASE_DIR) / p).resolve()
    return str(p)


def _env_path(cfg):
    """Resolve engine_env_path to absolute, anchored to BASE_DIR."""
    p = Path(cfg.engine_env_path)
    if not p.is_absolute():
        p = (Path(settings.BASE_DIR) / p).resolve()
    return str(p)


# ── Auth ──────────────────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        user = authenticate(request, username=request.POST["username"], password=request.POST["password"])
        if user:
            login(request, user)
            return redirect(request.GET.get("next", "dashboard"))
        messages.error(request, "Invalid credentials")
    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    health = engine_client.health()
    system = engine_client.system_info()
    cpu = engine_client.cpu_info()
    jobs = [j for j in engine_client.list_jobs() if j.get("status") == "running"]
    cameras = Camera.objects.all()
    schedules = Schedule.objects.filter(is_active=True)
    ctx = {
        "health": health,
        "system": system,
        "cpu": cpu,
        "jobs": jobs,
        "total_cameras": cameras.count(),
        "active_cameras": cameras.filter(is_active=True).count(),
        "running_schedules": schedules.exclude(current_job_id="").count(),
        "total_schedules": schedules.count(),
    }
    return render(request, "dashboard.html", ctx)


# ── Cameras ───────────────────────────────────────────────────────────────────

@role_required('admin', 'operator')
def camera_list(request):
    cameras = Camera.objects.all().order_by("-created_at")
    return render(request, "cameras/list.html", {"cameras": cameras})


@role_required('admin', 'operator')
def camera_form(request, pk=None):
    camera = get_object_or_404(Camera, pk=pk) if pk else None
    old_name = camera.name if camera else None

    if request.method == "POST":
        name = request.POST["name"].strip()
        rtsp_url = request.POST["rtsp_url"].strip()
        fields = {
            "name": name,
            "site_name": request.POST.get("site_name", ""),
            "floor": request.POST.get("floor", ""),
            "location": request.POST.get("location", ""),
            "rtsp_url": rtsp_url,
            "username": request.POST.get("username", ""),
            "password": request.POST.get("password", ""),
            "is_active": request.POST.get("is_active") == "on",
        }
        username = fields["username"]
        password = fields["password"]

        if camera:
            for k, v in fields.items():
                setattr(camera, k, v)
            camera.save()
            cfg = EdgeConfig.objects.first()
            if cfg:
                mtx.update_source(_yml_path(cfg), old_name, name, rtsp_url, username, password)
            messages.success(request, f"Camera '{name}' updated.")
        else:
            camera = Camera.objects.create(**fields)
            cfg = EdgeConfig.objects.first()
            if cfg:
                mtx.add_source(_yml_path(cfg), name, rtsp_url, username, password)
            messages.success(request, f"Camera '{name}' created.")
        return redirect("camera_list")

    return render(request, "cameras/form.html", {"camera": camera})


@role_required('admin', 'operator')
def camera_snapshot(request, pk):
    """Grab a single frame from the camera RTSP stream and return as JPEG."""
    import cv2
    from django.http import HttpResponse
    camera = get_object_or_404(Camera, pk=pk)
    cap = cv2.VideoCapture(camera.full_rtsp_url)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise Http404
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return HttpResponse(buf.tobytes(), content_type="image/jpeg")


@role_required('admin', 'operator')
def camera_delete(request, pk):
    camera = get_object_or_404(Camera, pk=pk)
    if request.method == "POST":
        cfg = EdgeConfig.objects.first()
        if cfg:
            mtx.remove_source(_yml_path(cfg), camera.name)
        camera.delete()
        messages.success(request, "Camera deleted.")
    return redirect("camera_list")


# ── Schedules ─────────────────────────────────────────────────────────────────

@role_required('admin', 'operator')
def schedule_list(request):
    schedules = Schedule.objects.select_related("camera").order_by("-created_at")
    for s in schedules:
        s.job_status = None
        if s.current_job_id:
            job = engine_client.get_job(s.current_job_id)
            s.job_status = job.get("status") if job else "unknown"
    edge = EdgeConfig.objects.first()
    engine_url = edge.engine_url if edge else settings.ENGINE_BASE_URL
    return render(request, "schedules/list.html", {"schedules": schedules, "engine_url": engine_url})


@role_required('admin', 'operator')
def schedule_form(request, pk=None):
    schedule = get_object_or_404(Schedule, pk=pk) if pk else None
    cameras = Camera.objects.filter(is_active=True)
    models = engine_client.list_models()

    if request.method == "POST":
        p = request.POST
        cls_ids_raw = p.get("cls_ids", "0")
        try:
            cls_ids = [int(x.strip()) for x in cls_ids_raw.split(",") if x.strip()]
        except ValueError:
            cls_ids = [0]

        roi_points_raw = p.get("roi_points", "[]")
        try:
            roi_points = json.loads(roi_points_raw)
        except json.JSONDecodeError:
            roi_points = []

        fields = {
            "name": p["name"],
            "camera_id": p["camera"],
            "model_path": p.get("model_path", "yolo/yolo11n.pt"),
            "cls_ids": cls_ids,
            "conf_threshold": max(0.01, min(1.0, float(p.get("conf_threshold", 0.5)))),
            "iou_threshold": max(0.0, min(1.0, float(p.get("iou_threshold", 0.45) or 0.45))),
            "frame_interval_ms": max(33, int(p.get("frame_interval_ms", 1000))),
            "roi_type": p.get("roi_type", "POLYGON"),
            "roi_points": roi_points,
            "aging_window": int(p.get("aging_window", 60)),
            "aging_cooldown": int(p.get("aging_cooldown", 60)),
            "min_count": int(p.get("min_count", 1)),
            "save_snapshot": p.get("save_snapshot") == "on",
            "publish_redis": p.get("publish_redis") == "on",
            "redis_stream": p.get("redis_stream", "soca:detections"),
            "alert_category": p.get("alert_category", "")[:255],
            "snapshot_message": p.get("snapshot_message", "{in_roi_count} object(s) detected at {time}"),
            "enable_monitor": p.get("enable_monitor") == "on",
            "is_active": p.get("is_active") == "on",
            "lpr_model_path": p.get("lpr_model_path", "").strip(),
            "crossing_direction": p.get("crossing_direction", "any"),
        }

        if schedule:
            for k, v in fields.items():
                setattr(schedule, k, v)
            schedule.save()
            messages.success(request, "Schedule updated.")
        else:
            Schedule.objects.create(**fields)
            messages.success(request, "Schedule created.")
        return redirect("schedule_list")

    rules = schedule.rules.all().order_by('priority') if schedule else []
    return render(request, "schedules/form.html", {
        "schedule": schedule,
        "cameras": cameras,
        "models": models,
        "rules": rules,
    })


@login_required
def schedule_delete(request, pk):
    schedule = get_object_or_404(Schedule, pk=pk)
    if request.method == "POST":
        if schedule.current_job_id:
            try:
                engine_client.stop_job(schedule.current_job_id)
            except Exception:
                pass
        schedule.delete()
        messages.success(request, "Schedule deleted.")
    return redirect("schedule_list")


@role_required('admin', 'operator')
def schedule_start(request, pk):
    if request.method != "POST":
        return redirect("schedule_list")
    schedule = get_object_or_404(Schedule, pk=pk)
    try:
        config = schedule.to_job_config()
        result = engine_client.start_job(config)
        schedule.current_job_id = result["job_id"]
        schedule.save(update_fields=["current_job_id"])
        messages.success(request, f"Job started: {result['job_id']}")
    except Exception as e:
        messages.error(request, f"Failed to start job: {e}")
    return redirect("schedule_list")


@role_required('admin', 'operator')
def schedule_stop(request, pk):
    if request.method != "POST":
        return redirect("schedule_list")
    schedule = get_object_or_404(Schedule, pk=pk)
    if schedule.current_job_id:
        try:
            engine_client.stop_job(schedule.current_job_id)
            messages.success(request, "Job stopped.")
        except Exception as e:
            # 404 means the worker already died (e.g. RTSP error) — still clear the job_id
            messages.warning(request, f"Job already ended: {e}")
        schedule.current_job_id = ""
        schedule.save(update_fields=["current_job_id"])
    return redirect("schedule_list")


@role_required('admin', 'operator')
def schedule_status(request, pk):
    schedule = get_object_or_404(Schedule, pk=pk)
    if not schedule.current_job_id:
        return JsonResponse({"status": "idle"})
    job = engine_client.get_job(schedule.current_job_id)
    if not job:
        return JsonResponse({"status": "unknown"})
    return JsonResponse(job)


# ── Monitor ───────────────────────────────────────────────────────────────────

@login_required
def monitor_view(request):
    edge = EdgeConfig.objects.first()
    engine_url = edge.engine_url if edge else settings.ENGINE_BASE_URL

    running = Schedule.objects.select_related("camera").filter(
        is_active=True, enable_monitor=True
    ).exclude(current_job_id="")

    streams = []
    for s in running:
        job = engine_client.get_job(s.current_job_id)
        if job and job.get("status") == "running":
            streams.append({
                "schedule_name": s.name,
                "camera_name": s.camera.name,
                "job_id": s.current_job_id,
                "stream_url": f"{engine_url}/jobs/{s.current_job_id}/monitor",
            })

    return render(request, "monitor.html", {"streams": streams, "engine_url": engine_url})


# ── Alerts & Snapshots ────────────────────────────────────────────────────────

@login_required
def alerts(request):
    db_path = settings.ENGINE_DB_PATH
    camera_filter   = request.GET.get("camera", "")
    date_from       = request.GET.get("date_from", "")
    date_to         = request.GET.get("date_to", "")
    location_filter = request.GET.get("location", "")
    category_filter = request.GET.get("category", "")
    message_filter  = request.GET.get("message", "")
    plate_filter    = request.GET.get("plate", "")
    page = int(request.GET.get("page", 1))
    per_page = 20
    offset = (page - 1) * per_page

    events = []
    total = 0
    cameras_list = Camera.objects.values_list("name", flat=True)

    if os.path.exists(db_path):
        try:
            con = sqlite3.connect(db_path)
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            wheres = []
            params = []
            if camera_filter:
                wheres.append("json_extract(j.config, '$.camera_id') = ?")
                from .models import Camera as CamModel
                cam = CamModel.objects.filter(name=camera_filter).first()
                params.append(str(cam.id) if cam else camera_filter)
            if location_filter:
                from .models import Camera as CamModel
                from django.db.models import Q
                cam_ids = list(CamModel.objects.filter(
                    Q(site_name__icontains=location_filter) |
                    Q(floor__icontains=location_filter) |
                    Q(location__icontains=location_filter)
                ).values_list('id', flat=True))
                if cam_ids:
                    placeholders = ",".join("?" * len(cam_ids))
                    wheres.append(f"json_extract(j.config, '$.camera_id') IN ({placeholders})")
                    params.extend(str(c) for c in cam_ids)
                else:
                    wheres.append("1=0")
            if date_from:
                wheres.append("e.timestamp >= ?")
                params.append(date_from)
            if date_to:
                wheres.append("e.timestamp <= ?")
                params.append(date_to + " 23:59:59")
            if category_filter:
                wheres.append("e.alert_category LIKE ?")
                params.append(f"%{category_filter}%")
            if message_filter:
                wheres.append("e.snapshot_message LIKE ?")
                params.append(f"%{message_filter}%")
            if plate_filter:
                wheres.append("e.lpr_results LIKE ?")
                params.append(f"%{plate_filter}%")

            where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""

            total_row = con.execute(
                f"SELECT COUNT(*) FROM detection_events e JOIN detection_jobs j ON e.job_id = j.id {where_sql}",
                params,
            ).fetchone()
            total = total_row[0] if total_row else 0

            rows = con.execute(
                f"""SELECT e.id, e.timestamp, e.rule_name, e.detection_count, e.in_roi_count,
                           e.snapshot_path, e.alert_category, e.snapshot_message, e.job_id, j.config,
                           e.crossing_counts, e.crowd_count, e.lpr_results,
                           COALESCE(e.cls_name_summary, '{{}}') as cls_name_summary
                    FROM detection_events e
                    JOIN detection_jobs j ON e.job_id = j.id
                    {where_sql}
                    ORDER BY e.timestamp DESC
                    LIMIT ? OFFSET ?""",
                params + [per_page, offset],
            ).fetchall()

            for row in rows:
                cfg = json.loads(row["config"] or "{}")
                camera_id = cfg.get("camera_id", "")
                cam_obj = Camera.objects.filter(id=camera_id).first()

                # Convert UTC timestamp to GMT+7 for display
                ts_raw = row["timestamp"] or ""
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    ts_display = dt.astimezone(_TZ_GMT7).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    ts_display = ts_raw

                try:
                    crossing_counts = json.loads(row["crossing_counts"] or "{}")
                except Exception:
                    crossing_counts = {}
                try:
                    lpr_plates = json.loads(row["lpr_results"] or "[]")
                except Exception:
                    lpr_plates = []
                try:
                    cls_name_summary = json.loads(row["cls_name_summary"] or "{}")
                except Exception:
                    cls_name_summary = {}

                events.append({
                    "id": row["id"],
                    "timestamp": ts_display,
                    "rule_name": row["rule_name"],
                    "detection_count": row["detection_count"],
                    "in_roi_count": row["in_roi_count"],
                    "snapshot_path": row["snapshot_path"],
                    "alert_category": row["alert_category"] or "",
                    "snapshot_message": row["snapshot_message"] or "",
                    "crossing_counts": crossing_counts,
                    "crowd_count": row["crowd_count"] or 0,
                    "lpr_plates": lpr_plates,
                    "cls_name_summary": cls_name_summary,
                    "camera_name": cam_obj.name if cam_obj else camera_id,
                    "job_id": row["job_id"],
                })
            con.close()
        except Exception as e:
            messages.error(request, f"Cannot read engine DB: {e}")

    total_pages = max(1, (total + per_page - 1) // per_page)
    return render(request, "alerts/list.html", {
        "events": events,
        "cameras_list": cameras_list,
        "camera_filter": camera_filter,
        "date_from": date_from,
        "date_to": date_to,
        "location_filter": location_filter,
        "category_filter": category_filter,
        "message_filter": message_filter,
        "plate_filter": plate_filter,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })


@login_required
def alerts_stats(request):
    db_path = settings.ENGINE_DB_PATH
    camera_filter   = request.GET.get("camera", "")
    date_from       = request.GET.get("date_from", "")
    date_to         = request.GET.get("date_to", "")
    location_filter = request.GET.get("location", "")
    category_filter = request.GET.get("category", "")
    message_filter  = request.GET.get("message", "")
    plate_filter    = request.GET.get("plate", "")

    charts = {'daily': {}, 'hourly': {}, 'category': {}, 'camera': {}}
    summary = {'total': 0, 'today': 0, 'top_category': '', 'top_camera': ''}
    cameras_list = Camera.objects.values_list("name", flat=True)

    if os.path.exists(db_path):
        try:
            con = sqlite3.connect(db_path)

            # Build same WHERE clause as alerts()
            wheres, params = [], []
            if camera_filter:
                cam = Camera.objects.filter(name=camera_filter).first()
                wheres.append("json_extract(j.config,'$.camera_id') = ?")
                params.append(str(cam.id) if cam else camera_filter)
            if location_filter:
                from django.db.models import Q
                cam_ids = list(Camera.objects.filter(
                    Q(site_name__icontains=location_filter) |
                    Q(floor__icontains=location_filter) |
                    Q(location__icontains=location_filter)
                ).values_list('id', flat=True))
                if cam_ids:
                    wheres.append(f"json_extract(j.config,'$.camera_id') IN ({','.join('?'*len(cam_ids))})")
                    params.extend(str(c) for c in cam_ids)
                else:
                    wheres.append("1=0")
            if date_from:
                wheres.append("e.timestamp >= ?")
                params.append(date_from)
            if date_to:
                wheres.append("e.timestamp <= ?")
                params.append(date_to + " 23:59:59")
            if category_filter:
                wheres.append("e.alert_category LIKE ?")
                params.append(f"%{category_filter}%")
            if message_filter:
                wheres.append("e.snapshot_message LIKE ?")
                params.append(f"%{message_filter}%")
            if plate_filter:
                wheres.append("e.lpr_results LIKE ?")
                params.append(f"%{plate_filter}%")

            base_from = "FROM detection_events e JOIN detection_jobs j ON e.job_id = j.id"
            w = ("WHERE " + " AND ".join(wheres)) if wheres else ""
            and_ = ("AND" if wheres else "WHERE")

            summary['total'] = con.execute(f"SELECT COUNT(*) {base_from} {w}", params).fetchone()[0] or 0
            summary['today'] = con.execute(
                f"SELECT COUNT(*) {base_from} {w} {and_} e.timestamp >= datetime('now','-24 hours')", params
            ).fetchone()[0] or 0

            # Daily trend (GMT+7)
            rows = con.execute(
                f"SELECT date(datetime(e.timestamp,'+7 hours')) d, COUNT(*) c "
                f"{base_from} {w} GROUP BY d ORDER BY d", params
            ).fetchall()
            charts['daily'] = {'labels': [r[0] for r in rows], 'data': [r[1] for r in rows]}

            # Hour of day (GMT+7)
            rows = con.execute(
                f"SELECT CAST(strftime('%H',datetime(e.timestamp,'+7 hours')) AS INTEGER) h, COUNT(*) c "
                f"{base_from} {w} GROUP BY h ORDER BY h", params
            ).fetchall()
            hour_map = {r[0]: r[1] for r in rows}
            charts['hourly'] = {
                'labels': [f"{h:02d}:00" for h in range(24)],
                'data': [hour_map.get(h, 0) for h in range(24)],
            }

            # By category
            cat_w = ("WHERE " + " AND ".join(wheres + ["e.alert_category != ''"])) if wheres else "WHERE e.alert_category != ''"
            rows = con.execute(
                f"SELECT e.alert_category, COUNT(*) c {base_from} {cat_w} GROUP BY e.alert_category ORDER BY c DESC LIMIT 10",
                params
            ).fetchall()
            charts['category'] = {'labels': [r[0] for r in rows], 'data': [r[1] for r in rows]}
            if rows:
                summary['top_category'] = rows[0][0]

            # By camera
            rows = con.execute(
                f"SELECT json_extract(j.config,'$.camera_id') cid, COUNT(*) c {base_from} {w} GROUP BY cid ORDER BY c DESC LIMIT 10",
                params
            ).fetchall()
            cam_labels = []
            for r in rows:
                cam_obj = Camera.objects.filter(id=r[0]).first()
                cam_labels.append(cam_obj.name if cam_obj else (r[0] or '?'))
            charts['camera'] = {'labels': cam_labels, 'data': [r[1] for r in rows]}
            if cam_labels:
                summary['top_camera'] = cam_labels[0]

            con.close()
        except Exception as e:
            messages.error(request, f"Cannot read engine DB: {e}")

    return render(request, "alerts/stats.html", {
        "charts": charts,
        "summary": summary,
        "cameras_list": cameras_list,
        "camera_filter": camera_filter,
        "date_from": date_from,
        "date_to": date_to,
        "location_filter": location_filter,
        "category_filter": category_filter,
        "message_filter": message_filter,
        "plate_filter": plate_filter,
    })


def snapshot_image(request, rel_path):
    snapshots_dir = Path(settings.ENGINE_SNAPSHOTS_DIR)
    full_path = (snapshots_dir / rel_path).resolve()
    if not str(full_path).startswith(str(snapshots_dir)):
        raise Http404
    if not full_path.exists():
        raise Http404
    return FileResponse(open(full_path, "rb"), content_type="image/jpeg")


# ── Settings ──────────────────────────────────────────────────────────────────

@role_required('admin')
def settings_view(request):
    users = User.objects.all().order_by("username")
    edge = EdgeConfig.objects.first()
    return render(request, "settings/index.html", {"users": users, "edge": edge})


def api_cameras(request):
    """Public API — returns id→name mapping for all cameras."""
    cameras = Camera.objects.values('id', 'name')
    return JsonResponse({str(c['id']): c['name'] for c in cameras})


def edge_info(request):
    """Public API — returns edge identity and site info for main server consumption."""
    edge = EdgeConfig.objects.first()
    if not edge:
        return JsonResponse({"error": "not configured"}, status=404)
    return JsonResponse({
        "edge_name":      edge.edge_name,
        "engine_url":     edge.engine_url,
        "location": {
            "latitude":   edge.latitude,
            "longitude":  edge.longitude,
            "address":    edge.address,
            "building":   edge.building,
            "floor":      edge.floor,
            "notes":      edge.site_notes,
        },
        "cameras": {
            "total":  Camera.objects.count(),
            "active": Camera.objects.filter(is_active=True).count(),
        },
        "updated_at": edge.updated_at.isoformat() if edge.updated_at else None,
    })


@role_required('admin')
def user_create(request):
    if request.method == "POST":
        p = request.POST
        username = p["username"].strip()
        password = p["password"].strip()
        role = p.get("role", "viewer")
        if role not in ("admin", "operator", "viewer"):
            role = "viewer"
        if User.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' already exists.")
        else:
            User.objects.create_user(username=username, password=password, role=role)
            messages.success(request, f"User '{username}' created.")
    return redirect("settings")


@role_required('admin')
def user_delete(request, pk):
    if request.method == "POST":
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            messages.error(request, "Cannot delete yourself.")
        else:
            user.delete()
            messages.success(request, "User deleted.")
    return redirect("settings")


def _write_engine_env(engine_env_path: str, edge_name: str, publisher_type: str = "redis",
                      pubsub_project_id: str = "", pubsub_topic: str = "soca-detections",
                      gac_path: str = ""):
    """Write or update EDGE_NAME, Pub/Sub, and GAC vars in the soca-engine .env file."""
    p = Path(engine_env_path)
    lines = p.read_text().splitlines() if p.exists() else []
    ENV_KEYS = {
        "EDGE_NAME": edge_name,
        "PUBLISHER_TYPE": publisher_type,
        "PUBSUB_PROJECT_ID": pubsub_project_id,
        "PUBSUB_TOPIC": pubsub_topic,
        "GOOGLE_APPLICATION_CREDENTIALS": gac_path,
    }
    updated = set()
    for i, line in enumerate(lines):
        for key in ENV_KEYS:
            if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                lines[i] = f"{key}={ENV_KEYS[key]}"
                updated.add(key)
                break
    for key, val in ENV_KEYS.items():
        if key not in updated:
            lines.append(f"{key}={val}")
    p.write_text("\n".join(lines) + "\n")


@role_required('admin')
def site_branding_save(request):
    if request.method != 'POST':
        return redirect('settings')
    config = SiteConfig.get()
    config.company_name = request.POST.get('company_name', config.company_name).strip() or config.company_name
    config.app_name     = request.POST.get('app_name', config.app_name).strip() or config.app_name
    try:
        config.logo_height = max(16, min(200, int(request.POST.get('logo_height', config.logo_height))))
    except (ValueError, TypeError):
        pass
    if request.POST.get('clear_logo') and config.company_logo:
        config.company_logo.delete(save=False)
        config.company_logo = None
    elif 'company_logo' in request.FILES:
        if config.company_logo:
            config.company_logo.delete(save=False)
        config.company_logo = request.FILES['company_logo']
    config.save()
    messages.success(request, 'Branding updated.')
    return redirect('settings')


@role_required('admin')
def edge_settings(request):
    if request.method == "POST":
        p = request.POST
        edge, _ = EdgeConfig.objects.get_or_create(pk=1)
        edge.edge_name = p.get("edge_name", edge.edge_name)
        edge.engine_url = p.get("engine_url", edge.engine_url)
        edge.mediamtx_url = p.get("mediamtx_url", edge.mediamtx_url)
        edge.mediamtx_rtsp_url = p.get("mediamtx_rtsp_url", edge.mediamtx_rtsp_url)
        edge.mediamtx_yml_path = p.get("mediamtx_yml_path", edge.mediamtx_yml_path)
        edge.engine_env_path = p.get("engine_env_path", edge.engine_env_path)
        edge.telegram_bot_token = p.get("telegram_bot_token", edge.telegram_bot_token)
        edge.telegram_chat_id = p.get("telegram_chat_id", edge.telegram_chat_id)
        edge.address    = p.get("address", edge.address)
        edge.building   = p.get("building", edge.building)
        edge.floor      = p.get("floor", edge.floor)
        edge.site_notes = p.get("site_notes", edge.site_notes)
        edge.engine_db_path = p.get('engine_db_path', edge.engine_db_path)
        edge.snapshots_root = p.get('snapshots_root', edge.snapshots_root)
        edge.redis_stream = p.get('redis_stream', 'soca:detections').strip() or 'soca:detections'
        edge.publisher_type    = p.get("publisher_type", "redis")
        edge.pubsub_project_id = p.get("pubsub_project_id", "")
        edge.pubsub_topic      = p.get("pubsub_topic", "soca-detections")
        # GCS key upload
        gcs_file = request.FILES.get('gcs_file')
        if gcs_file:
            from django.conf import settings as django_settings
            creds_dir = django_settings.BASE_DIR / 'credentials'
            creds_dir.mkdir(exist_ok=True)
            safe_name = Path(gcs_file.name).name
            dest = creds_dir / safe_name
            with open(dest, 'wb') as fh:
                for chunk in gcs_file.chunks():
                    fh.write(chunk)
            edge.gcs_key_path = str(dest)
        else:
            edge.gcs_key_path = p.get('gcs_key_path', edge.gcs_key_path).strip()

        # Pub/Sub key upload
        pubsub_file = request.FILES.get('pubsub_file')
        if pubsub_file:
            from django.conf import settings as django_settings
            creds_dir = django_settings.BASE_DIR / 'credentials'
            creds_dir.mkdir(exist_ok=True)
            safe_name = Path(pubsub_file.name).name
            dest = creds_dir / safe_name
            with open(dest, 'wb') as fh:
                for chunk in pubsub_file.chunks():
                    fh.write(chunk)
            edge.pubsub_key_path = str(dest)
        else:
            edge.pubsub_key_path = p.get('pubsub_key_path', edge.pubsub_key_path).strip()

        edge.gcs_bucket      = p.get('gcs_bucket', edge.gcs_bucket).strip()
        edge.gcs_path_prefix = p.get('gcs_path_prefix', edge.gcs_path_prefix).strip()
        edge.engine_api_key  = p.get('engine_api_key', edge.engine_api_key).strip()
        lat = p.get("latitude", "").strip()
        lng = p.get("longitude", "").strip()
        edge.latitude  = float(lat) if lat else None
        edge.longitude = float(lng) if lng else None
        edge.save()
        messages.success(request, "Edge settings saved.")
    return redirect("settings")

@role_required('admin')
@require_POST
def push_to_engine(request):
    """POST /settings/push-to-engine/ — push config to soca-engine via its config API."""
    import base64
    import requests as _requests
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    edge, _ = EdgeConfig.objects.get_or_create(pk=1)

    if not edge.engine_url:
        messages.error(request, 'Engine URL not configured.')
        return redirect('settings')
    if not edge.engine_api_key:
        messages.error(request, 'ENGINE_API_KEY not set — add it to Edge Config.')
        return redirect('settings')

    def _read_b64(path: str) -> str:
        if path and _Path(path).exists():
            return base64.b64encode(_Path(path).read_bytes()).decode()
        return ""

    payload = {
        "gcs_bucket":        edge.gcs_bucket,
        "gcs_path_prefix":   edge.gcs_path_prefix,
        "gcs_key":           _read_b64(edge.gcs_key_path),
        "publisher_type":    getattr(edge, 'publisher_type', 'redis'),
        "pubsub_project_id": getattr(edge, 'pubsub_project_id', ''),
        "pubsub_topic":      getattr(edge, 'pubsub_topic', 'soca-detections'),
        "pubsub_key":        _read_b64(edge.pubsub_key_path),
    }

    engine_url = edge.engine_url.rstrip('/')
    try:
        resp = _requests.post(
            f"{engine_url}/config",
            json=payload,
            headers={"Authorization": f"Bearer {edge.engine_api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        edge.last_engine_push_at = datetime.now(timezone.utc)
        edge.last_engine_push_ok = True
        edge.save(update_fields=['last_engine_push_at', 'last_engine_push_ok'])
        messages.success(request, 'Config pushed to soca-engine. Restart engine to apply.')
    except Exception as exc:
        edge.last_engine_push_at = datetime.now(timezone.utc)
        edge.last_engine_push_ok = False
        edge.save(update_fields=['last_engine_push_at', 'last_engine_push_ok'])
        messages.error(request, f'Push failed: {exc}')

    return redirect('settings')


# ── AI Models ─────────────────────────────────────────────────────────────────

def _engine_headers(edge):
    return {"Authorization": f"Bearer {edge.engine_api_key}"}


@login_required
def models_list_proxy(request):
    """GET /settings/models/ — fetch model list from soca-engine."""
    import requests as _requests
    edge = EdgeConfig.objects.first()
    if not edge or not edge.engine_url or not edge.engine_api_key:
        return JsonResponse({"error": "Engine not configured"}, status=503)
    try:
        resp = _requests.get(
            f"{edge.engine_url.rstrip('/')}/models",
            headers=_engine_headers(edge),
            timeout=8,
        )
        return JsonResponse(resp.json(), status=resp.status_code)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=502)


@role_required('admin')
@require_POST
def model_upload(request):
    """POST /settings/models/upload/ — upload a model file to soca-engine."""
    import requests as _requests
    edge = EdgeConfig.objects.first()
    if not edge or not edge.engine_url or not edge.engine_api_key:
        messages.error(request, 'Engine not configured.')
        return redirect('settings')
    uploaded = request.FILES.get('model_file')
    if not uploaded:
        messages.error(request, 'No file selected.')
        return redirect('settings')
    try:
        resp = _requests.post(
            f"{edge.engine_url.rstrip('/')}/models/upload",
            headers=_engine_headers(edge),
            files={"file": (uploaded.name, uploaded, uploaded.content_type or 'application/octet-stream')},
            timeout=60,
        )
        resp.raise_for_status()
        messages.success(request, f'"{uploaded.name}" uploaded to soca-engine.')
    except Exception as exc:
        messages.error(request, f'Upload failed: {exc}')
    return redirect('settings')


@role_required('admin')
@require_POST
def model_delete(request, filename):
    """POST /settings/models/<filename>/delete/ — delete a model file on soca-engine."""
    import requests as _requests
    edge = EdgeConfig.objects.first()
    if not edge or not edge.engine_url or not edge.engine_api_key:
        messages.error(request, 'Engine not configured.')
        return redirect('settings')
    try:
        resp = _requests.delete(
            f"{edge.engine_url.rstrip('/')}/models/{filename}",
            headers=_engine_headers(edge),
            timeout=10,
        )
        resp.raise_for_status()
        messages.success(request, f'"{filename}" deleted.')
    except Exception as exc:
        messages.error(request, f'Delete failed: {exc}')
    return redirect('settings')


# ── Operations: API key management ────────────────────────────────────────────

@role_required('admin')
def generate_api_key(request):
    if request.method == 'POST':
        edge, _ = EdgeConfig.objects.get_or_create(pk=1)
        edge.api_key = secrets.token_hex(32)
        edge.save(update_fields=['api_key'])
        messages.success(request, 'API key regenerated.')
    return redirect('settings')


# ── Operations: schedule list (session-auth) ───────────────────────────────────

@role_required('admin')
def schedule_status_all(request):
    return JsonResponse(_schedule_list_data(), safe=False)


# ── Operations: purge (session-auth) ──────────────────────────────────────────

@role_required('admin')
def purge_preview_view(request):
    try:
        older_than = int(request.GET.get('older_than', 0))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid older_than value'}, status=400)
    if older_than not in VALID_DAYS:
        return JsonResponse({'error': 'Invalid older_than value'}, status=400)
    edge = EdgeConfig.objects.first()
    if not edge or not edge.engine_db_path:
        return JsonResponse({'error': 'Engine DB path not configured'}, status=503)
    try:
        result = _purge_preview_helper(edge.engine_db_path, edge.snapshots_root, older_than)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': 'Internal error', 'detail': str(e)}, status=500)


@role_required('admin')
def purge_execute_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    import json as _json
    try:
        body = _json.loads(request.body)
        older_than = int(body.get('older_than', 0))
    except Exception:
        return JsonResponse({'error': 'Invalid request body'}, status=400)
    if older_than not in VALID_DAYS:
        return JsonResponse({'error': 'Invalid older_than value'}, status=400)
    edge = EdgeConfig.objects.first()
    if not edge or not edge.engine_db_path:
        return JsonResponse({'error': 'Engine DB path not configured'}, status=503)
    try:
        result = _purge_execute_helper(edge.engine_db_path, edge.snapshots_root, older_than)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': 'Internal error', 'detail': str(e)}, status=500)


# ── API v1: shared data helpers ────────────────────────────────────────────────

def _schedule_list_data():
    schedules = Schedule.objects.select_related('camera').order_by('name')
    result = []
    for s in schedules:
        status = 'stopped'
        if s.current_job_id:
            job = engine_client.get_job(s.current_job_id)
            if job is None:
                status = 'unknown'
            elif job.get('status') == 'running':
                status = 'running'
        result.append({
            'id': s.id,
            'name': s.name,
            'camera_id': s.camera_id,
            'camera_name': s.camera.name,
            'is_active': s.is_active,
            'alert_category': s.alert_category,
            'job_id': s.current_job_id or None,
            'status': status,
        })
    return result


# ── API v1 endpoints (API-key auth) ───────────────────────────────────────────

@require_api_key
def api_v1_schedules(request):
    return JsonResponse(_schedule_list_data(), safe=False)


@require_api_key
def api_v1_schedule_start(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    schedule = Schedule.objects.filter(pk=pk).select_related('camera').first()
    if not schedule:
        return JsonResponse({'error': 'Schedule not found'}, status=404)
    if not schedule.is_active or not schedule.camera_id:
        return JsonResponse({'error': 'Schedule not startable'}, status=400)
    try:
        config = schedule.to_job_config()
        result = engine_client.start_job(config)
        schedule.current_job_id = result['job_id']
        schedule.save(update_fields=['current_job_id'])
        return JsonResponse({'status': 'started', 'job_id': result['job_id']})
    except Exception as e:
        return JsonResponse({'error': 'Engine unreachable', 'detail': str(e)}, status=502)


@require_api_key
def api_v1_schedule_stop(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    schedule = Schedule.objects.filter(pk=pk).first()
    if not schedule:
        return JsonResponse({'error': 'Schedule not found'}, status=404)
    if not schedule.current_job_id:
        return JsonResponse({'status': 'already_stopped'})
    try:
        engine_client.stop_job(schedule.current_job_id)
    except Exception as e:
        return JsonResponse({'error': 'Engine unreachable', 'detail': str(e)}, status=502)
    schedule.current_job_id = ''
    schedule.save(update_fields=['current_job_id'])
    return JsonResponse({'status': 'stopped'})


@require_api_key
def api_v1_purge_preview(request):
    try:
        older_than = int(request.GET.get('older_than', 0))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid older_than value'}, status=400)
    if older_than not in VALID_DAYS:
        return JsonResponse({'error': 'Invalid older_than value'}, status=400)
    edge = EdgeConfig.objects.first()
    if not edge or not edge.engine_db_path:
        return JsonResponse({'error': 'Engine DB path not configured'}, status=503)
    try:
        return JsonResponse(_purge_preview_helper(edge.engine_db_path, edge.snapshots_root, older_than))
    except Exception as e:
        return JsonResponse({'error': 'Internal error', 'detail': str(e)}, status=500)


@require_api_key
def api_v1_cameras(request):
    cameras = list(Camera.objects.order_by('name').values(
        'id', 'name', 'site_name', 'floor', 'location', 'is_active', 'created_at'
    ))
    cfg = EdgeConfig.objects.first()
    relay_enabled = bool(cfg and cfg.mediamtx_rtsp_url)
    for c in cameras:
        if c.get('created_at'):
            c['created_at'] = c['created_at'].isoformat()
        c['mediamtx_relay_enabled'] = relay_enabled
    return JsonResponse({'cameras': cameras})


@require_api_key
def api_v1_purge_execute(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    import json as _json
    try:
        body = _json.loads(request.body)
        older_than = int(body.get('older_than', 0))
    except Exception:
        return JsonResponse({'error': 'Invalid request body'}, status=400)
    if older_than not in VALID_DAYS:
        return JsonResponse({'error': 'Invalid older_than value'}, status=400)
    edge = EdgeConfig.objects.first()
    if not edge or not edge.engine_db_path:
        return JsonResponse({'error': 'Engine DB path not configured'}, status=503)
    try:
        return JsonResponse(_purge_execute_helper(edge.engine_db_path, edge.snapshots_root, older_than))
    except Exception as e:
        return JsonResponse({'error': 'Internal error', 'detail': str(e)}, status=500)


# ── Rules ─────────────────────────────────────────────────────────────────────

@role_required('admin', 'operator')
def rule_save(request, pk):
    """Create or update a Rule for a schedule. POST only."""
    if request.method != 'POST':
        return redirect('schedule_edit', pk=pk)
    schedule = get_object_or_404(Schedule, pk=pk)
    rid = request.POST.get('rule_id', '').strip()

    name = request.POST.get('rule_name', '').strip()
    if not name:
        messages.error(request, 'Rule name is required.')
        return redirect('schedule_edit', pk=pk)

    def _int(key, default):
        try:
            return int(request.POST.get(key) or default)
        except (ValueError, TypeError):
            return default

    # Each rule card submits its own form — fields are singular (not [] arrays)
    data = {
        'name': name,
        'category': request.POST.get('rule_category', 'Intrusion').strip() or 'Intrusion',
        'cls_operator': request.POST.get('cls_operator', 'in'),
        'cls_ids': [int(x) for x in request.POST.getlist('cls_ids') if x.isdigit()],
        'processing': request.POST.get('processing', 'in_roi'),
        'trigger': request.POST.get('trigger', 'present'),
        'duration_op': request.POST.get('duration_op', 'immediate'),
        'duration_seconds': _int('duration_seconds', 0),
        'cooldown_seconds': _int('cooldown_seconds', 60),
        'cron_schedule': request.POST.get('cron_schedule', '* * * * *').strip() or '* * * * *',
        'message_template': request.POST.get('message_template', '').strip(),
        'action_telegram': request.POST.get('action_telegram') == 'on',
        'action_redis': request.POST.get('action_redis') == 'on',
        'action_snapshot': request.POST.get('action_snapshot') == 'on',
        'priority': _int('priority', 100),
        'is_active': request.POST.get('is_active') == 'on',
        'mode': request.POST.get('rule_mode', 'detection'),
        'count_threshold': _int('count_threshold', 0),
        # direction and crossing_line are schedule-level (ROI section) — not saved per-rule
    }

    if rid:
        Rule.objects.filter(pk=rid, schedule=schedule).update(**data)
    else:
        Rule.objects.create(schedule=schedule, **data)
    return redirect('schedule_edit', pk=pk)


@role_required('admin', 'operator')
def rule_delete(request, pk, rid):
    """Delete a Rule. POST only."""
    if request.method != 'POST':
        return redirect('schedule_edit', pk=pk)
    Rule.objects.filter(pk=rid, schedule_id=pk).delete()
    return redirect('schedule_edit', pk=pk)


@login_required
def model_labels_proxy(request):
    """Read class labels for a model directly from filesystem. Returns JSON."""
    model_path = request.GET.get('path', '')
    if not model_path:
        return JsonResponse({'labels': []})

    def _read_yaml_names(p):
        try:
            with open(p) as f:
                data = yaml.safe_load(f) or {}
            names = data.get('names', [])
            if isinstance(names, list):
                return [{'id': i, 'name': n} for i, n in enumerate(names)]
            if isinstance(names, dict):
                return [{'id': k, 'name': v} for k, v in sorted(names.items())]
        except Exception:
            pass
        return None

    base = os.path.splitext(model_path)[0]

    # <model>.names
    names_path = base + '.names'
    if os.path.exists(names_path):
        try:
            with open(names_path) as f:
                names = [l.strip() for l in f if l.strip()]
            return JsonResponse({'labels': [{'id': i, 'name': n} for i, n in enumerate(names)]})
        except Exception:
            pass

    # <full_path>.yaml  (e.g. yolo11n.mlpackage.yaml)
    result = _read_yaml_names(model_path + '.yaml')
    if result is not None:
        return JsonResponse({'labels': result})

    # <base>.yaml  (e.g. yolov8n.yaml)
    result = _read_yaml_names(base + '.yaml')
    if result is not None:
        return JsonResponse({'labels': result})

    # data.yaml in same directory
    result = _read_yaml_names(os.path.join(os.path.dirname(model_path), 'data.yaml'))
    if result is not None:
        return JsonResponse({'labels': result})

    # Fallback: try engine proxy
    labels = engine_client.get_model_labels(model_path)
    return JsonResponse({'labels': labels})
