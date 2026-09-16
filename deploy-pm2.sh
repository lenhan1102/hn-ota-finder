#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "================================================================================"
echo "🚀 BẮT ĐẦU QUY TRÌNH DEPLOY GOOGLE-MAPS-SCRAPER-FIND-OTA"
echo "================================================================================"

# Tự động nạp PATH cho PM2 nếu chưa có trong môi trường non-interactive
if ! command -v pm2 &> /dev/null; then
    for p in "$HOME/.nvm/versions/node/"*/bin /usr/local/bin /usr/bin; do
        if [ -x "$p/pm2" ]; then
            export PATH="$(dirname "$p/pm2"):$PATH"
            break
        fi
    done
fi

# 1. Cập nhật mã nguồn mới nhất
echo "--> [1/5] Pulling mã nguồn mới nhất từ git..."
git pull origin main

# 2. Cài đặt / cập nhật virtualenv và dependencies
echo "--> [2/5] Cập nhật thư viện Python trong .venv..."
if [ ! -d ".venv" ]; then
    echo "Khởi tạo môi trường ảo .venv..."
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt

# 3. Cài đặt Playwright browser
echo "--> [3/5] Kiểm tra và cài đặt Playwright Chromium..."
playwright install chromium
# Cài đặt OS libraries nếu đang chạy dưới quyền root trên Linux
if [ "$(id -u)" -eq 0 ]; then
    playwright install-deps chromium 2>/dev/null || true
fi

# 4. Kiểm tra binary google-maps-scraper
echo "--> [4/5] Kiểm tra Google Maps Scraper binary..."
mkdir -p bin
mkdir -p output
mkdir -p logs

if [ ! -f "bin/google-maps-scraper" ]; then
    echo "⚠️ CHÚ Ý: Chưa tìm thấy binary bin/google-maps-scraper cho Linux!"
    echo "Đang thử tải phiên bản Linux amd64 từ GitHub Release..."
    TMP_DIR=$(mktemp -d)
    curl -sL https://github.com/gosom/google-maps-scraper/releases/latest/download/google_maps_scraper_linux_amd64.tar.gz -o "$TMP_DIR/gmaps.tar.gz" || true
    if [ -f "$TMP_DIR/gmaps.tar.gz" ]; then
        tar -xzf "$TMP_DIR/gmaps.tar.gz" -C "$TMP_DIR" || true
        find "$TMP_DIR" -type f -name "*scraper*" -exec cp {} bin/google-maps-scraper \;
        rm -rf "$TMP_DIR"
    fi
fi

if [ -f "bin/google-maps-scraper" ]; then
    chmod +x bin/google-maps-scraper
    echo "✅ Scraper binary sẵn sàng."
else
    echo "❌ CẢNH BÁO: Chưa có bin/google-maps-scraper. Vui lòng tải binary Linux từ: https://github.com/gosom/google-maps-scraper/releases và đặt vào thư mục bin/ !"
fi

# 5. Khởi động / reload PM2 service
echo "--> [5/5] Reload PM2 service (ota-finder)..."
pm2 startOrReload ecosystem.config.cjs

echo "================================================================================"
echo "✅ DEPLOY HOÀN TẤT THÀNH CÔNG!"
echo "👉 Truy cập Web UI tại: http://localhost:8090"
echo "================================================================================"
