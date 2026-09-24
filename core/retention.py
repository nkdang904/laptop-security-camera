import os
import time
import logging
import threading
from typing import Optional, List, Tuple, Callable

logger = logging.getLogger(__name__)

class RetentionManager:
    """
    Quản lý chính sách lưu trữ (Retention Policy) cho thư mục ghi hình:
    - Xoá file cũ hơn max_days ngày.
    - Giới hạn tổng dung lượng thư mục <= max_storage_gb GB (tự động xoá file cũ nhất).
    - Chạy định kỳ ở background thread.
    """

    ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mkv", ".jpg", ".jpeg", ".png"}

    def __init__(
        self,
        storage_dir: str = "recordings",
        max_days: int = 7,
        max_storage_gb: float = 10.0,
        check_interval_minutes: int = 30,
        on_cleanup: Optional[Callable[[], None]] = None
    ):
        self.storage_dir = os.path.abspath(storage_dir)
        self.max_days = max_days
        self.max_storage_bytes = int(max_storage_gb * 1024 * 1024 * 1024)
        self.check_interval_seconds = check_interval_minutes * 60
        self.on_cleanup = on_cleanup

        os.makedirs(self.storage_dir, exist_ok=True)
        self.is_running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Khởi động luồng dọn dẹp định kỳ."""
        if self.is_running:
            return

        self.is_running = True
        self._thread = threading.Thread(target=self._loop, name="RetentionWorker", daemon=True)
        self._thread.start()
        logger.info(
            f"Retention Manager đã khởi động: Xoá sau {self.max_days} ngày, "
            f"Dung lượng tối đa {self.max_storage_bytes / (1024**3):.1f} GB"
        )

    def _loop(self):
        """Vòng lặp dọn dẹp chạy định kỳ."""
        # Chạy lần dọn dẹp đầu tiên sau khi khởi động 10 giây
        time.sleep(10)
        while self.is_running:
            try:
                self.run_cleanup()
            except Exception as e:
                logger.error(f"Lỗi trong quá trình dọn dẹp dung lượng: {e}")

            # Ngủ theo chu kỳ
            step = 5
            elapsed = 0
            while self.is_running and elapsed < self.check_interval_seconds:
                time.sleep(step)
                elapsed += step

    def get_tracked_files(self) -> List[Tuple[str, float, int]]:
        """Lấy danh sách các file video/ảnh: (filepath, mtime, size_bytes)."""
        files_info = []
        if not os.path.exists(self.storage_dir):
            return files_info

        # Quét cả thư mục con (recordings/continuous/YYYY-MM-DD/...)
        for root, _, files in os.walk(self.storage_dir):
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext in self.ALLOWED_EXTENSIONS and not name.endswith(".tmp.mp4"):
                    path = os.path.join(root, name)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    files_info.append((path, stat.st_mtime, stat.st_size))

        return files_info

    def run_cleanup(self) -> Tuple[int, float]:
        """
        Thực hiện dọn dẹp ngay lập tức.
        Trả về: (số file đã xoá, số MB đã giải phóng).
        """
        now = time.time()
        max_age_seconds = self.max_days * 86400
        files_info = self.get_tracked_files()

        deleted_count = 0
        freed_bytes = 0

        # 1. Xoá theo thời gian (cũ hơn max_days)
        remaining_files = []
        for path, mtime, size in files_info:
            age = now - mtime
            if age > max_age_seconds:
                try:
                    os.remove(path)
                    deleted_count += 1
                    freed_bytes += size
                    logger.info(f"[Retention] Đã xoá file quá hạn ({age / 86400:.1f} ngày): {os.path.basename(path)}")
                except Exception as e:
                    logger.warning(f"Không thể xoá file {path}: {e}")
            else:
                remaining_files.append((path, mtime, size))

        # 2. Xoá theo dung lượng tối đa (nếu vượt quá max_storage_gb)
        total_size = sum(size for _, _, size in remaining_files)
        target_size = int(self.max_storage_bytes * 0.85) # Dọn xuống 85% dung lượng để tạo khoảng trống

        if total_size > self.max_storage_bytes:
            logger.info(
                f"[Retention] Thư mục lưu trữ ({total_size / (1024**3):.2f} GB) "
                f"vượt ngưỡng cho phép ({self.max_storage_bytes / (1024**3):.2f} GB). Đang dọn dẹp file cũ nhất..."
            )
            # Sắp xếp file theo mtime từ cũ nhất đến mới nhất
            remaining_files.sort(key=lambda x: x[1])

            for path, _, size in remaining_files:
                if total_size <= target_size:
                    break
                try:
                    os.remove(path)
                    deleted_count += 1
                    freed_bytes += size
                    total_size -= size
                    logger.info(f"[Retention] Đã xoá file cũ để giảm tải: {os.path.basename(path)}")
                except Exception as e:
                    logger.warning(f"Không thể xoá file {path}: {e}")

        self._remove_empty_dirs()
        if deleted_count > 0 and self.on_cleanup:
            try:
                self.on_cleanup()
            except Exception as e:
                logger.warning(f"Lỗi đồng bộ chỉ mục sau khi dọn dẹp: {e}")

        freed_mb = freed_bytes / (1024 * 1024)
        if deleted_count > 0:
            logger.info(f"[Retention] Hoàn thành dọn dẹp: Đã xoá {deleted_count} file, giải phóng {freed_mb:.2f} MB.")

        return deleted_count, freed_mb

    def _remove_empty_dirs(self):
        for root, dirs, files in os.walk(self.storage_dir, topdown=False):
            if root != self.storage_dir and not dirs and not files:
                try:
                    os.rmdir(root)
                except OSError:
                    pass

    def stop(self):
        """Dừng luồng dọn dẹp."""
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Retention Manager đã dừng.")

