#!/usr/bin/env python3
"""
run.py - Khởi động Web Server trực tiếp (Native Python):
    python run.py
"""
import os
import sys
from pathlib import Path
import uvicorn
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8090))
    host = os.getenv("HOST", "0.0.0.0")
    reload = os.getenv("RELOAD", "false").lower() == "true"
    print("=" * 80)
    print(f"🚀 Khởi động Web Server tại: http://localhost:{port} (Reload={reload})")
    print("=" * 80)
    uvicorn.run("src.web.app:app", host=host, port=port, reload=reload)
