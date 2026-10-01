"""
Debug: xem raw HTML của about-us.htm để tìm email nằm ở đâu
"""
import asyncio
import httpx
import re

async def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True, verify=False) as client:
        res = await client.get("https://smiletrip.jp/about-us.htm")
        html = res.text

        print(f"HTTP {res.status_code} | body_length={len(html)}")
        print(f"\n--- Tìm từ khóa 'smiletrip' trong HTML ---")
        lines = html.split("\n")
        for i, line in enumerate(lines):
            if "smiletrip" in line.lower() and ("@" in line or "mail" in line.lower()):
                print(f"  Line {i}: {line.strip()[:200]}")

        print(f"\n--- Tìm '@' trong toàn bộ HTML ---")
        at_matches = [line.strip()[:200] for line in lines if "@" in line and len(line.strip()) < 500]
        for m in at_matches[:30]:
            print(f"  {m}")

        print(f"\n--- Tìm 'office' / 'airticket' / 'osaka' ---")
        for keyword in ["office", "airticket", "osaka", "contact", "mail"]:
            for i, line in enumerate(lines):
                if keyword in line.lower() and len(line.strip()) > 3:
                    print(f"  [{keyword}] Line {i}: {line.strip()[:200]}")

        # Tìm trong script tags
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
        print(f"\n--- Script tags ({len(scripts)} found) ---")
        for j, sc in enumerate(scripts):
            if "@" in sc or "smiletrip" in sc.lower():
                print(f"  Script {j}: {sc[:500]}")

asyncio.run(main())
