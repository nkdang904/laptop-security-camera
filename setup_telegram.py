import os
import sys
import time
import yaml
import httpx

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

def print_banner():
    print("=" * 65)
    print("      CÔNG CỤ THIẾT LẬP TELEGRAM BOT CHO CAMERA LAPTOP")
    print("=" * 65)

def guide_user():
    print("\n👉 BƯỚC 1: TẠO BOT TELEGRAM (CHỈ MẤT 30 GIÂY)")
    print("1. Mở Telegram Desktop đang chạy trên máy (hoặc trên điện thoại).")
    print("2. Tìm kiếm người dùng: @BotFather (có tích xanh).")
    print("3. Gửi tin nhắn: /newbot")
    print("4. Nhập tên hiển thị cho camera (VD: Camera Laptop Nha).")
    print("5. Nhập username cho bot kết thúc bằng chữ 'bot' (VD: kdg_laptop_cam_bot).")
    print("6. Sao chép chuỗi 'HTTP API token' mà BotFather gửi cho bạn.")
    print("-" * 65)

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"✅ Đã lưu cấu hình vào: {CONFIG_PATH}")

def main():
    print_banner()
    guide_user()

    cfg = load_config()
    current_token = cfg.get("telegram", {}).get("bot_token", "")

    prompt = "\n🔑 Dán HTTP API Token của bạn vào đây: "
    if current_token:
        prompt = f"\n🔑 Dán HTTP API Token (hoặc nhấn Enter để dùng token hiện tại [{current_token[:8]}...]): "

    bot_token = input(prompt).strip()
    if not bot_token and current_token:
        bot_token = current_token

    if not bot_token:
        print("❌ Token không được để trống. Thoát thiết lập.")
        return

    # 1. Kiểm tra Token qua getMe
    base_url = f"https://api.telegram.org/bot{bot_token}"
    print("\n⏳ Đang kiểm tra token với Telegram API...")
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(f"{base_url}/getMe")
            if res.status_code != 200:
                print(f"❌ Token không hợp lệ! Mã lỗi: {res.status_code} - {res.text}")
                return
            bot_info = res.json().get("result", {})
            bot_username = bot_info.get("username", "Unknown")
            first_name = bot_info.get("first_name", "Bot")
            print(f"✅ Xác thực thành công: Bot '{first_name}' (@{bot_username})")
    except Exception as e:
        print(f"❌ Không thể kết nối tới Telegram: {e}")
        return

    # 2. Hướng dẫn bấm Start để lấy Chat ID
    print("\n" + "=" * 65)
    print("👉 BƯỚC 2: TỰ ĐỘNG BẮT LẤY CHAT ID CỦA BẠN")
    print(f"Hãy mở Telegram, bấm vào bot: https://t.me/{bot_username}")
    print("Sau đó bấm nút 'START' (hoặc gửi bất kỳ tin nhắn nào cho bot)...")
    print("Hệ thống đang chờ tín hiệu (tối đa 60 giây)...")
    print("=" * 65)

    chat_id = None
    user_name = None
    start_wait = time.time()

    with httpx.Client(timeout=10.0) as client:
        # Xoá các update cũ
        client.get(f"{base_url}/getUpdates?offset=-1")

        while time.time() - start_wait < 60:
            try:
                r = client.get(f"{base_url}/getUpdates")
                if r.status_code == 200:
                    updates = r.json().get("result", [])
                    if updates:
                        last_msg = updates[-1].get("message")
                        if last_msg:
                            chat_id = str(last_msg.get("chat", {}).get("id"))
                            user_name = last_msg.get("from", {}).get("first_name", "User")
                            break
            except Exception:
                pass
            time.sleep(1.5)
            print(".", end="", flush=True)

    print()
    if not chat_id:
        print("\n⚠️ Chưa nhận được tin nhắn từ bạn trong 60 giây.")
        manual_id = input("Bạn có muốn tự nhập Chat ID thủ công không? (Để trống nếu muốn thử lại sau): ").strip()
        if manual_id:
            chat_id = manual_id
        else:
            print("❌ Chưa lấy được Chat ID. Vui lòng chạy lại script khi sẵn sàng.")
            return

    print(f"\n🎉 ĐÃ TÌM THẤY CHAT ID: {chat_id} (Người dùng: {user_name})")

    # 3. Cập nhật vào config.yaml
    if "telegram" not in cfg:
        cfg["telegram"] = {}
    cfg["telegram"]["bot_token"] = bot_token
    cfg["telegram"]["chat_id"] = str(chat_id)
    cfg["telegram"]["enabled"] = True
    save_config(cfg)

    # 4. Gửi tin nhắn chào mừng qua bot
    try:
        with httpx.Client(timeout=10.0) as client:
            welcome_text = (
                "🎉 *KẾT NỐI CAMERA THÀNH CÔNG!*\n\n"
                "Hệ thống Camera An Ninh Laptop đã được liên kết với Telegram của bạn.\n"
                "Bạn sẽ nhận được ảnh chụp và video sự kiện ngay khi phát hiện người.\n\n"
                "Thử gõ `/status` hoặc `/snapshot` để kiểm tra nhé!"
            )
            client.post(
                f"{base_url}/sendMessage",
                json={"chat_id": chat_id, "text": welcome_text, "parse_mode": "Markdown"}
            )
            print("🚀 Đã gửi tin nhắn xác nhận đến Telegram của bạn!")
    except Exception as e:
        print(f"⚠️ Gửi tin nhắn xác nhận thất bại: {e}")

    print("\n" + "=" * 65)
    print("HOÀN TẤT THIẾT LẬP! Bây giờ bạn có thể chạy camera bằng: python main.py")
    print("=" * 65)

if __name__ == "__main__":
    main()
