import os
import time
import logging
import threading
from datetime import datetime
from typing import Optional, Callable
import httpx
import psutil

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    Quản lý thông báo và tương tác 2 chiều với người dùng qua Telegram Bot:
    - Gửi tin nhắn cảnh báo
    - Gửi ảnh chụp snapshot (photo)
    - Gửi video clip sự kiện (video)
    - Lắng nghe lệnh từ xa qua Telegram: /status, /snapshot, /mute, /unmute, /help
    """

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        alert_title: str = "🚨 *CẢNH BÁO AN NINH: PHÁT HIỆN NGƯỜI!*",
        enable_commands: bool = True,
        snapshot_provider_fn: Optional[Callable[[], Optional[str]]] = None,
        live_clip_provider_fn: Optional[Callable[[Callable[[str], None]], None]] = None,
        stream_urls_provider_fn: Optional[Callable[[], dict]] = None
    ):
        self.bot_token = bot_token.strip()
        self.chat_id = str(chat_id).strip()
        self.alert_title = alert_title
        self.enable_commands = enable_commands
        self.snapshot_provider_fn = snapshot_provider_fn
        self.live_clip_provider_fn = live_clip_provider_fn
        self.stream_urls_provider_fn = stream_urls_provider_fn

        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.is_muted = False
        self.is_running = False
        self._command_thread: Optional[threading.Thread] = None
        self._last_update_id = 0
        self.start_time = time.time()

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id and len(self.bot_token) > 10)

    def start(self):
        """Bắt đầu listener lệnh nếu được kích hoạt."""
        if not self.is_configured:
            logger.warning("Telegram Bot chưa được cấu hình bot_token hoặc chat_id. Thông báo sẽ tạm tắt.")
            return

        if self.enable_commands and not self.is_running:
            self.is_running = True
            self._command_thread = threading.Thread(
                target=self._poll_commands,
                name="TelegramCommandPoller",
                daemon=True
            )
            self._command_thread.start()
            logger.info("Telegram Command Poller đã khởi động. Bạn có thể gửi /snapshot hoặc /status trên Telegram.")

    def stop(self):
        """Dừng Telegram command poller."""
        self.is_running = False
        if self._command_thread and self._command_thread.is_alive():
            self._command_thread.join(timeout=2.0)
        logger.info("Telegram Notifier đã dừng.")

    def send_alert_async(self, snapshot_path: Optional[str] = None, details: str = ""):
        """Gửi cảnh báo bất đồng bộ bằng thread riêng để không nghẽn luồng chính."""
        if not self.is_configured or self.is_muted:
            return

        threading.Thread(
            target=self._send_alert_worker,
            args=(snapshot_path, details),
            daemon=True
        ).start()

    def _send_alert_worker(self, snapshot_path: Optional[str], details: str):
        time_str = datetime.now().strftime("%H:%M:%S ngày %d/%m/%Y")
        caption = f"{self.alert_title}\n\n🕒 *Thời gian:* `{time_str}`\n📍 *Vị trí:* Laptop Camera"
        if details:
            caption += f"\nℹ️ *Chi tiết:* {details}"

        if snapshot_path and os.path.exists(snapshot_path):
            self.send_photo(snapshot_path, caption=caption)
        else:
            self.send_message(caption)

    def send_video_async(self, video_path: str, caption: str = ""):
        """Gửi video sự kiện bất đồng bộ."""
        if not self.is_configured or self.is_muted:
            return

        threading.Thread(
            target=self.send_video,
            args=(video_path, caption),
            daemon=True
        ).start()

    def send_message(self, text: str) -> bool:
    def send_message(self, text: str, reply_markup: Optional[dict] = None) -> bool:
        """Gửi tin nhắn dạng Markdown qua Telegram."""
        if not self.is_configured:
            return False

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "Markdown"
                    }
                )
                payload = {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown"
                }
                if reply_markup:
                    payload["reply_markup"] = reply_markup

                resp = client.post(f"{self.base_url}/sendMessage", json=payload)
                if resp.status_code == 200:
                    return True
                logger.error(f"Lỗi gửi tin nhắn Telegram ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Lỗi kết nối Telegram sendMessage: {e}")
        return False

    def send_photo(self, photo_path: str, caption: str = "") -> bool:
        """Gửi ảnh snapshot qua Telegram."""
        if not self.is_configured or not os.path.exists(photo_path):
            return False

        try:
            with httpx.Client(timeout=20.0) as client:
                with open(photo_path, "rb") as f:
                    files = {"photo": f}
                    data = {"chat_id": self.chat_id, "parse_mode": "Markdown"}
                    if caption:
                        data["caption"] = caption

                    resp = client.post(f"{self.base_url}/sendPhoto", data=data, files=files)
                    if resp.status_code == 200:
                        logger.info(f"Đã gửi ảnh Telegram thành công: {os.path.basename(photo_path)}")
                        return True
                    logger.error(f"Lỗi gửi ảnh Telegram ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Lỗi kết nối Telegram sendPhoto: {e}")
        return False

    def send_video(self, video_path: str, caption: str = "") -> bool:
        """Gửi file video clip qua Telegram."""
        if not self.is_configured or not os.path.exists(video_path):
            return False

        try:
            with httpx.Client(timeout=60.0) as client:
                with open(video_path, "rb") as f:
                    files = {"video": f}
                    data = {"chat_id": self.chat_id, "parse_mode": "Markdown"}
                    if caption:
                        data["caption"] = caption
                    else:
                        time_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                        data["caption"] = f"📹 *Video ghi nhận sự kiện* (`{time_str}`)"

                    resp = client.post(f"{self.base_url}/sendVideo", data=data, files=files)
                    if resp.status_code == 200:
                        logger.info(f"Đã gửi video Telegram thành công: {os.path.basename(video_path)}")
                        return True
                    logger.error(f"Lỗi gửi video Telegram ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Lỗi kết nối Telegram sendVideo: {e}")
        return False

    def _poll_commands(self):
        """Vòng lặp nhận lệnh từ người dùng trên Telegram."""
        while self.is_running:
            try:
                with httpx.Client(timeout=15.0) as client:
                    resp = client.get(
                        f"{self.base_url}/getUpdates",
                        params={"offset": self._last_update_id + 1, "timeout": 10}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for update in data.get("result", []):
                            self._last_update_id = update["update_id"]
                            try:
                                self._handle_update(update)
                            except Exception as e:
                                logger.error(f"Lỗi khi xử lý lệnh: {e}")
            except Exception as e:
                time.sleep(3)

    def _handle_update(self, update: dict):
        """Xử lý từng tin nhắn/lệnh nhận được."""
        message = update.get("message")
        if not message:
            return

        text = message.get("text", "").strip()
        sender_id = str(message.get("chat", {}).get("id", ""))

        # Chỉ chấp nhận lệnh từ chat_id đã được cấp quyền
        if self.chat_id and sender_id != self.chat_id:
            logger.warning(f"Từ chối lệnh từ người dùng lạ (Chat ID: {sender_id})")
            return

        # Cắt bỏ đuôi @bot_name nếu người dùng chọn từ gợi ý Telegram
        raw_cmd = text.split()[0].lower() if text else ""
        cmd = raw_cmd.split("@")[0]

        logger.info(f"Đã nhận lệnh từ Telegram: '{cmd}'")

        if cmd in ("/start", "/help"):
            reply = (
                "👋 *HỆ THỐNG CAMERA AN NINH LAPTOP*\n\n"
                "Danh sách lệnh bạn có thể sử dụng:\n"
                "🔴 `/live` - Xem trực tiếp thời gian thực (nhận link web + clip 5s tức thì)\n"
                "📸 `/snapshot` - Chụp ảnh tức thì từ camera laptop gửi về\n"
                "📊 `/status` - Xem trạng thái hệ thống, CPU, RAM, ổ đĩa\n"
                "🔕 `/mute` - Tạm dừng gửi thông báo cảnh báo (khi bạn ở nhà)\n"
                "🔔 `/unmute` - Bật lại thông báo cảnh báo (khi bạn ra ngoài)\n"
                "❓ `/help` - Xem hướng dẫn này"
            )
            self.send_message(reply)

        elif cmd in ("/live", "/stream"):
            urls = self.stream_urls_provider_fn() if self.stream_urls_provider_fn else {}
            pub_url = urls.get("public_url", "")
            loc_url = urls.get("local_url", "")

            msg = "🔴 *XEM TRỰC TIẾP (REALTIME STREAM)*\n\n"
            if pub_url and "trycloudflare" in pub_url:
                msg += f"🌐 *Link xem từ xa (4G/Internet):*\n{pub_url}\n\n"
            if loc_url:
                msg += f"🏠 *Link xem trong nhà (Wi-Fi):*\n{loc_url}\n\n"
            msg += "⏳ Đang quay ngay clip trực tiếp 5 giây gửi vào đây cho bạn..."

            reply_markup = None
            if pub_url or loc_url:
                target_url = pub_url if (pub_url and "trycloudflare" in pub_url) else loc_url
                reply_markup = {
                    "inline_keyboard": [
                        [{"text": "🔴 Mở Xem Trực Tiếp Trên Web", "url": target_url}]
                    ]
                }
            self.send_message(msg, reply_markup=reply_markup)

            if self.live_clip_provider_fn:
                def send_clip(clip_path):
                    self.send_video(clip_path, caption="🔴 *Clip quay trực tiếp thời gian thực (Live)*")
                threading.Thread(target=self.live_clip_provider_fn, args=(send_clip,), daemon=True).start()

        elif cmd == "/snapshot":
            self.send_message("📸 Đang chụp ảnh từ camera laptop...")
            if self.snapshot_provider_fn:
                photo_file = self.snapshot_provider_fn()
                if photo_file and os.path.exists(photo_file):
                    self.send_photo(photo_file, caption="📸 *Ảnh chụp tức thì từ Camera Laptop*")
                else:
                    self.send_message("❌ Không thể lấy ảnh snapshot từ camera vào lúc này.")
            else:
                self.send_message("❌ Hàm chụp ảnh chưa được đăng ký.")

        elif cmd == "/status":
            uptime = int(time.time() - self.start_time)
            hours, rem = divmod(uptime, 3600)
            minutes, seconds = divmod(rem, 60)

            cpu_usage = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory()

            mode_str = "🔕 Đang Tắt Báo Động (Mute)" if self.is_muted else "🔔 Đang Bật Báo Động"

            status_msg = (
                f"📊 *TRẠNG THÁI CAMERA LAPTOP*\n\n"
                f"• *Chế độ:* {mode_str}\n"
                f"• *Thời gian hoạt động:* `{hours:02d}h {minutes:02d}m {seconds:02d}s`\n"
                f"• *CPU:* `{cpu_usage}%`\n"
                f"• *RAM:* `{ram.percent}%` (Trống `{ram.available / (1024**3):.1f} GB`)\n"
                f"• *Thời gian hiện tại:* `{datetime.now().strftime('%H:%M:%S %d/%m/%Y')}`"
            )
            self.send_message(status_msg)

        elif cmd == "/mute":
            self.is_muted = True
            self.send_message("🔕 Đã tạm tắt thông báo cảnh báo tự động. (Dùng `/unmute` để bật lại)")

        elif cmd == "/unmute":
            self.is_muted = False
            self.send_message("🔔 Đã bật lại thông báo cảnh báo an ninh.")

