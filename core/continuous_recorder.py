import os
import time
import logging
import threading
from datetime import datetime
from typing import Optional, Callable, Tuple
import numpy as np

from core.storage import RecordingIndex
from core.video_writer import H264Writer, stamp_frame, remux_faststart

logger = logging.getLogger(__name__)


class ContinuousRecorder:
    """
    Ghi hình liên tục 24/7 thành các đoạn (segment) H.264 ngắn, lưu theo ngày:
        recordings/continuous/YYYY-MM-DD/HHMMSS.mp4
    Mỗi segment được ghi dạng fMP4 để có thể xem lại ngay cả khi đang ghi,
    đóng file khi đủ thời lượng / sang ngày mới / mất tín hiệu camera.
    """

    def __init__(
        self,
        frame_provider_fn: Callable[[], Tuple[bool, Optional[np.ndarray], float]],
        index: RecordingIndex,
        width: int = 640,
        height: int = 480,
        fps: int = 10,
        segment_minutes: float = 5,
        crf: int = 28,
        enabled: bool = True
    ):
        self.frame_provider_fn = frame_provider_fn
        self.index = index
        self.width = width
        self.height = height
        self.fps = max(1, fps)
        self.segment_seconds = max(30, segment_minutes * 60)
        self.crf = crf
        self.enabled = enabled
        self.base_dir = os.path.join(index.base_dir, "continuous")

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._writer: Optional[H264Writer] = None
        self._seg_id: Optional[int] = None
        self._seg_start = 0.0
        self._seg_day = ""
        self._last_index_update = 0.0

    @property
    def is_recording(self) -> bool:
        return self._writer is not None

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._loop, name="ContinuousRecorder", daemon=True)
        self._thread.start()
        logger.info(f"Ghi hình liên tục 24/7: {self.fps} FPS, mỗi đoạn {self.segment_seconds / 60:.0f} phút "
                    f"({'BẬT' if self.enabled else 'TẮT'}).")

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)

    def _loop(self):
        interval = 1.0 / self.fps
        last_frame_ts = 0.0
        while self.is_running:
            tick = time.time()
            try:
                if not self.enabled:
                    self._close_segment()
                    time.sleep(0.5)
                    continue

                ok, frame, ts = self.frame_provider_fn()
                if ok and frame is not None and ts > last_frame_ts:
                    last_frame_ts = ts
                    self._write(frame, ts)
                elif self._writer is not None and time.time() - last_frame_ts > 3.0:
                    # Mất tín hiệu camera -> đóng đoạn để timeline hiện khoảng trống
                    logger.warning("Không có frame mới > 3s, tạm đóng đoạn ghi liên tục.")
                    self._close_segment()
            except Exception as e:
                logger.error(f"Lỗi ghi hình liên tục: {e}")
                self._close_segment()
                time.sleep(1.0)

            sleep = interval - (time.time() - tick)
            if sleep > 0:
                time.sleep(sleep)
        self._close_segment(sync=True)

    def _write(self, frame: np.ndarray, ts: float):
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        if self._writer is not None and (ts - self._seg_start >= self.segment_seconds or day != self._seg_day):
            self._close_segment()
        if self._writer is None:
            self._open_segment(ts, day)

        self._writer.write(stamp_frame(frame, ts), ts)

        if ts - self._last_index_update >= 2.0:
            self._last_index_update = ts
            self.index.update_segment(self._seg_id, self._seg_start + self._writer.duration,
                                      self._file_size(), complete=False)

    def _open_segment(self, ts: float, day: str):
        path = os.path.join(self.base_dir, day, datetime.fromtimestamp(ts).strftime("%H%M%S") + ".mp4")
        self._writer = H264Writer(path, self.width, self.height, fps=self.fps, crf=self.crf, fragmented=True)
        self._seg_start = ts
        self._seg_day = day
        self._seg_id = self.index.add_segment(path, ts)
        self._last_index_update = ts

    def _file_size(self) -> int:
        try:
            return os.path.getsize(self._writer.path)
        except OSError:
            return 0

    def _close_segment(self, sync: bool = False):
        writer, seg_id = self._writer, self._seg_id
        if writer is None:
            return
        self._writer = None
        self._seg_id = None
        writer.close()
        end = self._seg_start + writer.duration
        if writer.frame_count == 0:
            try:
                os.remove(writer.path)
            except OSError:
                pass
            self.index.delete_segment_by_path(writer.path)
            return
        # Remux sang MP4 thường ở background để trình duyệt tua mượt
        def finalize():
            remux_faststart(writer.path)
            size = os.path.getsize(writer.path) if os.path.exists(writer.path) else 0
            self.index.update_segment(seg_id, end, size, complete=True)
        if sync:
            finalize()
        else:
            threading.Thread(target=finalize, name="SegmentFinalize", daemon=True).start()

    def stop(self):
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._close_segment(sync=True)
        logger.info("Ghi hình liên tục đã dừng.")
