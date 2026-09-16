#!/usr/bin/env python3
# orchestrator.py - Kich ban dieu phoi toan bo quy trinh tim kiem NDC Leads:
# 1. Sinh queries theo quoc gia / tu khoa (queries.py)
# 2. Chay cao Google Maps (google-maps-scraper) -> raw_results.csv
# 3. Loc sach du lieu rac & cham diem so bo (classify.pipeline) -> combined_candidates.csv
# 4. Tham dinh website (ndc.auto_verifier) -> verdicts.csv, reverify.json
# 5. Phan Tier NDC & Xuat file Excel chuan hoa (ndc.ndc_tiering) -> output/{country}_ndc_leads.xlsx

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Add src to sys.path
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from queries import COUNTRY_CONFIGS, build_queries
from classify.pipeline import run_pipeline
from ndc.auto_verifier import run_auto_verification
from ndc.ndc_tiering import run_tiering


def print_banner():
    print("=" * 80)
    print("       GOOGLE MAPS SCRAPER & NDC LEADS FINDER (ALL-IN-ONE)")
    print("=" * 80)


def sanitize_filename(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip().lower())
    return s[:50] or "custom"


def execute_pipeline(
    country: str = "vietnam",
    custom_keywords: list[str] = None,
    lang: str = "en",
    depth: int = 10,
    concurrency: int = 1,
    output_dir: str = "/app/output",
    data_dir: str = None,
    scraper_bin: str = "/usr/bin/google-maps-scraper",
    max_sites: int = 0,
    market_type: str = "auto",
    skip_scrape: bool = False,
    headless: bool = True,
    progress_callback=None,
) -> dict:
    import tempfile
    import json

    def update_progress(stage: int, stage_name: str, percent: int, message: str, inter_data: dict = None):
        print(f"[{stage}/5] ({percent}%) {stage_name}: {message}")
        if progress_callback:
            try:
                import inspect
                sig = inspect.signature(progress_callback)
                if 'inter_data' in sig.parameters:
                    progress_callback(stage, stage_name, percent, message, inter_data=inter_data)
                else:
                    progress_callback(stage, stage_name, percent, message)
            except Exception as e:
                print(f"    [WARN] Callback error: {e}")

    country_key = country.lower().strip() if country else "custom"
    task_name = country_key if country_key != "custom" else (sanitize_filename(custom_keywords[0]) if custom_keywords else "custom")
    
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    final_json = out_dir / f"{task_name}_leads_{timestamp_str}.json"
    excel_virtual_name = f"{task_name}_ndc_leads_{timestamp_str}.xlsx"

    # -------------------------------------------------------------------------
    # BƯỚC 1: SINH DANH SÁCH TỪ KHOÁ (QUERIES)
    # -------------------------------------------------------------------------
    update_progress(1, "Sinh danh sách từ khoá", 10, "Đang tổng hợp từ khoá tìm kiếm...")
    queries = []
    if custom_keywords:
        country_cfg = COUNTRY_CONFIGS.get(country_key, None)
        country_label = country_cfg.country_label if country_cfg else country_key.title()

        for kw in custom_keywords:
            kw_clean = kw.strip()
            if not kw_clean:
                continue

            kw_lower = kw_clean.lower()
            has_location = any(
                loc in kw_lower for loc in [
                    country_key,
                    country_label.lower(),
                    "việt nam", "viet nam", "hà nội", "hanoi", "sài gòn", "saigon",
                    "hồ chí minh", "ho chi minh", "đà nẵng", "danang", "bangkok",
                    "jakarta", "manila", "hong kong", "hongkong", "tại", "in", "ở"
                ]
            )

            # Nếu từ khóa chỉ là cụm chung chung không kèm địa danh (ví dụ 'phòng vé máy bay'),
            # tự động gắn thêm địa danh/quốc gia để Google Maps trả về danh sách Feed kết quả thay vì điều hướng đường đi
            if not has_location:
                if lang == "vi" or any(c in kw_lower for c in "áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ"):
                    scoped_kw = f"{kw_clean} tại {country_label}"
                else:
                    scoped_kw = f"{kw_clean} in {country_label}"
            else:
                scoped_kw = kw_clean

            if scoped_kw not in queries:
                queries.append(scoped_kw)

        print(f"    Sử dụng {len(queries)} từ khoá sau khi chuẩn hoá địa danh: {queries}")

    if not queries:
        if country_key in COUNTRY_CONFIGS:
            queries = build_queries(country_key)
            print(f"    Tải {len(queries)} từ khoá có sẵn cho quốc gia: {country_key}.")
        else:
            queries = [
                f"travel agency in {country_key}",
                f"online travel agency in {country_key}",
                f"airline ticket agency in {country_key}",
                f"air ticket in {country_key}",
                f"tour operator in {country_key}",
                f"flight booking in {country_key}",
            ]
            print(f"    Chưa có cấu hình sẵn cho {country_key}, sử dụng {len(queries)} từ khoá mặc định.")

    update_progress(1, "Sinh danh sách từ khoá", 20, f"Đã sinh xong {len(queries)} từ khoá: {queries}", inter_data={"queries": queries})

    # -------------------------------------------------------------------------
    # BƯỚC 2: CÀO DỮ LIỆU GOOGLE MAPS (IN-MEMORY QUA TEMPFILE)
    # -------------------------------------------------------------------------
    update_progress(2, "Cào dữ liệu Google Maps", 25, f"Đang khởi động {concurrency} trình duyệt (Chạy ẩn={headless})...")
    candidates_bin = [
        scraper_bin,
        str(SRC_DIR.parent / "bin" / "google-maps-scraper"),
        str(SRC_DIR.parent / "bin" / "google-maps-scraper.exe"),
        str(SRC_DIR.parent.parent / "google-maps-scraper" / "google-maps-scraper"),
        "/usr/bin/google-maps-scraper",
        "/usr/local/bin/google-maps-scraper",
    ]
    scraper_executable = shutil.which(scraper_bin) or shutil.which("google-maps-scraper")
    if not scraper_executable or not Path(scraper_executable).exists():
        for p in candidates_bin:
            if p and Path(p).exists():
                scraper_executable = p
                break
    if not scraper_executable or not Path(scraper_executable).exists():
        raise FileNotFoundError(f"Khong tim thay binary google-maps-scraper tai {scraper_bin}")

    # Tạo temp file cho queries và kết quả scraper dạng JSON
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as qf:
        qf.write("\n".join(queries) + "\n")
        temp_queries_file = qf.name

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as rf:
        temp_results_json = rf.name

    raw_places = []
    try:
        scraper_cmd = [
            scraper_executable,
            "-input", temp_queries_file,
            "-results", temp_results_json,
            "-json",
            "-lang", lang,
            "-depth", str(depth),
            "-c", str(concurrency),
            "-browser-pool-size", str(concurrency),
            "-pages-per-browser", "1",
            "-exit-on-inactivity", "3m",
            "-email",
        ]
        if not headless:
            scraper_cmd.append("-debug")

        print("    Executing:", " ".join(scraper_cmd))
        t0 = time.time()
        scraper_env = os.environ.copy()
        # Loại bỏ các biến IPC của PM2/Node để tránh làm crash tiến trình Node.js ngầm của playwright-go
        for k in list(scraper_env.keys()):
            if k.startswith("NODE_"):
                scraper_env.pop(k, None)
        user_home = os.path.expanduser("~")
        scraper_env["HOME"] = user_home
        scraper_env["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(user_home, ".cache", "ms-playwright")
        
        process = subprocess.Popen(scraper_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=scraper_env)
        
        while True:
            if progress_callback:
                try:
                    progress_callback(-1, "check_cancel", 0, "")
                except Exception as e:
                    process.terminate()
                    process.wait(timeout=5)
                    raise
            
            if process.poll() is not None:
                break
            time.sleep(1)
            
        stdout, stderr = process.communicate()
        class SubprocessResult:
            def __init__(self, returncode, stdout, stderr):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr
        scraper_res = SubprocessResult(process.returncode, stdout, stderr)
        
        print(f"    Cào dữ liệu hoàn tất trong {int(time.time() - t0)} giây.")

        if scraper_res.returncode != 0:
            err_msg = (scraper_res.stderr or scraper_res.stdout or "").strip()
            print(f"    [CẢNH BÁO] Scraper kết thúc với mã {scraper_res.returncode}: {err_msg[-400:] if err_msg else ''}")

        # Đọc dữ liệu JSON vào RAM ngay lập tức (hỗ trợ cả JSON Array và JSON Lines)
        if Path(temp_results_json).exists() and Path(temp_results_json).stat().st_size > 0:
            with open(temp_results_json, "r", encoding="utf-8", errors="replace") as f:
                content = f.read().strip()
                if content:
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, list):
                            raw_places = parsed
                        elif isinstance(parsed, dict):
                            raw_places = [parsed]
                    except json.JSONDecodeError:
                        # Fallback cho JSON Lines (mỗi dòng là một JSON object)
                        raw_places = []
                        for line in content.splitlines():
                            line_s = line.strip()
                            if line_s:
                                try:
                                    raw_places.append(json.loads(line_s))
                                except Exception:
                                    pass
            print(f"    Đọc thành công {len(raw_places)} địa điểm từ Google Maps vào bộ nhớ (In-Memory).")

        if not raw_places and scraper_res.returncode != 0:
            raise RuntimeError(
                f"Google Maps Scraper không tìm thấy kết quả hoặc bị lỗi khi cào các từ khóa: {queries}. "
                "Vui lòng thử từ khóa cụ thể hơn kèm địa danh (ví dụ: 'phòng vé máy bay tại Hà Nội', 'đại lý vé máy bay Việt Nam')."
            )
    finally:
        # Xoá ngay file tạm sau khi đã nạp dữ liệu vào RAM để tránh đầy đĩa server
        try:
            os.unlink(temp_queries_file)
        except Exception:
            pass
        try:
            os.unlink(temp_results_json)
        except Exception:
            pass

    raw_count = len(raw_places) if isinstance(raw_places, list) else 0
    
    # Lưu danh sách raw_places rút gọn vào intermediate để hiển thị trên UI
    simplified_raw = []
    if isinstance(raw_places, list):
        for p in raw_places:
            simplified_raw.append({
                "title": p.get("title", "N/A"),
                "category": p.get("category", ""),
                "address": p.get("address", ""),
                "website": p.get("web_site") or p.get("website", ""),
                "phone": p.get("phone", "")
            })
    
    if raw_count == 0:
        msg = (
            "Google Maps không trả về kết quả nào cho từ khoá này. "
            "Gợi ý: Dùng từ khoá cụ thể hơn kèm địa danh, ví dụ: "
            "'đại lý vé máy bay Hà Nội', 'travel agency Hanoi', "
            "'phòng vé máy bay quận 1', 'air ticket Ho Chi Minh'. "
            "Tránh dùng tên địa danh chung chung như 'Việt Nam' hoặc 'Hà Nội'."
        )
        update_progress(2, "Cào dữ liệu Google Maps", 50, f"[CẢNH BÁO] {msg}")
        update_progress(5, "Hoàn tất", 100, f"Không có kết quả. {msg}")
        return {
            "country": country_key,
            "task_name": task_name,
            "json_path": "",
            "json_filename": "",
            "excel_filename": "",
            "json_size_bytes": 0,
            "qualified_count": 0,
            "dropped_count": 0,
            "total_leads": 0,
            "leads_data": {},
            "intermediate": {"queries": queries, "raw_count": 0, "candidates_count": 0, "excluded_count": 0, "candidates": [], "excluded": []},
            "warning": msg,
        }

    print(f"    [BƯỚC 2 KẾT QUẢ] Google Maps cào được {raw_count} doanh nghiệp thô (In-Memory).")
    update_progress(2, "Cào dữ liệu Google Maps", 50, f"Cào thô hoàn tất: {raw_count} doanh nghiệp. Bắt đầu lọc rác sơ bộ...", inter_data={"raw_count": raw_count, "raw_places": simplified_raw[:500]})

    # -------------------------------------------------------------------------
    # BƯỚC 3: LỌC RÁC SƠ BỘ & CHẤM ĐIỂM HEURISTIC (THUẦN IN-MEMORY)
    # -------------------------------------------------------------------------
    update_progress(3, "Lọc rác sơ bộ & Heuristic", 55, "Đang loại bỏ hãng bay, tour thuần, SIM visa...")
    pipeline_res = run_pipeline(raw_places, country=country_key, output_dir=None, return_excluded=True)
    if isinstance(pipeline_res, tuple):
        candidates, excluded_records = pipeline_res
    else:
        candidates, excluded_records = pipeline_res, []

    cand_count = len(candidates)
    excl_count = len(excluded_records)
    print(f"    [BƯỚC 3 KẾT QUẢ] Sau lọc Heuristic còn lại {cand_count} ứng viên đủ điều kiện thẩm định (Đã lọc bỏ: {excl_count}).")
    update_progress(3, "Lọc rác sơ bộ & Heuristic", 65, f"Xong lọc rác. Còn {cand_count} ứng viên.", inter_data={"candidates_count": cand_count, "excluded_count": excl_count, "candidates": candidates, "excluded": excluded_records[:200]})

    if cand_count == 0:
        msg = f"0/{raw_count} doanh nghiệp vượt qua bước lọc Heuristic."
        print(f"    [CẢNH BÁO] {msg}")
        update_progress(3, "Lọc rác sơ bộ & Heuristic", 65, msg)
        update_progress(5, "Hoàn tất", 100, "Không có ứng viên nào vượt qua bước lọc Heuristic.")
        return {
            "country": country_key,
            "task_name": task_name,
            "json_path": "",
            "json_filename": "",
            "excel_filename": "",
            "json_size_bytes": 0,
            "qualified_count": 0,
            "dropped_count": 0,
            "total_leads": 0,
            "leads_data": {},
            "intermediate": {
                "queries": queries,
                "raw_count": raw_count,
                "raw_places": simplified_raw[:500], # Giới hạn 500 để tránh lag UI
                "candidates_count": 0,
                "excluded_count": excl_count,
                "candidates": [],
                "excluded": excluded_records[:200],
            },
        }

    update_progress(3, "Lọc rác sơ bộ & Heuristic", 65, f"Lọc rác xong: giữ lại {cand_count} ứng viên sang bước thẩm định website (Đã lọc bỏ {excl_count}).")

    # -------------------------------------------------------------------------
    # BƯỚC 4: THẨM ĐỊNH WEBSITE THỰC TẾ (THUẦN IN-MEMORY)
    # -------------------------------------------------------------------------
    update_progress(4, "Thẩm định website", 70, f"Đang mở Chromium (Chạy ẩn={headless}) kiểm tra form vé và IATA cho {cand_count} website...")
    verdicts, reverify_records = run_auto_verification(
        candidates_data=candidates,
        locale="vi-VN" if country_key == "vietnam" else "en-US",
        max_sites=max_sites,
        headless=headless,
        progress_callback=progress_callback,
    )
    v_count = len(verdicts)
    update_progress(4, "Thẩm định website", 85, f"Đã thẩm định xong {v_count} website ứng viên.", inter_data={"verdicts": verdicts, "reverify": reverify_records})

    # -------------------------------------------------------------------------
    # BƯỚC 5: PHÂN TIER & XUẤT JSON KẾT QUẢ DUY NHẤT (KHÔNG TẠO EXCEL TĨNH)
    # -------------------------------------------------------------------------
    update_progress(5, "Phân Tier & Xuất kết quả", 90, "Đang tổng hợp phân Tier và tạo danh sách leads...")
    if market_type == "ota_first" or (market_type == "auto" and country_key in ["indonesia", "philippines"]):
        req_online = True
    else:
        req_online = False

    qual, drop, leads_data = run_tiering(
        verdicts_data=verdicts,
        country=country_key,
        reverify_data=reverify_records,
        contacts_data=candidates,
        require_online_search=req_online,
        output_json=str(final_json),
        output_xlsx=None,  # Không lưu Excel tĩnh trên đĩa
    )

    update_progress(5, "Hoàn tất", 100, f"Hoàn tất phân Tier! Đã tạo danh sách ({len(qual)} đại lý đạt chuẩn, {len(drop)} đơn vị bị loại)")
    print("=" * 80)
    print(f"DANH SÁCH LEADS ĐÃ SẴN SÀNG TẠI: {final_json}")
    print(f"   • Đạt chuẩn (Qualified): {len(qual)} đại lý")
    print(f"   • Bị loại (Dropped):     {len(drop)} đơn vị")
    print("=" * 80)

    return {
        "country": country_key,
        "task_name": task_name,
        "json_path": str(final_json),
        "json_filename": final_json.name,
        "excel_filename": excel_virtual_name,
        "json_size_bytes": final_json.stat().st_size if final_json.exists() else 0,
        "qualified_count": len(qual),
        "dropped_count": len(drop),
        "total_leads": len(qual) + len(drop),
        "leads_data": leads_data,
        "intermediate": {
            "queries": queries,
            "raw_count": raw_count,
            "raw_places": simplified_raw,
            "candidates_count": len(candidates),
            "excluded_count": excl_count,
            "candidates": candidates[:200],
            "excluded": excluded_records[:200],
            "verdicts": verdicts[:200],
            "reverify": reverify_records[:200],
        },
        "status": "completed",
    }


def parse_args():
    p = argparse.ArgumentParser(description="NDC Leads Finder All-in-One")
    p.add_argument("--country", default="vietnam", help="Ten nuoc: thailand, vietnam, indonesia, philippines, hongkong...")
    p.add_argument("--keywords", nargs="*", default=None, help="Tu khoa tuy chinh (ngan cach bang dau cach)")
    p.add_argument("--lang", default="en", help="Ngon ngu cao Google Maps (mac dinh: en)")
    p.add_argument("--depth", type=int, default=10, help="Do sau cuon trang (mac dinh: 10)")
    p.add_argument("--concurrency", "-c", type=int, default=1, help="So luong trinh duyet chay song song (mac dinh: 1)")
    p.add_argument("--output-dir", default="/app/output", help="Thu muc xuat ket qua Excel (mac dinh: /app/output)")
    p.add_argument("--data-dir", default="/app/data", help="Thu muc chua du lieu trung gian (mac dinh: /app/data)")
    p.add_argument("--scraper-bin", default="/usr/bin/google-maps-scraper", help="Duong dan binary google-maps-scraper")
    p.add_argument("--max-sites", type=int, default=0, help="Gioi han so site tham dinh (0 = tat ca, >0 de test nhanh)")
    p.add_argument("--skip-scrape", action="store_true", help="Bo qua buoc cao neu da co raw_results.csv")
    p.add_argument("--market-type", choices=["auto", "ota_first", "consolidator"], default="auto",
                   help="Chuan thi truong: ota_first hoac consolidator")
    p.add_argument("--headful", action="store_true", default=False,
                   help="Mo cua so trinh duyet truc quan (mac dinh: False - chay ngam headless)")
    return p.parse_args()


def main():
    print_banner()
    args = parse_args()
    execute_pipeline(
        country=args.country,
        custom_keywords=args.keywords,
        lang=args.lang,
        depth=args.depth,
        concurrency=args.concurrency,
        output_dir=args.output_dir,
        data_dir=args.data_dir,
        scraper_bin=args.scraper_bin,
        max_sites=args.max_sites,
        market_type=args.market_type,
        skip_scrape=args.skip_scrape,
        headless=not args.headful,
    )


if __name__ == "__main__":
    main()
