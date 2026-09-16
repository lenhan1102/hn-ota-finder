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

    def update_progress(stage: int, stage_name: str, percent: int, message: str):
        print(f"[{stage}/5] ({percent}%) {stage_name}: {message}")
        if progress_callback:
            try:
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
    # BƯỚC 1: SINH DANH SÁCH QUERIES
    # -------------------------------------------------------------------------
    update_progress(1, "Sinh danh sach tu khoa", 10, "Dang tong hop tu khoa tim kiem...")
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

        print(f"    Su dung {len(queries)} tu khoa sau khi chuan hoa dia danh: {queries}")

    if not queries:
        if country_key in COUNTRY_CONFIGS:
            queries = build_queries(country_key)
            print(f"    Load {len(queries)} tu khoa co san cho quoc gia: {country_key}.")
        else:
            queries = [
                f"travel agency in {country_key}",
                f"online travel agency in {country_key}",
                f"airline ticket agency in {country_key}",
                f"air ticket in {country_key}",
                f"tour operator in {country_key}",
                f"flight booking in {country_key}",
            ]
            print(f"    Chua co config cho {country_key}, su dung {len(queries)} tu khoa mac dinh.")

    update_progress(1, "Sinh danh sach tu khoa", 20, f"Da sinh xong {len(queries)} queries: {queries[:3]}")

    # -------------------------------------------------------------------------
    # BƯỚC 2: CÀO DỮ LIỆU GOOGLE MAPS (IN-MEMORY QUA TEMPFILE)
    # -------------------------------------------------------------------------
    update_progress(2, "Cao du lieu Google Maps", 25, f"Dang khoi dong {concurrency} trinh duyet (Headless={headless})...")
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
        user_home = os.path.expanduser("~")
        scraper_env["HOME"] = user_home
        scraper_env["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(user_home, ".cache", "ms-playwright")
        scraper_res = subprocess.run(scraper_cmd, capture_output=True, text=True, env=scraper_env)
        print(f"    Cao xong trong {int(time.time() - t0)} giay.")

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
            print(f"    Doc thanh cong {len(raw_places)} dia diem tu scraper vao RAM.")

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
    if raw_count == 0:
        msg = (
            "Google Maps khong tra ve ket qua nao cho tu khoa nay. "
            "Goi y: Dung tu khoa cu the hon, vi du: "
            "'dai ly ve may bay Ha Noi', 'travel agency Hanoi', "
            "'phong ve may bay quan 1', 'air ticket Ho Chi Minh'. "
            "Tranh dung ten dia danh chung chung nhu 'Viet Nam' hoac 'Ha Noi'."
        )
        update_progress(2, "Cao du lieu Google Maps", 50, f"[WARN] {msg}")
        update_progress(5, "Hoan tat", 100, f"Khong co ket qua. {msg}")
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
            "intermediate": {"queries": queries, "raw_count": 0, "candidates_count": 0},
            "warning": msg,
        }

    print(f"    [BƯỚC 2 KẾT QUẢ] Google Maps cào được {raw_count} doanh nghiệp thô (In-Memory).")
    update_progress(2, "Cao du lieu Google Maps", 50, f"Cao thô hoan tat: {raw_count} doanh nghiep. Bat dau loc rac...")

    # -------------------------------------------------------------------------
    # BƯỚC 3: LỌC RÁC SƠ BỘ & CHẤM ĐIỂM HEURISTIC (THUẦN IN-MEMORY)
    # -------------------------------------------------------------------------
    update_progress(3, "Loc rac so bo & Heuristic", 55, "Dang loai hang bay, tour thuan, SIM visa...")
    candidates = run_pipeline(raw_places, country=country_key, output_dir=None)
    cand_count = len(candidates)
    print(f"    [BƯỚC 3 KẾT QUẢ] Sau lọc Heuristic còn lại {cand_count} ứng viên đủ điều kiện thẩm định.")

    if cand_count == 0:
        msg = f"0/{raw_count} doanh nghiep vuot qua buoc loc Heuristic."
        print(f"    [WARN] {msg}")
        update_progress(3, "Loc rac so bo & Heuristic", 65, msg)
        update_progress(5, "Hoan tat", 100, "Khong co ung vien nao vuot qua loc Heuristic.")
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
            "intermediate": {"queries": queries, "raw_count": raw_count, "candidates_count": 0},
        }

    update_progress(3, "Loc rac so bo & Heuristic", 65, f"Loc rac xong: giu lai {cand_count} ung vien sang buoc tham dinh web.")

    # -------------------------------------------------------------------------
    # BƯỚC 4: THẨM ĐỊNH WEBSITE THỰC TẾ (THUẦN IN-MEMORY)
    # -------------------------------------------------------------------------
    update_progress(4, "Tham dinh website", 70, f"Dang mo Chromium (Headless={headless}) kiem tra form ve va IATA cho {cand_count} web...")
    verdicts, reverify_records = run_auto_verification(
        candidates_data=candidates,
        locale="vi-VN" if country_key == "vietnam" else "en-US",
        max_sites=max_sites,
        headless=headless,
    )
    v_count = len(verdicts)
    update_progress(4, "Tham dinh website", 85, f"Da tham dinh xong {v_count} websites ung vien.")

    # -------------------------------------------------------------------------
    # BƯỚC 5: PHÂN TIER & XUẤT JSON KẾT QUẢ DUY NHẤT (KHÔNG TẠO EXCEL TĨNH)
    # -------------------------------------------------------------------------
    update_progress(5, "Phan Tier & Xuat JSON", 90, "Dang tong hop phan Tier va tao JSON leads...")
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

    update_progress(5, "Hoan tat", 100, f"Hoan tat phan tier! Da tao JSON leads ({len(qual)} qualified, {len(drop)} dropped)")
    print("=" * 80)
    print(f"JSON LEADS SAN SANG TAI: {final_json}")
    print(f"   • Qualified: {len(qual)} dai ly")
    print(f"   • Dropped:   {len(drop)} don vi")
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
            "candidates_count": cand_count,
            "candidates": candidates[:100],
            "verdicts": verdicts[:100],
            "reverify": reverify_records[:100],
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
