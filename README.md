# Laptop Smart Security Camera 🎥🚨

Hệ thống biến laptop thành camera an ninh thông minh tích hợp AI nhận diện người, lưu trữ cục bộ có chính sách tự động xoá theo thời gian/dung lượng, và gửi cảnh báo tức thì (kèm ảnh snapshot + clip video) qua Telegram.

---

## 🌟 Tính Năng Nổi Bật

1. **Bộ lọc thông minh 2 lớp (Zero False Alarm):**
   - **Lớp 1 (Motion Pre-filter):** Kiểm tra thay đổi pixel cực nhẹ (< 1% CPU). Không có chuyển động thì không đánh thức AI.
   - **Lớp 2 (AI YOLOv8n):** Khi có chuyển động, AI nhận diện chính xác đối tượng `person` (người). Rèm cửa đung đưa, đổi ánh sáng hay bóng chó mèo sẽ không làm phiền bạn.
2. **Quay đón đầu sự kiện (Pre-event Ring Buffer):**
   - Giữ lại 2-3 giây *trước* thời điểm phát hiện người để đảm bảo không bị lỡ khoảnh khắc đối tượng vừa bước vào phòng.
3. **Cảnh báo Telegram 2 chiều:**
   - Gửi ảnh chụp snapshot tức thì ngay khi phát hiện người.
   - Gửi tiếp file video MP4 ghi lại toàn bộ diễn biến sự kiện.
   - Hỗ trợ ra lệnh điều khiển từ xa từ điện thoại:
     - `/snapshot`: Yêu cầu laptop chụp ngay 1 ảnh gửi về Telegram.
     - `/status`: Kiểm tra trạng thái máy, CPU, RAM, thời gian chạy.
     - `/mute` / `/unmute`: Tắt/bật cảnh báo khi bạn ở nhà.
4. **Chính sách tự dọn dẹp (Retention Policy):**
   - Tự động xoá file cũ hơn `max_days` (mặc định 7 ngày).
   - Tự động giới hạn tổng dung lượng thư mục không vượt quá `max_storage_gb` (mặc định 10 GB).
   - Yên tâm cắm máy chạy 24/7 mà không lo đầy ổ cứng.

---

## 🚀 Hướng Dẫn Sử Dụng Nhanh

### Bước 1: Kết nối Telegram Bot (30 giây)

1. Mở ứng dụng **Telegram** trên máy tính hoặc điện thoại.
2. Tìm bot **`@BotFather`** (có dấu tích xanh).
3. Gửi lệnh `/newbot` và đặt tên hiển thị + username cho bot (ví dụ: `my_home_cam_bot`).
4. Copy chuỗi **HTTP API Token**.
5. Mở terminal tại thư mục dự án và chạy:
   ```bash
   python setup_telegram.py
   ```
6. Dán token vào. Script sẽ yêu cầu bạn bấm **START** trên bot vừa tạo để tự động bắt lấy `chat_id` và lưu vào `config.yaml`.

---

### Bước 2: Khởi động Camera

- Chạy trực tiếp:
  ```bash
  python main.py
  ```
- Hoặc nhấp đúp chuột vào file **`run.bat`**.

---

## ⚙️ Tùy Chỉnh Cấu Hình (`config.yaml`)

Bạn có thể chỉnh sửa các thông số trong file `config.yaml`:

```yaml
camera:
  source: 0                    # 0: webcam laptop
  fps: 20                      # Khung hình/giây

detection:
  confidence_threshold: 0.50   # Độ tin cậy AI (50%)
  cooldown_seconds: 30         # Khoảng nghỉ giữa các lần gửi cảnh báo

recording:
  save_dir: "recordings"       # Thư mục lưu video/ảnh
  record_on_detect_seconds: 8  # Thời lượng video sự kiện
  pre_buffer_seconds: 3        # Số giây quay đón đầu

retention:
  max_days: 7                  # Số ngày lưu trữ tối đa
  max_storage_gb: 10.0         # Dung lượng tối đa (GB)
```

---

## 💡 Mẹo Tối Ưu Cho Laptop Chạy 24/7 (Gập Màn Hình Vẫn Hoạt Động)

Để laptop gập màn hình lại mà camera vẫn hoạt động bình thường và tiết kiệm điện:

1. Nhấn phím `Windows`, gõ **Control Panel** -> mở **Power Options**.
2. Ở cột bên trái, bấm vào **Choose what closing the lid does** (Chọn hành động khi gập nắp máy).
3. Tại dòng **When I close the lid**, chuyển cả hai mục *(On battery)* và *(Plugged in)* thành: **`Do nothing`**.
4. Bấm **Save changes**.
5. Bây giờ bạn có thể cắm sạc laptop, khởi động camera (`run.bat`), gập nắp laptop lại và để ở góc phòng. Máy vẫn chạy êm ái, bảo mật và màn hình tắt tiết kiệm điện!

