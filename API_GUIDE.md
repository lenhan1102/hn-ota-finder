# API Reference — Google Maps Scraper / NDC Leads Finder

**Base URL (Production):** `http://192.168.88.111:8090`  
**Base URL (Local):** `http://localhost:8090`  
**Swagger UI:** `{BASE_URL}/docs`  
**Content-Type:** `application/json` (trừ các endpoint trả về file)

---

## Mục lục

1. [Countries — Danh sách quốc gia](#1-countries)
2. [Jobs — Tạo và quản lý tiến trình](#2-jobs)
   - [POST /api/jobs](#post-apijobs)
   - [GET /api/jobs](#get-apijobs)
   - [GET /api/jobs/:job_id](#get-apijobsjob_id)
   - [POST /api/jobs/:job_id/cancel](#post-apijobsjob_idcancel)
   - [GET /api/jobs/:job_id/excel](#get-apijobsjob_idexcel)
3. [Steps — Dữ liệu chi tiết 5 bước](#3-steps)
4. [Debug — Dữ liệu trung gian từng bước](#4-debug)
5. [Files — Quản lý file output](#5-files)
6. [Luồng tích hợp FE gợi ý](#6-luồng-tích-hợp-fe)

---

## 1. Countries

### `GET /api/countries`

Lấy danh sách các quốc gia được hỗ trợ.

**Response:**
```json
{
  "countries": ["hongkong", "indonesia", "philippines", "thailand", "vietnam"]
}
```

---

## 2. Jobs

### `POST /api/jobs`

**Tạo và khởi chạy** một tiến trình tìm kiếm mới. Pipeline chạy bất đồng bộ (background), API trả về ngay `job_id`.

**Request Body:**
```json
{
  "country": "vietnam",
  "custom_keywords": "đại lý vé máy bay Hà Nội\nphòng vé máy bay quận 1",
  "lang": "vi",
  "depth": 5,
  "concurrency": 1,
  "max_sites": 0,
  "market_type": "auto",
  "headless": true
}
```

| Trường | Kiểu | Mặc định | Mô tả |
|---|---|---|---|
| `country` | string | `"vietnam"` | Tên quốc gia (xem `/api/countries`) |
| `custom_keywords` | string \| null | `null` | Từ khoá tuỳ chỉnh, mỗi từ khoá một dòng. Nếu `null` dùng từ khoá mặc định theo quốc gia |
| `lang` | string | `"vi"` | Ngôn ngữ tìm kiếm Google Maps (`vi`, `en`, `th`, `id`, ...) |
| `depth` | int | `5` | Độ sâu cuộn trang Google Maps (càng lớn càng nhiều kết quả, càng chậm) |
| `concurrency` | int | `1` | Số trình duyệt chạy song song |
| `max_sites` | int | `0` | Giới hạn số website thẩm định. `0` = không giới hạn |
| `market_type` | string | `"auto"` | `"auto"` / `"ota_first"` / `"consolidator"` |
| `headless` | bool | `true` | Chạy trình duyệt ẩn (server nên để `true`) |

**Response `200`:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending"
}
```

---

### `GET /api/jobs`

**Danh sách** tất cả jobs (mới nhất trước). Dữ liệu được hợp nhất giữa MySQL và RAM cache.

**Response `200`:**
```json
{
  "jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "country": "vietnam",
      "custom_keywords": "đại lý vé máy bay Hà Nội",
      "lang": "vi",
      "depth": 5,
      "concurrency": 1,
      "max_sites": 0,
      "market_type": "auto",
      "status": "completed",
      "stage": 5,
      "stage_name": "Hoàn tất",
      "percent": 100,
      "message": "Hoàn tất phân Tier!",
      "error": null,
      "created_at": "2024-09-21 13:00:00",
      "started_at": "2024-09-21 13:00:05",
      "finished_at": "2024-09-21 13:15:23",
      "logs": ["[13:00:05] Bắt đầu tìm kiếm...", "..."],
      "result": {
        "qualified_count": 42,
        "dropped_count": 18,
        "total_leads": 60,
        "excel_filename": "vietnam_ndc_leads_20240921_130005.xlsx"
      }
    }
  ]
}
```

**Các giá trị `status`:**
| Giá trị | Ý nghĩa |
|---|---|
| `pending` | Đã tạo, đang chờ chạy |
| `running` | Đang thực thi pipeline |
| `completed` | Hoàn thành thành công |
| `failed` | Gặp lỗi, đã dừng |
| `cancelled` | Người dùng yêu cầu dừng |

**Các giá trị `stage` (bước hiện tại):**
| Giá trị | Ý nghĩa |
|---|---|
| `0` | Khởi tạo |
| `1` | Sinh danh sách từ khoá |
| `2` | Cào dữ liệu Google Maps |
| `3` | Lọc Heuristic & Chấm điểm |
| `4` | Thẩm định website |
| `5` | Phân Tier & Xuất kết quả |

---

### `GET /api/jobs/:job_id`

Chi tiết một job. Ưu tiên đọc từ RAM (nếu đang chạy), fallback sang MySQL.

**Response `200`:** Cùng cấu trúc với mỗi phần tử trong `GET /api/jobs`.

**Response `404`:**
```json
{ "detail": "Job không tồn tại" }
```

---

### `POST /api/jobs/:job_id/cancel`

Dừng tiến trình đang chạy. Pipeline sẽ dừng tại checkpoint gần nhất (không dừng ngay tức thì).

**Response `200` — Thành công:**
```json
{
  "status": "success",
  "message": "Đã gửi yêu cầu huỷ"
}
```

**Response `200` — Job đã kết thúc:**
```json
{
  "status": "error",
  "message": "Job đã kết thúc, không thể huỷ"
}
```

---

### `DELETE /api/jobs/:job_id`

Xoá một tiến trình tìm kiếm khỏi cơ sở dữ liệu và RAM cache.

**Response `200`:**
```json
{
  "status": "success",
  "message": "Đã xoá job 550e8400-e29b-41d4-a716-446655440000 thành công"
}
```

---

### `GET /api/jobs/:job_id/excel`

Tải file Excel kết quả leads. Tự động tổng hợp từ MySQL (không cần file tĩnh trên server).

**Response `200`:**  
Binary stream — file `.xlsx`  
`Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`  
`Content-Disposition: attachment; filename="vietnam_ndc_leads_xxx.xlsx"`

**Response `400`:**
```json
{ "detail": "Chưa có dữ liệu leads cho job này" }
```

> ⚠️ Chỉ khả dụng khi `status = "completed"`.

---

## 3. Steps

### `GET /api/jobs/:job_id/steps`

Dữ liệu chi tiết cả 5 bước của job, đọc từ MySQL. Dùng để FE hiển thị tab chi tiết từng bước.

**Response `200`:**
```json
{
  "job_id": "550e8400-...",
  "country": "vietnam",
  "status": "completed",
  "percent": 100,
  "stage": 5,
  "stage_name": "Hoàn tất",

  "step1": {
    "queries": ["đại lý vé máy bay tại Hà Nội", "travel agency Vietnam"],
    "count": 2
  },

  "step2": {
    "raw_count": 250,
    "raw_places": [
      {
        "title": "Công ty TNHH Du Lịch ABC",
        "category": "Travel agency",
        "address": "123 Nguyễn Huệ, Q1, TP.HCM",
        "website": "https://abc-travel.vn",
        "phone": "0901234567",
        "google_url": "https://maps.google.com/..."
      }
    ],
    "concurrency": 1,
    "depth": 5,
    "lang": "vi"
  },

  "step3": {
    "candidates_count": 85,
    "candidates": [
      {
        "title": "Công ty TNHH Du Lịch ABC",
        "segment": "Travel agency",
        "website": "https://abc-travel.vn",
        "phone": "0901234567",
        "score_total": 75,
        "priority_tier": "Tier 1"
      }
    ],
    "excluded_count": 165,
    "excluded": [
      {
        "title": "Bamboo Airways",
        "category": "Airline",
        "website": "https://bambooairways.com",
        "exclusion_reason": "Heuristic: hãng bay"
      }
    ]
  },

  "step4": {
    "verdicts_count": 80,
    "verdicts": [
      {
        "title": "Công ty TNHH Du Lịch ABC",
        "website": "https://abc-travel.vn",
        "reachable": 1,
        "flightticketing": 1,
        "onlinesearch": 1,
        "iata": 0,
        "iframe": 1,
        "iframe_src": "https://booking.vntrip.vn/...",
        "ai_classification": {},
        "error": ""
      }
    ],
    "reverify": [],
    "reverify_count": 0
  },

  "step5": {
    "qualified_leads": [
      {
        "title": "Công ty TNHH Du Lịch ABC",
        "company_name": "Công ty TNHH Du Lịch ABC",
        "category": "Travel agency",
        "address": "123 Nguyễn Huệ, Q1, TP.HCM",
        "website": "https://abc-travel.vn",
        "phone": "0901234567",
        "tier": "Tier 1",
        "reason": ""
      }
    ],
    "dropped_leads": [
      {
        "title": "XYZ Tours",
        "tier": "Dropped",
        "reason": "Website không truy cập được"
      }
    ],
    "summary": {
      "qualified_count": 42,
      "dropped_count": 18,
      "total_leads": 60
    }
  }
}
```

---

## 4. Debug

### `GET /api/jobs/:job_id/debug`

Danh sách các file dữ liệu trung gian có thể xem/tải của job.

**Response `200`:**
```json
{
  "work_dir": "Database (MySQL)",
  "files": [
    {
      "step": 1,
      "step_name": "Danh sách từ khoá tìm kiếm",
      "filename": "step1_queries.txt",
      "type": "text",
      "rows": 12,
      "size_human": "450 B",
      "download_url": "/api/jobs/{job_id}/debug/download/step1_queries.txt"
    },
    {
      "step": 2,
      "step_name": "Kết quả cào thô Google Maps",
      "filename": "step2_raw_summary.txt",
      "type": "text",
      "rows": 250,
      "size_human": "250 địa điểm",
      "download_url": "/api/jobs/{job_id}/debug/download/step2_raw_summary.txt"
    },
    {
      "step": 3,
      "step_name": "Lọc Heuristic — Ứng viên đại lý",
      "filename": "step3_candidates.json",
      "type": "json",
      "rows": 85,
      "size_human": "42.3 KB",
      "download_url": "/api/jobs/{job_id}/debug/download/step3_candidates.json"
    }
  ]
}
```

**Tên file hợp lệ:**
| Filename | Bước | Nội dung |
|---|---|---|
| `step1_queries.txt` | 1 | Danh sách từ khoá đã sinh |
| `step2_raw_summary.txt` | 2 | Tóm tắt số địa điểm cào được |
| `step3_candidates.json` | 3 | Danh sách ứng viên đủ điều kiện |
| `step3_excluded.json` | 3 | Danh sách bị loại bỏ (heuristic) |
| `step4_verdicts.json` | 4 | Kết quả thẩm định website |
| `step4_reverify.json` | 4 | Danh sách cần xác minh lại |
| `step5_final_leads.json` | 5 | Kết quả leads cuối cùng (qualified + dropped) |

---

### `GET /api/jobs/:job_id/debug/view/:filename`

Xem nội dung dữ liệu trung gian trả về JSON (để FE hiển thị modal/table).

**Response `200` — type text:**
```json
{
  "type": "text",
  "filename": "step1_queries.txt",
  "content": "đại lý vé máy bay tại Hà Nội\ntravel agency Vietnam\n..."
}
```

**Response `200` — type json:**
```json
{
  "type": "json",
  "filename": "step3_candidates.json",
  "data": [ { ... }, { ... } ]
}
```

---

### `GET /api/jobs/:job_id/debug/download/:filename`

Tải trực tiếp file dữ liệu trung gian (binary stream).

| Filename | Content-Type |
|---|---|
| `*.txt` | `text/plain` |
| `*.json` | `application/json` |

---

## 5. Files

> File output được lưu tại thư mục `output/` trên server. Chỉ tồn tại file `.json` (raw leads data), tự động convert sang `.xlsx` khi tải về.

### `GET /api/files`

Danh sách tất cả file output trên disk.

**Response `200`:**
```json
{
  "files": [
    {
      "filename": "vietnam_leads_20240921_130005.json",
      "is_json": true,
      "excel_virtual_name": "vietnam_leads_20240921_130005.xlsx",
      "size_bytes": 45320,
      "size_human": "44.3 KB",
      "modified_at": "21/09/2024 13:15:23",
      "download_url": "/api/files/vietnam_leads_20240921_130005.json/download",
      "raw_url": "/api/files/vietnam_leads_20240921_130005.json/raw"
    }
  ]
}
```

---

### `GET /api/files/:filename/download`

Tải file dưới dạng Excel (`.xlsx`). Nếu trên disk là `.json`, tự động convert.

**Response `200`:** Binary stream — file `.xlsx`

---

### `GET /api/files/:filename/raw`

Xem raw JSON content của file (chỉ dành cho `.json`).

**Response `200`:** `application/json` — toàn bộ dữ liệu leads thô.

---

### `DELETE /api/files/:filename`

Xoá file khỏi disk.

**Response `200`:**
```json
{ "status": "success", "message": "Da xoa file vietnam_leads_xxx.json" }
```

**Response `404`:**
```json
{ "detail": "File khong ton tai" }
```

---

## 6. Luồng tích hợp FE

### Tạo job và theo dõi tiến độ (Polling)

```
1. POST /api/jobs          → nhận job_id
2. Polling mỗi 2-3 giây:
   GET /api/jobs/{job_id}  → đọc percent, stage_name, message, logs
3. Khi status = "completed":
   - Hiển thị result.qualified_count, dropped_count
   - Cho phép tải Excel: GET /api/jobs/{job_id}/excel
4. Khi status = "failed":
   - Hiển thị job.error
```

### Xem chi tiết 5 bước (sau khi hoàn thành)

```
GET /api/jobs/{job_id}/steps
→ Dùng step1/step2/step3/step4/step5 để render từng Tab
```

### Gợi ý tần suất polling

| Trạng thái job | Tần suất poll |
|---|---|
| `pending` | mỗi 3 giây |
| `running` | mỗi 2 giây |
| `completed` / `failed` / `cancelled` | Dừng polling |

> 💡 **Lưu ý:** API không có WebSocket/SSE. FE dùng polling đơn giản là đủ.
