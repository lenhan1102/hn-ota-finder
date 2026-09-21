import io
import json
import math
import os
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

# Setup sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from queries import COUNTRY_CONFIGS
from orchestrator import execute_pipeline
from ndc.ndc_tiering import export_leads_to_excel_buffer
from db.queries import (
    create_search_job,
    update_job_status,
    update_job_progress,
    get_all_search_jobs,
    get_search_job,
    get_job_steps_data_from_db,
    get_job_leads_for_excel_from_db,
)


def sanitize_for_json(obj):
    """
    Đệ quy làm sạch dữ liệu để đảm bảo 100% tuân thủ chuẩn JSON.
    Thay thế mọi float('nan'), float('inf'), -float('inf') bằng None (null trong JSON).
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    return obj


class SafeJSONResponse(JSONResponse):
    """
    JSONResponse an toàn: tự động lọc bỏ mọi giá trị NaN / Infinity
    trước khi serialize bằng json.dumps(allow_nan=False).
    """
    def render(self, content: any) -> bytes:
        return json.dumps(
            sanitize_for_json(content),
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


app = FastAPI(
    title="Google Maps Scraper - NDC Leads & OTA Finder",
    description="Giao dien quan ly va tim kiem dai ly ban ve may bay & OTA",
    version="1.0.0",
    default_response_class=SafeJSONResponse,
)

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# In-memory jobs tracking (dùng làm fast cache song song với DB)
JOBS = {}


class JobCreateRequest(BaseModel):
    country: str = "vietnam"
    custom_keywords: str | None = None
    lang: str = "vi"
    depth: int = 5
    concurrency: int = 1
    max_sites: int = 0
    market_type: str = "auto"
    headless: bool = True


def format_bytes(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def run_job_task(job_id: str, payload: dict):
    job = JOBS.get(job_id)
    if not job:
        return

    job["status"] = "running"
    job["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def on_progress(stage: int, stage_name: str, percent: int, message: str, inter_data: dict = None):
        if job.get("cancelled"):
            raise Exception("Tiến trình đã bị huỷ bởi người dùng.")

        t_str = time.strftime("%H:%M:%S")
        if stage != -1:  # -1 is used for internal cancellation checks without updating UI
            job["stage"] = stage
            job["stage_name"] = stage_name
            job["percent"] = percent
            job["message"] = message
            job["logs"].append(f"[{t_str}] {message}")
            # Giới hạn tối đa 500 dòng logs trong RAM để tránh tràn bộ nhớ
            if len(job["logs"]) > 500:
                job["logs"] = job["logs"][-500:]
            if inter_data:
                if job.get("intermediate") is None:
                    job["intermediate"] = {}
                job["intermediate"].update(inter_data)

    keywords_list = []
    if payload.get("custom_keywords"):
        for line in payload["custom_keywords"].splitlines():
            line_s = line.strip()
            if line_s:
                keywords_list.append(line_s)

    try:
        res = execute_pipeline(
            country=payload.get("country", "vietnam"),
            custom_keywords=keywords_list if keywords_list else None,
            lang=payload.get("lang", "en"),
            depth=payload.get("depth", 5),
            concurrency=payload.get("concurrency", 1),
            output_dir=str(OUTPUT_DIR),
            max_sites=payload.get("max_sites", 0),
            market_type=payload.get("market_type", "auto"),
            headless=payload.get("headless", True),
            progress_callback=on_progress,
            job_id=job_id,
        )
        qualified_count = res.get("qualified_count", 0)
        dropped_count = res.get("dropped_count", 0)
        total_leads = res.get("total_leads", 0)
        excel_filename = res.get("excel_filename", f"{payload.get('country', 'leads')}_{job_id}.xlsx")

        job["status"] = "completed"
        job["percent"] = 100
        job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job["result"] = {
            "qualified_count": qualified_count,
            "dropped_count": dropped_count,
            "total_leads": total_leads,
            "excel_filename": excel_filename,
        }
        # Giải phóng hoàn toàn các mảng lớn khỏi RAM, dữ liệu chi tiết đã nằm bền vững trong DB
        job.pop("intermediate", None)
        job.pop("leads_data", None)
        del res
        import gc
        gc.collect()
    except Exception as e:
        t_err = time.strftime("%H:%M:%S")
        job["status"] = "failed"
        job["error"] = str(e)
        job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job["logs"].append(f"[{t_err}] [ERROR] {e}")
        try:
            update_job_status(job_id, "failed", error_message=str(e))
        except Exception:
            pass


def is_local_env() -> bool:
    if os.getenv("APP_ENV", "").lower() == "production":
        return False
    if Path("/home/tide").exists():
        return False
    return True


@app.get("/", response_class=HTMLResponse)
async def index():
    template = jinja_env.get_template("index.html")
    rendered = template.render(
        countries=sorted(list(COUNTRY_CONFIGS.keys())),
        is_local=is_local_env()
    )
    return HTMLResponse(content=rendered)


@app.get("/api/countries")
async def get_countries():
    return {"countries": sorted(list(COUNTRY_CONFIGS.keys()))}


@app.post("/api/jobs")
async def create_job(req: JobCreateRequest, bg_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    t_now = time.strftime("%H:%M:%S")
    headless_val = req.headless

    keywords_list = []
    if req.custom_keywords:
        for line in req.custom_keywords.splitlines():
            line_s = line.strip()
            if line_s:
                keywords_list.append(line_s)

    # Lưu job vào Database MySQL
    try:
        create_search_job(
            country=req.country,
            custom_keywords=keywords_list if keywords_list else None,
            lang=req.lang,
            depth=req.depth,
            concurrency=req.concurrency,
            max_sites=req.max_sites,
            market_type=req.market_type,
            job_id=job_id,
        )
    except Exception as e:
        print(f"Warn: Khong the tao job trong DB, chay in-memory fallback: {e}")

    job_data = {
        "id": job_id,
        "country": req.country,
        "custom_keywords": req.custom_keywords,
        "lang": req.lang,
        "depth": req.depth,
        "concurrency": req.concurrency,
        "market_type": req.market_type,
        "max_sites": req.max_sites,
        "headless": headless_val,
        "status": "pending",
        "stage": 0,
        "stage_name": "Khởi tạo",
        "percent": 0,
        "message": "Đã đưa vào hàng đợi xử lý...",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "result": None,
        "logs": [f"[{t_now}] Đã tạo yêu cầu tìm kiếm cho quốc gia {req.country}"],
    }
    JOBS[job_id] = job_data
    payload_data = req.model_dump()
    payload_data["headless"] = headless_val
    bg_tasks.add_task(run_job_task, job_id, payload_data)
    return {"job_id": job_id, "status": "pending"}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = JOBS.get(job_id)
    if job:
        if job["status"] in ["completed", "failed", "cancelled"]:
            return {"status": "error", "message": "Job đã kết thúc, không thể huỷ"}
        job["cancelled"] = True
        job["status"] = "cancelled"
        job["message"] = "Đang huỷ tiến trình..."
        job["logs"].append(f"[{time.strftime('%H:%M:%S')}] Người dùng yêu cầu huỷ tiến trình.")

    try:
        update_job_status(job_id, "cancelled", error_message="Người dùng yêu cầu huỷ tiến trình.")
    except Exception as e:
        print(f"Warn: Khong the update job cancel trong DB: {e}")

    return {"status": "success", "message": "Đã gửi yêu cầu huỷ"}


@app.get("/api/jobs")
async def list_jobs():
    """Lấy danh sách jobs, hợp nhất giữa DB và Memory cache."""
    try:
        db_jobs = get_all_search_jobs(limit=50)
    except Exception as e:
        print(f"Warn: Khong the lay jobs tu DB: {e}")
        db_jobs = []

    jobs_map = {j["id"]: j for j in db_jobs}

    for job_id, mem_job in JOBS.items():
        if job_id in jobs_map:
            if mem_job.get("status") in ["running", "pending"]:
                jobs_map[job_id]["status"] = mem_job["status"]
                jobs_map[job_id]["stage"] = mem_job.get("stage", jobs_map[job_id].get("stage", 0))
                jobs_map[job_id]["stage_name"] = mem_job.get("stage_name", jobs_map[job_id].get("stage_name", ""))
                jobs_map[job_id]["percent"] = mem_job.get("percent", jobs_map[job_id].get("percent", 0))
                jobs_map[job_id]["message"] = mem_job.get("message", jobs_map[job_id].get("message", ""))
                jobs_map[job_id]["logs"] = mem_job.get("logs", jobs_map[job_id].get("logs", []))
            elif mem_job.get("result"):
                jobs_map[job_id]["result"] = mem_job["result"]
        else:
            jobs_map[job_id] = mem_job

    sorted_jobs = sorted(
        list(jobs_map.values()),
        key=lambda x: str(x.get("created_at") or ""),
        reverse=True
    )
    return {"jobs": sorted_jobs}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if job:
        return job
    try:
        db_job = get_search_job(job_id)
        if db_job:
            return db_job
    except Exception as e:
        print(f"Warn: Khong the lay job {job_id} tu DB: {e}")
    raise HTTPException(status_code=404, detail="Job không tồn tại")


@app.get("/api/jobs/{job_id}/excel")
async def download_job_excel(job_id: str):
    """Xuất file Excel trực tiếp từ RAM hoặc DB (on-the-fly) cho một Job đã hoàn thành."""
    job = JOBS.get(job_id)
    leads_data = None
    country_name = "leads"
    excel_name = None

    if job:
        country_name = job.get("country", "leads")
        leads_data = job.get("leads_data")
        if not leads_data and job.get("result"):
            leads_data = job["result"].get("leads_data")
        excel_name = (job.get("result") or {}).get("excel_filename")

    # Fallback 1: đọc từ file JSON nếu có json_path
    if not leads_data and job and job.get("result", {}).get("json_path"):
        jp = Path(job["result"]["json_path"])
        if jp.exists():
            try:
                with open(jp, "r", encoding="utf-8") as f:
                    leads_data = json.load(f)
            except Exception:
                pass

    # Fallback 2: Truy vấn từ Database
    if not leads_data:
        try:
            leads_data = get_job_leads_for_excel_from_db(job_id)
            if not job:
                db_job = get_search_job(job_id)
                if db_job:
                    country_name = db_job.get("country", "leads")
                    excel_name = (db_job.get("result") or {}).get("excel_filename")
        except Exception as e:
            print(f"Lỗi truy vấn leads từ DB: {e}")

    if not leads_data:
        raise HTTPException(status_code=400, detail="Chưa có dữ liệu leads cho job này")

    buf = export_leads_to_excel_buffer(leads_data)
    excel_name = excel_name or f"{country_name}_{job_id}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{excel_name}"'}
    )


@app.get("/api/files")
async def list_files():
    files = []
    if OUTPUT_DIR.exists():
        candidates = list(OUTPUT_DIR.glob("*.json")) + list(OUTPUT_DIR.glob("*.xlsx"))
        candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for p in candidates:
            stat = p.stat()
            is_json = p.suffix.lower() == ".json"
            files.append({
                "filename": p.name,
                "is_json": is_json,
                "excel_virtual_name": p.stem + ".xlsx" if is_json else p.name,
                "size_bytes": stat.st_size,
                "size_human": format_bytes(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M:%S"),
                "download_url": f"/api/files/{p.name}/download",
                "raw_url": f"/api/files/{p.name}/raw" if is_json else None,
            })
    return {"files": files}


@app.get("/api/files/{filename}/download")
async def download_file(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        # Nếu người dùng yêu cầu .xlsx nhưng trên đĩa chỉ có .json tương ứng
        if filename.endswith(".xlsx"):
            json_alt = OUTPUT_DIR / (filename[:-5] + ".json")
            if json_alt.exists():
                file_path = json_alt
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File không tồn tại")

    if file_path.suffix.lower() == ".json":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                leads_data = json.load(f)
            buf = export_leads_to_excel_buffer(leads_data)
            excel_filename = file_path.stem + ".xlsx"
            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="{excel_filename}"'}
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi khi chuyển đổi JSON sang Excel: {e}")

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/files/{filename}/raw")
async def get_raw_file(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File không tồn tại")
    return FileResponse(path=str(file_path), filename=filename, media_type="application/json")


@app.delete("/api/files/{filename}")
async def delete_file(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File khong ton tai")
    try:
        file_path.unlink()
        return {"status": "success", "message": f"Da xoa file {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs/{job_id}/debug")
async def get_job_debug_files(job_id: str):
    """Trả về danh sách dữ liệu trung gian của job từ DB để hiển thị trực tiếp."""
    try:
        steps_data = get_job_steps_data_from_db(job_id)
    except Exception as e:
        print(f"Warn: Khong the lay debug steps tu DB: {e}")
        steps_data = None

    if not steps_data:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job không tồn tại")
        return {"files": [], "work_dir": "Database (MySQL)"}

    step_files = []

    # Bước 1: queries
    queries = steps_data.get("step1", {}).get("queries") or []
    if queries:
        step_files.append({
            "step": 1,
            "step_name": "Danh sách từ khoá tìm kiếm",
            "filename": "step1_queries.txt",
            "type": "text",
            "rows": len(queries),
            "size_human": format_bytes(sum(len(q.encode()) for q in queries)),
            "download_url": f"/api/jobs/{job_id}/debug/download/step1_queries.txt"
        })

    # Bước 2: raw count
    raw_count = steps_data.get("step2", {}).get("raw_count", 0)
    if raw_count > 0:
        step_files.append({
            "step": 2,
            "step_name": "Kết quả cào thô Google Maps",
            "filename": "step2_raw_summary.txt",
            "type": "text",
            "rows": raw_count,
            "size_human": f"{raw_count} địa điểm",
            "download_url": f"/api/jobs/{job_id}/debug/download/step2_raw_summary.txt"
        })

    # Bước 3: candidates
    candidates = steps_data.get("step3", {}).get("candidates") or []
    cand_count = steps_data.get("step3", {}).get("candidates_count", len(candidates))
    if candidates or cand_count > 0:
        step_files.append({
            "step": 3,
            "step_name": "Lọc Heuristic — Ứng viên đại lý",
            "filename": "step3_candidates.json",
            "type": "json",
            "rows": cand_count,
            "size_human": format_bytes(len(json.dumps(sanitize_for_json(candidates)))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step3_candidates.json"
        })

    # Bước 3b: excluded
    excluded = steps_data.get("step3", {}).get("excluded") or []
    excl_count = steps_data.get("step3", {}).get("excluded_count", len(excluded))
    if excluded or excl_count > 0:
        step_files.append({
            "step": 3,
            "step_name": "Lọc Heuristic — Danh sách bị loại",
            "filename": "step3_excluded.json",
            "type": "json",
            "rows": excl_count,
            "size_human": format_bytes(len(json.dumps(sanitize_for_json(excluded)))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step3_excluded.json"
        })

    # Bước 4: verdicts
    verdicts = steps_data.get("step4", {}).get("verdicts") or []
    if verdicts:
        step_files.append({
            "step": 4,
            "step_name": "Thẩm định website (Verdicts)",
            "filename": "step4_verdicts.json",
            "type": "json",
            "rows": len(verdicts),
            "size_human": format_bytes(len(json.dumps(sanitize_for_json(verdicts)))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step4_verdicts.json"
        })

    # Bước 4b: reverify
    reverify = steps_data.get("step4", {}).get("reverify") or []
    if reverify:
        step_files.append({
            "step": 4,
            "step_name": "Reverify browser kết quả (JSON)",
            "filename": "step4_reverify.json",
            "type": "json",
            "rows": len(reverify),
            "size_human": format_bytes(len(json.dumps(sanitize_for_json(reverify)))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step4_reverify.json"
        })

    # Bước 5: leads
    s5 = steps_data.get("step5", {})
    qual = s5.get("qualified_leads", [])
    drop = s5.get("dropped_leads", [])
    if qual or drop:
        step_files.append({
            "step": 5,
            "step_name": "Phân Tier NDC Leads (JSON Object)",
            "filename": "step5_final_leads.json",
            "type": "json",
            "rows": len(qual) + len(drop),
            "size_human": format_bytes(len(json.dumps(s5))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step5_final_leads.json"
        })

    return {"files": step_files, "work_dir": "Database (MySQL)"}


@app.get("/api/jobs/{job_id}/steps")
async def get_job_steps_data(job_id: str):
    """Trả về dữ liệu có cấu trúc chi tiết của cả 5 bước từ DB để Web UI hiển thị theo từng Tab."""
    try:
        db_steps = get_job_steps_data_from_db(job_id)
        if db_steps:
            job = JOBS.get(job_id)
            if job and job.get("status") in ["running", "pending"]:
                db_steps["status"] = job["status"]
                db_steps["percent"] = job.get("percent", db_steps.get("percent", 0))
                db_steps["stage"] = job.get("stage", db_steps.get("stage", 0))
                db_steps["stage_name"] = job.get("stage_name", db_steps.get("stage_name", ""))
            return db_steps
    except Exception as e:
        print(f"Lỗi truy vấn steps từ DB cho job {job_id}: {e}")

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    return {
        "job_id": job_id,
        "country": job.get("country", ""),
        "status": job.get("status", ""),
        "percent": job.get("percent", 0),
        "stage": job.get("stage", 0),
        "stage_name": job.get("stage_name", ""),
        "step1": {"queries": [], "count": 0},
        "step2": {"raw_count": 0, "raw_places": [], "concurrency": 1, "depth": 5, "lang": "vi"},
        "step3": {"candidates": [], "candidates_count": 0, "excluded": [], "excluded_count": 0},
        "step4": {"verdicts": [], "verdicts_count": 0, "reverify": [], "reverify_count": 0},
        "step5": {"qualified_leads": [], "dropped_leads": [], "summary": {"qualified_count": 0, "dropped_count": 0, "total_leads": 0}}
    }


@app.get("/api/jobs/{job_id}/debug/view/{filename}")
async def view_debug_file(job_id: str, filename: str):
    """Trả về nội dung intermediate từ DB dưới dạng JSON để hiển thị modal."""
    steps_data = None
    try:
        steps_data = get_job_steps_data_from_db(job_id)
    except Exception as e:
        print(f"Lỗi đọc dữ liệu debug từ DB: {e}")

    if not steps_data:
        raise HTTPException(status_code=404, detail="Không tìm thấy dữ liệu cho job này")

    if filename == "step1_queries.txt":
        queries = steps_data.get("step1", {}).get("queries") or []
        return JSONResponse({"type": "text", "content": "\n".join(queries), "filename": filename})

    elif filename == "step2_raw_summary.txt":
        raw_count = steps_data.get("step2", {}).get("raw_count", 0)
        content = f"Google Maps cào được {raw_count} địa điểm thô.\nDữ liệu được lưu trữ an toàn trong Database MySQL."
        return JSONResponse({"type": "text", "content": content, "filename": filename})

    elif filename == "step3_candidates.json":
        cand = steps_data.get("step3", {}).get("candidates") or []
        return JSONResponse({"type": "json", "data": cand, "filename": filename})

    elif filename == "step3_excluded.json":
        excl = steps_data.get("step3", {}).get("excluded") or []
        return JSONResponse({"type": "json", "data": excl, "filename": filename})

    elif filename == "step4_verdicts.json":
        verdicts = steps_data.get("step4", {}).get("verdicts") or []
        return JSONResponse({"type": "json", "data": verdicts, "filename": filename})

    elif filename == "step4_reverify.json":
        reverify = steps_data.get("step4", {}).get("reverify") or []
        return JSONResponse({"type": "json", "data": reverify, "filename": filename})

    elif filename == "step5_final_leads.json":
        leads = steps_data.get("step5", {})
        return JSONResponse({"type": "json", "data": leads, "filename": filename})

    raise HTTPException(status_code=404, detail=f"Không tìm thấy dữ liệu cho {filename}")


@app.get("/api/jobs/{job_id}/debug/download/{filename}")
async def download_debug_file(job_id: str, filename: str):
    """Tải file debug trực tiếp từ DB."""
    steps_data = None
    try:
        steps_data = get_job_steps_data_from_db(job_id)
    except Exception as e:
        print(f"Lỗi đọc dữ liệu debug từ DB: {e}")

    if not steps_data:
        raise HTTPException(status_code=404, detail="Không tìm thấy dữ liệu cho job này")

    if filename == "step1_queries.txt":
        queries = steps_data.get("step1", {}).get("queries") or []
        buf = io.BytesIO("\n".join(queries).encode("utf-8"))
        return StreamingResponse(buf, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step2_raw_summary.txt":
        raw_count = steps_data.get("step2", {}).get("raw_count", 0)
        buf = io.BytesIO(f"raw_count: {raw_count}\n".encode("utf-8"))
        return StreamingResponse(buf, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step3_candidates.json":
        cand = steps_data.get("step3", {}).get("candidates") or []
        buf = io.BytesIO(json.dumps(cand, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step3_excluded.json":
        excl = steps_data.get("step3", {}).get("excluded") or []
        buf = io.BytesIO(json.dumps(excl, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step4_verdicts.json":
        verdicts = steps_data.get("step4", {}).get("verdicts") or []
        buf = io.BytesIO(json.dumps(verdicts, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step4_reverify.json":
        reverify = steps_data.get("step4", {}).get("reverify") or []
        buf = io.BytesIO(json.dumps(reverify, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step5_final_leads.json":
        leads = steps_data.get("step5", {})
        buf = io.BytesIO(json.dumps(leads, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    raise HTTPException(status_code=404, detail=f"Không tìm thấy dữ liệu cho {filename}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
