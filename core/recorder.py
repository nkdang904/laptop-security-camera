import os
import cv2
import time
import logging
import threading
from datetime import datetime
from typing import List, Tuple, Optional, Callable
import numpy as np

logger = logging.getLogger(__name__)

class VideoRecorder:
    """
    Quản lý việc ghi lại video sự kiện và lưu ảnh snapshot vào ổ đĩa.
    Chạy đa luồng (background worker) để việc ghi file MP4 không làm lag luồng camera chính.
    """

    def __init__(
        self,
        save_dir: str = "recordings",
        record_seconds: int = 8,
        fps: int = 20,
        frame_size: Tuple[int, int] = (640, 480),
        codec: str = "mp4v"
    ):
        self.save_dir = os.path.abspath(save_dir)
        self.record_seconds = record_seconds
        self.fps = fps
        self.frame_size = frame_size
        self.codec = codec

        os.makedirs(self.save_dir, exist_ok=True)
        self.is_recording = False
        self._record_thread: Optional[threading.Thread] = None

    def save_snapshot(self, frame: np.ndarray, prefix: str = "alert") -> str:
        """Lưu một ảnh snapshot ra file JPEG với timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.jpg"
        filepath = os.path.join(self.save_dir, filename)

        # Thêm timestamp vào góc ảnh
        stamped = self._stamp_frame(frame.copy())
        cv2.imwrite(filepath, stamped)
        logger.info(f"Đã lưu snapshot: {filepath}")
        return filepath

    def record_event_async(
        self,
        pre_frames: List[Tuple[float, np.ndarray]],
        frame_provider_fn: Callable[[], Tuple[bool, Optional[np.ndarray], float]],
        on_complete_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        Khởi chạy luồng ghi video sự kiện:
        - pre_frames: danh sách frame trong ring buffer trước khi kích hoạt
        - frame_provider_fn: hàm lấy frame realtime hiện tại
        - on_complete_callback: hàm gọi khi ghi xong (ví dụ gửi file qua Telegram)
        """
        if self.is_recording:
            logger.info("Đang có một tiến trình ghi video khác đang chạy, bỏ qua kích hoạt mới.")
            return False

        self.is_recording = True
        self._record_thread = threading.Thread(
            target=self._record_worker,
            args=(pre_frames, frame_provider_fn, on_complete_callback),
            name="VideoRecordWorker",
            daemon=True
        )
        self._record_thread.start()
        return True

    def _record_worker(
        self,
        pre_frames: List[Tuple[float, np.ndarray]],
        frame_provider_fn: Callable[[], Tuple[bool, Optional[np.ndarray], float]],
        on_complete_callback: Optional[Callable[[str], None]]
    ):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"event_{timestamp}.mp4"
        filepath = os.path.join(self.save_dir, filename)

        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        writer = cv2.VideoWriter(filepath, fourcc, self.fps, self.frame_size)

        if not writer.isOpened():
            logger.error(f"Không thể khởi tạo VideoWriter cho file: {filepath}")
            self.is_recording = False
            return

        logger.info(f"Bắt đầu ghi video sự kiện: {filepath}")

        # 1. Ghi các frame trong ring buffer trước sự kiện
        for _, frame in pre_frames:
            resized = cv2.resize(frame, self.frame_size)
            writer.write(self._stamp_frame(resized))

        # 2. Ghi các frame tiếp theo trong thời gian record_seconds
        start_time = time.time()
        delay = 1.0 / self.fps

        while time.time() - start_time < self.record_seconds:
            loop_start = time.time()
            ok, frame, _ = frame_provider_fn()
            if ok and frame is not None:
                resized = cv2.resize(frame, self.frame_size)
                writer.write(self._stamp_frame(resized))

            sleep_time = delay - (time.time() - loop_start)
            if sleep_time > 0:
                time.sleep(sleep_time)

        writer.release()
        self.is_recording = False
        logger.info(f"Đã hoàn thành ghi video sự kiện: {filepath} ({os.path.getsize(filepath) / 1024:.1f} KB)")

        if on_complete_callback:
            try:
                on_complete_callback(filepath)
            except Exception as e:
                logger.error(f"Lỗi trong callback sau khi ghi video: {e}")

    def _stamp_frame(self, frame: np.ndarray) -> np.ndarray:
        """In thời gian thực (Watermark/OSD) lên góc trên của khung hình."""
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(
            frame,
            f"CAM-LAPTOP | {time_str}",
            (15, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
            cv2.LINE_AA
        )
        return frame

