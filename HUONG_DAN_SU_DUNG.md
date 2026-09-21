# 📖 HƯỚNG DẪN SỬ DỤNG HỆ THỐNG CAMERA AN NINH LAPTOP

Chào bạn, đây là toàn bộ cẩm nang hướng dẫn vận hành, điều khiển từ xa và tinh chỉnh hệ thống Camera An Ninh trên chiếc laptop của bạn.

---

## 1. Cách Bật / Tắt Camera Hàng Ngày (1-Click)

Trong thư mục `d:\.WorkSpace\Tools\laptop-security-camera`, bạn có 2 cách chạy tuỳ sở thích:

### Cách 1: Chạy có cửa sổ thông tin (Khuyên dùng khi mới làm quen)
- Nhấp đúp chuột vào file: **`KHOI_DONG_CAMERA.bat`** (hoặc **`run.bat`**).
- Một cửa sổ màu đen sẽ hiện lên hiển thị trạng thái kết nối webcam, nạp AI và log khi có người.
- **Cách tắt:** Nhấn phím `Ctrl + C` hoặc bấm dấu `X` tắt cửa sổ đó đi là xong.

### Cách 2: Chạy hoàn toàn ẩn danh (Không hiện cửa sổ nào trên màn hình)
- Nhấp đúp chuột vào file: **`Chay_Ngam_Khong_Cua_So.vbs`**.
- Camera sẽ âm thầm chạy ngầm dưới nền Windows mà không có cửa sổ console nào làm vướng mắt.
- **Cách tắt:** Nhấp đúp vào file **`Dung_Camera_Chay_Ngam.bat`** để dừng máy quay.

---

## 2. Cách Điều Khiển Camera Từ Xa Qua Telegram

Bạn có thể mở Telegram trên điện thoại hoặc máy tính bất cứ lúc nào và gửi các lệnh sau cho Bot:

| Lệnh | Ý nghĩa & Tác dụng |
| :--- | :--- |
| **`/snapshot`** | Yêu cầu laptop chụp ngay 1 tấm ảnh từ webcam và gửi về cho bạn lập tức (dùng để kiểm tra nhà cửa khi đang ở ngoài). |
| **`/status`** | Kiểm tra trạng thái máy: Laptop đang chạy được bao lâu, mức tiêu thụ CPU, dung lượng RAM còn trống, thời gian thực. |
| **`/mute`** | Tắt chuông cảnh báo tự động (dùng khi bạn đã về nhà, không muốn camera gửi tin nhắn phát hiện người liên tục). |
| **`/unmute`** | Bật lại chuông cảnh báo (khi bạn chuẩn bị rời khỏi nhà). |
| **`/help`** | Xem danh sách các lệnh hỗ trợ. |

---

## 3. Cơ Chế Hoạt Động Tự Động Khi Có Người

Khi có người xuất hiện trong phòng:
1. **Gửi ảnh ngay lập tức:** Bot sẽ gửi ảnh chụp rõ nét đối tượng kèm khung chữ nhật đỏ nhận diện và tỷ lệ chính xác (Ví dụ: `person 85%`).
2. **Quay và gửi video clip:** 
   - Hệ thống tự động ghi lại clip ngắn (khoảng 8 giây).
   - Nhờ công nghệ **Ring Buffer**, clip này có sẵn 2–3 giây **trước khi người đó bước vào**, giúp bạn thấy trọn vẹn toàn bộ hành động từ đầu.
   - Khi ghi xong, file video `.mp4` sẽ được bot gửi thẳng vào Telegram.

---

## 4. Nơi Lưu Dữ Liệu & Chính Sách Tự Động Xoá (Retention)

- Tất cả ảnh snapshot và video quay lại được lưu tại thư mục:
  `d:\.WorkSpace\Tools\laptop-security-camera\recordings`
- **Chính sách tự dọn dẹp:**
  - Hệ thống định kỳ tự động xoá các video cũ hơn **7 ngày**.
  - Nếu tổng dung lượng thư mục vượt quá **10 GB**, hệ thống sẽ tự động dọn bớt các video cũ nhất để ổ cứng máy không bao giờ bị đầy.
  - Bạn hoàn toàn có thể yên tâm cắm máy chạy quanh năm suốt tháng.

---

## 5. Tùy Chỉnh Theo Ý Muốn (`config.yaml`)

Mở file **`config.yaml`** bằng Notepad để thay đổi các thông số nếu cần:
- `cooldown_seconds: 30`: Khoảng cách thời gian tối thiểu giữa 2 lần gửi cảnh báo (tránh bị bot spam liên tục nếu người đó đứng lâu trong phòng).
- `record_on_detect_seconds: 8`: Độ dài clip video quay lại khi phát hiện người.
- `max_days: 7`: Số ngày lưu video trước khi tự động xoá.
- `max_storage_gb: 10.0`: Dung lượng ổ đĩa tối đa cho phép lưu trữ.
- `confidence_threshold: 0.5`: Độ nhạy AI (từ 0.1 đến 1.0; tăng lên nếu muốn chặt chẽ hơn, giảm xuống nếu góc quay ở xa).

---

## 6. Mẹo Cài Đặt Để Gập Màn Hình Laptop Mà Máy Vẫn Chạy 24/7

Để biến laptop thành một chiếc camera ngụy trang kín đáo, bạn có thể gập màn hình lại mà máy không bị ngủ (Sleep):
1. Bấm phím **Windows**, gõ tìm kiếm **Control Panel** và mở ra.
2. Chọn mục **Power Options** (hoặc gõ Power Options vào ô tìm kiếm của Control Panel).
3. Bấm vào dòng **Choose what closing the lid does** ở cột bên trái.
4. Ở dòng **When I close the lid**, chuyển cả 2 cột *(On battery)* và *(Plugged in)* thành **`Do nothing`**.
5. Bấm nút **Save changes** ở dưới cùng.

👉 **Cách dùng tối ưu:** Cắm sạc laptop, bấm chạy file **`Chay_Ngam_Khong_Cua_So.vbs`** (hoặc `KHOI_DONG_CAMERA.bat`), sau đó gập nắp laptop lại và đặt máy hướng camera về phía cửa. Màn hình laptop sẽ tự tắt để tiết kiệm điện và làm mát máy, trong khi webcam và AI vẫn hoạt động giám sát 24/7!

