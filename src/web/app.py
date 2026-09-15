#!/usr/bin/env python3
import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
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

app = FastAPI(
    title="Google Maps Scraper - NDC Leads & OTA Finder",
    description="Giao dien quan ly va tim kiem dai ly ban ve may bay & OTA",
    version="1.0.0",
)

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# In-memory jobs tracking
JOBS = {}


class JobCreateRequest(BaseModel):
    country: str = "vietnam"
    custom_keywords: str | None = None
    lang: str = "vi"
    depth: int = 5
    concurrency: int = 4
    max_sites: int = 0
    market_type: str = "auto"


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

    def on_progress(stage: int, stage_name: str, percent: int, message: str):
        t_str = time.strftime("%H:%M:%S")
        job["stage"] = stage
        job["stage_name"] = stage_name
        job["percent"] = percent
        job["message"] = message
        job["logs"].append(f"[{t_str}] {message}")

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
            concurrency=payload.get("concurrency", 4),
            output_dir=str(OUTPUT_DIR),
            data_dir=str(DATA_DIR),
            max_sites=payload.get("max_sites", 0),
            market_type=payload.get("market_type", "auto"),
            progress_callback=on_progress,
        )
        job["status"] = "completed"
        job["percent"] = 100
        job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job["result"] = res
    except Exception as e:
        t_err = time.strftime("%H:%M:%S")
        job["status"] = "failed"
        job["error"] = str(e)
        job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job["logs"].append(f"[{t_err}] [ERROR] {e}")


@app.get("/", response_class=HTMLResponse)
async def index():
    template = jinja_env.get_template("index.html")
    rendered = template.render(countries=sorted(list(COUNTRY_CONFIGS.keys())))
    return HTMLResponse(content=rendered)


@app.get("/api/countries")
async def get_countries():
    return {"countries": sorted(list(COUNTRY_CONFIGS.keys()))}


@app.post("/api/jobs")
async def create_job(req: JobCreateRequest, bg_tasks: BackgroundTasks):
    job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    t_now = time.strftime("%H:%M:%S")
    job_data = {
        "id": job_id,
        "country": req.country,
        "custom_keywords": req.custom_keywords,
        "lang": req.lang,
        "depth": req.depth,
        "concurrency": req.concurrency,
        "market_type": req.market_type,
        "max_sites": req.max_sites,
        "status": "pending",
        "stage": 0,
        "stage_name": "Khoi tao",
        "percent": 0,
        "message": "Da dua vao hang doi xu ly...",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "result": None,
        "logs": [f"[{t_now}] Da tao yeu cau tim kiem cho {req.country}"],
    }
    JOBS[job_id] = job_data
    bg_tasks.add_task(run_job_task, job_id, req.model_dump())
    return {"job_id": job_id, "status": "pending"}


@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": list(reversed(list(JOBS.values())))}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job khong ton tai")
    return job


@app.get("/api/files")
async def list_files():
    files = []
    if OUTPUT_DIR.exists():
        for p in sorted(OUTPUT_DIR.glob("*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True):
            stat = p.stat()
            files.append({
                "filename": p.name,
                "size_bytes": stat.st_size,
                "size_human": format_bytes(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M:%S"),
                "download_url": f"/api/files/{p.name}/download",
            })
    return {"files": files}


@app.get("/api/files/{filename}/download")
async def download_file(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File khong ton tai")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
