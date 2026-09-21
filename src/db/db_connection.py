import os
import re
import queue
import threading
from urllib.parse import urlparse, unquote
from pathlib import Path
from contextlib import contextmanager
import pymysql
import pymysql.cursors

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass


def parse_db_config():
    """
    Phân tích cấu hình kết nối MySQL từ DATABASE_URL hoặc các biến MYSQL_*.
    """
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("MYSQL_URL")
    
    if db_url and ("mysql" in db_url):
        # Hỗ trợ định dạng mysql:// hoặc mysql+pymysql://
        clean_url = re.sub(r"^mysql(\+pymysql)?:\/\/", "http://", db_url)
        parsed = urlparse(clean_url)
        
        host = parsed.hostname or "localhost"
        port = parsed.port or 3306
        user = unquote(parsed.username) if parsed.username else "root"
        password = unquote(parsed.password) if parsed.password else ""
        db_name = parsed.path.lstrip("/") if parsed.path else "google_maps_scraper"
        
        return {
            "host": host,
            "port": int(port),
            "user": user,
            "password": password,
            "database": db_name,
            "charset": "utf8mb4",
            "autocommit": False
        }
    
    # Sử dụng các biến môi trường rời rạc
    return {
        "host": os.environ.get("MYSQL_HOST", "localhost"),
        "port": int(os.environ.get("MYSQL_PORT", 3306)),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "database": os.environ.get("MYSQL_DATABASE", "google_maps_scraper"),
        "charset": "utf8mb4",
        "autocommit": False
    }


class MySQLConnectionPool:
    """
    Thread-safe MySQL Connection Pool với tính năng auto-reconnect.
    """
    def __init__(self, max_connections=10):
        self.config = parse_db_config()
        self.max_connections = max_connections
        self._pool = queue.Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._created_connections = 0

    def _create_new_connection(self, database=None):
        cfg = dict(self.config)
        if database is not None:
            cfg["database"] = database
        return pymysql.connect(**cfg)

    def get_connection(self):
        # Lấy kết nối từ pool hoặc tạo mới nếu chưa đạt giới hạn
        conn = None
        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created_connections < self.max_connections:
                    conn = self._create_new_connection()
                    self._created_connections += 1

        if conn is None:
            # Chờ connection khả dụng (timeout 30s)
            conn = self._pool.get(timeout=30)

        # Đảm bảo connection còn sống
        try:
            conn.ping(reconnect=True)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            conn = self._create_new_connection()

        return conn

    def release_connection(self, conn):
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:
            pass

        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._created_connections = max(0, self._created_connections - 1)

    def close_all(self):
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Exception:
                    pass
            self._created_connections = 0


_db_pool = None


def get_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = MySQLConnectionPool(max_connections=10)
    return _db_pool


@contextmanager
def get_db_connection():
    """
    Context manager để mượn kết nối từ MySQL Pool và hoàn trả sau khi xong.
    """
    pool_inst = get_pool()
    conn = pool_inst.get_connection()
    try:
        yield conn
    finally:
        pool_inst.release_connection(conn)
