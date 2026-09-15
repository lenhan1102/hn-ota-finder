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
    concurrency: int = 4,
    output_dir: str = "/app/output",
    data_dir: str = "/app/data",
    scraper_bin: str = "/usr/bin/google-maps-scraper",
    max_sites: int = 0,
    market_type: str = "auto",
    skip_scrape: bool = False,
    progress_callback=None,
) -> dict:
    def update_progress(stage: int, stage_name: str, percent: int, message: str):
        print(f"[{stage}/5] ({percent}%) {stage_name}: {message}")
        if progress_callback:
            try:
                progress_callback(stage, stage_name, percent, message)
            except Exception as e:
                print(f"    [WARN] Callback error: {e}")

    country_key = country.lower().strip() if country else "custom"
    task_name = country_key if country_key != "custom" else (sanitize_filename(custom_keywords[0]) if custom_keywords else "custom")
    
    # Tao thu muc
    work_dir = Path(data_dir) / f"{task_name}_{int(time.time())}"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    queries_file = work_dir / "queries.txt"
    raw_csv = work_dir / "raw_results.csv"
    pipeline_dir = work_dir / "pipeline_results"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    candidates_csv = pipeline_dir / "combined_candidates.csv"
    verdicts_csv = work_dir / "verdicts.csv"
    reverify_json = work_dir / "reverify.json"
    
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    final_excel = out_dir / f"{task_name}_ndc_leads_{timestamp_str}.xlsx"

    # -------------------------------------------------------------------------
    # BƯỚC 1: SINH DANH SÁCH QUERIES
    # -------------------------------------------------------------------------
    update_progress(1, "Sinh danh sach tu khoa", 10, "Dang tong hop tu khoa tim kiem...")
    queries = []
    if custom_keywords:
        for kw in custom_keywords:
            kw_clean = kw.strip()
            if kw_clean and kw_clean not in queries:
                queries.append(kw_clean)
        print(f"    Su dung {len(queries)} tu khoa tuy chinh do nguoi dung nhap.")

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

    queries_file.write_text("\n".join(queries) + "\n", encoding="utf-8")
    update_progress(1, "Sinh danh sach tu khoa", 20, f"Da sinh xong {len(queries)} queries.")

    # -------------------------------------------------------------------------
    # BƯỚC 2: CÀO DỮ LIỆU GOOGLE MAPS
    # -------------------------------------------------------------------------
    update_progress(2, "Cao du lieu Google Maps", 25, f"Dang khoi dong {concurrency} trinh duyet Playwright...")
    if skip_scrape and raw_csv.exists() and raw_csv.stat().st_size > 0:
        print(f"    Bo qua cao vi da co {raw_csv}.")
    else:
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

        scraper_cmd = [
            scraper_executable,
            "-input", str(queries_file),
            "-results", str(raw_csv),
            "-lang", lang,
            "-depth", str(depth),
            "-c", str(concurrency),
            "-exit-on-inactivity", "3m",
            "-email",
        ]
        print("    Executing:", " ".join(scraper_cmd))
        t0 = time.time()
        subprocess.run(scraper_cmd, check=True)
        print(f"    Cao xong trong {int(time.time() - t0)} giay.")

    if not raw_csv.exists() or raw_csv.stat().st_size == 0:
        raise RuntimeError(f"File {raw_csv} rong hoac khong ton tai sau khi cao.")
    update_progress(2, "Cao du lieu Google Maps", 50, "Cao thô hoan tat, bat dau loc rac.")

    # -------------------------------------------------------------------------
    # BƯỚC 3: LỌC RÁC SƠ BỘ & CHẤM ĐIỂM PANDAS
    # -------------------------------------------------------------------------
    update_progress(3, "Loc rac so bo & Heuristic", 55, "Dang loai hang bay, tour thuan, SIM visa...")
    run_pipeline(str(raw_csv), country_key, str(pipeline_dir))
    if not candidates_csv.exists():
        raise RuntimeError(f"Khong tim thay {candidates_csv} sau khi loc.")
    update_progress(3, "Loc rac so bo & Heuristic", 65, "Loc rac thanh cong, da co danh sach ung vien.")

    # -------------------------------------------------------------------------
    # BƯỚC 4: THẨM ĐỊNH WEBSITE THỰC TẾ
    # -------------------------------------------------------------------------
    update_progress(4, "Tham dinh website", 70, "Dang mo Chromium kiem tra form ve va IATA...")
    v_count, rv_count = run_auto_verification(
        candidates_csv=candidates_csv,
        output_verdicts_csv=verdicts_csv,
        output_reverify_json=reverify_json,
        locale="vi-VN" if country_key == "vietnam" else "en-US",
        max_sites=max_sites,
    )
    update_progress(4, "Tham dinh website", 85, f"Da tham dinh {v_count} websites ung vien.")

    # -------------------------------------------------------------------------
    # BƯỚC 5: PHÂN TIER & XUẤT EXCEL
    # -------------------------------------------------------------------------
    update_progress(5, "Phan Tier & Xuat Excel", 90, "Dang tong hop va dinh dang file Excel 2 sheet...")
    if market_type == "ota_first" or (market_type == "auto" and country_key in ["indonesia", "philippines"]):
        req_online = True
    else:
        req_online = False

    qual, drop, out = run_tiering(
        verdicts_csv=str(verdicts_csv),
        country=country_key,
        output_xlsx=str(final_excel),
        reverify_json=str(reverify_json),
        contacts_csv=str(candidates_csv),
        require_online_search=req_online,
    )

    update_progress(5, "Hoan tat", 100, f"Xuat file Excel thanh cong: {final_excel.name}")
    print("=" * 80)
    print(f"FILE EXCEL DA SAN SANG: {final_excel}")
    print(f"   • Qualified: {len(qual)} dai ly")
    print(f"   • Dropped:   {len(drop)} don vi")
    print("=" * 80)

    return {
        "country": country_key,
        "task_name": task_name,
        "excel_path": str(final_excel),
        "excel_filename": final_excel.name,
        "excel_size_bytes": final_excel.stat().st_size if final_excel.exists() else 0,
        "qualified_count": len(qual),
        "dropped_count": len(drop),
        "total_leads": len(qual) + len(drop),
        "status": "completed",
    }


def parse_args():
    p = argparse.ArgumentParser(description="NDC Leads Finder All-in-One")
    p.add_argument("--country", default="vietnam", help="Ten nuoc: thailand, vietnam, indonesia, philippines, hongkong...")
    p.add_argument("--keywords", nargs="*", default=None, help="Tu khoa tuy chinh (ngan cach bang dau cach)")
    p.add_argument("--lang", default="en", help="Ngon ngu cao Google Maps (mac dinh: en)")
    p.add_argument("--depth", type=int, default=10, help="Do sau cuon trang (mac dinh: 10)")
    p.add_argument("--concurrency", "-c", type=int, default=4, help="So luong trinh duyet chay song song (mac dinh: 4)")
    p.add_argument("--output-dir", default="/app/output", help="Thu muc xuat ket qua Excel (mac dinh: /app/output)")
    p.add_argument("--data-dir", default="/app/data", help="Thu muc chua du lieu trung gian (mac dinh: /app/data)")
    p.add_argument("--scraper-bin", default="/usr/bin/google-maps-scraper", help="Duong dan binary google-maps-scraper")
    p.add_argument("--max-sites", type=int, default=0, help="Gioi han so site tham dinh (0 = tat ca, >0 de test nhanh)")
    p.add_argument("--skip-scrape", action="store_true", help="Bo qua buoc cao neu da co raw_results.csv")
    p.add_argument("--market-type", choices=["auto", "ota_first", "consolidator"], default="auto",
                   help="Chuan thi truong: ota_first hoac consolidator")
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
    )


if __name__ == "__main__":
    main()
