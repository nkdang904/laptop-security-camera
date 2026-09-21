import cv2
import time
import logging
import threading
from collections import deque
from typing import Optional, Tuple, List
import numpy as np

logger = logging.getLogger(__name__)

class CameraStream:
    """
    Quản lý luồng lấy hình ảnh từ Webcam laptop trong một background thread độc lập.
    Hỗ trợ Ring Buffer để lưu trữ các khung hình trước khi có sự kiện (Pre-event recording).
    """

    def __init__(self, source=0, width: int = 640, height: int = 480, fps: int = 20, pre_buffer_seconds: int = 3):
        self.source = source
        self.width = width
        self.height = height
        self.fps = fps
        self.pre_buffer_seconds = pre_buffer_seconds

        # Ring buffer lưu trữ các frame gần nhất
        self.buffer_size = max(10, int(fps * pre_buffer_seconds))
        self.frame_buffer = deque(maxlen=self.buffer_size)

        self.cap: Optional[cv2.VideoCapture] = None
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_timestamp: float = 0.0

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.is_connected = False

    def start(self):
        """Khởi động luồng đọc camera."""
        if self.is_running:
            return

        logger.info(f"Đang kết nối camera nguồn: {self.source}...")
        self._init_capture()

        self.is_running = True
        self._thread = threading.Thread(target=self._capture_loop, name="CameraCaptureThread", daemon=True)
        self._thread.start()
        logger.info("Camera Stream đã khởi động thành công.")

    def _init_capture(self):
        """Khởi tạo VideoCapture với tối ưu DirectShow trên Windows."""
        if isinstance(self.source, int):
            # Trên Windows, CAP_DSHOW giúp mở webcam tích hợp nhanh hơn và giảm lag
            self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(self.source)

        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            self.is_connected = True
        else:
            self.is_connected = False
            logger.error(f"Không thể mở camera nguồn: {self.source}")

    def _capture_loop(self):
        """Vòng lặp đọc frame liên tục."""
        delay = 1.0 / self.fps if self.fps > 0 else 0.033

        while self.is_running:
            start_time = time.time()

            if not self.cap or not self.cap.isOpened():
                self.is_connected = False
                logger.warning("Mất kết nối camera. Đang thử kết nối lại sau 2 giây...")
                time.sleep(2.0)
                self._init_capture()
                continue

            ret, frame = self.cap.read()
            now = time.time()

            if ret and frame is not None:
                self.is_connected = True
                with self._lock:
                    self.latest_frame = frame
                    self.latest_timestamp = now
                    # Lưu bản copy nông/hoặc frame vào ring buffer
                    self.frame_buffer.append((now, frame))
            else:
                self.is_connected = False
                logger.warning("Đọc frame thất bại. Đang thử lại...")
                time.sleep(0.5)
                continue

            # Điều tiết tốc độ đọc frame tương ứng với FPS cấu hình
            elapsed = time.time() - start_time
            sleep_time = delay - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_latest_frame(self) -> Tuple[bool, Optional[np.ndarray], float]:
        """Lấy frame mới nhất (thread-safe)."""
        with self._lock:
            if self.latest_frame is not None:
                return True, self.latest_frame.copy(), self.latest_timestamp
            return False, None, 0.0

    def get_snapshot(self) -> Optional[np.ndarray]:
        """Chụp 1 snapshot hiện tại."""
        ok, frame, _ = self.get_latest_frame()
        return frame if ok else None

    def get_buffered_frames(self) -> List[Tuple[float, np.ndarray]]:
        """Lấy toàn bộ các frame trong ring buffer (trước khi có sự kiện)."""
        with self._lock:
            return list(self.frame_buffer)

    def stop(self):
        """Dừng luồng đọc camera và giải phóng tài nguyên."""
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None

        self.is_connected = False
        logger.info("Camera Stream đã dừng.")

