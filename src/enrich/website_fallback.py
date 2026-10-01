import re
from typing import List, Optional, Set
import httpx

from .models import ContactPerson, ContactTier
from .email_resolver import clean_domain

# Từ khóa phòng ban chuyên trách theo Rule BR-01.2 (hỗ trợ cả Tiếng Anh và Tiếng Việt)
TIER_4_PREFERRED = [
    "partnerships@", "partner@", "contracting@", "b2b@", "air@", "ticketing@",
    "kinhdoanh", "phongve", "datve", "daily", "vemaybay"
]
TIER_4_SECONDARY = [
    "commercial@", "business@", "sales@", "inquiry@", "booking@", "reservation@",
    "banhang", "hotro", "cskh", "tuvan"
]
TIER_4_GENERIC = ["info@", "contact@", "support@", "admin@", "help@", "office@"]

# Regex nhận diện email chuẩn quốc tế (yêu cầu domain có TLD chỉ chứa chữ từ 2 đến 10 ký tự)
EMAIL_REGEX = re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,10}\b")

# Danh sách đuôi tệp tin hoặc TLD không hợp lệ thường bị parse nhầm thành email
DISALLOWED_TLDS = {
    "png", "jpg", "jpeg", "gif", "webp", "svg", "js", "css", "json",
    "woff", "woff2", "ttf", "otf", "map", "ico", "pdf", "zip"
}

# Các domain dịch vụ kỹ thuật, CDN, tracking hoặc mạng xã hội không phải email đại lý
DISALLOWED_DOMAINS = {
    "sentry.io", "wixpress.com", "schema.org", "w3.org", "jsdelivr.net",
    "unpkg.com", "cloudflare.com", "github.com", "wordpress.org",
    "wordpress.com", "gravatar.com", "googleapis.com", "google.com",
    "gstatic.com", "facebook.com", "twitter.com", "example.com", "domain.com"
}

# Tên các thư viện / package frontend thường nằm trong URL dạng package@version (vd: bootstrap@5.3.3)
DISALLOWED_PREFIXES = {
    "bootstrap", "bootstrap-icons", "jquery", "react", "vue", "angular",
    "swiper", "fontawesome", "font-awesome", "popper", "lodash", "core-js",
    "webpack", "tailwind", "icon", "icons", "glyphicons"
}

# Regex tìm email bị mã hóa bởi Cloudflare Email Protection
# Dạng: data-cfemail="b5d4dcc7..."  hoặc  class="__cf_email__" data-cfemail="..."
CF_EMAIL_REGEX = re.compile(r'data-cfemail=["\']([0-9a-fA-F]+)["\']')


def decode_cf_email(encoded: str) -> str:
    """
    Giải mã email bị Cloudflare mã hóa (Email Obfuscation).
    Thuật toán: byte đầu là key XOR, các byte còn lại XOR với key -> ra ký tự email.
    Tham khảo: https://usamaejaz.com/cloudflare-email-decoding/
    """
    try:
        data = bytes.fromhex(encoded)
        key = data[0]
        decoded = "".join(chr(b ^ key) for b in data[1:])
        return decoded
    except Exception:
        return ""



def is_valid_email(email: str) -> bool:
    """Kiểm tra một chuỗi có phải là email thực sự hợp lệ không, lọc bỏ rác CDN/Assets/Tech."""
    if not email or "@" not in email:
        return False

    parts = email.lower().split("@")
    if len(parts) != 2:
        return False

    local_part, domain_part = parts[0].strip(), parts[1].strip()

    # 1. Kiểm tra local-part
    if len(local_part) < 2 or len(local_part) > 64:
        return False
    if any(bad_prefix in local_part for bad_prefix in DISALLOWED_PREFIXES):
        return False

    # 2. Kiểm tra domain-part
    domain_subparts = domain_part.split(".")
    if len(domain_subparts) < 2:
        return False

    # Không cho phép domain có thành phần hoàn toàn là số (như 5.3.3)
    if any(sub.isdigit() for sub in domain_subparts):
        return False

    tld = domain_subparts[-1]
    if not tld.isalpha() or len(tld) < 2 or tld in DISALLOWED_TLDS:
        return False

    # 3. Lọc bỏ các domain rác / dịch vụ kỹ thuật
    if any(bad_domain in domain_part for bad_domain in DISALLOWED_DOMAINS):
        return False

    return True


# Từ khóa đường dẫn cần tìm trong menu/nav của website (Đa ngôn ngữ & pháp lý JP/KR/VN/Global)
LINK_KEYWORDS = [
    "about", "contact", "company", "corporate", "profile", "offices", "office", "who-we-are",
    "about-us", "contact-us", "our-team", "team", "partner", "partnerships", "b2b",
    "tokushoho", "law", "legal", "footer", "gaiyou", "kaisya", "gioi-thieu", "lien-he"
]

# Từ khóa nhận diện API endpoint trả về office/contact JSON
OFFICE_API_KEYWORDS = ["office", "contact", "branch", "location", "staff", "team", "about"]


async def _discover_nav_links(
    html: str,
    base_domain: str,
    client: "httpx.AsyncClient"
) -> "tuple[list, set]":
    """
    Khám phá thông minh từ trang chủ qua 3 chiến lược:
    1. Quét <a href> tĩnh trong HTML -> lấy path có từ khóa liên quan
    2. Quét <script> tìm path (.htm/.php/.aspx) và API endpoint JSON
    3. Gọi trực tiếp API endpoint JSON để lấy email từ dữ liệu văn phòng

    Trả về: (discovered_paths: List[str], api_emails: Set[str])
    """
    import json as json_lib
    from urllib.parse import urlparse

    discovered_paths = []
    api_emails: set = set()
    seen_paths: set = set()

    # ── Chiến lược 1: Quét <a href> tĩnh ──────────────────────────────
    hrefs = re.findall(r'href=[\'"]([^\'"#?\s]{1,300})[\'"]', html, flags=re.IGNORECASE)
    for href in hrefs:
        href = href.strip()
        if not href or href.startswith("javascript:") or href == "/":
            continue
        if href.startswith("http"):
            if base_domain not in href:
                continue
            try:
                path = urlparse(href).path
            except Exception:
                continue
        elif href.startswith("/"):
            path = href
        else:
            path = "/" + href

        if not path or path in seen_paths:
            continue

        if any(kw in path.lower() for kw in LINK_KEYWORDS):
            seen_paths.add(path)
            discovered_paths.append(path)

    # ── Chiến lược 2: Quét nội dung <script> ──────────────────────────
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    candidate_api_urls = []

    for sc in scripts:
        # Tìm API URL patterns: url: '/xxx', fetch('/xxx')
        for pat in [
            r"url\s*:\s*['\"]([/][A-Za-z0-9_./?=&%-]{3,200})['\"]",
            r"fetch\s*\(\s*['\"]([/][A-Za-z0-9_./?=&%-]{3,200})['\"]",
            r"\"url\"\s*:\s*\"([/][A-Za-z0-9_./?=&%-]{3,200})\"",
        ]:
            for m in re.findall(pat, sc, re.IGNORECASE):
                m = m.replace("\\/", "/")
                if any(kw in m.lower() for kw in OFFICE_API_KEYWORDS) and m not in candidate_api_urls:
                    candidate_api_urls.append(m)

        # Tìm path tĩnh trong JS string: '/about-us.htm', '/contact.aspx'
        for pat in [
            r"['\"](/[A-Za-z0-9_\-/]+\.(?:htm|html|php|asp|aspx))['\"]",
            r"href\s*:\s*['\"](/[A-Za-z0-9_\-/]+\.(?:htm|html|php|asp|aspx))['\"]",
        ]:
            for m in re.findall(pat, sc, re.IGNORECASE):
                m = m.replace("\\/", "/")
                if any(kw in m.lower() for kw in LINK_KEYWORDS) and m not in seen_paths:
                    seen_paths.add(m)
                    discovered_paths.append(m)

    # ── Chiến lược 3: Gọi API endpoint JSON ───────────────────────────
    print(f"[Fallback] API candidates từ script: {candidate_api_urls}")
    for api_url in candidate_api_urls[:6]:
        full_url = f"https://{base_domain}{api_url}"
        try:
            r = await client.post(
                full_url, json={},
                headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
                timeout=5.0
            )
            if r.status_code != 200:
                r = await client.get(full_url, timeout=5.0)

            if r.status_code == 200 and len(r.text) < 200_000:
                ct = r.headers.get("content-type", "")
                body = r.text.strip()
                if "json" in ct or body.startswith("{") or body.startswith("["):
                    # Unwrap ASP.NET Web Method: {"d": "..."}
                    try:
                        outer = json_lib.loads(body)
                        if isinstance(outer, dict) and "d" in outer:
                            inner = outer["d"]
                            body = inner if isinstance(inner, str) else json_lib.dumps(inner)
                    except Exception:
                        pass

                    email_hits = re.findall(
                        r'"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,10})"',
                        body
                    )
                    for em in email_hits:
                        em = em.strip().lower()
                        if is_valid_email(em):
                            api_emails.add(em)
                            print(f"[Fallback] ✔ API email từ {api_url}: {em}")
        except Exception as ex:
            print(f"[Fallback] API {api_url} lỗi: {ex}")

    # ── Chiến lược 4: Đọc sâu file Component (Footer/Header/Common) ─────────
    # Nếu phát hiện template component tách rời như /component/footer.html, tải về bóc link
    component_paths = [p for p in list(discovered_paths) if any(c in p.lower() for c in ["footer", "header", "component", "common", "nav"])]
    for cp in component_paths[:3]:
        full_cp_url = f"https://{base_domain}{cp}"
        try:
            r_cp = await client.get(full_cp_url, timeout=4.0)
            if r_cp.status_code == 200:
                cp_text = r_cp.text
                for m in EMAIL_REGEX.findall(cp_text):
                    clean_m = m.strip().lower()
                    if is_valid_email(clean_m):
                        api_emails.add(clean_m)
                for h in re.findall(r'href=[\'"]([^\'"#?\s]{1,300})[\'"]', cp_text, flags=re.IGNORECASE):
                    h = h.strip()
                    if not h or h.startswith("javascript:") or h == "/":
                        continue
                    if h.startswith("http"):
                        if base_domain not in h:
                            continue
                        try:
                            h_path = urlparse(h).path
                        except Exception:
                            continue
                    elif h.startswith("/"):
                        h_path = h
                    else:
                        h_path = "/" + h

                    if any(kw in h_path.lower() for kw in LINK_KEYWORDS) and h_path not in seen_paths:
                        seen_paths.add(h_path)
                        discovered_paths.append(h_path)
        except Exception:
            pass

    print(f"[Fallback] Link Discovery: paths={discovered_paths} | api_emails={api_emails}")
    return discovered_paths, api_emails



async def scrape_department_emails(domain: str) -> List[ContactPerson]:
    """
    Quét website của Agency để tìm email phòng ban theo quy tắc Fallback BR-01.2.
    Tự động khám phá link từ menu/nav trên trang chủ (Link Discovery) và hỗ trợ HTTP/2.
    """
    contacts: List[ContactPerson] = []
    clean_d = clean_domain(domain)
    if not clean_d:
        return contacts

    # Danh sách path cố định thường chứa thông tin liên hệ phòng ban
    fixed_paths = [
        "",
        "/contact",
        "/contact-us",
        "/contact.html",
        "/company",
        "/company.html",
        "/about",
        "/about-us",
        "/about.html",
        "/about-us.html",
        "/component/footer.html",
        "/gioi-thieu",
        "/lien-he",
        "/partnerships",
        "/b2b",
        "/about-us.htm",
        "/contact-us.htm",
        "/about.htm",
        "/contact.htm",
    ]

    found_emails: Set[str] = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    import asyncio

    # Sử dụng http2=True vì nhiều server đại lý VN (Cloudflare, Caddy, Nginx) bị nghẽn/drop trên HTTP/1.1
    async with httpx.AsyncClient(headers=headers, timeout=5.0, http2=True, follow_redirects=True, verify=False) as client:
        # --- BƯỚC 0: Link Discovery & kiểm tra liveness của domain ---
        target_paths = list(fixed_paths)
        print(f"[Fallback] ▶ Bắt đầu quét website: {clean_d}")

        home_res = None
        protocol = "https"
        try:
            home_res = await client.get(f"https://{clean_d}")
        except Exception as e_https:
            try:
                home_res = await client.get(f"http://{clean_d}")
                protocol = "http"
            except Exception as e_http:
                print(f"[Fallback] ⚠️ Không truy cập được trang chủ {clean_d}, vẫn tiếp tục quét các path trực tiếp...")

        if home_res and home_res.status_code == 200:
            try:
                nav_paths, api_emails = await _discover_nav_links(home_res.text, clean_d, client)
                found_emails.update(api_emails)
                for p in nav_paths:
                    if p not in target_paths:
                        target_paths.append(p)
            except Exception as e:
                print(f"[Fallback] Link discovery warning: {e}")

        # Giới hạn tối đa 10 paths quan trọng nhất để quét nhanh chóng
        target_paths = target_paths[:20]
        print(f"[Fallback] Quét song song {len(target_paths)} paths trên {protocol}://{clean_d}...")

        async def _scrape_path(path: str):
            url = f"{protocol}://{clean_d}{path}"
            try:
                res = await client.get(url)
                if res.status_code == 200:
                    text = res.text
                    # 1. Quét qua mailto:
                    for m in re.findall(r'href=[\'"]mailto:([^\'"?\s]+)', text, flags=re.IGNORECASE):
                        clean_m = m.strip().lower()
                        if is_valid_email(clean_m):
                            found_emails.add(clean_m)

                    # 2. Quét qua regex email thô
                    for match in EMAIL_REGEX.findall(text):
                        clean_m = match.strip().lower()
                        if is_valid_email(clean_m):
                            found_emails.add(clean_m)

                    # 3. Giải mã Cloudflare Email Obfuscation
                    for encoded in CF_EMAIL_REGEX.findall(text):
                        decoded = decode_cf_email(encoded)
                        if decoded and is_valid_email(decoded):
                            found_emails.add(decoded.lower())
            except Exception:
                pass

        # Quét song song toàn bộ các paths cùng lúc bằng asyncio.gather
        await asyncio.gather(*[_scrape_path(p) for p in target_paths], return_exceptions=True)

    print(f"[Fallback] Tổng emails tìm được sau khi quét: {len(found_emails)} | {found_emails}")

    if not found_emails:
        return contacts

    # Phân loại danh sách email theo độ ưu tiên
    classified = []
    # Lấy tên thương hiệu từ domain (vd: vemaybaykhampha từ vemaybaykhampha.com)
    brand_name = clean_d.split(".")[0].lower() if clean_d else ""

    for em in found_emails:
        score = 0
        em_lower = em.lower()
        parts = em_lower.split("@")
        local_part = parts[0]
        em_domain = parts[1]

        # Kiểm tra xem email có chứa thương hiệu công ty (trong domain hoặc trong tên tài khoản free mail)
        has_brand_match = (
            (brand_name and len(brand_name) >= 3 and (brand_name in local_part or local_part in brand_name))
            or any(token in local_part for token in brand_name.split("-") if len(token) >= 4)
        )
        has_same_domain = (
            (clean_d and (clean_d in em_domain or em_domain in clean_d))
            or (brand_name and brand_name in em_domain)
            or has_brand_match
        )
        is_free_mail = em_domain in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"]

        if any(pref in em_lower for pref in TIER_4_PREFERRED):
            score = 5 if has_same_domain else 3
        elif any(sec in em_lower for sec in TIER_4_SECONDARY):
            score = 4 if has_same_domain else 2
        elif any(gen in em_lower for gen in TIER_4_GENERIC):
            score = 3 if has_same_domain else 1
        elif has_same_domain:
            score = 2
        elif is_free_mail:
            score = 1
        else:
            # Email thuộc domain lạ không khớp với website và không thuộc các phòng ban -> bỏ qua
            continue

        classified.append((score, em))

    if not classified:
        return contacts

    # Sắp xếp theo score giảm dần
    classified.sort(key=lambda x: x[0], reverse=True)

    for score, em in classified:
        local = em.split("@")[0].lower()

        # Định danh phòng ban và chức vụ thân thiện (English standardized)
        if any(k in local for k in ["kinhdoanh", "sales", "commercial"]):
            full_name = "Sales Department"
            display_title = "Sales Department"
            first_name = "Sales"
            last_name = "Dept"
        elif any(k in local for k in ["phongve", "datve", "ticketing", "vemaybay"]):
            full_name = "Ticketing Department"
            display_title = "Ticketing / Reservations Dept"
            first_name = "Ticketing"
            last_name = "Dept"
        elif any(k in local for k in ["daily", "b2b", "partner", "contracting"]):
            full_name = "B2B & Partnerships"
            display_title = "Agency & Partner Relations (B2B)"
            first_name = "B2B"
            last_name = "Partnerships"
        elif any(k in local for k in ["hotro", "cskh", "support", "tuvan"]):
            full_name = "Customer Support"
            display_title = "Customer Support Dept"
            first_name = "Customer"
            last_name = "Support"
        elif any(k in local for k in ["banhang"]):
            full_name = "Sales Team"
            display_title = "Sales Operations"
            first_name = "Sales"
            last_name = "Team"
        elif any(k in local for k in ["info", "contact", "office", "admin"]):
            dept_title = (
                "Contact" if "contact" in local
                else ("Information" if "info" in local
                else ("Administration" if "admin" in local
                else local.capitalize()))
            )
            full_name = f"{dept_title} Office"
            display_title = f"{dept_title} Office"
            first_name = dept_title
            last_name = "Office"
        else:
            clean_local = local.replace(".", " ").replace("_", " ").title()
            full_name = f"{clean_local} Dept"
            display_title = f"{clean_local} Operations"
            first_name = clean_local
            last_name = "Dept"

        contacts.append(
            ContactPerson(
                full_name=full_name,
                first_name=first_name,
                last_name=last_name,
                title=display_title,
                tier=ContactTier.TIER_4,
                tier_label="Tier 4: Fallback Department Contact",
                email=em,
                is_primary=False,
                source="website_fallback",
                verification_status="fallback",
                confidence_score=85.0 if score >= 4 else (70.0 if score >= 3 else 50.0)
            )
        )

    return contacts

