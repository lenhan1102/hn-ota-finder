#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "================================================================================"
echo "🚀 KHỞI ĐỘNG NDC LEADS & OTA FINDER WEB SERVER"
echo "================================================================================"

# Kiểm tra và cài đặt thư viện cần thiết nếu thiếu
if ! python3 -c "import fastapi, uvicorn, pandas, openpyxl" 2>/dev/null; then
    echo "Đang cài đặt thư viện cần thiết từ requirements.txt..."
    pip install -r requirements.txt
fi

python3 run.py
