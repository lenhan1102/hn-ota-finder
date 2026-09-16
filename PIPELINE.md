# Pipeline Tìm OTA / Đại Lý Vé Máy Bay

## Input

| Tham số | Mô tả | Mặc định |
|---|---|---|
| `country` | Tên quốc gia | `vietnam` |
| `custom_keywords` | Từ khóa tùy chỉnh (tuỳ chọn) | _(tự sinh theo quốc gia)_ |
| `lang` | Ngôn ngữ tìm kiếm | `en` |
| `depth` | Độ sâu cuộn trang Google Maps | `5` |
| `concurrency` | Số browser Playwright song song | `1` |
| `max_sites` | Giới hạn website thẩm định | `0` (toàn bộ) |

---

## 5 Bước Xử Lý

### Bước 1 — Sinh danh sách từ khóa
- **File**: `src/queries.py`
- **Input**: tên quốc gia hoặc từ khóa tùy chỉnh
- **Output**: `queries.txt`
- Nếu có config sẵn → dùng danh sách từ khóa theo quốc gia  
- Nếu không → sinh mặc định: `"travel agency in {country}"`, `"air ticket in {country}"`...

---

### Bước 2 — Cào Google Maps
- **Tool**: binary `google-maps-scraper` (Go + Playwright)
- **Input**: `queries.txt`
- **Output**: `raw_results.csv`
- Tự động cuộn trang Google Maps, thu thập: tên, địa chỉ, website, SĐT, email

---

### Bước 3 — Lọc rác & chấm điểm Heuristic
- **File**: `src/classify/pipeline.py`
- **Input**: `raw_results.csv`
- **Output**: `combined_candidates.csv`
- Loại bỏ: hãng bay thuần, tour thuần, SIM/visa, doanh nghiệp không liên quan

---

### Bước 4 — Thẩm định website (Playwright)
- **File**: `src/ndc/auto_verifier.py`
- **Input**: `combined_candidates.csv`
- **Output**: `verdicts.csv` + `reverify.json`
- Mở từng website, kiểm tra:
  - Site còn sống không?
  - Có form tìm chuyến bay (origin / destination / date / search button)?
  - Có mã IATA?
  - Có iframe booking (Skyscanner, Traveloka, Amadeus...)?
- Nếu có API Key → gọi GPT-4o-mini hoặc Gemini để phân loại thêm

---

### Bước 5 — Phân Tier & Xuất Excel
- **File**: `src/ndc/ndc_tiering.py`
- **Input**: `verdicts.csv` + `reverify.json` + `combined_candidates.csv`
- **Output**: `output/{country}_ndc_leads_{timestamp}.xlsx`

---

## Output

File Excel gồm 2 sheet:

| Sheet | Nội dung |
|---|---|
| **Qualified leads** | Đại lý đủ điều kiện, có bán vé máy bay |
| **Dropped** | Đơn vị bị loại + lý do |

---

## Luồng file

```
queries.txt
    ↓ Bước 2: Google Maps Scraper
raw_results.csv
    ↓ Bước 3: Lọc Pandas + Heuristic
combined_candidates.csv
    ↓ Bước 4: Playwright probe từng site
verdicts.csv + reverify.json
    ↓ Bước 5: Tiering + Excel
{country}_ndc_leads_YYYYMMDD_HHMMSS.xlsx
```
