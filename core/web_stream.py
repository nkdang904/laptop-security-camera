import os
import re
import time
import socket
import logging
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Callable
import cv2
import numpy as np

logger = logging.getLogger(__name__)

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

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Camera An Ninh Laptop</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: #0f172a;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
            padding: 1rem;
        }
        .header {
            text-align: center;
            margin-bottom: 1rem;
        }
        .header h1 {
            font-size: 1.5rem;
            color: #38bdf8;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
        }
        .badge-live {
            background-color: #ef4444;
            color: white;
            font-size: 0.75rem;
            font-weight: bold;
            padding: 0.2rem 0.6rem;
            border-radius: 9999px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        .video-container {
            width: 100%;
            max-width: 720px;
            background: #1e293b;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            border: 1px solid #334155;
            position: relative;
        }
        .video-container img {
            width: 100%;
            height: auto;
            display: block;
        }
        .controls {
            margin-top: 1.2rem;
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            justify-content: center;
        }
        .btn {
            background: #2563eb;
            color: white;
            padding: 0.6rem 1.2rem;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 500;
            border: none;
            cursor: pointer;
            transition: 0.2s;
            font-size: 0.95rem;
        }
        .btn:hover { background: #1d4ed8; }
        .footer {
            margin-top: auto;
            padding-top: 1.5rem;
            font-size: 0.8rem;
            color: #64748b;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1><span>🎥</span> Camera An Ninh Laptop <span class="badge-live">LIVE</span></h1>
        <p style="color: #94a3b8; font-size: 0.9rem; margin-top: 0.3rem;">Phát trực tiếp thời gian thực</p>
    </div>
    <div class="video-container">
        <img src="/stream" alt="Live Camera Feed">
    </div>
    <div class="controls">
        <button class="btn" onclick="window.location.reload()">🔄 Làm mới</button>
        <a class="btn" href="/snapshot" target="_blank">📸 Tải ảnh Snapshot</a>
    </div>
    <div class="footer">
        Laptop Security Camera System • DirectShow • AI YOLOv8
    </div>
</body>
</html>
"""

class StreamingServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, frame_provider: Callable[[], Optional[np.ndarray]]):
        super().__init__(server_address, RequestHandlerClass)
        self.frame_provider = frame_provider

class StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Tắt in log request HTTP thông thường để không làm loãng console
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))

        elif self.path == "/snapshot":
            frame = self.server.frame_provider()
            if frame is not None:
                ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ret:
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(jpeg)))
                    self.end_headers()
                    self.wfile.write(jpeg.tobytes())
                    return
            self.send_error(503, "Camera snapshot not available")

        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

            try:
                while True:
                    frame = self.server.frame_provider()
                    if frame is not None:
                        ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        if ret:
                            data = jpeg.tobytes()
                            self.wfile.write(b"--frame\r\n")
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode())
                            self.wfile.write(data)
                            self.wfile.write(b"\r\n")
                    time.sleep(0.05) # ~20 FPS
            except (ConnectionResetError, BrokenPipeError):
                pass
        else:
            self.send_error(404, "Not found")

class LiveStreamManager:
    """
    Quản lý luồng phát trực tiếp qua Web (MJPEG) và Cloudflare Quick Tunnel.
    """
    def __init__(self, port: int = 8080, frame_provider: Optional[Callable[[], Optional[np.ndarray]]] = None, enable_tunnel: bool = True):
        self.port = port
        self.frame_provider = frame_provider
        self.enable_tunnel = enable_tunnel

        self.server: Optional[StreamingServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.tunnel_process: Optional[subprocess.Popen] = None
        self.tunnel_url: Optional[str] = None
        self.is_running = False

    def start(self):
        if self.is_running or not self.frame_provider:
            return

        try:
            self.server = StreamingServer(("0.0.0.0", self.port), StreamHandler, self.frame_provider)
            self.is_running = True
            self.server_thread = threading.Thread(target=self.server.serve_forever, name="WebStreamServer", daemon=True)
            self.server_thread.start()
            logger.info(f"Live Stream Web Server đã chạy tại: http://localhost:{self.port} (LAN: http://{get_local_ip()}:{self.port})")

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
                errors="ignore"
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
                logger.info(f"🌐 Cloudflare Live Stream URL (Công khai xem từ xa): {self.tunnel_url}")
                break

    def get_stream_urls(self) -> dict:
        """Trả về danh sách URL xem trực tiếp."""
        local_ip = get_local_ip()
        return {
            "local_url": f"http://{local_ip}:{self.port}",
            "public_url": self.tunnel_url or f"http://{local_ip}:{self.port}"
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
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        logger.info("Web Stream Manager đã dừng.")
