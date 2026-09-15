# NDC Leads & OTA Finder (Standalone Web Server & Dashboard)

Hệ thống tự động hóa trọn gói quy trình tìm kiếm, sàng lọc và thẩm định **Đại lý vé máy bay & Online Travel Agency (OTA)** theo tiêu chuẩn **NDC Leads** từ Google Maps.

Ứng dụng chạy độc lập bằng **Python Web Server (FastAPI)**, hoàn toàn **không cần Docker**, đi kèm giao diện Web Dashboard hiện đại:
* 🔍 **Nhập từ khoá tuỳ ý** hoặc chọn quốc gia có sẵn (Việt Nam, Thái Lan, Hong Kong, Indonesia, Philippines...).
* ⚡ **Theo dõi tiến độ cào và thẩm định** theo thời gian thực qua 5 giai đoạn.
* 📁 **Quản lý danh sách các file Excel kết quả** đã cào và bấm nút **Tải về (.xlsx)** trực tiếp từ trình duyệt.

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy Nhanh

### 1. Yêu cầu môi trường:
* **Python 3.10 trở lên**.

### 2. Cài đặt thư viện:
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Chuẩn bị Scraper Binary:
Tải file binary `google-maps-scraper` tương ứng với hệ điều hành của bạn từ [gosom/google-maps-scraper Releases](https://github.com/gosom/google-maps-scraper/releases/latest) và đặt vào thư mục `bin/`:
* **macOS**: Tải file `google_maps_scraper-...-darwin-amd64`, đổi tên thành `google-maps-scraper`, đặt vào `bin/` và cấp quyền:
  ```bash
  chmod +x bin/google-maps-scraper
  ```
* **Linux**: Tải `linux-amd64`, đổi tên thành `google-maps-scraper`, đặt vào `bin/`.
* **Windows**: Tải `windows-amd64.exe`, đổi tên thành `google-maps-scraper.exe`, đặt vào `bin/`.

---

## 💻 Cách Khởi Động Web Server

### Cách 1: Chạy bằng lệnh Python
```bash
python run.py
```

### Cách 2: Nhấp đúp chuột file khởi động
* **macOS / Linux**: Chạy file `./start.sh`
* **Windows**: Nhấp đúp file `start.bat`

Sau khi khởi động, mở trình duyệt truy cập vào:
👉 **`http://localhost:8090`**

---

## 🌟 Các Tính Năng Trên Giao Diện Web

1. **Tab "🔍 Tìm kiếm mới"**:
   * Chọn quốc gia có sẵn hoặc nhập danh sách từ khoá tuỳ ý (mỗi dòng 1 từ khoá).
   * Cấu hình Độ sâu (Depth: 2, 5, 10), Số luồng cào (Concurrency: 2, 4, 6), Chuẩn thị trường (Consolidator vs OTA-First).
   * Bấm nút: **[ 🚀 BẮT ĐẦU QUÉT LEADS VÀ THẨM ĐỊNH ]**.

2. **Tab "⚡ Tiến độ đang chạy"**:
   * Hiển thị thanh tiến trình từ `0%` đến `100%` qua 5 giai đoạn:
     `[1] Sinh Query` ➔ `[2] Cào GMaps` ➔ `[3] Lọc Heuristic` ➔ `[4] Thẩm định Web` ➔ `[5] Xuất Excel`.
   * Khung nhật ký hoạt động (Live Logs) cập nhật theo thời gian thực.
   * Chạy ngầm hoàn toàn: Bạn có thể đóng trình duyệt, tác vụ vẫn tiếp tục chạy.

3. **Tab "📁 File kết quả Excel"**:
   * Danh sách toàn bộ các file Excel báo cáo đã tạo trong thư mục `output/`.
   * Xem ngày giờ tạo, kích thước file.
   * Nút **[ 📥 Tải về (.xlsx) ]** và **[ 🗑️ Xoá ]**.

---

## 🛠️ Chạy Bằng Dòng Lệnh (CLI Mode)

Nếu muốn chạy trực tiếp bằng dòng lệnh không qua giao diện web:
```bash
python src/orchestrator.py --country vietnam --lang vi --depth 5
```
