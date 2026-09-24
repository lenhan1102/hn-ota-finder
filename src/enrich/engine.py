"""
engine.py — Điều phối toàn bộ luồng tìm kiếm và làm giàu thông tin liên hệ.

Luồng xử lý:
  BR-01.1 Discovery: Tìm nhân sự Tier 1-3 qua Google Dorking / Playwright LinkedIn
  BR-01.2 Fallback:  Nếu không tìm được → scrape email phòng ban từ website
  BR-01.3 Missing:   Nếu cả 2 đều thất bại → trả về status='missing_contact'
"""

import time
from typing import List, Optional

try:
    from .models import (
        ContactPerson,
        ContactTier,
        DiscoveryMethod,
        EnrichmentOptions,
        EnrichmentResult,
        SingleEnrichRequest,
    )
    from .discovery import discover_via_google_dorking, discover_via_playwright
    from .email_resolver import resolve_contact_email
    from .website_fallback import scrape_department_emails
except ImportError:
    from models import (  # type: ignore
        ContactPerson,
        ContactTier,
        DiscoveryMethod,
        EnrichmentOptions,
        EnrichmentResult,
        SingleEnrichRequest,
    )
    from discovery import discover_via_google_dorking, discover_via_playwright  # type: ignore
    from email_resolver import resolve_contact_email  # type: ignore
    from website_fallback import scrape_department_emails  # type: ignore


def format_greeting_name(contact: ContactPerson) -> str:
    """Định dạng tên chào hỏi cho email Outreach (Feature 3)."""
    # Nếu là email phòng ban (Tier 4 không có tên) → dùng "Team"
    if contact.tier == ContactTier.TIER_4 or not contact.last_name:
        return "Team"
    return f"Mr./Ms. {contact.last_name}"


async def enrich_single_lead(req: SingleEnrichRequest) -> EnrichmentResult:
    """
    Tiến trình điều phối toàn bộ luồng tìm kiếm và làm giàu thông tin liên hệ.
    Tuân thủ các tùy chọn do FE gửi lên và áp dụng bộ quy tắc BR-01.1 -> BR-01.3.
    """
    start_time = time.time()

    company_name = req.company_name.strip()
    domain = req.domain.strip()
    country = req.country or "vietnam"
    opts: EnrichmentOptions = req.options or EnrichmentOptions()

    all_contacts: List[ContactPerson] = []
    primary_contact: Optional[ContactPerson] = None
    rule_applied = ""
    status = "ok"
    primary_email = ""
    error_msg = ""

    # ── BR-01.1: Discovery ─────────────────────────────────────────────────────
    discovered: List[ContactPerson] = []
    discovery_used = ""
    try:
        if opts.discovery_method == DiscoveryMethod.PLAYWRIGHT_LINKEDIN:
            discovered = await discover_via_playwright(
                company_name=company_name,
                domain=domain,
                linkedin_cookie=opts.linkedin_cookie,
                country=country,
            )
            discovery_used = "playwright_linkedin"
        else:
            discovered = await discover_via_google_dorking(
                company_name=company_name,
                domain=domain,
                country=country,
            )
            discovery_used = "google_dorking"
    except Exception as e:
        error_msg = f"Lỗi ở bước Discovery ({opts.discovery_method.value}): {e}"
        print(f"[engine] {error_msg}")

    all_contacts.extend(discovered)

    # Lọc contact có Tier 1-3 (có nhân sự cụ thể)
    personal_candidates = [
        c for c in all_contacts
        if c.tier in (ContactTier.TIER_1, ContactTier.TIER_2, ContactTier.TIER_3)
        and c.email
    ]

    if not personal_candidates and discovered:
        # Tìm email cho nhân sự đã phát hiện nhưng chưa có email
        best = sorted(discovered, key=lambda c: (c.tier, -c.confidence_score))[0]
        provider_used = ""
        try:
            res = await resolve_contact_email(
                first_name=best.first_name,
                last_name=best.last_name,
                domain=domain,
                provider=opts.provider.value,
            )
            if res and res.get("email"):
                best.email = res["email"]
                best.confidence_score = res.get("confidence_score", best.confidence_score)
                best.provider_used = res.get("provider", "")
                provider_used = best.provider_used
                personal_candidates = [best]
        except Exception as e:
            print(f"[engine] Email resolve lỗi: {e}")

        rule_applied = "BR-01.1"
        primary_contact = personal_candidates[0] if personal_candidates else None

    elif personal_candidates:
        rule_applied = "BR-01.1"
        primary_contact = sorted(
            personal_candidates, key=lambda x: (x.tier, -x.confidence_score)
        )[0]

    # ── BR-01.2: Fallback — scrape email phòng ban ───────────────────────────
    if not primary_contact and domain:
        try:
            dept_contacts = await scrape_department_emails(domain)
            all_contacts.extend(dept_contacts)
            if dept_contacts:
                primary_contact = dept_contacts[0]
                rule_applied = "BR-01.2"
        except Exception as e:
            print(f"[engine] Website fallback lỗi: {e}")

    # ── BR-01.3: Missing contact ─────────────────────────────────────────────
    if not primary_contact:
        status = "missing_contact"
        rule_applied = "BR-01.3"

    if primary_contact:
        primary_email = primary_contact.email

    return EnrichmentResult(
        company_name=company_name,
        domain=domain,
        primary_contact=primary_contact,
        all_contacts=all_contacts[: opts.max_contacts],
        primary_email=primary_email,
        discovery_used=discovery_used,
        provider_used=primary_contact.provider_used if primary_contact else "",
        rule_applied=rule_applied,
        status=status,
        error_message=error_msg,
        elapsed_sec=round(time.time() - start_time, 2),
    )
