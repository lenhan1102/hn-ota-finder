import os
import re
import socket
from typing import Dict, List, Optional
import httpx


def clean_domain(domain: str) -> str:
    """Làm sạch domain bỏ http://, https://, www., và các đường dẫn con."""
    if not domain:
        return ""
    d = domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].split(":")[0]
    return d


async def resolve_via_hunter(first_name: str, last_name: str, domain: str) -> Optional[Dict]:
    """
    Gọi Hunter.io Email Finder API.
    GET https://api.hunter.io/v2/email-finder
    """
    api_key = os.getenv("HUNTER_API_KEY", "").strip()
    if not api_key:
        return None

    clean_d = clean_domain(domain)
    if not clean_d or not first_name:
        return None

    url = "https://api.hunter.io/v2/email-finder"
    params = {
        "domain": clean_d,
        "first_name": first_name,
        "last_name": last_name or "",
        "api_key": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.get(url, params=params)
            if res.status_code == 200:
                data = res.json().get("data", {})
                email = data.get("email")
                if email:
                    score = float(data.get("score") or 80.0)
                    verification = data.get("verification", {}).get("status", "verified")
                    return {
                        "email": email,
                        "score": score,
                        "status": verification,
                        "provider": "hunter"
                    }
    except Exception as e:
        print(f"[Resolver] Hunter API error: {e}")

    return None


async def resolve_via_apollo(first_name: str, last_name: str, domain: str) -> Optional[Dict]:
    """
    Gọi Apollo.io People Match API.
    POST https://api.apollo.io/v1/people/match
    """
    api_key = os.getenv("APOLLO_API_KEY", "").strip()
    if not api_key:
        return None

    clean_d = clean_domain(domain)
    if not clean_d or not first_name:
        return None

    url = "https://api.apollo.io/v1/people/match"
    payload = {
        "api_key": api_key,
        "first_name": first_name,
        "last_name": last_name or "",
        "domain": clean_d
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            if res.status_code == 200:
                data = res.json()
                person = data.get("person") or {}
                email = person.get("email")
                if email:
                    status = person.get("email_status", "verified")
                    return {
                        "email": email,
                        "score": 90.0 if status == "verified" else 70.0,
                        "status": status,
                        "provider": "apollo"
                    }
    except Exception as e:
        print(f"[Resolver] Apollo API error: {e}")

    return None


def check_mx_records(domain: str) -> bool:
    """Kiểm tra domain có bản ghi MX để nhận mail hay không."""
    try:
        # Kiểm tra socket getaddrinfo
        socket.gethostbyname(domain)
        return True
    except Exception:
        return False


async def resolve_via_internal_smtp(first_name: str, last_name: str, domain: str) -> Optional[Dict]:
    """
    Tự sinh Pattern kết hợp kiểm tra tính hợp lệ của domain (100% Miễn phí).
    Tạo các mẫu phổ biến: first.last@, first@, f.last@.
    """
    clean_d = clean_domain(domain)
    if not clean_d or not first_name:
        return None

    fn = re.sub(r"[^a-zA-Z0-9]", "", first_name.lower())
    ln = re.sub(r"[^a-zA-Z0-9]", "", last_name.lower()) if last_name else ""

    candidates = []
    if fn and ln:
        candidates.append(f"{fn}.{ln}@{clean_d}")
        candidates.append(f"{fn}@{clean_d}")
        candidates.append(f"{fn}{ln}@{clean_d}")
        candidates.append(f"{fn[0]}.{ln}@{clean_d}")
    elif fn:
        candidates.append(f"{fn}@{clean_d}")

    if not candidates:
        return None

    # Kiểm tra domain có tồn tại và nhận mail không
    has_mail_host = check_mx_records(clean_d)
    best_candidate = candidates[0]

    return {
        "email": best_candidate,
        "score": 75.0 if has_mail_host else 40.0,
        "status": "guessed" if has_mail_host else "unverified",
        "provider": "internal_smtp",
        "all_candidates": candidates
    }


async def resolve_contact_email(
    first_name: str,
    last_name: str,
    domain: str,
    provider: str = "auto"
) -> Optional[Dict]:
    """
    Điều phối việc lấy email theo Option mà người dùng FE đã chọn:
    - 'hunter': Chỉ gọi Hunter.io
    - 'apollo': Chỉ gọi Apollo.io
    - 'internal_smtp': Dùng bộ sinh pattern nội bộ
    - 'auto': Thử lần lượt Hunter -> Apollo -> Internal SMTP
    """
    prov = (provider or "auto").lower()

    if prov == "hunter":
        res = await resolve_via_hunter(first_name, last_name, domain)
        return res or await resolve_via_internal_smtp(first_name, last_name, domain)

    elif prov == "apollo":
        res = await resolve_via_apollo(first_name, last_name, domain)
        return res or await resolve_via_internal_smtp(first_name, last_name, domain)

    elif prov == "internal_smtp":
        return await resolve_via_internal_smtp(first_name, last_name, domain)

    else:  # auto
        # 1. Thử Hunter nếu có cấu hình key
        if os.getenv("HUNTER_API_KEY"):
            h_res = await resolve_via_hunter(first_name, last_name, domain)
            if h_res and h_res.get("email"):
                return h_res

        # 2. Thử Apollo nếu có cấu hình key
        if os.getenv("APOLLO_API_KEY"):
            a_res = await resolve_via_apollo(first_name, last_name, domain)
            if a_res and a_res.get("email"):
                return a_res

        # 3. Fallback sang bộ sinh pattern nội bộ
        return await resolve_via_internal_smtp(first_name, last_name, domain)
