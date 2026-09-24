import cv2
import time
import logging
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

logger = logging.getLogger(__name__)

class SmartDetector:
    """
    Bộ phát hiện 2 lớp:
    - Lớp 1 (Motion pre-filter): Kiểm tra chuyển động siêu nhanh bằng so sánh frame pixel để tiết kiệm CPU/pin.
    - Lớp 2 (YOLOv8 AI): Chỉ khi có chuyển động, kích hoạt YOLOv8n để lọc chính xác đối tượng (mặc định: 'person').
    """

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        target_classes: Optional[List[str]] = None,
        confidence_threshold: float = 0.50,
        use_motion_prefilter: bool = True,
        motion_threshold: int = 25,
        min_motion_area: int = 800,
        cooldown_seconds: int = 30
    ):
        self.model_name = model_name
        self.target_classes = target_classes or ["person"]
        self.confidence_threshold = confidence_threshold
        self.use_motion_prefilter = use_motion_prefilter
        self.motion_threshold = motion_threshold
        self.min_motion_area = min_motion_area
        self.cooldown_seconds = cooldown_seconds

        self.enabled = True
        self.last_alert_time = 0.0
        self.prev_gray_frame = None
        self.model = None

        # Kết quả gần nhất (dùng để vẽ khung AI lên live stream trên web)
        self.last_detections: List[Dict] = []
        self.last_detection_time = 0.0

        self._init_yolo()

    def _init_yolo(self):
        """Khởi tạo model Ultralytics YOLOv8."""
        try:
            from ultralytics import YOLO
            logger.info(f"Đang tải mô hình YOLO AI: {self.model_name}...")
            self.model = YOLO(self.model_name)
            logger.info("Tải mô hình YOLO thành công.")
        except Exception as e:
            logger.error(f"Lỗi khi tải mô hình YOLO: {e}")
            self.model = None

    def check_motion(self, frame: np.ndarray) -> bool:
        """Kiểm tra xem khung hình có chuyển động pixel hay không (Lớp 1)."""
        if not self.use_motion_prefilter:
            return True

        # Chuyển về grayscale và làm mờ giảm nhiễu hạt
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self.prev_gray_frame is None:
            self.prev_gray_frame = gray
            return False

        # Tính độ khác biệt tuyệt đối giữa 2 khung hình liên tiếp
        frame_diff = cv2.absdiff(self.prev_gray_frame, gray)
        self.prev_gray_frame = gray

        thresh = cv2.threshold(frame_diff, self.motion_threshold, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)

        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            if cv2.contourArea(contour) >= self.min_motion_area:
                return True

        return False

    def detect(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Xử lý phát hiện trên 1 frame:
        Trả về dict gồm:
        {
            'has_motion': bool,
            'has_target': bool,
            'detections': List[Dict], # [{label, conf, box: [x1, y1, x2, y2]}]
            'can_alert': bool,
            'annotated_frame': np.ndarray
        }
        """
        now = time.time()
        if not self.enabled:
            self.prev_gray_frame = None
            return {"has_motion": False, "has_target": False, "detections": [],
                    "can_alert": False, "annotated_frame": frame}
        has_motion = self.check_motion(frame)

        result = {
            "has_motion": has_motion,
            "has_target": False,
            "detections": [],
            "can_alert": False,
            "annotated_frame": frame.copy()
        }

        # Nếu không có chuyển động và đang bật prefilter -> bỏ qua YOLO để tiết kiệm tài nguyên
        if not has_motion and self.use_motion_prefilter:
            return result

        if self.model is None:
            # Nếu chưa có model YOLO thì fallback coi chuyển động là sự kiện
            result["has_target"] = has_motion
            result["can_alert"] = has_motion and (now - self.last_alert_time >= self.cooldown_seconds)
            if result["can_alert"]:
                self.last_alert_time = now
            return result

        # Chạy YOLO inference
        try:
            predictions = self.model(frame, verbose=False, conf=self.confidence_threshold)[0]
            matched_detections = []

            for box in predictions.boxes:
                cls_id = int(box.cls[0].item())
                label = predictions.names[cls_id]
                conf = float(box.conf[0].item())

                if label in self.target_classes and conf >= self.confidence_threshold:
                    xyxy = [int(v) for v in box.xyxy[0].tolist()]
                    matched_detections.append({
                        "label": label,
                        "confidence": conf,
                        "box": xyxy
                    })

            if len(matched_detections) > 0:
                result["has_target"] = True
                result["detections"] = matched_detections
                result["annotated_frame"] = self._draw_detections(frame, matched_detections)
                self.last_detections = matched_detections
                self.last_detection_time = now

                # Kiểm tra cooldown trước khi kích hoạt cảnh báo
                if now - self.last_alert_time >= self.cooldown_seconds:
                    result["can_alert"] = True
                    self.last_alert_time = now

        except Exception as e:
            logger.error(f"Lỗi trong quá trình inference YOLO: {e}")

        return result

    def draw_recent(self, frame: np.ndarray, max_age: float = 1.0) -> np.ndarray:
        """Vẽ các khung nhận diện gần nhất (nếu còn mới) lên frame live."""
        if self.last_detections and time.time() - self.last_detection_time <= max_age:
            return self._draw_detections(frame, self.last_detections, copy=False)
        return frame

    def _draw_detections(self, frame: np.ndarray, detections: List[Dict], copy: bool = True) -> np.ndarray:
        """Vẽ bounding box và nhãn lên ảnh."""
        annotated = frame.copy() if copy else frame
        for det in detections:
            x1, y1, x2, y2 = det["box"]
            label = f"{det['label']} {det['confidence']:.2f}"
            # Vẽ hình chữ nhật cảnh báo (màu đỏ rực rỡ)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
            # Vẽ nhãn text
            cv2.putText(annotated, label, (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        return annotated

