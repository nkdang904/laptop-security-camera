import os
import json
import time
import shutil
import secrets
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any

import psutil

from core.video_writer import H264Writer, stamp_frame

logger = logging.getLogger(__name__)

# Các thiết lập có thể chỉnh trực tiếp trên web (ghi đè config.yaml, lưu ở runtime_settings.json)
SETTINGS_SPEC = {
    "armed": bool,
    "detection_enabled": bool,
    "confidence_threshold": float,
    "cooldown_seconds": int,
    "motion_threshold": int,
    "min_motion_area": int,
    "log_motion_events": bool,
    "continuous_enabled": bool,
    "record_on_detect_seconds": int,
    "send_snapshot": bool,
    "send_video": bool,
    "retention_max_days": int,
    "retention_max_gb": float,
}


class SystemController:
    """
    Điểm điều khiển trung tâm cho web app: trạng thái hệ thống, thiết lập runtime,
    chụp ảnh, ghi clip thủ công. Các module khác (camera, detector...) được gắn vào sau khi khởi tạo.
    """

    def __init__(self, settings_path: str = "runtime_settings.json"):
        self.settings_path = os.path.abspath(settings_path)
        self.started_at = time.time()
        self.camera = None
        self.detector = None
        self.recorder = None
        self.continuous = None
        self.retention = None
        self.telegram = None
        self.index = None
        self.web = None
        self.flags: Dict[str, Any] = {"send_snapshot": True, "send_video": True, "log_motion_events": True}

        self._saved = self._load_file()
        self._manual_writer: Optional[H264Writer] = None
        self._manual_thread: Optional[threading.Thread] = None
        self._manual_event_id: Optional[int] = None
        self._manual_started = 0.0
        self._storage_cache = (0.0, 0)

    # ---------------------------------------------------------------- persist
    def _load_file(self) -> Dict[str, Any]:
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Không đọc được {self.settings_path}: {e}")
        return {}

    def _save_file(self):
        try:
            tmp = self.settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._saved, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.settings_path)
        except Exception as e:
            logger.error(f"Không lưu được thiết lập: {e}")

    def get_access_key(self, configured: str = "") -> str:
        """Khoá truy cập web: lấy từ config, nếu trống thì tự sinh 1 lần và lưu lại."""
        if configured:
            return configured
        key = self._saved.get("web_access_key")
        if not key:
            key = secrets.token_urlsafe(12)
            self._saved["web_access_key"] = key
            self._save_file()
        return key

    def apply_saved_settings(self):
        """Áp các thiết lập đã lưu từ web (sau khi các module đã được gắn)."""
        saved = {k: v for k, v in self._saved.get("settings", {}).items() if k in SETTINGS_SPEC}
        if saved:
            self.update_settings(saved, persist=False)

    # --------------------------------------------------------------- settings
    def get_settings(self) -> Dict[str, Any]:
        d, r, ret, t = self.detector, self.recorder, self.retention, self.telegram
        return {
            "armed": not t.is_muted if t else True,
            "detection_enabled": d.enabled if d else False,
            "confidence_threshold": d.confidence_threshold if d else 0.5,
            "cooldown_seconds": d.cooldown_seconds if d else 30,
            "motion_threshold": d.motion_threshold if d else 25,
            "min_motion_area": d.min_motion_area if d else 800,
            "log_motion_events": self.flags["log_motion_events"],
            "continuous_enabled": self.continuous.enabled if self.continuous else False,
            "record_on_detect_seconds": r.record_seconds if r else 8,
            "send_snapshot": self.flags["send_snapshot"],
            "send_video": self.flags["send_video"],
            "retention_max_days": ret.max_days if ret else 0,
            "retention_max_gb": round(ret.max_storage_bytes / 1024 ** 3, 2) if ret else 0,
            "telegram_configured": bool(t and t.is_configured),
        }

    def update_settings(self, changes: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}
        for k, v in changes.items():
            typ = SETTINGS_SPEC.get(k)
            if typ is None:
                continue
            try:
                clean[k] = (v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on")) if typ is bool else typ(v)
            except (TypeError, ValueError):
                continue

        d, r, ret, t = self.detector, self.recorder, self.retention, self.telegram
        for k, v in clean.items():
            if k == "armed" and t:
                t.is_muted = not v
            elif k == "detection_enabled" and d:
                d.enabled = v
            elif k == "confidence_threshold" and d:
                d.confidence_threshold = min(0.95, max(0.1, v))
            elif k == "cooldown_seconds" and d:
                d.cooldown_seconds = max(0, v)
            elif k == "motion_threshold" and d:
                d.motion_threshold = min(100, max(5, v))
            elif k == "min_motion_area" and d:
                d.min_motion_area = max(50, v)
            elif k == "continuous_enabled" and self.continuous:
                self.continuous.set_enabled(v)
            elif k == "record_on_detect_seconds" and r:
                r.record_seconds = min(120, max(3, v))
            elif k == "retention_max_days" and ret:
                ret.max_days = max(1, v)
            elif k == "retention_max_gb" and ret:
                ret.max_storage_bytes = int(max(0.5, v) * 1024 ** 3)
            elif k in self.flags:
                self.flags[k] = v

        if persist and clean:
            saved = self._saved.setdefault("settings", {})
            saved.update(clean)
            self._save_file()
            logger.info(f"Đã cập nhật thiết lập từ web: {clean}")
        return self.get_settings()

    # ----------------------------------------------------------------- status
    def storage_bytes(self) -> int:
        ts, size = self._storage_cache
        if time.time() - ts < 30 and ts:
            return size
        total = 0
        base = self.index.base_dir if self.index else "recordings"
        for root, _, files in os.walk(base):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        self._storage_cache = (time.time(), total)
        return total

    def status(self) -> Dict[str, Any]:
        cam = self.camera
        base = self.index.base_dir if self.index else os.getcwd()
        disk = shutil.disk_usage(base)
        ram = psutil.virtual_memory()
        return {
            "now": time.time(),
            "uptime": int(time.time() - self.started_at),
            "camera_connected": bool(cam and cam.is_connected),
            "camera_fps": round(getattr(cam, "measured_fps", 0.0), 1) if cam else 0,
            "resolution": f"{cam.width}x{cam.height}" if cam else "",
            "continuous_recording": bool(self.continuous and self.continuous.is_recording),
            "event_recording": bool(self.recorder and self.recorder.is_recording),
            "manual_recording": self._manual_writer is not None,
            "manual_started": self._manual_started if self._manual_writer else 0,
            "last_detection": self.detector.last_detection_time if self.detector else 0,
            "cpu": psutil.cpu_percent(interval=None),
            "ram": ram.percent,
            "storage_used": self.storage_bytes(),
            "storage_limit": self.retention.max_storage_bytes if self.retention else 0,
            "disk_free": disk.free,
            "disk_total": disk.total,
            "urls": self.web.get_stream_urls(with_key=False) if self.web else {},
            "armed": not self.telegram.is_muted if self.telegram else True,
        }

    # ---------------------------------------------------------------- actions
    def take_snapshot(self) -> Optional[Dict[str, Any]]:
        frame = self.camera.get_snapshot() if self.camera else None
        if frame is None:
            return None
        path = self.recorder.save_snapshot(frame, prefix="manual")
        now = time.time()
        event_id = self.index.add_event("manual", now, now, label="snapshot", snapshot=path)
        return self.index.get_event(event_id)

    def start_manual_recording(self, max_seconds: int = 600) -> bool:
        if self._manual_writer is not None or not self.camera:
            return False
        now = time.time()
        path = os.path.join(self.recorder.save_dir, f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        cam = self.camera
        self._manual_writer = H264Writer(path, cam.width, cam.height, fps=cam.fps, crf=24)
        self._manual_started = now
        frame = cam.get_snapshot()
        thumb = self.recorder.save_snapshot(frame, prefix="manual") if frame is not None else ""
        self._manual_event_id = self.index.add_event("manual", now, now, label="record", snapshot=thumb)

        def worker():
            writer = self._manual_writer
            last_ts = 0.0
            delay = 1.0 / max(1, cam.fps)
            while self._manual_writer is writer and time.time() - now < max_seconds:
                ok, frame, ts = cam.get_latest_frame()
                if ok and ts > last_ts:
                    last_ts = ts
                    writer.write(stamp_frame(frame, ts), ts)
                time.sleep(delay)
            writer.close()
            self._manual_writer = None
            self.index.update_event(self._manual_event_id, end=time.time(), clip=path)
            logger.info(f"Đã lưu clip ghi thủ công: {path}")

        self._manual_thread = threading.Thread(target=worker, name="ManualRecorder", daemon=True)
        self._manual_thread.start()
        logger.info("Bắt đầu ghi clip thủ công từ web.")
        return True

    def stop_manual_recording(self) -> Optional[Dict[str, Any]]:
        if self._manual_writer is None:
            return None
        event_id = self._manual_event_id
        self._manual_writer = None
        if self._manual_thread:
            self._manual_thread.join(timeout=5)
        return self.index.get_event(event_id)
