import os
import sys
import time
import signal
import logging
import yaml
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from core.camera_stream import CameraStream
from core.detector import SmartDetector
from core.recorder import VideoRecorder
from core.retention import RetentionManager
from core.telegram_notifier import TelegramNotifier

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("camera.log", encoding="utf-8")
        ]
    )

def load_config(config_path="config.yaml"):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Không tìm thấy file cấu hình: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main():
    setup_logging()
    logger = logging.getLogger("MAIN")

    logger.info("=" * 60)
    logger.info("   KHỞI ĐỘNG HỆ THỐNG CAMERA AN NINH THÔNG MINH LAPTOP")
    logger.info("=" * 60)

    # 1. Nạp file cấu hình
    cfg = load_config()
    cam_cfg = cfg.get("camera", {})
    det_cfg = cfg.get("detection", {})
    rec_cfg = cfg.get("recording", {})
    ret_cfg = cfg.get("retention", {})
    tel_cfg = cfg.get("telegram", {})

    # 2. Khởi tạo Camera Stream
    camera = CameraStream(
        source=cam_cfg.get("source", 0),
        width=cam_cfg.get("width", 640),
        height=cam_cfg.get("height", 480),
        fps=cam_cfg.get("fps", 20),
        pre_buffer_seconds=rec_cfg.get("pre_buffer_seconds", 3)
    )

    # 3. Khởi tạo Video Recorder
    recorder = VideoRecorder(
        save_dir=rec_cfg.get("save_dir", "recordings"),
        record_seconds=rec_cfg.get("record_on_detect_seconds", 8),
        fps=cam_cfg.get("fps", 20),
        frame_size=(cam_cfg.get("width", 640), cam_cfg.get("height", 480)),
        codec=rec_cfg.get("codec", "mp4v")
    )

    # 4. Khởi tạo Bộ phát hiện AI (Detector)
    detector = SmartDetector(
        model_name=det_cfg.get("model", "yolov8n.pt"),
        target_classes=det_cfg.get("target_classes", ["person"]),
        confidence_threshold=det_cfg.get("confidence_threshold", 0.50),
        use_motion_prefilter=det_cfg.get("motion_prefilter", True),
        motion_threshold=det_cfg.get("motion_threshold", 25),
        min_motion_area=det_cfg.get("min_motion_area", 800),
        cooldown_seconds=det_cfg.get("cooldown_seconds", 30)
    )

    # 5. Khởi tạo Retention Manager (Dọn dẹp lưu trữ)
    retention = None
    if ret_cfg.get("enabled", True):
        retention = RetentionManager(
            storage_dir=rec_cfg.get("save_dir", "recordings"),
            max_days=ret_cfg.get("max_days", 7),
            max_storage_gb=ret_cfg.get("max_storage_gb", 10.0),
            check_interval_minutes=ret_cfg.get("check_interval_minutes", 30)
        )

    # 6. Khởi tạo Telegram Notifier
    def take_manual_snapshot():
        snap = camera.get_snapshot()
        if snap is not None:
            return recorder.save_snapshot(snap, prefix="cmd_snap")
        return None

    telegram = TelegramNotifier(
        bot_token=tel_cfg.get("bot_token", ""),
        chat_id=tel_cfg.get("chat_id", ""),
        alert_title=tel_cfg.get("alert_title", "🚨 *CẢNH BÁO AN NINH: PHÁT HIỆN NGƯỜI!*"),
        enable_commands=tel_cfg.get("enable_commands", True),
        snapshot_provider_fn=take_manual_snapshot
    )

    # Biến cờ dừng an toàn
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        logger.info("\nĐang dừng hệ thống an toàn...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Khởi động các tiến trình con
    camera.start()
    if retention:
        retention.start()
    telegram.start()

    logger.info("Hệ thống đã sẵn sàng và đang giám sát không gian...")
    if not telegram.is_configured:
        logger.warning("👉 Telegram chưa được thiết lập. Hãy chạy 'python setup_telegram.py' để kết nối bot.")

    fps_target = cam_cfg.get("fps", 20)
    loop_delay = 1.0 / max(1, fps_target)

    # Vòng lặp giám sát chính
    try:
        while running:
            loop_start = time.time()

            ok, frame, _ = camera.get_latest_frame()
            if not ok or frame is None:
                time.sleep(0.05)
                continue

            # Chạy phát hiện qua AI
            result = detector.detect(frame)

            # Xử lý khi phát hiện mục tiêu và đủ điều kiện cảnh báo
            if result.get("can_alert"):
                detections = result.get("detections", [])
                det_info = ", ".join([f"{d['label']} ({d['confidence']*100:.0f}%)" for d in detections])
                logger.info(f"🚨 PHÁT HIỆN MỤC TIÊU: {det_info}!")

                # 1. Lưu snapshot lập tức
                annotated = result.get("annotated_frame", frame)
                snapshot_file = recorder.save_snapshot(annotated, prefix="alert")

                # 2. Gửi ảnh snapshot cảnh báo qua Telegram ngay lập tức
                if tel_cfg.get("send_snapshot", True):
                    telegram.send_alert_async(
                        snapshot_path=snapshot_file,
                        details=f"Phát hiện: *{det_info}*"
                    )

                # 3. Kích hoạt quay video sự kiện (bao gồm 2-3s trước đó từ ring buffer)
                if tel_cfg.get("send_video", True):
                    pre_frames = camera.get_buffered_frames()

                    def on_video_ready(video_path):
                        logger.info(f"Đang gửi clip video sự kiện qua Telegram: {video_path}")
                        telegram.send_video_async(
                            video_path,
                            caption=f"📹 *Video ghi lại sự kiện phát hiện:* `{det_info}`"
                        )

                    recorder.record_event_async(
                        pre_frames=pre_frames,
                        frame_provider_fn=camera.get_latest_frame,
                        on_complete_callback=on_video_ready
                    )

            # Điều tiết chu kỳ quét
            elapsed = time.time() - loop_start
            sleep_time = loop_delay - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Đang giải phóng tài nguyên...")
        camera.stop()
        if retention:
            retention.stop()
        telegram.stop()
        logger.info("Hệ thống camera đã dừng hoàn toàn.")

if __name__ == "__main__":
    main()
