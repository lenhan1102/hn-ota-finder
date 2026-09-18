import os
import sys

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db.db_connection import get_db_connection

CREATE_TABLES_SQL = """
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS search_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    country VARCHAR(255),
    custom_keywords JSONB,
    lang VARCHAR(50),
    depth INTEGER,
    concurrency INTEGER,
    max_sites INTEGER,
    market_type VARCHAR(100),
    status VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_queries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES search_jobs(id) ON DELETE CASCADE,
    keyword VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scraped_places (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES search_jobs(id) ON DELETE CASCADE,
    title VARCHAR(500),
    category VARCHAR(255),
    address TEXT,
    website VARCHAR(1000),
    phone VARCHAR(255),
    google_url TEXT,
    raw_json JSONB,
    is_excluded_heuristic BOOLEAN DEFAULT FALSE,
    heuristic_exclude_reason VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS place_verdicts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    place_id UUID REFERENCES scraped_places(id) ON DELETE CASCADE,
    is_alive BOOLEAN,
    has_flight_form BOOLEAN,
    has_iata BOOLEAN,
    has_iframe BOOLEAN,
    iframe_src TEXT,
    ai_classification JSONB,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS final_leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    place_id UUID REFERENCES scraped_places(id) ON DELETE CASCADE,
    tier VARCHAR(100),
    dropped_reason VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                print("Tạo các bảng cơ sở dữ liệu...")
                cur.execute(CREATE_TABLES_SQL)
            conn.commit()
            print("Hoàn tất tạo bảng.")
    except Exception as e:
        print(f"Lỗi khi khởi tạo CSDL: {e}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
    init_db()
