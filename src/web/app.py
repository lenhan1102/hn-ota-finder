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

# In-memory jobs tracking
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
            if len(job["logs"]) > 500:
                job["logs"] = job["logs"][-500:]
            if inter_data:
                if job.get("intermediate") is None:
                    job["intermediate"] = {}
                job["intermediate"].update(sanitize_for_json(inter_data))

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
        )
        safe_res = sanitize_for_json(res)
        job["status"] = "completed"
        job["percent"] = 100
        job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job["result"] = safe_res
        job["leads_data"] = safe_res.get("leads_data", {})
        job["intermediate"] = safe_res.get("intermediate", {})
    except Exception as e:
        t_err = time.strftime("%H:%M:%S")
        job["status"] = "failed"
        job["error"] = str(e)
        job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job["logs"].append(f"[{t_err}] [ERROR] {e}")


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
    job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    t_now = time.strftime("%H:%M:%S")
    headless_val = req.headless
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
        "leads_data": None,
        "intermediate": None,
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
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")
    
    if job["status"] in ["completed", "failed", "cancelled"]:
        return {"status": "error", "message": "Job đã kết thúc, không thể huỷ"}
    
    job["cancelled"] = True
    job["status"] = "cancelled"
    job["message"] = "Đang huỷ tiến trình..."
    job["logs"].append(f"[{time.strftime('%H:%M:%S')}] Người dùng yêu cầu huỷ tiến trình.")
    return {"status": "success", "message": "Đã gửi yêu cầu huỷ"}


@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": list(reversed(list(JOBS.values())))}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job khong ton tai")
    return job


@app.get("/api/jobs/{job_id}/excel")
async def download_job_excel(job_id: str):
    """Xuất file Excel trực tiếp từ RAM (on-the-fly) cho một Job đã hoàn thành."""
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    leads_data = job.get("leads_data")
    if not leads_data and job.get("result"):
        leads_data = job["result"].get("leads_data")

    # Fallback: đọc từ file JSON nếu có json_path
    if not leads_data and job.get("result", {}).get("json_path"):
        jp = Path(job["result"]["json_path"])
        if jp.exists():
            try:
                with open(jp, "r", encoding="utf-8") as f:
                    leads_data = json.load(f)
            except Exception:
                pass

    if not leads_data:
        raise HTTPException(status_code=400, detail="Chưa có dữ liệu leads cho job này")

    buf = export_leads_to_excel_buffer(leads_data)
    excel_name = (job.get("result") or {}).get("excel_filename") or f"{job.get('country', 'leads')}_{job_id}.xlsx"
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
    """Trả về danh sách dữ liệu trung gian của job từ RAM/Object để hiển thị trực tiếp."""
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job khong ton tai")

    inter = job.get("intermediate") or (job.get("result") or {}).get("intermediate") or {}
    leads = job.get("leads_data") or (job.get("result") or {}).get("leads_data") or {}

    step_files = []

    # Bước 1: queries
    queries = inter.get("queries") or []
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
    raw_count = inter.get("raw_count", 0)
    if raw_count > 0:
        step_files.append({
            "step": 2,
            "step_name": "Kết quả cào thô Google Maps (In-Memory)",
            "filename": "step2_raw_summary.txt",
            "type": "text",
            "rows": raw_count,
            "size_human": f"{raw_count} địa điểm",
            "download_url": f"/api/jobs/{job_id}/debug/download/step2_raw_summary.txt"
        })

    # Bước 3: candidates
    candidates = inter.get("candidates") or []
    cand_count = inter.get("candidates_count", len(candidates))
    if candidates or cand_count > 0:
        step_files.append({
            "step": 3,
            "step_name": "Lọc Heuristic — Ứng viên đại lý (In-Memory)",
            "filename": "step3_candidates.json",
            "type": "json",
            "rows": cand_count,
            "size_human": format_bytes(len(json.dumps(sanitize_for_json(candidates)))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step3_candidates.json"
        })

    # Bước 3b: excluded
    excluded = inter.get("excluded") or []
    excl_count = inter.get("excluded_count", len(excluded))
    if excluded or excl_count > 0:
        step_files.append({
            "step": 3,
            "step_name": "Lọc Heuristic — Danh sách bị loại (In-Memory)",
            "filename": "step3_excluded.json",
            "type": "json",
            "rows": excl_count,
            "size_human": format_bytes(len(json.dumps(sanitize_for_json(excluded)))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step3_excluded.json"
        })

    # Bước 4: verdicts
    verdicts = inter.get("verdicts") or []
    if verdicts:
        step_files.append({
            "step": 4,
            "step_name": "Thẩm định website (Verdicts In-Memory)",
            "filename": "step4_verdicts.json",
            "type": "json",
            "rows": len(verdicts),
            "size_human": format_bytes(len(json.dumps(sanitize_for_json(verdicts)))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step4_verdicts.json"
        })

    # Bước 4b: reverify
    reverify = inter.get("reverify") or []
    if reverify:
        step_files.append({
            "step": 4,
            "step_name": "Reverify browser kết quả (JSON In-Memory)",
            "filename": "step4_reverify.json",
            "type": "json",
            "rows": len(reverify),
            "size_human": format_bytes(len(json.dumps(sanitize_for_json(reverify)))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step4_reverify.json"
        })

    # Bước 5: leads_data
    if leads:
        qual_count = len(leads.get("qualified_leads", []))
        drop_count = len(leads.get("dropped_leads", []))
        step_files.append({
            "step": 5,
            "step_name": "Phân Tier NDC Leads (JSON Object)",
            "filename": "step5_final_leads.json",
            "type": "json",
            "rows": qual_count + drop_count,
            "size_human": format_bytes(len(json.dumps(sanitize_for_json(leads)))),
            "download_url": f"/api/jobs/{job_id}/debug/download/step5_final_leads.json"
        })

    return {"files": step_files, "work_dir": "In-Memory (RAM Object - Không lưu file rác)"}


@app.get("/api/jobs/{job_id}/steps")
async def get_job_steps_data(job_id: str):
    """Trả về dữ liệu có cấu trúc chi tiết của cả 5 bước để Web UI hiển thị theo từng Tab."""
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    inter = job.get("intermediate") or (job.get("result") or {}).get("intermediate") or {}
    leads = job.get("leads_data") or (job.get("result") or {}).get("leads_data") or {}

    queries = inter.get("queries") or []
    raw_count = inter.get("raw_count", 0)
    candidates = inter.get("candidates") or []
    excluded = inter.get("excluded") or []
    verdicts = inter.get("verdicts") or []
    reverify = inter.get("reverify") or []
    qual = leads.get("qualified_leads") or []
    drop = leads.get("dropped_leads") or []
    summary = leads.get("summary") or {
        "qualified_count": len(qual),
        "dropped_count": len(drop),
        "total_leads": len(qual) + len(drop),
    }

    return {
        "job_id": job_id,
        "country": job.get("country", ""),
        "status": job.get("status", ""),
        "percent": job.get("percent", 0),
        "stage": job.get("stage", 0),
        "stage_name": job.get("stage_name", ""),
        "step1": {
            "queries": queries,
            "count": len(queries),
        },
        "step2": {
            "raw_count": raw_count,
            "raw_places": inter.get("raw_places", []),
            "concurrency": job.get("concurrency", 1),
            "depth": job.get("depth", 5),
            "lang": job.get("lang", "vi"),
        },
        "step3": {
            "candidates": candidates,
            "candidates_count": inter.get("candidates_count", len(candidates)),
            "excluded": excluded,
            "excluded_count": inter.get("excluded_count", len(excluded)),
        },
        "step4": {
            "verdicts": verdicts,
            "verdicts_count": len(verdicts),
            "reverify": reverify,
            "reverify_count": len(reverify),
        },
        "step5": {
            "qualified_leads": qual,
            "dropped_leads": drop,
            "summary": summary,
        }
    }


@app.get("/api/jobs/{job_id}/debug/view/{filename}")
async def view_debug_file(job_id: str, filename: str):
    """Trả về nội dung intermediate trực tiếp từ RAM dưới dạng JSON để hiển thị modal."""
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job khong ton tai")

    inter = job.get("intermediate") or (job.get("result") or {}).get("intermediate") or {}
    leads = job.get("leads_data") or (job.get("result") or {}).get("leads_data") or {}

    if filename == "step1_queries.txt":
        queries = inter.get("queries") or []
        return SafeJSONResponse({"type": "text", "content": "\n".join(queries), "filename": filename})

    elif filename == "step2_raw_summary.txt":
        raw_count = inter.get("raw_count", 0)
        content = f"Google Maps cào được {raw_count} địa điểm thô.\nDữ liệu được xử lý trực tiếp trên RAM và giải phóng ngay để tối ưu dung lượng server."
        return SafeJSONResponse({"type": "text", "content": content, "filename": filename})

    elif filename == "step3_candidates.json":
        cand = inter.get("candidates") or []
        return SafeJSONResponse({"type": "json", "data": cand, "filename": filename})

    elif filename == "step3_excluded.json":
        excl = inter.get("excluded") or []
        return SafeJSONResponse({"type": "json", "data": excl, "filename": filename})

    elif filename == "step4_verdicts.json":
        verdicts = inter.get("verdicts") or []
        return SafeJSONResponse({"type": "json", "data": verdicts, "filename": filename})

    elif filename == "step4_reverify.json":
        reverify = inter.get("reverify") or []
        return SafeJSONResponse({"type": "json", "data": reverify, "filename": filename})

    elif filename == "step5_final_leads.json":
        return SafeJSONResponse({"type": "json", "data": leads, "filename": filename})

    raise HTTPException(status_code=404, detail=f"Không tìm thấy dữ liệu cho {filename}")


@app.get("/api/jobs/{job_id}/debug/download/{filename}")
async def download_debug_file(job_id: str, filename: str):
    """Tải file debug trực tiếp từ RAM."""
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job khong ton tai")

    inter = job.get("intermediate") or (job.get("result") or {}).get("intermediate") or {}
    leads = job.get("leads_data") or (job.get("result") or {}).get("leads_data") or {}

    if filename == "step1_queries.txt":
        queries = inter.get("queries") or []
        buf = io.BytesIO("\n".join(queries).encode("utf-8"))
        return StreamingResponse(buf, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step2_raw_summary.txt":
        raw_count = inter.get("raw_count", 0)
        buf = io.BytesIO(f"raw_count: {raw_count}\n".encode("utf-8"))
        return StreamingResponse(buf, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step3_candidates.json":
        cand = sanitize_for_json(inter.get("candidates") or [])
        buf = io.BytesIO(json.dumps(cand, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step3_excluded.json":
        excl = sanitize_for_json(inter.get("excluded") or [])
        buf = io.BytesIO(json.dumps(excl, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step4_verdicts.json":
        verdicts = sanitize_for_json(inter.get("verdicts") or [])
        buf = io.BytesIO(json.dumps(verdicts, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step4_reverify.json":
        reverify = sanitize_for_json(inter.get("reverify") or [])
        buf = io.BytesIO(json.dumps(reverify, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    elif filename == "step5_final_leads.json":
        safe_leads = sanitize_for_json(leads)
        buf = io.BytesIO(json.dumps(safe_leads, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(buf, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    raise HTTPException(status_code=404, detail=f"Không tìm thấy dữ liệu cho {filename}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
