import json
import uuid
from pathlib import Path
from db.db_connection import get_db_connection


def safe_json_loads(val, default=None):
    """Parse an toàn dữ liệu JSON từ MySQL (có thể là dict, list hoặc chuỗi JSON)."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return default


def create_search_job(country, custom_keywords, lang, depth, concurrency, max_sites, market_type, job_id=None):
    """Tạo một Job tìm kiếm mới và trả về job_id. Hỗ trợ truyền sẵn job_id (UUID string)."""
    actual_id = str(job_id) if job_id else str(uuid.uuid4())
    query = """
        INSERT INTO search_jobs 
        (id, country, custom_keywords, lang, depth, concurrency, max_sites, market_type, status, stage, stage_name, percent, current_message, started_at) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', 0, 'Khởi tạo', 0, 'Đã tạo chiến dịch tìm kiếm...', CURRENT_TIMESTAMP)
        ON DUPLICATE KEY UPDATE status = 'pending';
    """
    params = (
        actual_id, country,
        json.dumps(custom_keywords) if custom_keywords else None,
        lang, depth, concurrency, max_sites, market_type
    )

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()
            return actual_id
    except Exception as e:
        print(f"Lỗi tạo search job: {e}")
        return actual_id


def update_job_status(job_id, status, error_message=None, leads_summary=None):
    """Cập nhật trạng thái của Job."""
    if not job_id:
        return
    query = """
        UPDATE search_jobs 
        SET status = %s, 
            error_message = %s, 
            leads_summary = COALESCE(%s, leads_summary),
            finished_at = CASE WHEN %s IN ('completed', 'failed', 'cancelled') THEN CURRENT_TIMESTAMP ELSE finished_at END,
            updated_at = CURRENT_TIMESTAMP 
        WHERE id = %s;
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (
                    status, error_message,
                    json.dumps(leads_summary) if leads_summary else None,
                    status, str(job_id)
                ))
            conn.commit()
    except Exception as e:
        print(f"Lỗi cập nhật job status: {e}")


def update_job_progress(job_id, stage, stage_name, percent, message, log_line=None):
    """Cập nhật tiến độ realtime của Job vào Database MySQL."""
    if not job_id:
        return
    if log_line:
        query = """
            UPDATE search_jobs 
            SET stage = %s,
                stage_name = %s,
                percent = %s,
                current_message = %s,
                logs = JSON_ARRAY_APPEND(IFNULL(logs, JSON_ARRAY()), '$', %s),
                status = CASE WHEN status = 'pending' THEN 'running' ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """
        params = (stage, stage_name, percent, message, str(log_line), str(job_id))
    else:
        query = """
            UPDATE search_jobs 
            SET stage = %s,
                stage_name = %s,
                percent = %s,
                current_message = %s,
                status = CASE WHEN status = 'pending' THEN 'running' ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """
        params = (stage, stage_name, percent, message, str(job_id))

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()
    except Exception as e:
        print(f"Lỗi cập nhật job progress: {e}")


def insert_search_queries(job_id, queries):
    """Lưu danh sách từ khóa tìm kiếm."""
    if not job_id or not queries:
        return
    query = "INSERT INTO search_queries (id, job_id, keyword) VALUES (%s, %s, %s)"
    data = [(str(uuid.uuid4()), str(job_id), q) for q in queries]
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, data)
            conn.commit()
    except Exception as e:
        print(f"Lỗi insert queries: {e}")


def insert_scraped_places(job_id, raw_places):
    """Lưu danh sách kết quả thô từ Google Maps."""
    if not job_id or not raw_places:
        return []
    
    query = """
        INSERT INTO scraped_places 
        (id, job_id, title, category, address, website, phone, google_url, raw_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    place_ids = []
    data = []
    for p in raw_places:
        pid = str(uuid.uuid4())
        place_ids.append(pid)
        data.append((
            pid,
            str(job_id),
            p.get("title", ""),
            p.get("category", ""),
            p.get("address", ""),
            p.get("web_site") or p.get("website", ""),
            p.get("phone", ""),
            p.get("url", ""),
            json.dumps(p)
        ))

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, data)
            conn.commit()
        return place_ids
    except Exception as e:
        print(f"Lỗi insert scraped places: {e}")
        return []


def mark_places_excluded(place_ids_and_reasons):
    """Cập nhật các place bị loại bỏ ở bước Heuristic.
    Input: list of tuples (place_id, reason)
    """
    if not place_ids_and_reasons:
        return
    query = "UPDATE scraped_places SET is_excluded_heuristic = 1, heuristic_exclude_reason = %s WHERE id = %s"
    data = [(reason, str(pid)) for pid, reason in place_ids_and_reasons]
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, data)
            conn.commit()
    except Exception as e:
        print(f"Lỗi mark places excluded: {e}")


def insert_place_verdicts(verdicts_data):
    """Lưu kết quả thẩm định website.
    Input: list of dicts. Mỗi dict phải có 'db_place_id'.
    """
    if not verdicts_data:
        return
    
    query = """
        INSERT INTO place_verdicts 
        (id, place_id, is_alive, has_flight_form, has_iata, has_iframe, iframe_src, ai_classification, error_message)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    data = []
    for v in verdicts_data:
        if not v.get("db_place_id"):
            continue
        is_alive = 1 if (v.get("is_alive") or v.get("reachable") or v.get("real")) else 0
        has_flight_form = 1 if (v.get("has_flight_form") or v.get("flightticketing") or v.get("onlinesearch")) else 0
        has_iata = 1 if (v.get("has_iata") or v.get("iata")) else 0
        has_iframe = 1 if (v.get("has_iframe") or v.get("iframe")) else 0
        error_msg = v.get("error") or v.get("evidence") or ""
        data.append((
            str(uuid.uuid4()),
            str(v.get("db_place_id")),
            is_alive,
            has_flight_form,
            has_iata,
            has_iframe,
            v.get("iframe_src"),
            json.dumps(v.get("ai_classification")) if v.get("ai_classification") else None,
            error_msg
        ))
        
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, data)
            conn.commit()
    except Exception as e:
        print(f"Lỗi insert place verdicts: {e}")


def insert_final_leads(leads_data):
    """Lưu kết quả phân Tier cuối cùng.
    Input: list of dicts. Mỗi dict cần có 'db_place_id', 'tier', 'dropped_reason'.
    """
    if not leads_data:
        return
    
    query = """
        INSERT INTO final_leads (id, place_id, tier, dropped_reason)
        VALUES (%s, %s, %s, %s)
    """
    data = []
    for ld in leads_data:
        if not ld.get("db_place_id"):
            continue
        data.append((
            str(uuid.uuid4()),
            str(ld.get("db_place_id")),
            ld.get("tier"),
            ld.get("dropped_reason")
        ))
        
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, data)
            conn.commit()
    except Exception as e:
        print(f"Lỗi insert final leads: {e}")


def get_all_search_jobs(limit=50):
    """Lấy danh sách tất cả các Job từ DB theo thứ tự mới nhất để hiển thị Web UI."""
    query = """
        SELECT 
            id, country, custom_keywords, lang, depth, concurrency, max_sites, market_type,
            status, stage, stage_name, percent, current_message, error_message,
            created_at, started_at, finished_at, leads_summary, logs
        FROM search_jobs
        ORDER BY created_at DESC
        LIMIT %s;
    """
    jobs = []
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                rows = cur.fetchall()
                for r in rows:
                    job_id = str(r[0])
                    created_at_str = r[14].strftime("%Y-%m-%d %H:%M:%S") if r[14] else ""
                    started_at_str = r[15].strftime("%Y-%m-%d %H:%M:%S") if r[15] else ""
                    finished_at_str = r[16].strftime("%Y-%m-%d %H:%M:%S") if r[16] else ""
                    leads_summary = safe_json_loads(r[17], default={})
                    logs = safe_json_loads(r[18], default=[])
                    c_kw_parsed = safe_json_loads(r[2], default=r[2])

                    if isinstance(c_kw_parsed, list):
                        c_kw_str = "\n".join(str(k) for k in c_kw_parsed)
                    elif isinstance(c_kw_parsed, str):
                        c_kw_str = c_kw_parsed
                    else:
                        c_kw_str = ""

                    jobs.append({
                        "id": job_id,
                        "country": r[1] or "",
                        "custom_keywords": c_kw_str,
                        "lang": r[3] or "en",
                        "depth": r[4] or 5,
                        "concurrency": r[5] or 1,
                        "max_sites": r[6] or 0,
                        "market_type": r[7] or "auto",
                        "status": r[8] or "pending",
                        "stage": r[9] if r[9] is not None else 0,
                        "stage_name": r[10] or "Khởi tạo",
                        "percent": r[11] if r[11] is not None else 0,
                        "message": r[12] or "",
                        "error": r[13],
                        "created_at": created_at_str,
                        "started_at": started_at_str,
                        "finished_at": finished_at_str,
                        "result": {
                            "qualified_count": leads_summary.get("qualified_count", 0),
                            "dropped_count": leads_summary.get("dropped_count", 0),
                            "total_leads": leads_summary.get("total_leads", 0),
                            "excel_filename": leads_summary.get("excel_filename", f"{r[1] or 'leads'}_{job_id}.xlsx"),
                        } if leads_summary else None,
                        "leads_data": None,
                        "intermediate": None,
                        "logs": logs or ([f"[{created_at_str}] Khởi tạo tác vụ"] if created_at_str else [])
                    })
        return jobs
    except Exception as e:
        print(f"Lỗi get all search jobs: {e}")
        return []


def get_search_job(job_id):
    """Lấy thông tin chi tiết 1 Job từ DB."""
    if not job_id:
        return None
    query = """
        SELECT 
            id, country, custom_keywords, lang, depth, concurrency, max_sites, market_type,
            status, stage, stage_name, percent, current_message, error_message,
            created_at, started_at, finished_at, leads_summary, logs
        FROM search_jobs
        WHERE id = %s;
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (str(job_id),))
                r = cur.fetchone()
                if not r:
                    return None
                created_at_str = r[14].strftime("%Y-%m-%d %H:%M:%S") if r[14] else ""
                started_at_str = r[15].strftime("%Y-%m-%d %H:%M:%S") if r[15] else ""
                finished_at_str = r[16].strftime("%Y-%m-%d %H:%M:%S") if r[16] else ""
                leads_summary = safe_json_loads(r[17], default={})
                logs = safe_json_loads(r[18], default=[])
                c_kw_parsed = safe_json_loads(r[2], default=r[2])

                if isinstance(c_kw_parsed, list):
                    c_kw_str = "\n".join(str(k) for k in c_kw_parsed)
                elif isinstance(c_kw_parsed, str):
                    c_kw_str = c_kw_parsed
                else:
                    c_kw_str = ""

                return {
                    "id": str(r[0]),
                    "country": r[1] or "",
                    "custom_keywords": c_kw_str,
                    "lang": r[3] or "en",
                    "depth": r[4] or 5,
                    "concurrency": r[5] or 1,
                    "max_sites": r[6] or 0,
                    "market_type": r[7] or "auto",
                    "status": r[8] or "pending",
                    "stage": r[9] if r[9] is not None else 0,
                    "stage_name": r[10] or "Khởi tạo",
                    "percent": r[11] if r[11] is not None else 0,
                    "message": r[12] or "",
                    "error": r[13],
                    "created_at": created_at_str,
                    "started_at": started_at_str,
                    "finished_at": finished_at_str,
                    "result": {
                        "qualified_count": leads_summary.get("qualified_count", 0),
                        "dropped_count": leads_summary.get("dropped_count", 0),
                        "total_leads": leads_summary.get("total_leads", 0),
                        "excel_filename": leads_summary.get("excel_filename", f"{r[1] or 'leads'}_{str(r[0])}.xlsx"),
                    } if leads_summary else None,
                    "leads_data": None,
                    "intermediate": None,
                    "logs": logs
                }
    except Exception as e:
        print(f"Lỗi get search job {job_id}: {e}")
        return None


def get_job_steps_data_from_db(job_id):
    """Tái tạo dữ liệu chi tiết của cả 5 bước từ DB cho giao diện Web UI theo từng Tab."""
    job = get_search_job(job_id)
    if not job:
        return None

    str_id = str(job_id)
    steps_data = {
        "job_id": str_id,
        "country": job.get("country", ""),
        "status": job.get("status", ""),
        "percent": job.get("percent", 0),
        "stage": job.get("stage", 0),
        "stage_name": job.get("stage_name", ""),
        "step1": {"queries": [], "count": 0},
        "step2": {
            "raw_count": 0,
            "raw_places": [],
            "concurrency": job.get("concurrency", 1),
            "depth": job.get("depth", 5),
            "lang": job.get("lang", "vi"),
        },
        "step3": {
            "candidates": [],
            "candidates_count": 0,
            "excluded": [],
            "excluded_count": 0,
        },
        "step4": {
            "verdicts": [],
            "verdicts_count": 0,
            "reverify": [],
            "reverify_count": 0,
        },
        "step5": {
            "qualified_leads": [],
            "dropped_leads": [],
            "summary": {"qualified_count": 0, "dropped_count": 0, "total_leads": 0},
        }
    }

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Bước 1: Queries
                cur.execute("SELECT keyword FROM search_queries WHERE job_id = %s ORDER BY created_at ASC", (str_id,))
                q_rows = cur.fetchall()
                queries = [q[0] for q in q_rows]
                steps_data["step1"] = {"queries": queries, "count": len(queries)}

                # Bước 2 & 3: Scraped places & Candidates / Excluded
                cur.execute("""
                    SELECT id, title, category, address, website, phone, google_url, 
                           is_excluded_heuristic, heuristic_exclude_reason, raw_json
                    FROM scraped_places 
                    WHERE job_id = %s 
                    ORDER BY created_at ASC
                """, (str_id,))
                places_rows = cur.fetchall()

                raw_places = []
                candidates = []
                excluded = []

                for p in places_rows:
                    pid, title, cat, addr, web, phone, gurl, is_excl, excl_reason, rjson = p
                    parsed_rjson = safe_json_loads(rjson, default={})
                    raw_item = {
                        "title": title or "N/A",
                        "category": cat or "",
                        "address": addr or "",
                        "website": web or "",
                        "phone": phone or "",
                        "google_url": gurl or ""
                    }
                    raw_places.append(raw_item)

                    if is_excl:
                        excluded.append({
                            "title": title or "–",
                            "category": cat or "–",
                            "website": web or "",
                            "exclusion_reason": excl_reason or "Heuristic filter"
                        })
                    else:
                        cand_item = {
                            "title": title or "–",
                            "segment": cat or "–",
                            "category": cat or "–",
                            "website": web or "",
                            "phone": phone or "–",
                            "score_total": 5,
                            "priority_tier": "Tier 2",
                        }
                        if isinstance(parsed_rjson, dict):
                            cand_item.update({k: v for k, v in parsed_rjson.items() if k not in cand_item})
                        candidates.append(cand_item)

                steps_data["step2"]["raw_count"] = len(raw_places)
                steps_data["step2"]["raw_places"] = raw_places[:500]
                steps_data["step3"]["candidates"] = candidates[:500]
                steps_data["step3"]["candidates_count"] = len(candidates)
                steps_data["step3"]["excluded"] = excluded[:500]
                steps_data["step3"]["excluded_count"] = len(excluded)

                # Bước 4: Verdicts
                cur.execute("""
                    SELECT p.title, p.website, v.is_alive, v.has_flight_form, v.has_iata, 
                           v.has_iframe, v.iframe_src, v.ai_classification, v.error_message
                    FROM place_verdicts v
                    JOIN scraped_places p ON v.place_id = p.id
                    WHERE p.job_id = %s
                    ORDER BY v.created_at ASC
                """, (str_id,))
                v_rows = cur.fetchall()
                verdicts = []
                for vr in v_rows:
                    title, web, alive, fl_form, iata, iframe, if_src, ai_cls, err = vr
                    parsed_ai = safe_json_loads(ai_cls, default={})
                    is_reachable = 1 if alive else 0
                    has_ticket = 1 if fl_form else 0
                    is_accepted = 1 if (is_reachable and has_ticket) else 0
                    
                    if not is_reachable:
                        verdict_status = "Bị loại: Không thể truy cập website"
                    elif not has_ticket:
                        verdict_status = "Bị loại: Không có cổng đặt vé máy bay"
                    else:
                        verdict_status = "Đạt chuẩn: Có bán vé máy bay"
                        
                    verdicts.append({
                        "website": web or "",
                        "title": title or "",
                        "reachable": is_reachable,
                        "flightticketing": has_ticket,
                        "onlinesearch": has_ticket,
                        "iata": 1 if iata else 0,
                        "iframe": 1 if iframe else 0,
                        "iframe_src": if_src or "",
                        "ai_classification": parsed_ai,
                        "error": err or "",
                        "is_accepted": is_accepted,
                        "verdict_status": verdict_status
                    })
                accepted_count = sum(1 for v in verdicts if v.get("is_accepted"))
                rejected_count = len(verdicts) - accepted_count
                steps_data["step4"]["verdicts"] = verdicts
                steps_data["step4"]["verdicts_count"] = len(verdicts)
                steps_data["step4"]["summary"] = {
                    "total_tested": len(verdicts),
                    "accepted_count": accepted_count,
                    "rejected_count": rejected_count,
                    "iata_count": sum(1 for v in verdicts if v.get("iata")),
                }

                # Bước 5: Final Leads
                cur.execute("""
                    SELECT p.title, p.category, p.address, p.website, p.phone, 
                           f.tier, f.dropped_reason, p.raw_json
                    FROM final_leads f
                    JOIN scraped_places p ON f.place_id = p.id
                    WHERE p.job_id = %s
                    ORDER BY f.created_at ASC
                """, (str_id,))
                l_rows = cur.fetchall()
                qual = []
                drop = []
                for lr in l_rows:
                    title, cat, addr, web, phone, tier, reason, rjson = lr
                    parsed_rjson = safe_json_loads(rjson, default={})
                    lead_item = {
                        "title": title or "–",
                        "company_name": title or "–",
                        "category": cat or "–",
                        "address": addr or "–",
                        "website": web or "",
                        "phone": phone or "–",
                        "tier": tier or "Tier 1",
                        "reason": reason or "",
                    }
                    if isinstance(parsed_rjson, dict):
                        for k, v in parsed_rjson.items():
                            if k not in lead_item:
                                lead_item[k] = v

                    if tier == "Dropped" or (reason and reason.strip()):
                        drop.append(lead_item)
                    else:
                        qual.append(lead_item)

                steps_data["step5"]["qualified_leads"] = qual
                steps_data["step5"]["dropped_leads"] = drop
                if len(qual) == 0 and len(drop) == 0:
                    l_sum = job.get("leads_summary") or job.get("result") or {}
                    if isinstance(l_sum, str):
                        l_sum = safe_json_loads(l_sum, default={})
                    
                    excel_fn = l_sum.get("excel_filename", "")
                    json_fn = excel_fn.replace("_ndc_leads_", "_leads_").replace(".xlsx", ".json") if excel_fn else ""
                    
                    output_dir = Path(__file__).resolve().parent.parent.parent / "output"
                    json_file_path = output_dir / json_fn if json_fn else None
                    if json_file_path and json_file_path.exists():
                        try:
                            with open(json_file_path, "r", encoding="utf-8") as jf:
                                jdata = json.load(jf)
                                qual = jdata.get("qualified_leads", [])
                                drop = jdata.get("dropped_leads", [])
                                for item in qual:
                                    c_name = item.get("name") or item.get("company_name") or item.get("title") or item.get("gmaps_name") or ""
                                    item["company_name"] = c_name
                                    item["title"] = c_name
                                    if "tier" not in item:
                                        item["tier"] = "Tier 1"
                                for item in drop:
                                    c_name = item.get("name") or item.get("company_name") or item.get("title") or item.get("gmaps_name") or ""
                                    item["company_name"] = c_name
                                    item["title"] = c_name
                                    if "tier" not in item:
                                        item["tier"] = "Dropped"
                                steps_data["step5"]["qualified_leads"] = qual
                                steps_data["step5"]["dropped_leads"] = drop
                                steps_data["step5"]["summary"] = {
                                    "qualified_count": len(qual),
                                    "dropped_count": len(drop),
                                    "total_leads": len(qual) + len(drop)
                                }
                                
                                # Khôi phục cờ Đạt chuẩn cho Step 4 nếu dữ liệu DB cũ bị ghi 0
                                if steps_data["step4"]["summary"]["accepted_count"] == 0 and len(qual) > 0:
                                    qual_urls = {str(l.get("website", "")).strip().rstrip("/").lower() for l in qual if l.get("website")}
                                    qual_names = {str(l.get("name", "")).strip().lower() for l in qual if l.get("name")}
                                    for v in steps_data["step4"]["verdicts"]:
                                        v_web = str(v.get("website", "")).strip().rstrip("/").lower()
                                        v_title = str(v.get("title", "")).strip().lower()
                                        if v_web in qual_urls or v_title in qual_names:
                                            v["reachable"] = 1
                                            v["flightticketing"] = 1
                                            v["onlinesearch"] = 1
                                            v["is_accepted"] = 1
                                            v["verdict_status"] = "Đạt chuẩn: Có bán vé máy bay"
                                    
                                    acc_cnt = sum(1 for v in steps_data["step4"]["verdicts"] if v.get("is_accepted"))
                                    steps_data["step4"]["summary"]["accepted_count"] = acc_cnt
                                    steps_data["step4"]["summary"]["rejected_count"] = len(steps_data["step4"]["verdicts"]) - acc_cnt
                        except Exception as ex:
                            print(f"Lỗi đọc fallback json {json_file_path}: {ex}")
                    else:
                        # Tái tạo danh sách từ dữ liệu thẩm định Step 4 của chính job này
                        s4_verdicts = steps_data.get("step4", {}).get("verdicts", [])
                        qual_from_s4 = [
                            {
                                "title": v.get("title") or "–",
                                "company_name": v.get("title") or "–",
                                "website": v.get("website") or "",
                                "tier": "Tier 1",
                                "reason": v.get("verdict_status") or "Đạt chuẩn",
                            }
                            for v in s4_verdicts
                            if v.get("is_accepted")
                        ]
                        dropped_from_s4 = [
                            {
                                "title": v.get("title") or "–",
                                "company_name": v.get("title") or "–",
                                "website": v.get("website") or "",
                                "tier": "Dropped",
                                "reason": v.get("verdict_status") or v.get("error") or "Không đạt tiêu chuẩn",
                            }
                            for v in s4_verdicts
                            if not v.get("is_accepted")
                        ]
                        steps_data["step5"]["qualified_leads"] = qual_from_s4
                        steps_data["step5"]["dropped_leads"] = dropped_from_s4
                        q_cnt = l_sum.get("qualified_count", len(qual_from_s4))
                        d_cnt = l_sum.get("dropped_count", len(dropped_from_s4))
                        t_cnt = l_sum.get("total_leads", q_cnt + d_cnt)
                        steps_data["step5"]["summary"] = {
                            "qualified_count": q_cnt,
                            "dropped_count": d_cnt,
                            "total_leads": t_cnt,
                        }
                else:
                    steps_data["step5"]["summary"] = {
                        "qualified_count": len(qual),
                        "dropped_count": len(drop),
                        "total_leads": len(qual) + len(drop)
                    }

        return steps_data
    except Exception as e:
        print(f"Lỗi lấy dữ liệu steps từ DB cho job {job_id}: {e}")
        return steps_data


def get_job_leads_for_excel_from_db(job_id):
    """Lấy danh sách leads để xuất file Excel trực tiếp từ CSDL."""
    steps_data = get_job_steps_data_from_db(job_id)
    if not steps_data:
        return None
    return {
        "qualified_leads": steps_data["step5"]["qualified_leads"],
        "dropped_leads": steps_data["step5"]["dropped_leads"],
        "summary": steps_data["step5"]["summary"]
    }


def delete_search_job(job_id: str) -> bool:
    """Xoá một Job tìm kiếm khỏi Database MySQL (ON DELETE CASCADE sẽ xoá bảng con)."""
    if not job_id:
        return False
    query = "DELETE FROM search_jobs WHERE id = %s;"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (str(job_id),))
            conn.commit()
            return True
    except Exception as e:
        print(f"Lỗi xoá search job trong DB: {e}")
        return False
