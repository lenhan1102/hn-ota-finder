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

    print(f"[Dorking] ▶ Bắt đầu tìm kiếm nhân sự cho: '{company_name}' | domain={domain}")
    print(f"[Dorking] 🔍 Query: {query}")
    print(f"[Dorking] 🔑 Serper key: {'CÓ' if serper_api_key else 'KHÔNG'} | SerpAPI key: {'CÓ' if serpapi_key else 'KHÔNG'}")

    raw_items = []

    # 1. Thử dùng Serper API nếu có key
    if serper_api_key:
        print("[Dorking] → Gọi Serper.dev API...")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": serper_api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": 5}
                )
                print(f"[Dorking] Serper status: {res.status_code}")
                if res.status_code == 200:
                    data = res.json()
                    organic = data.get("organic", [])
                    print(f"[Dorking] Serper trả về {len(organic)} kết quả organic")
                    for org in organic:
                        raw_items.append({
                            "title": org.get("title", ""),
                            "link": org.get("link", ""),
                            "snippet": org.get("snippet", "")
                        })
                else:
                    print(f"[Dorking] Serper lỗi HTTP {res.status_code}: {res.text[:200]}")
        except Exception as e:
            print(f"[Dorking] Serper API exception: {e}")

    # 2. Thử dùng SerpAPI nếu có key
    elif serpapi_key:
        print("[Dorking] → Gọi SerpAPI...")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    "https://serpapi.com/search.json",
                    params={"q": query, "api_key": serpapi_key, "num": 5}
                )
                print(f"[Dorking] SerpAPI status: {res.status_code}")
                if res.status_code == 200:
                    data = res.json()
                    organic = data.get("organic_results", [])
                    print(f"[Dorking] SerpAPI trả về {len(organic)} kết quả organic")
                    for org in organic:
                        raw_items.append({
                            "title": org.get("title", ""),
                            "link": org.get("link", ""),
                            "snippet": org.get("snippet", "")
                        })
                else:
                    print(f"[Dorking] SerpAPI lỗi HTTP {res.status_code}: {res.text[:200]}")
        except Exception as e:
            print(f"[Dorking] SerpAPI exception: {e}")

    # 3. Fallback: Truy vấn qua DuckDuckGo HTML
    if not raw_items:
        print("[Dorking] → Không có API key hoặc API trả về rỗng, fallback DuckDuckGo HTML...")
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            encoded_q = urllib.parse.quote(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
            print(f"[Dorking] DuckDuckGo URL: {url[:120]}")
            async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url)
                print(f"[Dorking] DuckDuckGo status: {resp.status_code} | body_len={len(resp.text)}")
                if resp.status_code == 200:
                    links = re.findall(r'class="result__url"[^>]*href="([^"]+)"', resp.text)
                    titles = re.findall(r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>', resp.text, re.DOTALL)
                    print(f"[Dorking] DuckDuckGo tìm thấy {len(links)} link, {len(titles)} title")
                    linkedin_count = 0
                    for l, t in zip(links, titles):
                        clean_t = re.sub(r"<[^>]+>", "", t).strip()
                        if "linkedin.com/in/" in l:
                            linkedin_count += 1
                            raw_items.append({"title": clean_t, "link": l, "snippet": ""})
                    print(f"[Dorking] DuckDuckGo linkedin.com/in/ links: {linkedin_count}")
                else:
                    print(f"[Dorking] DuckDuckGo lỗi HTTP {resp.status_code}")
        except Exception as e:
            print(f"[Dorking] DuckDuckGo exception: {e}")

    print(f"[Dorking] Tổng raw_items trước khi phân tích: {len(raw_items)}")

    # Xử lý kết quả bóc tách được
    for item in raw_items:
        raw_t = item.get("title", "")
        link = item.get("link", "")
        if "linkedin.com/in/" not in link:
            continue

        name, title = parse_linkedin_search_title(raw_t)
        if not title and item.get("snippet"):
            title = item.get("snippet")

        tier_num, tier_label = classify_title(title)
        first_name, last_name = split_full_name(name)

        print(f"[Dorking]   item: name='{name}' | title='{title}' | tier={tier_num}")

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

    contacts.sort(key=lambda c: c.tier)
    print(f"[Dorking] ✅ Kết quả cuối: {len(contacts)} nhân sự Tier 1-3 tìm được")
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

    # Bảo vệ: Xóa PLAYWRIGHT_BROWSERS_PATH nếu đường dẫn không tồn tại trên máy hiện tại
    pw_path = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
    if pw_path and not os.path.exists(pw_path):
        del os.environ["PLAYWRIGHT_BROWSERS_PATH"]

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[Playwright] Thư viện playwright chưa được cài đặt.")
        return contacts

    env_headless = os.getenv("ENRICH_HEADLESS", "").strip().lower()
    is_headless = env_headless in ["true", "1", "yes"]

    try:
        async with async_playwright() as p:
            print(f"[Playwright] 🚀 Khởi động Chromium trực quan (headless={is_headless})...")
            browser = await p.chromium.launch(
                headless=is_headless,
                slow_mo=300 if not is_headless else 0,
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 850}
            )

            # Nạp cookie nếu có
            if cookie_val:
                print("[Playwright] 🔑 Nạp cookie li_at cho LinkedIn...")
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
                print(f"[Playwright] 🌐 Mở trang tìm kiếm LinkedIn: {search_url}")
                try:
                    await page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
                except Exception as nav_err:
                    if "ERR_TOO_MANY_REDIRECTS" in str(nav_err):
                        print("[Playwright] ⚠️ Cookie 'li_at' đã hết hạn hoặc bị LinkedIn checkpoint. Đang xóa cookie và tải lại trang...")
                        await context.clear_cookies()
                        await page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
                    else:
                        raise nav_err

                await page.wait_for_timeout(3000)

                # Kiểm tra và đóng banner consent cookie nếu có
                try:
                    for btn in await page.query_selector_all("button"):
                        txt = (await btn.inner_text()).lower()
                        if any(k in txt for k in ["chấp nhận", "đồng ý", "accept", "agree", "allow"]):
                            await btn.click()
                            print(f"[Playwright] ✔ Đã nhấn nút đồng ý cookie: {txt[:30]}")
                            await page.wait_for_timeout(1000)
                            break
                except Exception:
                    pass

                current_url = page.url
                page_title = await page.title()
                print(f"[Playwright] 📌 URL hiện tại: {current_url} | Tiêu đề: {page_title}")

                # Bóc tách danh sách kết quả
                cards = await page.query_selector_all(".reusable-search__result-container, .entity-result, li.artdeco-list__item")
                print(f"[Playwright] 📄 Tìm thấy {len(cards)} thẻ nhân sự trên trang...")

                for card in cards[:6]:
                    name_elem = await card.query_selector(".entity-result__title-text a, .app-aware-link, a[data-test-app-aware-link]")
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
                            print(f"[Playwright]   ✔ Nhân sự: {name_text} | Title: {title_text} | Tier: {tier_num}")
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

                if not is_headless:
                    # Giữ cửa sổ 3s để người dùng kịp quan sát kết quả trực quan
                    await page.wait_for_timeout(3000)

            except Exception as e:
                print(f"[Playwright] ❌ Lỗi trong lúc cào trang LinkedIn: {e}")
                if not is_headless:
                    await page.wait_for_timeout(2000)
            finally:
                await browser.close()
    except Exception as ex:
        print(f"[Playwright] ❌ Lỗi khởi động trình duyệt: {ex}")

    contacts.sort(key=lambda c: c.tier)
    print(f"[Playwright] ✅ Tìm được {len(contacts)} nhân sự qua Playwright LinkedIn")
    return contacts
