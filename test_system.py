import os
import sys
import time
import shutil
import cv2
import numpy as np
import yaml

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from core.camera_stream import CameraStream
from core.detector import SmartDetector
from core.recorder import VideoRecorder
from core.retention import RetentionManager
from core.telegram_notifier import TelegramNotifier

def test_camera_and_recorder():
    print("\n--- TEST 1: Camera Stream & Ring Buffer & Video Recorder ---")
    camera = CameraStream(source=0, width=640, height=480, fps=15, pre_buffer_seconds=2)
    camera.start()
    time.sleep(1.0)

    ok, frame, ts = camera.get_latest_frame()
    assert ok and frame is not None, "Không đọc được frame từ camera!"
    print(f"✅ Camera OK: Kích thước {frame.shape}, timestamp {ts}")

    # Chờ 2s để ring buffer tích luỹ frame
    time.sleep(2.0)
    buffered = camera.get_buffered_frames()
    print(f"✅ Ring Buffer OK: Đã lưu {len(buffered)} frames")
    assert len(buffered) > 5, "Ring buffer chưa lưu đủ frame!"

    # Test recorder
    test_dir = "test_recordings"
    recorder = VideoRecorder(save_dir=test_dir, record_seconds=2, fps=15)
    snap_path = recorder.save_snapshot(frame, prefix="test_snap")
    assert os.path.exists(snap_path), "Snapshot không được lưu!"
    print(f"✅ Snapshot OK: {snap_path}")

    # Test record event
    video_completed = []
    recorder.record_event_async(
        pre_frames=buffered[:10],
        frame_provider_fn=camera.get_latest_frame,
        on_complete_callback=lambda p: video_completed.append(p)
    )

    # Chờ ghi xong 2s
    time.sleep(3.0)
    assert len(video_completed) > 0 and os.path.exists(video_completed[0]), "Video event không được tạo!"
    print(f"✅ Video Event OK: {video_completed[0]} ({os.path.getsize(video_completed[0])} bytes)")

    camera.stop()
    return test_dir

def test_detector():
    print("\n--- TEST 2: Smart Detector (Motion & YOLOv8n) ---")
    detector = SmartDetector(model_name="yolov8n.pt", cooldown_seconds=2)

    # Tạo 2 frame giả lập chuyển động
    frame1 = np.zeros((480, 640, 3), dtype=np.uint8)
    frame2 = np.zeros((480, 640, 3), dtype=np.uint8)
    # Vẽ một khối trắng lớn ở giữa frame2 để kích hoạt motion
    cv2.rectangle(frame2, (100, 100), (300, 300), (255, 255, 255), -1)

    res1 = detector.detect(frame1)
    res2 = detector.detect(frame2)

    print(f"✅ Frame 1 (tĩnh): has_motion={res1['has_motion']}, has_target={res1['has_target']}")
    print(f"✅ Frame 2 (chuyển động): has_motion={res2['has_motion']}, has_target={res2['has_target']}")
    assert res2["has_motion"] == True, "Bộ lọc chuyển động không phát hiện thay đổi!"

def test_retention():
    print("\n--- TEST 3: Retention Manager (Tự động dọn dẹp) ---")
    test_ret_dir = "test_retention_dir"
    os.makedirs(test_ret_dir, exist_ok=True)

    # Tạo 1 file giả lập cũ 10 ngày trước
    old_file = os.path.join(test_ret_dir, "event_old.mp4")
    with open(old_file, "wb") as f:
        f.write(b"0" * 1024)
    # Sửa mtime lùi về 10 ngày trước (10 * 86400 giây)
    ten_days_ago = time.time() - (10 * 86400)
    os.utime(old_file, (ten_days_ago, ten_days_ago))

    # Tạo 1 file mới
    new_file = os.path.join(test_ret_dir, "event_new.mp4")
    with open(new_file, "wb") as f:
        f.write(b"1" * 1024)

    retention = RetentionManager(storage_dir=test_ret_dir, max_days=7, max_storage_gb=1.0)
    deleted, freed = retention.run_cleanup()

    assert not os.path.exists(old_file), "File cũ hơn 7 ngày chưa bị xoá!"
    assert os.path.exists(new_file), "File mới không được giữ lại!"
    print(f"✅ Retention Policy OK: Đã xoá file quá hạn, giải phóng {freed:.4f} MB")

    # Dọn thư mục test
    shutil.rmtree(test_ret_dir, ignore_errors=True)

if __name__ == "__main__":
    print("=== BẮT ĐẦU KIỂM THỬ TỰ ĐỘNG HỆ THỐNG CAMERA ===")
    test_dir = test_camera_and_recorder()
    test_detector()
    test_retention()

    # Dọn dẹp thư mục test_recordings
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir, ignore_errors=True)

    print("\n=======================================================")
    print("🎉 TẤT CẢ CÁC BÀI KIỂM THỬ ĐỀU THÀNH CÔNG RỰC RỠ!")
    print("=======================================================")
