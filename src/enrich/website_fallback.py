import re
from typing import List, Optional
import httpx

from .models import ContactPerson, ContactTier
from .email_resolver import clean_domain

# Từ khóa phòng ban chuyên trách theo Rule BR-01.2
TIER_4_PREFERRED = ["partnerships@", "partner@", "contracting@", "b2b@", "air@", "ticketing@"]
TIER_4_SECONDARY = ["commercial@", "business@", "sales@", "inquiry@"]
TIER_4_GENERIC = ["info@", "contact@", "support@", "admin@", "help@"]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


async def scrape_department_emails(domain: str) -> List[ContactPerson]:
    """
    Quét website của Agency để tìm email phòng ban theo quy tắc Fallback BR-01.2.
    """
    contacts: List[ContactPerson] = []
    clean_d = clean_domain(domain)
    if not clean_d:
        return contacts

    target_paths = [
        "",
        "/contact",
        "/contact-us",
        "/about",
        "/about-us",
        "/partnerships",
        "/b2b"
    ]

    found_emails = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    async with httpx.AsyncClient(headers=headers, timeout=6.0, follow_redirects=True, verify=False) as client:
        for path in target_paths:
            url = f"https://{clean_d}{path}"
            try:
                res = await client.get(url)
                if res.status_code == 200:
                    text = res.text
                    # 1. Quét qua mailto:
                    mailtos = re.findall(r'href=[\'"]mailto:([^\'"?]+)', text, flags=re.IGNORECASE)
                    for m in mailtos:
                        clean_m = m.strip().lower()
                        if "@" in clean_m:
                            found_emails.add(clean_m)

                    # 2. Quét qua regex
                    matches = EMAIL_REGEX.findall(text)
                    for match in matches:
                        clean_m = match.strip().lower()
                        # Loại bỏ các file ảnh hoặc domain rác
                        if not any(clean_m.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"]):
                            if "sentry" not in clean_m and "wixpress" not in clean_m and "schema.org" not in clean_m:
                                found_emails.add(clean_m)
            except Exception:
                continue

    if not found_emails:
        return contacts

    # Phân loại danh sách email theo độ ưu tiên
    classified = []
    for em in found_emails:
        # Chỉ ưu tiên email có cùng domain hoặc tên thương hiệu
        score = 0
        em_lower = em.lower()
        if any(pref in em_lower for pref in TIER_4_PREFERRED):
            score = 3
        elif any(sec in em_lower for sec in TIER_4_SECONDARY):
            score = 2
        elif any(gen in em_lower for gen in TIER_4_GENERIC):
            score = 1

        classified.append((score, em))

    # Sắp xếp theo score giảm dần
    classified.sort(key=lambda x: x[0], reverse=True)

    for score, em in classified:
        dept_name = em.split("@")[0].capitalize()
        contacts.append(
            ContactPerson(
                full_name=f"{dept_name} Department",
                first_name=dept_name,
                last_name="Team",
                title=f"{dept_name} Operations",
                tier=ContactTier.TIER_4,
                tier_label="Tier 4: Fallback Department Contact",
                email=em,
                is_primary=False,
                source="website_fallback",
                verification_status="fallback",
                confidence_score=70.0 if score >= 2 else 50.0
            )
        )

    return contacts
