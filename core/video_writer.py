import os
import time
import logging
from fractions import Fraction
from datetime import datetime
from typing import Optional
import cv2
import numpy as np

logger = logging.getLogger(__name__)

try:
    import av
    HAS_PYAV = "libx264" in av.codecs_available
except Exception:
    av = None
    HAS_PYAV = False

if not HAS_PYAV:
    logger.warning("Không tìm thấy PyAV/libx264 -> video sẽ ghi bằng mp4v (trình duyệt không phát được). Cài: pip install av")


def stamp_frame(frame: np.ndarray, ts: Optional[float] = None, label: str = "CAM-LAPTOP") -> np.ndarray:
    """In thời gian (OSD) lên góc trên khung hình. Sửa trực tiếp trên frame được truyền vào."""
    time_str = datetime.fromtimestamp(ts or time.time()).strftime("%Y-%m-%d %H:%M:%S")
    text = f"{label} | {time_str}"
    # Viền đen giúp chữ dễ đọc trên nền sáng
    cv2.putText(frame, text, (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(frame, text, (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
    return frame


class H264Writer:
    """
    Ghi video H.264 (MP4) với timestamp theo thời gian thực (VFR) để timeline luôn khớp đồng hồ.
    - fragmented=True: ghi fMP4, có thể đọc/phát ngay cả khi file đang được ghi.
    - Fallback sang cv2.VideoWriter (mp4v) nếu không có PyAV.
    """

    def __init__(self, path: str, width: int, height: int, fps: int = 10,
                 crf: int = 28, preset: str = "veryfast", fragmented: bool = False):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.t0: Optional[float] = None
        self.last_ts: Optional[float] = None
        self._last_pts = -1
        self.frame_count = 0
        self._cv_writer = None
        self._container = None
        self._stream = None

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        if HAS_PYAV:
            options = ({"movflags": "frag_keyframe+empty_moov+default_base_moof", "flush_packets": "1"}
                       if fragmented else {"movflags": "+faststart"})
            self._container = av.open(path, mode="w", format="mp4", options=options)
            stream = self._container.add_stream("libx264", rate=fps)
            stream.width = width
            stream.height = height
            stream.pix_fmt = "yuv420p"
            stream.codec_context.time_base = Fraction(1, 1000)
            # Keyframe mỗi ~2 giây để tua nhanh & fragment nhỏ
            stream.options = {"preset": preset, "crf": str(crf), "g": str(max(1, fps * 2)), "tune": "zerolatency"}
            self._stream = stream
        else:
            self._cv_writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
            if not self._cv_writer.isOpened():
                raise IOError(f"Không thể mở VideoWriter: {path}")

    def write(self, frame: np.ndarray, ts: Optional[float] = None):
        ts = ts if ts is not None else time.time()
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height))
        if self.t0 is None:
            self.t0 = ts
        self.last_ts = ts
        self.frame_count += 1

        if self._cv_writer is not None:
            self._cv_writer.write(frame)
            return

        pts = int(round((ts - self.t0) * 1000))
        if pts <= self._last_pts:
            pts = self._last_pts + 1
        self._last_pts = pts
        vf = av.VideoFrame.from_ndarray(frame, format="bgr24")
        vf.pts = pts
        vf.time_base = Fraction(1, 1000)
        for packet in self._stream.encode(vf):
            self._container.mux(packet)

    @property
    def duration(self) -> float:
        if self.t0 is None or self.last_ts is None:
            return 0.0
        return self.last_ts - self.t0 + (1.0 / max(1, self.fps))

    def close(self):
        try:
            if self._cv_writer is not None:
                self._cv_writer.release()
            elif self._container is not None:
                for packet in self._stream.encode():
                    self._container.mux(packet)
                self._container.close()
        except Exception as e:
            logger.error(f"Lỗi khi đóng file video {self.path}: {e}")
        finally:
            self._cv_writer = None
            self._container = None


def remux_faststart(path: str) -> bool:
    """Chuyển file fMP4 đã ghi xong thành MP4 thường (moov ở đầu) để trình duyệt tua mượt hơn."""
    if not HAS_PYAV or not os.path.exists(path):
        return False
    tmp = path + ".tmp.mp4"
    try:
        with av.open(path) as src, av.open(tmp, "w", format="mp4", options={"movflags": "+faststart"}) as dst:
            ist = src.streams.video[0]
            ost = dst.add_stream_from_template(ist)
            for packet in src.demux(ist):
                if packet.dts is None:
                    continue
                packet.stream = ost
                dst.mux(packet)
        for _ in range(5):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                # File đang được trình duyệt đọc -> thử lại sau
                time.sleep(1)
        logger.debug(f"Không thể thay thế {path} (đang được đọc), giữ bản fMP4.")
    except Exception as e:
        logger.warning(f"Remux thất bại cho {path}: {e}")
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
    return False


def export_clip(segments, start: float, end: float, out_path: str) -> bool:
    """
    Ghép các đoạn ghi liên tục thành 1 file MP4 trong khoảng [start, end] (cắt theo keyframe, không encode lại).
    segments: list (abs_path, seg_start) đã sắp xếp theo thời gian.
    """
    if not HAS_PYAV:
        return False
    written = 0
    with av.open(out_path, "w", format="mp4", options={"movflags": "+faststart"}) as dst:
        ost = None
        last_dts = None
        base_t = None
        for path, seg_start in segments:
            if not os.path.exists(path):
                continue
            try:
                src = av.open(path)
            except Exception as e:
                logger.warning(f"Bỏ qua segment lỗi {path}: {e}")
                continue
            with src:
                ist = src.streams.video[0]
                if ost is None:
                    ost = dst.add_stream_from_template(ist)
                tb = ist.time_base
                started = False
                for packet in src.demux(ist):
                    if packet.pts is None or packet.dts is None:
                        continue
                    abs_t = seg_start + float(packet.pts * tb)
                    if abs_t > end:
                        break
                    if not started:
                        # Bắt đầu từ keyframe gần nhất trước/tại thời điểm start
                        if not packet.is_keyframe:
                            continue
                        if abs_t < start - 2.5:
                            continue
                        started = True
                    if base_t is None:
                        base_t = abs_t
                    delta = int(round((abs_t - base_t) / tb)) - packet.pts
                    packet.pts += delta
                    packet.dts += delta
                    packet.time_base = tb
                    if last_dts is not None and packet.dts <= last_dts:
                        shift = last_dts + 1 - packet.dts
                        packet.dts += shift
                        packet.pts += shift
                    last_dts = packet.dts
                    packet.stream = ost
                    dst.mux(packet)
                    written += 1
    return written > 0
