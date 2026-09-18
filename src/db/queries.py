import json
from psycopg2.extras import execute_batch
from db.db_connection import get_db_connection

def create_search_job(country, custom_keywords, lang, depth, concurrency, max_sites, market_type):
    """Tạo một Job tìm kiếm mới và trả về job_id."""
    query = """
        INSERT INTO search_jobs 
        (country, custom_keywords, lang, depth, concurrency, max_sites, market_type, status) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
        RETURNING id;
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (
                    country,
                    json.dumps(custom_keywords) if custom_keywords else None,
                    lang, depth, concurrency, max_sites, market_type
                ))
                job_id = cur.fetchone()[0]
            conn.commit()
            return job_id
    except Exception as e:
        print(f"Lỗi tạo search job: {e}")
        return None

def update_job_status(job_id, status, error_message=None):
    """Cập nhật trạng thái của Job."""
    query = "UPDATE search_jobs SET status = %s, error_message = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (status, error_message, job_id))
            conn.commit()
    except Exception as e:
        print(f"Lỗi cập nhật job status: {e}")

def insert_search_queries(job_id, queries):
    """Lưu danh sách từ khóa tìm kiếm."""
    if not job_id or not queries:
        return
    query = "INSERT INTO search_queries (job_id, keyword) VALUES (%s, %s)"
    data = [(job_id, q) for q in queries]
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_batch(cur, query, data)
            conn.commit()
    except Exception as e:
        print(f"Lỗi insert queries: {e}")

def insert_scraped_places(job_id, raw_places):
    """Lưu danh sách kết quả thô từ Google Maps."""
    if not job_id or not raw_places:
        return []
    
    query = """
        INSERT INTO scraped_places 
        (job_id, title, category, address, website, phone, google_url, raw_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """
    
    place_ids = []
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for p in raw_places:
                    cur.execute(query, (
                        job_id,
                        p.get("title", ""),
                        p.get("category", ""),
                        p.get("address", ""),
                        p.get("web_site") or p.get("website", ""),
                        p.get("phone", ""),
                        p.get("url", ""),
                        json.dumps(p)
                    ))
                    place_ids.append(cur.fetchone()[0])
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
    query = "UPDATE scraped_places SET is_excluded_heuristic = TRUE, heuristic_exclude_reason = %s WHERE id = %s"
    # Note: data format for execute_batch requires (reason, place_id)
    data = [(reason, pid) for pid, reason in place_ids_and_reasons]
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_batch(cur, query, data)
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
        (place_id, is_alive, has_flight_form, has_iata, has_iframe, iframe_src, ai_classification, error_message)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    data = []
    for v in verdicts_data:
        if not v.get("db_place_id"):
            continue
        data.append((
            v.get("db_place_id"),
            v.get("is_alive"),
            v.get("has_flight_form"),
            v.get("has_iata"),
            v.get("has_iframe"),
            v.get("iframe_src"),
            json.dumps(v.get("ai_classification")) if v.get("ai_classification") else None,
            v.get("error")
        ))
        
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_batch(cur, query, data)
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
        INSERT INTO final_leads (place_id, tier, dropped_reason)
        VALUES (%s, %s, %s)
    """
    data = []
    for ld in leads_data:
        if not ld.get("db_place_id"):
            continue
        data.append((
            ld.get("db_place_id"),
            ld.get("tier"),
            ld.get("dropped_reason")
        ))
        
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_batch(cur, query, data)
            conn.commit()
    except Exception as e:
        print(f"Lỗi insert final leads: {e}")
