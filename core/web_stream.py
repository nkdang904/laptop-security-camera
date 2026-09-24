import os
import re
import hmac
import json
import time
import socket
import hashlib
import logging
import tempfile
import mimetypes
import threading
import subprocess
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode, unquote
from typing import Optional, Callable, Dict, Any, Tuple
import cv2
import numpy as np

from core.video_writer import export_clip

logger = logging.getLogger(__name__)

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
COOKIE_NAME = "camsess"
CLIENT_GONE = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError)


def get_local_ip() -> str:
    """Lấy địa chỉ IP nội bộ (LAN IP) của laptop."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class JpegCache:
    """Mã hoá JPEG 1 lần cho mỗi frame mới, dùng chung cho mọi người xem (tiết kiệm CPU)."""

    def __init__(self, camera, detector=None):
        self.camera = camera
        self.detector = detector
        self._lock = threading.Lock()
        self._cache: Dict[Tuple[bool, int], Tuple[float, bytes]] = {}

    def get(self, overlay: bool = False, quality: int = 70) -> Tuple[float, Optional[bytes]]:
        ok, frame, ts = self.camera.get_latest_frame()
        if not ok or frame is None:
            return 0.0, None
        key = (overlay, quality)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] == ts:
                return cached
        if overlay and self.detector is not None:
            frame = self.detector.draw_recent(frame)
        ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ret:
            return 0.0, None
        data = jpeg.tobytes()
        with self._lock:
            self._cache[key] = (ts, data)
        return ts, data


class StreamingServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler, manager: "LiveStreamManager"):
        super().__init__(server_address, handler)
        self.manager = manager
        self.stopping = False


class StreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: StreamingServer

    def log_message(self, format, *args):
        # Tắt in log request HTTP thông thường để không làm loãng console
        pass

    # ------------------------------------------------------------ utilities
    @property
    def mgr(self) -> "LiveStreamManager":
        return self.server.manager

    def _parse(self):
        u = urlparse(self.path)
        self.route = unquote(u.path)
        self.query = {k: v[-1] for k, v in parse_qs(u.query).items()}

    def _cookie(self, name: str) -> str:
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def _authed(self) -> bool:
        return hmac.compare_digest(self._cookie(COOKIE_NAME), self.mgr.session_token)

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200, headers: Optional[dict] = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, obj: Any, status: int = 200, headers: Optional[dict] = None):
        self._send_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8", status, {"Cache-Control": "no-store", **(headers or {})})

    def _read_body(self):
        # Luôn đọc hết body để phần dư không bị hiểu nhầm là request kế tiếp (keep-alive)
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > 1_000_000:
            self.close_connection = True
            self.raw_body = b""
            return
        self.raw_body = self.rfile.read(length) if length > 0 else b""

    def _body(self) -> Dict[str, Any]:
        try:
            return json.loads(self.raw_body.decode("utf-8")) if self.raw_body else {}
        except Exception:
            return {}

    def _send_file(self, path: str, content_type: Optional[str] = None, download_name: Optional[str] = None,
                   cache: str = "no-cache"):
        """Gửi file có hỗ trợ HTTP Range (bắt buộc để trình duyệt tua video)."""
        if not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        size = os.path.getsize(path)
        ctype = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if m and size > 0:
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", cache)
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _safe_join(self, base: str, rel: str) -> Optional[str]:
        full = os.path.abspath(os.path.join(base, rel.replace("/", os.sep)))
        if os.path.commonpath([full, os.path.abspath(base)]) != os.path.abspath(base):
            return None
        return full

    # -------------------------------------------------------------- routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method: str):
        try:
            self._parse()
            self._read_body()
            route = self.route

            # Đăng nhập nhanh qua link có ?key=... (link gửi trong Telegram)
            if method == "GET" and "key" in self.query:
                if hmac.compare_digest(self.query["key"], self.mgr.access_key):
                    rest = {k: v for k, v in self.query.items() if k != "key"}
                    loc = route + ("?" + urlencode(rest) if rest else "")
                    return self._send_bytes(b"", "text/plain", 302, {"Location": loc, "Set-Cookie": self.mgr.cookie_header()})

            if route.startswith("/static/"):
                path = self._safe_join(WEB_DIR, route[len("/static/"):])
                return self._send_file(path, cache="no-cache") if path else self._json({"error": "bad path"}, 400)

            if route == "/api/login" and method == "POST":
                return self._login()

            if not self._authed():
                if route in ("/", "/index.html"):
                    return self._send_file(os.path.join(WEB_DIR, "login.html"), "text/html; charset=utf-8")
                return self._json({"error": "unauthorized"}, 401)

            handler = self.mgr.routes.get((method, route))
            if handler:
                return handler(self)
            for (m, pattern), fn in self.mgr.regex_routes:
                if m == method:
                    match = pattern.fullmatch(route)
                    if match:
                        return fn(self, *match.groups())
            self._json({"error": "not found"}, 404)
        except CLIENT_GONE:
            pass
        except Exception as e:
            logger.exception(f"Lỗi xử lý request {self.path}: {e}")
            try:
                self._json({"error": str(e)}, 500)
            except Exception:
                pass

    def _login(self):
        body = self._body()
        pw = str(body.get("password", ""))
        ok = hmac.compare_digest(pw, self.mgr.access_key) or (
            self.mgr.password and hmac.compare_digest(pw, self.mgr.password))
        if not ok:
            time.sleep(1.0)  # chống dò mật khẩu
            return self._json({"ok": False, "error": "Sai mật khẩu hoặc khoá truy cập"}, 403)
        self._json({"ok": True}, headers={"Set-Cookie": self.mgr.cookie_header()})


# ================================================================== API routes
def _ev_json(index, ev: Dict[str, Any]) -> Dict[str, Any]:
    ev = dict(ev)
    ev["snapshot_url"] = f"/media/{ev['snapshot']}" if ev.get("snapshot") else ""
    ev["clip_url"] = f"/media/{ev['clip']}" if ev.get("clip") else ""
    return ev


def r_index(h: StreamHandler):
    h._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")


def r_logout(h: StreamHandler):
    h._json({"ok": True}, headers={"Set-Cookie": f"{COOKIE_NAME}=; Path=/; Max-Age=0"})


def r_stream(h: StreamHandler):
    overlay = h.query.get("overlay") == "1"
    quality = min(95, max(30, int(h.query.get("q", 70))))
    max_fps = min(30, max(1, int(h.query.get("fps", 20))))
    min_interval = 1.0 / max_fps
    h.send_response(200)
    h.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
    h.send_header("Cache-Control", "no-cache, private")
    h.send_header("Pragma", "no-cache")
    h.send_header("Connection", "close")
    h.end_headers()
    h.close_connection = True
    last_ts, last_sent = 0.0, 0.0
    while not h.server.stopping:
        ts, data = h.mgr.jpeg.get(overlay, quality)
        now = time.time()
        if data is None or ts == last_ts or now - last_sent < min_interval:
            time.sleep(0.01)
            continue
        last_ts, last_sent = ts, now
        h.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
        h.wfile.write(f"Content-Length: {len(data)}\r\nX-Timestamp: {ts:.3f}\r\n\r\n".encode())
        h.wfile.write(data)
        h.wfile.write(b"\r\n")


def r_snapshot(h: StreamHandler):
    ts, data = h.mgr.jpeg.get(h.query.get("overlay") == "1", 90)
    if data is None:
        return h._json({"error": "Camera chưa sẵn sàng"}, 503)
    headers = {"Cache-Control": "no-store"}
    if h.query.get("download") == "1":
        name = datetime.fromtimestamp(ts).strftime("snapshot_%Y%m%d_%H%M%S.jpg")
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    h._send_bytes(data, "image/jpeg", headers=headers)


def r_status(h: StreamHandler):
    h._json(h.mgr.controller.status())


def r_settings_get(h: StreamHandler):
    h._json(h.mgr.controller.get_settings())


def r_settings_post(h: StreamHandler):
    h._json(h.mgr.controller.update_settings(h._body()))


def r_timeline(h: StreamHandler):
    now = time.time()
    start = float(h.query.get("start", now - 86400))
    end = float(h.query.get("end", now))
    idx = h.mgr.index
    types = [t for t in h.query.get("types", "").split(",") if t] or None
    h._json({
        "now": now,
        "segments": idx.query_segments(start, end),
        "events": [] if h.query.get("events") == "0" else [_ev_json(idx, e) for e in idx.query_events(start, end, types)],
    })


def r_events(h: StreamHandler):
    now = time.time()
    start = float(h.query.get("start", now - 7 * 86400))
    end = float(h.query.get("end", now + 60))
    types = [t for t in h.query.get("types", "").split(",") if t] or None
    limit = min(1000, int(h.query.get("limit", 200)))
    idx = h.mgr.index
    h._json({"events": [_ev_json(idx, e) for e in idx.query_events(start, end, types, limit, newest_first=True)]})


def r_days(h: StreamHandler):
    h._json(h.mgr.index.day_summary())


def r_segment(h: StreamHandler, seg_id: str):
    seg = h.mgr.index.get_segment(int(seg_id))
    if not seg:
        return h._json({"error": "not found"}, 404)
    h._send_file(h.mgr.index.abs(seg["path"]), "video/mp4",
                 cache="max-age=3600" if seg["complete"] else "no-cache")


def r_media(h: StreamHandler, rel: str):
    path = h._safe_join(h.mgr.index.base_dir, rel)
    if not path or os.path.basename(path) == "index.db" or path.endswith((".db-wal", ".db-shm")):
        return h._json({"error": "forbidden"}, 403)
    name = os.path.basename(path) if h.query.get("download") == "1" else None
    h._send_file(path, download_name=name, cache="max-age=86400")


def r_export(h: StreamHandler):
    start, end = float(h.query["start"]), float(h.query["end"])
    if end <= start or end - start > 3600:
        return h._json({"error": "Khoảng thời gian không hợp lệ (tối đa 60 phút)"}, 400)
    idx = h.mgr.index
    segs = [(idx.abs(s["path"]), s["start"]) for s in idx.segments_for_range(start, end)]
    if not segs:
        return h._json({"error": "Không có dữ liệu ghi hình trong khoảng này"}, 404)
    fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="cam_export_")
    os.close(fd)
    try:
        if not export_clip(segs, start, end, tmp):
            return h._json({"error": "Xuất clip thất bại"}, 500)
        name = (datetime.fromtimestamp(start).strftime("cam_%Y%m%d_%H%M%S")
                + datetime.fromtimestamp(end).strftime("-%H%M%S.mp4"))
        h._send_file(tmp, "video/mp4", download_name=name, cache="no-store")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def r_take_snapshot(h: StreamHandler):
    ev = h.mgr.controller.take_snapshot()
    if not ev:
        return h._json({"error": "Camera chưa sẵn sàng"}, 503)
    h._json({"ok": True, "event": _ev_json(h.mgr.index, ev)})


def r_record_start(h: StreamHandler):
    ok = h.mgr.controller.start_manual_recording()
    h._json({"ok": ok})


def r_record_stop(h: StreamHandler):
    ev = h.mgr.controller.stop_manual_recording()
    h._json({"ok": bool(ev), "event": _ev_json(h.mgr.index, ev) if ev else None})


def r_event_delete(h: StreamHandler, event_id: str):
    h._json({"ok": h.mgr.index.delete_event(int(event_id))})


class LiveStreamManager:
    """
    Web app camera: xem trực tiếp (MJPEG), xem lại theo timeline (H.264), sự kiện, thiết lập.
    Kèm Cloudflare Quick Tunnel để xem từ xa qua 4G.
    """

    def __init__(self, port: int = 8080, camera=None, detector=None, controller=None, index=None,
                 access_key: str = "", password: str = "", enable_tunnel: bool = True):
        self.port = port
        self.camera = camera
        self.controller = controller
        self.index = index
        self.access_key = access_key
        self.password = password or ""
        self.enable_tunnel = enable_tunnel
        self.jpeg = JpegCache(camera, detector)
        self.session_token = hashlib.sha256(f"camsess:{access_key}:{self.password}".encode()).hexdigest()

        self.routes: Dict[Tuple[str, str], Callable] = {
            ("GET", "/"): r_index,
            ("GET", "/index.html"): r_index,
            ("GET", "/stream"): r_stream,
            ("GET", "/snapshot"): r_snapshot,
            ("GET", "/snapshot.jpg"): r_snapshot,
            ("GET", "/api/status"): r_status,
            ("GET", "/api/settings"): r_settings_get,
            ("POST", "/api/settings"): r_settings_post,
            ("GET", "/api/timeline"): r_timeline,
            ("GET", "/api/events"): r_events,
            ("GET", "/api/days"): r_days,
            ("GET", "/api/export"): r_export,
            ("POST", "/api/snapshot"): r_take_snapshot,
            ("POST", "/api/record/start"): r_record_start,
            ("POST", "/api/record/stop"): r_record_stop,
            ("POST", "/api/logout"): r_logout,
        }
        self.regex_routes = [
            (("GET", re.compile(r"/api/segment/(\d+)(?:\.mp4)?")), r_segment),
            (("GET", re.compile(r"/media/(.+)")), r_media),
            (("POST", re.compile(r"/api/events/(\d+)/delete")), r_event_delete),
        ]

        self.server: Optional[StreamingServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.tunnel_process: Optional[subprocess.Popen] = None
        self.tunnel_url: Optional[str] = None
        self.is_running = False

    def cookie_header(self) -> str:
        return f"{COOKIE_NAME}={self.session_token}; Path=/; Max-Age={30 * 86400}; HttpOnly; SameSite=Lax"

    def start(self):
        if self.is_running or not self.camera:
            return

        try:
            self.server = StreamingServer(("0.0.0.0", self.port), StreamHandler, self)
            self.is_running = True
            self.server_thread = threading.Thread(target=self.server.serve_forever, name="WebStreamServer", daemon=True)
            self.server_thread.start()
            logger.info(f"Web App Camera đã chạy tại: http://localhost:{self.port}/?key={self.access_key}")
            logger.info(f"   (LAN: http://{get_local_ip()}:{self.port}/?key={self.access_key})")

            if self.enable_tunnel:
                self._start_tunnel()
        except Exception as e:
            logger.error(f"Không thể khởi động Web Stream Server: {e}")

    def _start_tunnel(self):
        """Khởi động Cloudflare Quick Tunnel nếu có cloudflared."""
        cloudflared_path = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
        if not os.path.exists(cloudflared_path):
            cloudflared_path = "cloudflared"

        try:
            cmd = [cloudflared_path, "tunnel", "--url", f"http://127.0.0.1:{self.port}"]
            self.tunnel_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )

            # Đọc log để trích xuất URL tunnel
            threading.Thread(target=self._monitor_tunnel_output, name="TunnelMonitor", daemon=True).start()
        except Exception as e:
            logger.warning(f"Không thể khởi động Cloudflare Tunnel: {e}")

    def _monitor_tunnel_output(self):
        if not self.tunnel_process or not self.tunnel_process.stdout:
            return

        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        for line in self.tunnel_process.stdout:
            match = url_pattern.search(line)
            if match and not self.tunnel_url:
                self.tunnel_url = match.group(0)
                logger.info(f"🌐 Cloudflare URL (xem từ xa): {self.tunnel_url}/?key={self.access_key}")
        # Tiếp tục đọc hết output để pipe không bị đầy làm treo cloudflared

    def get_stream_urls(self, with_key: bool = True) -> dict:
        """Trả về danh sách URL xem trực tiếp (kèm khoá truy cập để mở thẳng từ Telegram)."""
        local_ip = get_local_ip()
        suffix = f"/?key={self.access_key}" if with_key else ""
        local = f"http://{local_ip}:{self.port}"
        return {
            "local_url": local + suffix,
            "public_url": (self.tunnel_url or local) + suffix
        }

    def stop(self):
        self.is_running = False
        if self.tunnel_process:
            try:
                self.tunnel_process.terminate()
                self.tunnel_process.kill()
            except Exception:
                pass
            self.tunnel_process = None

        if self.server:
            try:
                self.server.stopping = True
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        logger.info("Web Stream Manager đã dừng.")
