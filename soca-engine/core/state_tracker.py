from datetime import datetime, timezone
from models.schemas import Detection, AgingConfig


class StateTracker:
    def __init__(self, cfg: AgingConfig):
        self.window_seconds   = cfg.window_seconds
        self.cooldown_seconds = cfg.cooldown_seconds
        self._state: dict[int, dict] = {}

    def update(self, detections: list[Detection]) -> dict:
        now = datetime.now(timezone.utc)
        detected_cls = {d.cls_id for d in detections if d.in_roi}

        for cls_id in list(self._state.keys()):
            if cls_id not in detected_cls:
                s = self._state[cls_id]
                # Preserve state while cooldown is still active so it isn't reset
                # by a brief detection gap (occlusion, frame skip, etc.)
                if s["in_cooldown"] and s["cooldown_until"] and now < s["cooldown_until"]:
                    s["duration_seconds"] = 0.0  # object gone, reset duration only
                else:
                    self._state.pop(cls_id)

        for cls_id in detected_cls:
            s = self._state.setdefault(cls_id, {
                "first_seen": now,
                "in_cooldown": False,
                "cooldown_until": None,
            })

            duration = (now - s["first_seen"]).total_seconds()

            if duration >= self.window_seconds:
                s["first_seen"] = now
                duration = 0.0

            if s["in_cooldown"] and s["cooldown_until"] and now >= s["cooldown_until"]:
                s["in_cooldown"] = False
                s["cooldown_until"] = None

            s["duration_seconds"] = duration

        return self._build_context(now)

    def any_in_cooldown(self, cls_ids: list[int]) -> bool:
        """Return True if ANY of the given class IDs is currently in cooldown."""
        now = datetime.now(timezone.utc)
        for cls_id in cls_ids:
            s = self._state.get(cls_id)
            if s and s["in_cooldown"] and s["cooldown_until"] and now < s["cooldown_until"]:
                return True
        return False

    def mark_triggered(self, cls_ids: list[int]):
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        for cls_id in cls_ids:
            if cls_id in self._state:
                self._state[cls_id]["in_cooldown"] = True
                self._state[cls_id]["cooldown_until"] = now + timedelta(seconds=self.cooldown_seconds)

    def _build_context(self, now: datetime) -> dict:
        return {
            f"cls_{cls_id}": {
                "duration_seconds": s.get("duration_seconds", 0.0),
                "first_seen": s["first_seen"].isoformat(),
                "in_cooldown": s["in_cooldown"],
            }
            for cls_id, s in self._state.items()
        }
