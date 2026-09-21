import os
import re
import sys
from pathlib import Path
import pymysql

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db.db_connection import parse_db_config, get_db_connection

TABLES_DDL = [
    """
    CREATE TABLE IF NOT EXISTS search_jobs (
        id VARCHAR(36) PRIMARY KEY,
        country VARCHAR(255),
        custom_keywords JSON,
        lang VARCHAR(50),
        depth INT,
        concurrency INT,
        max_sites INT,
        market_type VARCHAR(100),
        status VARCHAR(100),
        stage INT DEFAULT 0,
        stage_name VARCHAR(255) DEFAULT 'Khởi tạo',
        percent INT DEFAULT 0,
        current_message TEXT,
        logs JSON,
        error_message TEXT,
        started_at DATETIME,
        finished_at DATETIME,
        leads_summary JSON,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS search_queries (
        id VARCHAR(36) PRIMARY KEY,
        job_id VARCHAR(36),
        keyword VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_sq_job_id (job_id),
        CONSTRAINT fk_sq_job FOREIGN KEY (job_id) REFERENCES search_jobs(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS scraped_places (
        id VARCHAR(36) PRIMARY KEY,
        job_id VARCHAR(36),
        title VARCHAR(500),
        category VARCHAR(255),
        address TEXT,
        website VARCHAR(1000),
        phone VARCHAR(255),
        google_url TEXT,
        raw_json JSON,
        is_excluded_heuristic TINYINT(1) DEFAULT 0,
        heuristic_exclude_reason VARCHAR(255),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_sp_job_id (job_id),
        CONSTRAINT fk_sp_job FOREIGN KEY (job_id) REFERENCES search_jobs(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS place_verdicts (
        id VARCHAR(36) PRIMARY KEY,
        place_id VARCHAR(36),
        is_alive TINYINT(1),
        has_flight_form TINYINT(1),
        has_iata TINYINT(1),
        has_iframe TINYINT(1),
        iframe_src TEXT,
        ai_classification JSON,
        error_message TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_pv_place_id (place_id),
        CONSTRAINT fk_pv_place FOREIGN KEY (place_id) REFERENCES scraped_places(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS final_leads (
        id VARCHAR(36) PRIMARY KEY,
        place_id VARCHAR(36),
        tier VARCHAR(100),
        dropped_reason VARCHAR(255),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_fl_place_id (place_id),
        CONSTRAINT fk_fl_place FOREIGN KEY (place_id) REFERENCES scraped_places(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
]

# Các cột cần kiểm tra và migrate nếu bảng search_jobs đã tạo trước đó
SEARCH_JOBS_EXTRA_COLUMNS = [
    ("stage", "INT DEFAULT 0"),
    ("stage_name", "VARCHAR(255) DEFAULT 'Khởi tạo'"),
    ("percent", "INT DEFAULT 0"),
    ("current_message", "TEXT"),
    ("logs", "JSON"),
    ("started_at", "DATETIME"),
    ("finished_at", "DATETIME"),
    ("leads_summary", "JSON"),
]


def ensure_database_exists():
    """Tạo cơ sở dữ liệu MySQL nếu chưa tồn tại."""
    cfg = parse_db_config()
    db_name = cfg["database"]
    server_cfg = dict(cfg)
    server_cfg.pop("database", None)

    try:
        conn = pymysql.connect(**server_cfg)
        try:
            with conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            conn.commit()
            print(f"✅ Cơ sở dữ liệu `{db_name}` đã sẵn sàng.")
        finally:
            conn.close()
    except Exception as e:
        print(f"⚠️ Không thể kiểm tra/tạo database tự động: {e}")


def migrate_columns(conn, db_name):
    """Kiểm tra và tự động bổ sung các cột còn thiếu cho bảng search_jobs."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'search_jobs'
            """, (db_name,))
            existing_cols = {row[0].lower() for row in cur.fetchall()}

            for col_name, col_def in SEARCH_JOBS_EXTRA_COLUMNS:
                if col_name.lower() not in existing_cols:
                    print(f"🔄 Đang bổ sung cột `{col_name}` vào bảng search_jobs...")
                    cur.execute(f"ALTER TABLE search_jobs ADD COLUMN {col_name} {col_def};")
        conn.commit()
    except Exception as e:
        print(f"⚠️ Lỗi khi kiểm tra migrate cột: {e}")


def init_db():
    cfg = parse_db_config()
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("MYSQL_URL", "")
    masked_url = re.sub(r":([^@]+)@", ":****@", db_url) if "@" in db_url else f"{cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}"
    print(f"Đang kết nối MySQL: {masked_url}")

    # 1. Đảm bảo database tồn tại
    ensure_database_exists()

    # 2. Tạo bảng và migrate cấu trúc
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                print("Đang tạo và cập nhật cấu trúc các bảng cơ sở dữ liệu MySQL...")
                for ddl in TABLES_DDL:
                    cur.execute(ddl)
            conn.commit()

            # 3. Migrate cột nếu bảng đã tồn tại
            migrate_columns(conn, cfg["database"])

            print("✅ Hoàn tất tạo bảng và migrate các cột tiến độ MySQL thành công!")
    except Exception as e:
        print(f"❌ Lỗi khi khởi tạo CSDL MySQL: {e}")


if __name__ == "__main__":
    init_db()
