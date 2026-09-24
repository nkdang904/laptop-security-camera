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
from core.web_stream import LiveStreamManager
from core.storage import RecordingIndex
from core.continuous_recorder import ContinuousRecorder
from core.controller import SystemController
from core.events import ActivityTracker

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("camera.log", encoding="utf-8")
        ]
    )
    # httpx log mỗi request kèm URL chứa bot token -> chỉ log cảnh báo trở lên
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

def load_config(config_path="config.yaml"):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Không tìm thấy file cấu hình: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def cleanup_previous_instances(logger=None):
    """Tự động tắt các tiến trình camera cũ bị kẹt để giải phóng webcam."""
    try:
        import psutil
        me = psutil.Process()
        # Không tắt chính mình và các tiến trình cha (shell/cmd đã gọi lệnh này)
        protected = {me.pid} | {p.pid for p in me.parents()}
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] not in protected and proc.info['cmdline']                         and 'python' in (proc.info['name'] or '').lower():
                    if any(os.path.basename(str(arg)) == 'main.py' for arg in proc.info['cmdline']):
                        if logger:
                            logger.info(f"Đang đóng tiến trình camera cũ (PID {proc.info['pid']}) để giải phóng webcam...")
                        proc.terminate()
                        try:
                            proc.wait(timeout=2)
                        except Exception:
                            proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass

def main():
    setup_logging()
    logger = logging.getLogger("MAIN")
    cleanup_previous_instances(logger)

    logger.info("=" * 60)
    logger.info("   KHỞI ĐỘNG HỆ THỐNG CAMERA AN NINH THÔNG MINH LAPTOP")
    logger.info("=" * 60)

    # 1. Nạp file cấu hình (mặc định config.yaml, có thể chỉ định: python main.py --config other.yaml)
    import argparse
    parser = argparse.ArgumentParser(description="Laptop Smart Security Camera")
    parser.add_argument("--config", default="config.yaml", help="Đường dẫn file cấu hình")
    args = parser.parse_args()
    cfg = load_config(args.config)
    cam_cfg = cfg.get("camera", {})
    det_cfg = cfg.get("detection", {})
    rec_cfg = cfg.get("recording", {})
    ret_cfg = cfg.get("retention", {})
    tel_cfg = cfg.get("telegram", {})
    web_cfg = cfg.get("web_stream", {})
    cont_cfg = cfg.get("continuous_recording", {})
    save_dir = rec_cfg.get("save_dir", "recordings")

    controller = SystemController()
    index = RecordingIndex(save_dir)
    index.import_legacy_files()

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
    detector.enabled = det_cfg.get("enabled", True)

    # 4b. Ghi hình liên tục 24/7 (phục vụ tua lại trên timeline web)
    continuous = ContinuousRecorder(
        frame_provider_fn=camera.get_latest_frame,
        index=index,
        width=cam_cfg.get("width", 640),
        height=cam_cfg.get("height", 480),
        fps=cont_cfg.get("fps", 10),
        segment_minutes=cont_cfg.get("segment_minutes", 5),
        crf=cont_cfg.get("quality_crf", 28),
        enabled=cont_cfg.get("enabled", True)
    )

    # 5. Khởi tạo Retention Manager (Dọn dẹp lưu trữ)
    retention = None
    if ret_cfg.get("enabled", True):
        retention = RetentionManager(
            storage_dir=rec_cfg.get("save_dir", "recordings"),
            max_days=ret_cfg.get("max_days", 7),
            max_storage_gb=ret_cfg.get("max_storage_gb", 10.0),
            check_interval_minutes=ret_cfg.get("check_interval_minutes", 30),
            on_cleanup=index.prune_missing
        )

    # 6. Khởi tạo Web App (live + xem lại + sự kiện + cài đặt)
    web_stream = None
    if web_cfg.get("enabled", True):
        web_stream = LiveStreamManager(
            port=web_cfg.get("port", 8080),
            camera=camera,
            detector=detector,
            controller=controller,
            index=index,
            access_key=controller.get_access_key(str(web_cfg.get("access_key", "") or "")),
            password=str(web_cfg.get("password", "") or ""),
            enable_tunnel=web_cfg.get("enable_tunnel", True)
        )

    # 7. Khởi tạo Telegram Notifier
    def take_manual_snapshot():
        snap = camera.get_snapshot()
        if snap is not None:
            return recorder.save_snapshot(snap, prefix="cmd_snap")
        return None

    def record_live_clip(on_complete):
        # Quay clip trực tiếp theo yêu cầu
        buffered = camera.get_buffered_frames()
        recent = buffered[-10:] if len(buffered) >= 10 else buffered
        recorder.record_event_async(
            pre_frames=recent,
            frame_provider_fn=camera.get_latest_frame,
            on_complete_callback=on_complete
        )

    telegram = TelegramNotifier(
        bot_token=tel_cfg.get("bot_token", ""),
        chat_id=tel_cfg.get("chat_id", ""),
        alert_title=tel_cfg.get("alert_title", "🚨 *CẢNH BÁO AN NINH: PHÁT HIỆN NGƯỜI!*"),
        enable_commands=tel_cfg.get("enable_commands", True),
        snapshot_provider_fn=take_manual_snapshot,
        live_clip_provider_fn=record_live_clip,
        stream_urls_provider_fn=lambda: web_stream.get_stream_urls() if web_stream else {}
    )

    # Gắn các module vào bộ điều khiển web & áp thiết lập đã lưu từ web
    controller.camera = camera
    controller.detector = detector
    controller.recorder = recorder
    controller.continuous = continuous
    controller.retention = retention
    controller.telegram = telegram
    controller.index = index
    controller.web = web_stream
    controller.flags["send_snapshot"] = tel_cfg.get("send_snapshot", True)
    controller.flags["send_video"] = tel_cfg.get("send_video", True)
    controller.apply_saved_settings()

    # Gộp các lần phát hiện liên tiếp thành sự kiện hiển thị trên timeline
    person_tracker = ActivityTracker(index, "person", gap_seconds=8.0)
    motion_tracker = ActivityTracker(index, "motion", gap_seconds=5.0, min_duration=1.0, insert_on_open=False)

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
    continuous.start()
    if retention:
        retention.start()
    if web_stream:
        web_stream.start()
    telegram.start()

    # Gửi thông báo khởi động kèm link Live Stream tới Telegram
    def notify_startup_async():
        time.sleep(4)
        if not telegram.is_configured:
            return
        urls = web_stream.get_stream_urls() if web_stream else {}
        pub_url = urls.get("public_url", "")
        loc_url = urls.get("local_url", "")

        msg = "🟢 *CAMERA LAPTOP ĐÃ KHỞI ĐỘNG THÀNH CÔNG!*\n\n"
        msg += "Hệ thống đang hoạt động và giám sát an ninh.\n\n"
        if pub_url and "trycloudflare" in pub_url:
            msg += f"🌐 *Link xem trực tiếp từ xa (4G):*\n{pub_url}\n\n"
        if loc_url:
            msg += f"🏠 *Link xem trong nhà (Wi-Fi):*\n{loc_url}\n\n"
        msg += "📼 Web app hỗ trợ xem trực tiếp, tua lại timeline 24/7, xem sự kiện & chỉnh cài đặt.\n"
        msg += "💡 Gửi `/live` hoặc `/snapshot` bất cứ lúc nào để kiểm tra camera."

        target_url = pub_url if (pub_url and "trycloudflare" in pub_url) else loc_url
        reply_markup = None
        if target_url:
            reply_markup = {
                "inline_keyboard": [
                    [{"text": "📹 Mở Camera (Live + Xem lại)", "url": target_url}]
                ]
            }
        telegram.send_message(msg, reply_markup=reply_markup)

    import threading
    threading.Thread(target=notify_startup_async, name="StartupNotifier", daemon=True).start()

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

            # Cập nhật dải sự kiện trên timeline
            now = time.time()
            motion_tracker.update(bool(result.get("has_motion")) and controller.flags["log_motion_events"], now)
            if result.get("has_target") and result.get("detections"):
                best = max(result["detections"], key=lambda d: d["confidence"])
                prev_event = person_tracker.event_id
                new_event = person_tracker.update(True, now, label=best["label"], confidence=best["confidence"])
                # Sự kiện mới nhưng đang trong cooldown (không cảnh báo) -> vẫn lưu ảnh thu nhỏ cho timeline
                if new_event and new_event != prev_event and not result.get("can_alert"):
                    thumb = recorder.save_snapshot(result.get("annotated_frame", frame), prefix="det")
                    index.update_event(new_event, snapshot=thumb)
            else:
                person_tracker.update(False, now)

            # Xử lý khi phát hiện mục tiêu và đủ điều kiện cảnh báo
            if result.get("can_alert"):
                detections = result.get("detections", [])
                det_info = ", ".join([f"{d['label']} ({d['confidence']*100:.0f}%)" for d in detections])
                logger.info(f"🚨 PHÁT HIỆN MỤC TIÊU: {det_info}!")

                # 1. Lưu snapshot lập tức
                annotated = result.get("annotated_frame", frame)
                snapshot_file = recorder.save_snapshot(annotated, prefix="alert")
                event_id = person_tracker.event_id
                if event_id:
                    ev = index.get_event(event_id)
                    if ev and not ev.get("snapshot"):
                        index.update_event(event_id, snapshot=snapshot_file)

                # 2. Gửi ảnh snapshot cảnh báo qua Telegram ngay lập tức
                if controller.flags["send_snapshot"]:
                    telegram.send_alert_async(
                        snapshot_path=snapshot_file,
                        details=f"Phát hiện: *{det_info}*"
                    )

                # 3. Kích hoạt quay video sự kiện (bao gồm 2-3s trước đó từ ring buffer)
                if controller.flags["send_video"]:
                    pre_frames = camera.get_buffered_frames()

                    def on_video_ready(video_path, event_id=event_id, det_info=det_info):
                        if event_id:
                            ev = index.get_event(event_id)
                            if ev and not ev.get("clip"):
                                index.update_event(event_id, clip=video_path)
                        logger.info(f"Đang gửi clip video sự kiện qua Telegram: {video_path}")
                        reply_markup = None
                        if web_stream:
                            urls = web_stream.get_stream_urls()
                            pub_url = urls.get("public_url", "")
                            loc_url = urls.get("local_url", "")
                            view_url = pub_url if (pub_url and "trycloudflare" in pub_url) else loc_url
                            if view_url:
                                reply_markup = {
                                    "inline_keyboard": [
                                        [{"text": "🔴 Xem Live Trực Tiếp", "url": view_url}]
                                    ]
                                }

                        telegram.send_video_async(
                            video_path,
                            caption=f"📹 *Video ghi lại sự kiện phát hiện:* `{det_info}`",
                            reply_markup=reply_markup
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
        person_tracker.close()
        motion_tracker.close()
        continuous.stop()
        camera.stop()
        if retention:
            retention.stop()
        if web_stream:
            web_stream.stop()
        telegram.stop()
        logger.info("Hệ thống camera đã dừng hoàn toàn.")

if __name__ == "__main__":
    main()
