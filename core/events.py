import time
import logging
from typing import Optional

from core.storage import RecordingIndex

logger = logging.getLogger(__name__)


class ActivityTracker:
    """
    Gộp các lần phát hiện liên tiếp thành 1 "sự kiện" có thời điểm bắt đầu/kết thúc
    để hiển thị thành dải màu trên timeline (giống app camera).
    - gap_seconds: khoảng lặng tối đa giữa 2 lần phát hiện vẫn tính là cùng 1 sự kiện
    - min_duration: sự kiện ngắn hơn ngưỡng này sẽ bị bỏ (lọc nhiễu chuyển động)
    - insert_on_open: ghi vào DB ngay khi bắt đầu (cần event_id sớm để gắn snapshot/clip)
    """

    def __init__(self, index: RecordingIndex, type_: str, gap_seconds: float = 8.0,
                 min_duration: float = 0.0, insert_on_open: bool = True):
        self.index = index
        self.type = type_
        self.gap_seconds = gap_seconds
        self.min_duration = min_duration
        self.insert_on_open = insert_on_open

        self.event_id: Optional[int] = None
        self.start = 0.0
        self.last_active = 0.0
        self.label = ""
        self.confidence = 0.0
        self._last_flush = 0.0
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def update(self, active: bool, now: Optional[float] = None, label: str = "", confidence: float = 0.0) -> Optional[int]:
        now = now or time.time()
        if active:
            if self._open and now - self.last_active <= self.gap_seconds:
                self.last_active = now
                self.confidence = max(self.confidence, confidence)
                if label and label not in self.label.split(","):
                    self.label = ",".join(filter(None, [self.label, label]))
                if self.event_id and now - self._last_flush >= 2.0:
                    self._flush()
            else:
                self.close()
                self._open = True
                self.start = self.last_active = now
                self.label = label
                self.confidence = confidence
                if self.insert_on_open:
                    self.event_id = self.index.add_event(self.type, now, now, label=label, confidence=confidence)
                    self._last_flush = now
        elif self._open and now - self.last_active > self.gap_seconds:
            self.close()
        return self.event_id

    def _flush(self):
        self._last_flush = time.time()
        self.index.update_event(self.event_id, end=self.last_active, label=self.label, confidence=self.confidence)

    def close(self):
        if not self._open:
            return
        self._open = False
        duration = self.last_active - self.start
        if self.event_id:
            self._flush()
        elif duration >= self.min_duration:
            self.index.add_event(self.type, self.start, self.last_active, label=self.label, confidence=self.confidence)
        self.event_id = None
