"""
discovery.py — Tìm kiếm nhân sự (Contact Discovery) cho leads.

Hỗ trợ 2 phương pháp:
  1. Google Dorking (Serper / SerpAPI / HTTP fallback) — không cần cookie
  2. Playwright Chromium cào trực tiếp LinkedIn — cần cookie 'li_at'
"""

import os
import re
from typing import List, Optional, Tuple
from urllib import parse

import httpx

try:
    from .models import ContactPerson, ContactTier
except ImportError:
    from models import ContactPerson, ContactTier  # type: ignore


# ─── Danh sách từ khoá phân loại chức danh → Tier ────────────────────────────
TIER_1 = [
    "ceo", "chief executive", "founder", "co-founder", "managing director",
    "president", "owner", "proprietor", "director general",
]

TIER_2 = [
    "head of business development", "business development", "bd manager",
    "head of partnerships", "partnerships", "head of ticketing", "ticketing manager",
    "head of flight", "flight operations", "head of aviation",
    "commercial director", "vp sales", "vice president sales",
]

TIER_3 = [
    "manager", "supervisor", "team lead", "senior", "lead",
    "deputy", "assistant manager",
]

TIER_KEYWORDS = {
    ContactTier.TIER_1: TIER_1,
    ContactTier.TIER_2: TIER_2,
    ContactTier.TIER_3: TIER_3,
}


def classify_title(title: str) -> ContactTier:
    """Phân loại chức danh → ContactTier."""
    t = title.lower().strip()
    for tier, keywords in TIER_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return tier
    return ContactTier.TIER_4


def split_full_name(full_name: str) -> Tuple[str, str]:
    """Tách họ và tên từ full_name."""
    parts = [p.strip() for p in full_name.strip().split() if p.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


async def discover_via_google_dorking(
    company_name: str,
    domain: str,
    country: str = "vietnam",
) -> List[ContactPerson]:
    """
    Tìm kiếm nhân sự trên LinkedIn thông qua Google Search Dorking.
    Ưu tiên gọi Serper.dev / SerpAPI nếu có API Key, nếu không sẽ gọi HTTP search fallback.
    """
    contacts: List[ContactPerson] = []
    serper_api_key = os.getenv("SERPER_API_KEY", "").strip()
    serpapi_key = os.getenv("SERPAPI_API_KEY", "").strip()

    # Làm sạch tên công ty
    clean_company = re.sub(
        r"(co\.,\s*ltd\.?|ltd\.?|inc\.?|corp\.?|travel|agency)",
        "", company_name, flags=re.IGNORECASE
    ).strip()

    query = (
        f'site:linkedin.com/in/ "{clean_company}" '
        f'("CEO" OR "Founder" OR "Managing Director" OR "Head of Business Development" '
        f'OR "Partnerships" OR "Ticketing" OR "Head of Flight")'
    )

    raw_items = []

    try:
        if serper_api_key:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://google.serper.dev/search",
                    json={"q": query, "gl": "vn", "hl": "en", "num": 10},
                    headers={
                        "X-API-KEY": serper_api_key,
                        "Content-Type": "application/json",
                    },
                    timeout=10.0,
                )
                if res.status_code == 200:
                    data = res.json()
                    raw_items = data.get("organic", [])

        elif serpapi_key:
            encoded_q = parse.quote(query)
            url = f"https://serpapi.com/search?q={encoded_q}&api_key={serpapi_key}&num=10"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10.0)
                if resp.status_code == 200:
                    raw_items = resp.json().get("organic_results", [])

        else:
            # HTTP fallback — gọi Google trực tiếp (dễ bị giới hạn)
            encoded_q = parse.quote(query)
            url = f"https://www.google.com/search?q={encoded_q}&num=10"
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    links = re.findall(r'href="(https://www\.linkedin\.com/in/[^"]+)"', resp.text)
                    titles = re.findall(r'<h3[^>]*>([^<]+)</h3>', resp.text)
                    raw_items = [{"link": l, "title": t} for l, t in zip(links, titles)]

    except Exception as e:
        print(f"[discovery] discover_via_google_dorking lỗi: {e}")

    # Parse raw_items → ContactPerson
    for org in raw_items:
        title_raw = org.get("title", "")
        # Trích tên — thường định dạng "Nguyễn Văn A - CEO tại ABC Corp | LinkedIn"
        m = re.match(r"^([^|\-–]+)[\-–|]", title_raw)
        name_str = m.group(1).strip() if m else title_raw.split("|")[0].strip()
        # Trích chức danh
        title_parts = title_raw.split("|")[0].split("-")
        title_str = title_parts[1].strip() if len(title_parts) >= 2 else ""

        first_name, last_name = split_full_name(name_str)
        tier = classify_title(title_str)

        contacts.append(ContactPerson(
            full_name=name_str,
            first_name=first_name,
            last_name=last_name,
            title=title_str,
            tier=tier,
            linkedin_url=org.get("link", ""),
            source="google_dorking",
            discovery_method="google_dorking",
            confidence_score=0.7 if tier in (ContactTier.TIER_1, ContactTier.TIER_2) else 0.5,
        ))

    return sorted(contacts, key=lambda c: c.tier)


async def discover_via_playwright(
    company_name: str,
    domain: str,
    linkedin_cookie: str = "",
    country: str = "vietnam",
) -> List[ContactPerson]:
    """
    Cào sâu trực tiếp LinkedIn sử dụng Playwright Chromium.
    Có thể nạp cookie 'li_at' nếu người dùng cung cấp.
    """
    contacts: List[ContactPerson] = []
    cookie_val = linkedin_cookie or os.getenv("LINKEDIN_COOKIE_LI_AT", "").strip()

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[Playwright] Thư viện playwright chưa được cài đặt.")
        return contacts

    clean_company = re.sub(
        r"(co\.,\s*ltd\.?|ltd\.?|inc\.?|corp\.?|travel|agency)",
        "", company_name, flags=re.IGNORECASE
    ).strip()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                ),
            )
            if cookie_val:
                await context.add_cookies([{
                    "name": "li_at",
                    "value": cookie_val,
                    "domain": ".linkedin.com",
                    "path": "/",
                }])
            page = await context.new_page()

            keywords = (
                "CEO OR Founder OR Managing+Director "
                "OR Business+Development OR Ticketing"
            )
            search_url = (
                f"https://www.linkedin.com/search/results/people/"
                f"?keywords={parse.quote(clean_company)}+{keywords}"
            )
            await page.goto(search_url, timeout=15000)
            await page.wait_for_timeout(2000)

            cards = await page.query_selector_all(".entity-result__item")
            for card in cards[:10]:
                name_elem = await card.query_selector(".entity-result__title-text")
                title_elem = await card.query_selector(".entity-result__primary-subtitle")
                if not name_elem:
                    continue
                name_text = (await name_elem.inner_text()).strip()
                title_text = (await title_elem.inner_text()).strip() if title_elem else ""
                link_elem = await card.query_selector("a.app-aware-link")
                link_href = (await link_elem.get_attribute("href") or "") if link_elem else ""

                first_name, last_name = split_full_name(name_text)
                tier = classify_title(title_text)

                contacts.append(ContactPerson(
                    full_name=name_text,
                    first_name=first_name,
                    last_name=last_name,
                    title=title_text,
                    tier=tier,
                    linkedin_url=link_href,
                    source="playwright_linkedin",
                    discovery_method="playwright_linkedin",
                    confidence_score=0.85 if tier in (ContactTier.TIER_1, ContactTier.TIER_2) else 0.6,
                ))

            await browser.close()
    except Exception as e:
        print(f"[discovery] discover_via_playwright lỗi: {e}")

    return sorted(contacts, key=lambda c: c.tier)
