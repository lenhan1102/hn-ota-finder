"""
Script debug trực tiếp website_fallback cho smiletrip.jp
Chạy: .venv/bin/python debug_smiletrip.py
"""
import asyncio
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from src.enrich.website_fallback import scrape_department_emails
    from src.enrich.email_resolver import clean_domain
except ImportError:
    from enrich.website_fallback import scrape_department_emails  # type: ignore
    from enrich.email_resolver import clean_domain  # type: ignore
import httpx
import re

EMAIL_REGEX = re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,10}\b")

async def main():
    domain = "smiletrip.jp"
    clean_d = clean_domain(domain)

    print(f"\n=== Test trực tiếp httpx → smiletrip.jp ===")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    # Thử trực tiếp các URL quan trọng
    test_urls = [
        f"https://{clean_d}",
        f"https://{clean_d}/about-us.htm",
        f"https://{clean_d}/contact.htm",
        f"https://{clean_d}/about",
        f"https://{clean_d}/contact",
    ]

    async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True, verify=False) as client:
        for url in test_urls:
            try:
                res = await client.get(url)
                text = res.text

                mailtos = re.findall(r'href=[\'"]mailto:([^\'"?\s]+)', text, flags=re.IGNORECASE)
                regex_emails = EMAIL_REGEX.findall(text)

                # Filter smiletrip.jp domain
                filtered_mailtos = [m for m in mailtos if "@" in m]
                filtered_regex = [e for e in regex_emails if "smiletrip" in e.lower()]

                print(f"\n  URL: {url}")
                print(f"  → HTTP {res.status_code} | final_url={str(res.url)[:80]}")
                print(f"  → mailto raw: {filtered_mailtos}")
                print(f"  → regex (smiletrip only): {filtered_regex}")
                print(f"  → body preview: {text[:300].replace(chr(10), ' ')}")
            except Exception as e:
                print(f"\n  URL: {url} → LỖI: {e}")

    print(f"\n\n=== Chạy scrape_department_emails() đầy đủ ===")
    contacts = await scrape_department_emails(domain)
    print(f"\nKết quả cuối: {len(contacts)} contact(s)")
    for c in contacts:
        print(f"  → {c.email} | tier={c.tier} | score={c.confidence_score}")

asyncio.run(main())
