import time
from typing import List, Optional

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


def format_greeting_name(contact: Optional[ContactPerson]) -> str:
    """Định dạng tên chào hỏi cho email Outreach (Feature 3)."""
    if not contact:
        return "Team"
    if contact.tier == ContactTier.TIER_4:
        return "Team"
    if contact.last_name:
        return f"Mr./Ms. {contact.last_name}"
    if contact.first_name:
        return f"Mr./Ms. {contact.first_name}"
    if contact.full_name:
        return contact.full_name
    return "Team"


async def enrich_single_lead(req: SingleEnrichRequest) -> EnrichmentResult:
    """
    Tiến trình điều phối toàn bộ luồng tìm kiếm và làm giàu thông tin liên hệ.
    Tuân thủ các tùy chọn do FE gửi lên và áp dụng bộ quy tắc BR-01.1 -> BR-01.3.
    """
    start_time = time.time()
    company_name = req.company_name.strip()
    domain = req.domain.strip()
    country = req.country or "vietnam"
    opts = req.options or EnrichmentOptions()

    all_contacts: List[ContactPerson] = []
    primary_contact: Optional[ContactPerson] = None
    rule_applied = "BR-01.3"
    status = "missing_contact"
    primary_email = None
    error_msg = None

    # --- BƯỚC 1: TÌM DANH TÍNH (DISCOVERY) THEO OPTION FE CHỌN ---
    try:
        if opts.discovery_method == DiscoveryMethod.PLAYWRIGHT_LINKEDIN:
            discovered = await discover_via_playwright(
                company_name=company_name,
                domain=domain,
                linkedin_cookie=opts.linkedin_cookie,
                country=country
            )
            discovery_used = "playwright_linkedin"
        else:
            discovered = await discover_via_google_dorking(
                company_name=company_name,
                domain=domain,
                country=country
            )
            discovery_used = "google_dorking"
    except Exception as e:
        discovered = []
        discovery_used = str(opts.discovery_method.value)
        error_msg = f"Lỗi ở bước Discovery ({discovery_used}): {str(e)}"

    # --- BƯỚC 2: PHÂN GIẢI & XÁC THỰC EMAIL (ENRICHMENT) ---
    provider_used = opts.provider.value

    for cand in discovered:
        try:
            res = await resolve_contact_email(
                first_name=cand.first_name or "",
                last_name=cand.last_name or "",
                domain=domain,
                provider=opts.provider.value
            )
            if res and res.get("email"):
                cand.email = res["email"]
                cand.verification_status = res.get("status", "verified")
                cand.confidence_score = float(res.get("score", cand.confidence_score))
                if res.get("provider"):
                    provider_used = res["provider"]
        except Exception as e:
            print(f"[Engine] Resolve error for {cand.full_name}: {e}")

        all_contacts.append(cand)

    # --- BƯỚC 3: ÁP DỤNG QUY TẮC NGHIỆP VỤ BR-01 (DECISION ENGINE) ---

    # 3.1. Tìm kiếm ứng viên Tier 1-3 có email
    personal_candidates = [c for c in all_contacts if c.email and c.tier in [1, 2, 3]]

    if personal_candidates:
        # Sắp xếp ưu tiên: Tier 1 > Tier 2 > Tier 3
        personal_candidates.sort(key=lambda x: (x.tier, -x.confidence_score))
        primary_contact = personal_candidates[0]
        primary_contact.is_primary = True
        primary_email = primary_contact.email
        rule_applied = "BR-01.1"
        status = "success"

    # 3.2. Nếu không tìm thấy Tier 1-3 -> Kích hoạt Fallback quét Website đại lý lấy Tier 4 (BR-01.2)
    elif opts.check_website_fallback:
        try:
            dept_contacts = await scrape_department_emails(domain)
            if dept_contacts:
                primary_contact = dept_contacts[0]
                primary_contact.is_primary = True
                primary_email = primary_contact.email
                rule_applied = "BR-01.2"
                status = "success"
                all_contacts.extend(dept_contacts)
        except Exception as e:
            print(f"[Engine] Fallback scrape error: {e}")

    # 3.3. Nếu vẫn không có email nào -> Đưa vào danh sách Missing Contact (BR-01.3)
    if not primary_email:
        rule_applied = "BR-01.3"
        status = "missing_contact"

    elapsed = round(time.time() - start_time, 2)
    greeting = format_greeting_name(primary_contact)

    return EnrichmentResult(
        company_name=company_name,
        domain=domain,
        country=country,
        primary_email=primary_email,
        primary_contact=primary_contact,
        all_contacts=all_contacts,
        rule_applied=rule_applied,
        status=status,
        greeting_name=greeting,
        discovery_method_used=discovery_used,
        provider_used=provider_used,
        execution_time_seconds=elapsed,
        error_message=error_msg
    )
