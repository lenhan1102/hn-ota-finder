import os
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager

# Create a global connection pool
try:
    # Use standard environment variables or a specific DATABASE_URL
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    
    # Initialize the connection pool
    db_pool = psycopg2.pool.SimpleConnectionPool(
        1, 10, DATABASE_URL
    )
except Exception as e:
    print(f"Error initializing database connection pool: {e}")
    db_pool = None


@contextmanager
def get_db_connection():
    """
    Context manager to get a connection from the pool and return it when done.
    """
    if db_pool is None:
        raise Exception("Database connection pool is not initialized.")
    
    conn = db_pool.getconn()
    try:
        yield conn
    finally:
        db_pool.putconn(conn)
