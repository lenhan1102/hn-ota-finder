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
            print(f"[Resolver] Hunter HTTP {res.status_code} cho {first_name} {last_name}@{clean_d}")
            if res.status_code == 200:
                data = res.json().get("data", {})
                email = data.get("email")
                if email:
                    score = float(data.get("score") or 80.0)
                    verification = data.get("verification", {}).get("status", "verified")
                    print(f"[Resolver] Hunter ✔ {email} (score={score})")
                    return {
                        "email": email,
                        "score": score,
                        "status": verification,
                        "provider": "hunter"
                    }
                else:
                    print(f"[Resolver] Hunter: không tìm thấy email (domain chưa có trong database)")
            else:
                print(f"[Resolver] Hunter lỗi: {res.text[:200]}")
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
    # Apollo yêu cầu API key trong header X-Api-Key, KHÔNG đặt trong body
    payload = {
        "first_name": first_name,
        "last_name": last_name or "",
        "domain": clean_d
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": api_key
                }
            )
            print(f"[Resolver] Apollo HTTP {res.status_code} cho {first_name} {last_name}@{clean_d}")
            if res.status_code == 200:
                data = res.json()
                person = data.get("person") or {}
                email = person.get("email")
                if email:
                    status = person.get("email_status", "verified")
                    print(f"[Resolver] Apollo ✔ {email} (status={status})")
                    return {
                        "email": email,
                        "score": 90.0 if status == "verified" else 70.0,
                        "status": status,
                        "provider": "apollo"
                    }
                else:
                    print(f"[Resolver] Apollo: không có email cho người này")
            else:
                print(f"[Resolver] Apollo lỗi: {res.text[:200]}")
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
    [ĐÃ TẮT] Bộ sinh pattern email nội bộ (first.last@domain).
    Không sử dụng vì dễ tạo ra email giả, gây mất uy tín khi gửi outreach.
    Chỉ giữ lại hàm để tránh lỗi import, nhưng luôn trả về None.
    """
    return None


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
    - 'auto': Thử lần lượt Hunter -> Apollo
    KHÔNG dùng internal_smtp pattern để tránh tạo email giả.
    Nếu không có API nào trả kết quả thực → trả về None.
    """
    prov = (provider or "auto").lower()

    if prov == "hunter":
        # Chỉ gọi Hunter, không fallback sang pattern giả
        return await resolve_via_hunter(first_name, last_name, domain)

    elif prov == "apollo":
        # Chỉ gọi Apollo, không fallback sang pattern giả
        return await resolve_via_apollo(first_name, last_name, domain)

    elif prov == "internal_smtp":
        # internal_smtp đã bị tắt — trả về None
        print(f"[Resolver] internal_smtp bị vô hiệu hóa, không sinh email giả cho {first_name} {last_name}@{domain}")
        return None

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

        # Không sinh email giả — trả về None để hệ thống chuyển sang Fallback BR-01.2
        return None
