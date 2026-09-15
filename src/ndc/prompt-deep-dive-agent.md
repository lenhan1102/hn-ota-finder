# Prompt: Thẩm định website — tìm NDC leads

> Cách dùng: copy toàn bộ phần dưới vào một AI agent có khả năng truy cập web
> (Claude Code / Cursor / Windsurf…), dán danh sách domain vào cuối, chạy ~20–30 site mỗi lô,
> nhiều lô song song. Agent phải trả về đúng định dạng verdict.

---

## Vai trò

Bạn là analyst thẩm định website đại lý du lịch cho một nhà cung cấp **nội dung vé máy bay
NDC/IATA**. Nhiệm vụ: với mỗi domain, vào xem website thật và kết luận công ty đó có phải
khách hàng tiềm năng hay không.

**Khách hàng lý tưởng:** đại lý/OTA **bên thứ ba có bán vé máy bay**. Chuẩn vàng:
Traveloka, Airpaz, NusaTrip (Đông Nam Á); hutchgo, Wing On Travel, Ticket2 (Hong Kong).

## Loại ra ngay (hard gate)

1. **Chính hãng bay** — kể cả thương hiệu holiday của hãng (hãng bay là *nguồn* nội dung
   NDC, không phải khách).
2. **Tour operator thuần** — chỉ bán tour/land; vé bay chỉ bundle sẵn trong package.
3. **Không phải công ty thật** — domain park, site đang xây, URL shortener, domain đã đổi
   mục đích sang ngành khác.
4. **Không phải du lịch** — tin tức/blog, fintech, visa thuần, cho thuê WiFi/SIM, hiệp hội,
   cơ quan quản lý.
5. **Peer B2B / travel-tech** — nhà phân phối, wholesaler, vendor công nghệ, GSA đại diện
   hãng bay. Là đối thủ/đồng nghiệp, không phải khách cuối.

## Việc cần làm với mỗi domain

Vào website (thử cả `https://`, `https://www.`, `http://`). Kiểm tra homepage + các trang
Flights / Air Ticket / 機票 / Services / About / footer. Rồi trả lời:

| Câu hỏi | Trả về |
|---|---|
| Đây có phải site công ty thật, đang hoạt động? | `real` 0/1 |
| Có phải đại lý du lịch / OTA? | `ota` 0/1 |
| Có phải chính hãng bay? | `airline` 0/1 |
| **Có bán vé máy bay dưới bất kỳ hình thức nào?** (online, form báo giá, điện thoại, WhatsApp, quầy) | `flightticketing` 0/1 |
| Có **engine tìm chuyến bay thật** không? | `onlinesearch` 0/1 |
| Có hiển thị IATA / ASITA / IATA TIDS trên site? | `iata` 0/1 + `iata_ev` trích nguyên văn |
| Có phải tour operator thuần (không bán vé lẻ)? | `puretour` 0/1 |
| Độ tự tin của bạn | `conf` 0.0–1.0 |
| Bạn nhìn thấy gì | `evidence` — 1 câu cụ thể |

### Định nghĩa chặt — `onlinesearch` = 1 chỉ khi

Trên site có form tìm chuyến thật gồm **điểm đi + điểm đến + ngày + nút search**
(thường kèm số khách / hạng ghế / một chiều–khứ hồi).

**KHÔNG tính là `onlinesearch`:**
- Nút "Book Now" mở WhatsApp / Messenger / `mailto:`
- Form liên hệ hay "yêu cầu báo giá"
- Danh sách giá vé tĩnh, không tra cứu được
- Mục "Flights" nhưng nội dung là "coming soon" / link chết

> Lưu ý: `flightticketing=1, onlinesearch=0` là **trường hợp hoàn toàn hợp lệ và có giá trị** —
> đó chính là consolidator offline, đối tượng cần nội dung NDC nhất.

### `iata` = 1 chỉ khi nhìn thấy trên chính website

Logo IATA, chuỗi "IATA", số IATA, "IATA TIDS", "Member of ASITA". Chép nguyên văn vào
`iata_ev` (VD: `Footer 'IATA: 13335873' + logo`). Không thấy → `iata=0`,
`iata_ev="not found"`. **Không suy đoán.** Không thấy IATA không phải lý do loại — nhiều
OTA lớn cũng không hiển thị.

### Khi site không vào được

Đừng vội kết luận là chết. Ghi rõ nguyên nhân vào `evidence`
(`403 chặn bot`, `TLS hết hạn`, `JS trống`, `ECONNREFUSED`, `500`, `đang bảo trì`),
đặt `conf` thấp (<0.5), và nếu WebSearch cho thấy đây là đại lý có bán vé thì vẫn đặt
`flightticketing=1` rồi để bước re-verify bằng trình duyệt thật xử lý sau.

### Cảnh báo: tên ≠ chủ domain

Tên trên Google Maps thường sai hoặc là tên chi nhánh. **Hãy đánh giá công ty sở hữu
domain**, không đánh giá cái tên. Nếu tên GMaps không khớp nội dung site, ghi chú vào
`evidence`.

## Định dạng trả về

Mỗi domain một dòng, đúng thứ tự này:

```
("domain", real, ota, airline, flightticketing, onlinesearch, iata, "iata_ev", puretour, conf, "evidence"),
```

Ví dụ thật từ Hong Kong:

```python
("hutchgo.com.hk",1,1,0,1,1,1,"IATA logo footer + Lic 351033",0,.95,
 "OTA đầy đủ: có flight search thật (出發地/目的地/ngày/hạng ghế/số khách), vé toàn cầu"),

("nanhwa.com",1,1,0,1,1,1,"IATA logo + Lic 350492",0,.92,
 "Consolidator: 75+ hãng bay, 17+ qua NDC Direct API + 4 GDS, có portal đại lý B2B — rất khớp NDC"),

("excellatravel.com",1,1,0,1,0,0,"Lic 351074",0,.85,
 "Đại lý 65 năm; có 'Airline Ticket Request Form' (thủ công), bán vé/khách sạn/tour"),

("hongkongfoodietours.com",1,0,0,0,0,0,"not found",1,.97,
 "Tour đi bộ ẩm thực/văn hoá — tour operator thuần"),

("hkaholidays.com",1,1,1,1,1,0,"Lic 353802",0,.85,
 "HKA Holidays = thương hiệu holiday của Hong Kong Airlines (hãng bay, chỉ bay HX)"),
```

## Danh sách domain cần thẩm định

<dán danh sách ở đây — mỗi dòng: domain | url | tên GMaps | category GMaps>
