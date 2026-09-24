import os
import re
import urllib.parse
from typing import List, Optional, Tuple
import httpx

from .models import ContactPerson, ContactTier

# Danh mục từ khóa phân loại chức danh theo đúng đặc tả PRD Feature 2
TIER_KEYWORDS = {
    ContactTier.TIER_1: [
        r"\bceo\b", r"\bfounder\b", r"\bco-founder\b", r"\bmanaging director\b",
        r"\bowner\b", r"\bco-owner\b", r"\bpresident\b", r"\bchief executive\b",
        r"\bgeneral manager\b", r"\bgm\b"
    ],
    ContactTier.TIER_2: [
        r"\bhead of business development\b", r"\bhead of bd\b", r"\bbusiness development director\b",
        r"\bbd director\b", r"\bhead of partnerships\b", r"\bpartnership director\b",
        r"\bchief commercial officer\b", r"\bcco\b", r"\bbusiness development manager\b",
        r"\bcommercial director\b"
    ],
    ContactTier.TIER_3: [
        r"\bhead of flight\b", r"\bhead of ticketing\b", r"\bair ticketing manager\b",
        r"\bticketing manager\b", r"\bflight manager\b", r"\bticketing director\b",
        r"\bairline distribution\b", r"\bair product\b"
    ]
}


def classify_title(title: str) -> Tuple[int, str]:
    """Phân loại chức danh vào Tier 1, 2, 3 hoặc 0 (chưa rõ)."""
    if not title:
        return 0, "Unknown"

    t_lower = title.lower()

    # Kiểm tra theo thứ tự Tier 1 -> Tier 2 -> Tier 3
    for pattern in TIER_KEYWORDS[ContactTier.TIER_1]:
        if re.search(pattern, t_lower):
            return 1, "Tier 1: CEO / Founder / MD"

    for pattern in TIER_KEYWORDS[ContactTier.TIER_2]:
        if re.search(pattern, t_lower):
            return 2, "Tier 2: Head of BD / Partnerships"

    for pattern in TIER_KEYWORDS[ContactTier.TIER_3]:
        if re.search(pattern, t_lower):
            return 3, "Tier 3: Head of Flight / Ticketing"

    return 0, "Other Staff"


def split_full_name(full_name: str) -> Tuple[str, str]:
    """Tách Full Name thành First Name và Last Name."""
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def parse_linkedin_search_title(raw_title: str) -> Tuple[str, str]:
    """
    Phân tích thẻ title từ Google Search:
    Ví dụ: 'Tan Boon - Head of Ticketing & Operations - 12Go | LinkedIn'
    Trả về: (full_name, job_title)
    """
    clean_title = re.sub(r"\s*\|\s*LinkedIn.*$", "", raw_title, flags=re.IGNORECASE)
    parts = [p.strip() for p in clean_title.split(" - ")]

    if len(parts) >= 2:
        name = parts[0]
        title = parts[1]
        return name, title
    elif len(parts) == 1 and "-" in parts[0]:
        subparts = [p.strip() for p in parts[0].split("-")]
        if len(subparts) >= 2:
            return subparts[0], subparts[1]

    return clean_title, ""


async def discover_via_google_dorking(
    company_name: str,
    domain: str,
    country: str = ""
) -> List[ContactPerson]:
    """
    Tìm kiếm nhân sự trên LinkedIn thông qua Google Search Dorking.
    Ưu tiên gọi Serper.dev / SerpAPI nếu có API Key, nếu không sẽ gọi HTTP search fallback.
    """
    contacts: List[ContactPerson] = []
    serper_api_key = os.getenv("SERPER_API_KEY", "").strip()
    serpapi_key = os.getenv("SERPAPI_API_KEY", "").strip()

    # Làm sạch tên công ty để query chính xác
    clean_company = re.sub(r"(co\.,\s*ltd\.?|ltd\.?|inc\.?|corp\.?|travel|agency)", "", company_name, flags=re.IGNORECASE).strip()
    if not clean_company:
        clean_company = company_name

    query = (
        f'site:linkedin.com/in/ "{clean_company}" '
        f'("CEO" OR "Founder" OR "Managing Director" OR "Head of Business Development" OR "Partnerships" OR "Ticketing" OR "Head of Flight")'
    )

    raw_items = []

    # 1. Thử dùng Serper API nếu có key
    if serper_api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": serper_api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": 5}
                )
                if res.status_code == 200:
                    data = res.json()
                    for org in data.get("organic", []):
                        raw_items.append({
                            "title": org.get("title", ""),
                            "link": org.get("link", ""),
                            "snippet": org.get("snippet", "")
                        })
        except Exception as e:
            print(f"[Dorking] Serper API error: {e}")

    # 2. Thử dùng SerpAPI nếu có key
    elif serpapi_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    "https://serpapi.com/search.json",
                    params={"q": query, "api_key": serpapi_key, "num": 5}
                )
                if res.status_code == 200:
                    data = res.json()
                    for org in data.get("organic_results", []):
                        raw_items.append({
                            "title": org.get("title", ""),
                            "link": org.get("link", ""),
                            "snippet": org.get("snippet", "")
                        })
        except Exception as e:
            print(f"[Dorking] SerpAPI error: {e}")

    # 3. Fallback: Truy vấn qua DuckDuckGo HTML / SearXNG mở
    if not raw_items:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            encoded_q = urllib.parse.quote(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
            async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    # Regex bóc tách các kết quả linkedin
                    links = re.findall(r'class="result__url"[^>]*href="([^"]+)"', resp.text)
                    titles = re.findall(r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>', resp.text, re.DOTALL)
                    for l, t in zip(links, titles):
                        clean_t = re.sub(r"<[^>]+>", "", t).strip()
                        if "linkedin.com/in/" in l:
                            raw_items.append({"title": clean_t, "link": l, "snippet": ""})
        except Exception as e:
            print(f"[Dorking] Fallback search error: {e}")

    # Xử lý kết quả bóc tách được
    for item in raw_items:
        raw_t = item.get("title", "")
        link = item.get("link", "")
        if "linkedin.com/in/" not in link:
            continue

        name, title = parse_linkedin_search_title(raw_t)
        # Nếu title chưa rõ, thử tìm trong snippet
        if not title and item.get("snippet"):
            title = item.get("snippet")

        tier_num, tier_label = classify_title(title)
        first_name, last_name = split_full_name(name)

        if tier_num in [1, 2, 3]:
            contacts.append(
                ContactPerson(
                    full_name=name,
                    first_name=first_name,
                    last_name=last_name,
                    title=title,
                    tier=tier_num,
                    tier_label=tier_label,
                    linkedin_url=link,
                    source="google_dorking",
                    confidence_score=90.0 if tier_num == 1 else (85.0 if tier_num == 2 else 75.0)
                )
            )

    # Sắp xếp kết quả theo độ ưu tiên: Tier 1 > Tier 2 > Tier 3
    contacts.sort(key=lambda c: c.tier)
    return contacts


async def discover_via_playwright(
    company_name: str,
    domain: str,
    linkedin_cookie: Optional[str] = None,
    country: str = ""
) -> List[ContactPerson]:
    """
    Cào sâu trực tiếp LinkedIn sử dụng Playwright Chromium.
    Có thể nạp cookie 'li_at' nếu người dùng cung cấp.
    """
    contacts: List[ContactPerson] = []
    cookie_val = linkedin_cookie or os.getenv("LINKEDIN_COOKIE_LI_AT", "").strip()

    clean_company = re.sub(r"(co\.,\s*ltd\.?|ltd\.?|inc\.?|corp\.?|travel|agency)", "", company_name, flags=re.IGNORECASE).strip()
    if not clean_company:
        clean_company = company_name

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[Playwright] Thư viện playwright chưa được cài đặt.")
        return contacts

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )

            # Nạp cookie nếu có
            if cookie_val:
                await context.add_cookies([{
                    "name": "li_at",
                    "value": cookie_val,
                    "domain": ".linkedin.com",
                    "path": "/"
                }])

            page = await context.new_page()

            # URL tìm kiếm nhân sự của công ty
            keywords = urllib.parse.quote(f"{clean_company} CEO OR Founder OR Partnerships OR Ticketing")
            search_url = f"https://www.linkedin.com/search/results/people/?keywords={keywords}"

            try:
                await page.goto(search_url, timeout=12000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # Bóc tách danh sách kết quả
                cards = await page.query_selector_all(".reusable-search__result-container, .entity-result")

                for card in cards[:5]:
                    name_elem = await card.query_selector(".entity-result__title-text a, .app-aware-link")
                    title_elem = await card.query_selector(".entity-result__primary-subtitle")

                    name_text = (await name_elem.inner_text()).strip() if name_elem else ""
                    # Lấy link profile
                    link_href = (await name_elem.get_attribute("href")) if name_elem else ""
                    if link_href and "?" in link_href:
                        link_href = link_href.split("?")[0]

                    title_text = (await title_elem.inner_text()).strip() if title_elem else ""

                    if name_text and "LinkedIn Member" not in name_text:
                        tier_num, tier_label = classify_title(title_text)
                        if tier_num in [1, 2, 3]:
                            first_n, last_n = split_full_name(name_text)
                            contacts.append(
                                ContactPerson(
                                    full_name=name_text,
                                    first_name=first_n,
                                    last_name=last_n,
                                    title=title_text,
                                    tier=tier_num,
                                    tier_label=tier_label,
                                    linkedin_url=link_href,
                                    source="playwright_linkedin",
                                    confidence_score=95.0 if tier_num == 1 else (85.0 if tier_num == 2 else 80.0)
                                )
                            )
            except Exception as e:
                print(f"[Playwright] Error during page crawl: {e}")
            finally:
                await browser.close()
    except Exception as ex:
        print(f"[Playwright] Launch error: {ex}")

    contacts.sort(key=lambda c: c.tier)
    return contacts
