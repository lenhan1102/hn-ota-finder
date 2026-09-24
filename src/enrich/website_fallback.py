"""
website_fallback.py — Quét website của Agency để tìm email phòng ban.

Áp dụng quy tắc Fallback BR-01.2:
  Khi không tìm được nhân sự cụ thể (Tier 1-3), thu thập email phòng ban
  (sales@, booking@, info@...) từ các trang Contact/About/Team.
"""

import re
from typing import List, Optional

import httpx

try:
    from .models import ContactPerson, ContactTier
    from .email_resolver import clean_domain
except ImportError:
    from models import ContactPerson, ContactTier  # type: ignore
    from email_resolver import clean_domain  # type: ignore


EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    re.IGNORECASE,
)

# Từ khoá phân loại email phòng ban → score
TIER_4_PREFERRED = [
    "sales", "booking", "reservations", "ticketing", "flight",
    "biz", "business", "bd", "partner", "commercial",
]
TIER_4_SECONDARY = [
    "contact", "support", "help", "service", "cs", "team",
]
TIER_4_GENERIC = [
    "info", "hello", "hi", "mail", "email", "admin", "office",
]


async def scrape_department_emails(
    domain: str,
) -> List[ContactPerson]:
    """
    Quét website của Agency để tìm email phòng ban theo quy tắc Fallback BR-01.2.
    """
    contacts: List[ContactPerson] = []
    clean_d = clean_domain(domain)
    target_paths = ["/contact", "/about", "/team", "/contact-us", "/about-us", "/reach-us"]
    found_emails = set()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=6.0,
        ) as client:
            for path in target_paths:
                url = f"https://{clean_d}{path}"
                try:
                    res = await client.get(url)
                    if res.status_code != 200:
                        continue
                    text = res.text

                    # Thu thập từ href="mailto:..."
                    mailtos = re.findall(r'href=[\'"]mailto:([^\'"?]+)', text, re.IGNORECASE)
                    for m in mailtos:
                        found_emails.add(m.strip())

                    # Thu thập từ text thô (regex)
                    matches = EMAIL_REGEX.findall(text)
                    for match in matches:
                        em = match.strip().lower()
                        if "@" not in em:
                            continue
                        # Loại email của third-party (sentry, wixpress...)
                        if any(
                            em.endswith(ext)
                            for ext in ["sentry.io", "wixpress.com", "example.com", ".png", ".jpg"]
                        ):
                            continue
                        found_emails.add(em)

                except Exception:
                    continue
    except Exception as e:
        print(f"[website_fallback] scrape_department_emails lỗi: {e}")

    # Phân loại và tạo ContactPerson cho từng email tìm được
    for em in found_emails:
        local = em.split("@")[0].lower()

        # Tính score ưu tiên
        if any(pref in local for pref in TIER_4_PREFERRED):
            score = 0.75
            dept_name = next(p for p in TIER_4_PREFERRED if p in local)
        elif any(sec in local for sec in TIER_4_SECONDARY):
            score = 0.55
            dept_name = next(s for s in TIER_4_SECONDARY if s in local)
        elif any(gen in local for gen in TIER_4_GENERIC):
            score = 0.40
            dept_name = next(g for g in TIER_4_GENERIC if g in local)
        else:
            score = 0.30
            dept_name = local

        contacts.append(ContactPerson(
            full_name="",
            first_name="",
            last_name="",
            title=f"{dept_name.title()} Department",
            tier=ContactTier.TIER_4,
            email=em,
            confidence_score=score,
            source="website_fallback",
            discovery_method="website_fallback",
        ))

    # Sắp xếp theo score cao nhất trước
    return sorted(contacts, key=lambda x: x.confidence_score, reverse=True)
