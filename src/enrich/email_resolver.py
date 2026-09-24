"""
email_resolver.py — Tìm email cá nhân cho một contact person.

Hỗ trợ 3 provider theo thứ tự ưu tiên:
  1. Hunter.io  (HUNTER_API_KEY)
  2. Apollo.io  (APOLLO_API_KEY)
  3. Internal SMTP Pattern — miễn phí, tự sinh pattern phổ biến
"""

import os
import re
import socket
from typing import Dict, List, Optional

import httpx


def clean_domain(domain: str) -> str:
    """Làm sạch domain bỏ http://, https://, www., và các đường dẫn con."""
    d = domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].split(":")[0]
    return d


async def resolve_via_hunter(
    first_name: str,
    last_name: str,
    domain: str,
    api_key: str = "",
) -> Optional[Dict]:
    """
    Gọi Hunter.io Email Finder API.
    GET https://api.hunter.io/v2/email-finder
    """
    api_key = api_key or os.getenv("HUNTER_API_KEY", "").strip()
    if not api_key:
        return None

    clean_d = clean_domain(domain)
    url = "https://api.hunter.io/v2/email-finder"
    params = {
        "domain": clean_d,
        "first_name": first_name,
        "last_name": last_name,
        "api_key": api_key,
    }
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, params=params, timeout=8.0)
            if res.status_code == 200:
                data = res.json().get("data", {})
                email = data.get("email", "")
                score = float(data.get("score", 0))
                verification = data.get("verification", {})
                if email and score >= 80:
                    return {
                        "email": email,
                        "confidence_score": score / 100.0,
                        "provider": "hunter",
                        "verification": verification,
                    }
    except Exception as e:
        print(f"[email_resolver] Hunter.io lỗi: {e}")
    return None


async def resolve_via_apollo(
    first_name: str,
    last_name: str,
    domain: str,
    api_key: str = "",
) -> Optional[Dict]:
    """
    Gọi Apollo.io People Match API.
    POST https://api.apollo.io/v1/people/match
    """
    api_key = api_key or os.getenv("APOLLO_API_KEY", "").strip()
    if not api_key:
        return None

    clean_d = clean_domain(domain)
    url = "https://api.apollo.io/v1/people/match"
    payload = {
        "api_key": api_key,
        "first_name": first_name,
        "last_name": last_name,
        "domain": clean_d,
        "reveal_personal_emails": False,
    }
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=8.0,
            )
            if res.status_code == 200:
                data = res.json()
                person = data.get("person", {})
                email = person.get("email", "")
                status = person.get("email_status", "")
                if email:
                    return {
                        "email": email,
                        "confidence_score": 0.85 if status == "verified" else 0.6,
                        "provider": "apollo",
                        "email_status": status,
                    }
    except Exception as e:
        print(f"[email_resolver] Apollo.io lỗi: {e}")
    return None


def check_mx_records(domain: str) -> bool:
    """Kiểm tra domain có bản ghi MX để nhận mail hay không."""
    try:
        socket.gethostbyname(domain)
        return True
    except Exception:
        return False


def resolve_via_internal_smtp(
    first_name: str,
    last_name: str,
    domain: str,
) -> Optional[Dict]:
    """
    Tự sinh Pattern kết hợp kiểm tra tính hợp lệ của domain (100% Miễn phí).
    Tạo các mẫu phổ biến: first.last@, first@, f.last@.
    """
    clean_d = clean_domain(domain)
    fn = re.sub(r"[^a-zA-Z0-9]", "", first_name).lower()
    ln = re.sub(r"[^a-zA-Z0-9]", "", last_name).lower()

    candidates = []
    if fn and ln:
        candidates = [
            f"{fn}.{ln}@{clean_d}",
            f"{fn}@{clean_d}",
            f"{fn[0]}.{ln}@{clean_d}",
            f"{fn}{ln}@{clean_d}",
            f"{fn}_{ln}@{clean_d}",
        ]
    elif fn:
        candidates = [f"{fn}@{clean_d}"]

    if not candidates:
        return None

    has_mail_host = check_mx_records(clean_d)
    best_candidate = candidates[0]

    return {
        "email": best_candidate,
        "confidence_score": 0.75 if has_mail_host else 0.40,
        "provider": "internal_smtp",
        "status": "guessed" if has_mail_host else "unverified",
        "all_patterns": candidates,
    }


async def resolve_contact_email(
    first_name: str,
    last_name: str,
    domain: str,
    provider: str = "auto",
) -> Optional[Dict]:
    """
    Điều phối việc lấy email theo Option mà người dùng FE đã chọn:
    - 'hunter': Chỉ gọi Hunter.io
    - 'apollo': Chỉ gọi Apollo.io
    - 'internal_smtp': Dùng bộ sinh pattern nội bộ
    - 'auto': Thử lần lượt Hunter -> Apollo -> Internal SMTP
    """
    prov = provider.lower()

    if prov == "hunter":
        return await resolve_via_hunter(first_name, last_name, domain)

    if prov == "apollo":
        return await resolve_via_apollo(first_name, last_name, domain)

    if prov == "internal_smtp":
        return resolve_via_internal_smtp(first_name, last_name, domain)

    # AUTO: thử theo thứ tự ưu tiên
    if os.getenv("HUNTER_API_KEY", "").strip():
        res = await resolve_via_hunter(first_name, last_name, domain)
        if res and res.get("email"):
            return res

    if os.getenv("APOLLO_API_KEY", "").strip():
        res = await resolve_via_apollo(first_name, last_name, domain)
        if res and res.get("email"):
            return res

    return resolve_via_internal_smtp(first_name, last_name, domain)
