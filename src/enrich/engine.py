import time
from typing import Callable, List, Optional

from .models import (
    ContactPerson,
    ContactTier,
    DebugStep,
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


def _ms(start: float) -> float:
    """Tính số ms từ thời điểm start đến hiện tại."""
    return round((time.time() - start) * 1000, 1)


async def enrich_single_lead(
    req: SingleEnrichRequest,
    progress_callback: Optional[Callable[[int, str, Optional[str]], None]] = None
) -> EnrichmentResult:
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
    discovery_used = "google_dorking"
    debug_trace: List[DebugStep] = []

    if progress_callback:
        progress_callback(10, f"Bắt đầu tìm kiếm danh tính nhân sự cho {company_name}...", "discovery")

    print(f"\n{'='*60}")
    print(f"[Engine] ▶ Bắt đầu Enrich: '{company_name}' | domain={domain} | country={country}")
    print(f"[Engine] Options: method={opts.discovery_method.value} | provider={opts.provider.value} | fallback={opts.check_website_fallback}")
    print(f"{'='*60}")

    # ═══════════════════════════════════════════════════════════
    # BƯỚC 1: TÌM DANH TÍNH (DISCOVERY)
    # ═══════════════════════════════════════════════════════════
    print(f"[Engine] 🔍 Bước 1: Discovery nhân sự...")
    step1_start = time.time()
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

        print(f"[Engine] Bước 1 xong: tìm được {len(discovered)} nhân sự")
        if progress_callback:
            if len(discovered) > 0:
                progress_callback(35, f"Discovery xong: tìm thấy {len(discovered)} nhân sự qua {discovery_used}", "discovery")
            else:
                progress_callback(35, f"Discovery xong: Không tìm thấy nhân sự cấp cao trên LinkedIn qua {discovery_used}. Bỏ qua Hunter/Apollo để quét Website Fallback...", "discovery")
        debug_trace.append(DebugStep(
            step="discovery",
            status="success" if discovered else "no_result",
            detail=f"Tìm được {len(discovered)} nhân sự qua {discovery_used}",
            duration_ms=_ms(step1_start),
            data={
                "method": discovery_used,
                "count": len(discovered),
                "candidates": [
                    {
                        "name": c.full_name,
                        "title": c.title,
                        "tier": c.tier,
                        "linkedin": c.linkedin_url,
                    }
                    for c in discovered
                ]
            }
        ))
    except Exception as e:
        discovered = []
        discovery_used = str(opts.discovery_method.value)
        error_msg = f"Lỗi ở bước Discovery ({discovery_used}): {str(e)}"
        print(f"[Engine] ❌ Bước 1 lỗi: {error_msg}")
        if progress_callback:
            progress_callback(35, f"Discovery gặp lỗi: {error_msg}", "discovery")
        debug_trace.append(DebugStep(
            step="discovery",
            status="failed",
            detail=error_msg,
            duration_ms=_ms(step1_start),
        ))

    # Danh sách các phương thức đã thực tế chạy trong pipeline
    methods_attempted: List[str] = [f"Discovery ({discovery_used})"]

    # ═══════════════════════════════════════════════════════════
    # BƯỚC 2: PHÂN GIẢI & XÁC THỰC EMAIL
    # ═══════════════════════════════════════════════════════════
    provider_used = opts.provider.value
    step2_start = time.time()
    resolution_results = []
    if len(discovered) > 0:
        methods_attempted.append(f"Email Resolution ({provider_used.upper()})")
        print(f"[Engine] 📧 Bước 2: Phân giải email cho {len(discovered)} ứng viên (provider={provider_used})...")
        if progress_callback:
            progress_callback(50, f"Đang phân giải & xác thực email cho {len(discovered)} ứng viên ({provider_used})...", "email_resolution")

    for cand in discovered:
        provider_name = "Hunter.io & Apollo.io" if opts.provider.value == "auto" else opts.provider.value.upper()
        print(f"[Engine]   Resolve email cho: {cand.full_name} | first='{cand.first_name}' last='{cand.last_name}' qua {provider_name}")
        if progress_callback:
            progress_callback(55, f"Đang gọi {provider_name} tra cứu email cho: {cand.full_name} ({cand.title or 'Key contact'})...", "email_resolution")

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
                found_prov = res.get("provider", provider_used).capitalize()
                print(f"[Engine]   ✔ Email tìm được: {cand.email} (provider={provider_used}, status={cand.verification_status})")
                if progress_callback:
                    progress_callback(65, f"✔ {found_prov} tìm thấy: {cand.email} (status={cand.verification_status}, score={cand.confidence_score})", "email_resolution")
                resolution_results.append({
                    "name": cand.full_name,
                    "email": cand.email,
                    "provider": provider_used,
                    "status": cand.verification_status,
                })
            else:
                print(f"[Engine]   ✗ Không tìm được email cho {cand.full_name}")
                if progress_callback:
                    progress_callback(65, f"✗ {provider_name}: Chưa có email của {cand.full_name} trong database", "email_resolution")
                resolution_results.append({
                    "name": cand.full_name,
                    "email": None,
                    "provider": opts.provider.value,
                    "status": "not_found",
                })
        except Exception as e:
            print(f"[Engine]   ❌ Resolve error cho {cand.full_name}: {e}")
            if progress_callback:
                progress_callback(65, f"❌ Lỗi khi gọi {provider_name} cho {cand.full_name}: {e}", "email_resolution")
            resolution_results.append({
                "name": cand.full_name,
                "email": None,
                "provider": opts.provider.value,
                "status": f"error: {e}",
            })

        all_contacts.append(cand)

    resolved_count = sum(1 for r in resolution_results if r.get("email"))
    if progress_callback and discovered:
        progress_callback(70, f"Tổng kết: {resolved_count}/{len(discovered)} email tìm thấy qua {provider_used.upper()}", "email_resolution")
    if discovered:
        debug_trace.append(DebugStep(
            step="email_resolution",
            status="success" if resolved_count > 0 else "no_result",
            detail=f"Phân giải {resolved_count}/{len(discovered)} email thành công qua {provider_used}",
            duration_ms=_ms(step2_start),
            data={
                "provider": provider_used,
                "resolved": resolved_count,
                "total": len(discovered),
                "results": resolution_results,
            }
        ))
    else:
        debug_trace.append(DebugStep(
            step="email_resolution",
            status="skipped",
            detail="Bỏ qua — không có nhân sự nào từ bước Discovery",
            duration_ms=_ms(step2_start),
        ))

    # ═══════════════════════════════════════════════════════════
    # BƯỚC 3: ÁP DỤNG QUY TẮC BR-01
    # ═══════════════════════════════════════════════════════════
    print(f"[Engine] 🎯 Bước 3: Áp dụng quy tắc BR-01...")

    # 3.1 BR-01.1 — Cá nhân Tier 1-3 có email
    personal_candidates = [c for c in all_contacts if c.email and c.tier in [1, 2, 3]]
    print(f"[Engine]   Ứng viên Tier 1-3 có email: {len(personal_candidates)}")

    if personal_candidates:
        personal_candidates.sort(key=lambda x: (x.tier, -x.confidence_score))
        primary_contact = personal_candidates[0]
        primary_contact.is_primary = True
        primary_email = primary_contact.email
        rule_applied = "BR-01.1"
        status = "success"
        print(f"[Engine] ✅ BR-01.1: Primary contact = {primary_contact.full_name} | email = {primary_email}")
        debug_trace.append(DebugStep(
            step="decision",
            status="success",
            detail=f"BR-01.1: Tìm được email cá nhân Tier {primary_contact.tier} — {primary_contact.full_name}",
            data={"rule": "BR-01.1", "email": primary_email, "tier": primary_contact.tier}
        ))

    # 3.2 BR-01.2 — Fallback quét website
    elif opts.check_website_fallback:
        methods_attempted.append("Website Fallback (HTTP/2)")
        print(f"[Engine] → Không có email cá nhân, kích hoạt Fallback quét website (BR-01.2)...")
        if progress_callback:
            progress_callback(75, f"Không có email cá nhân, đang quét website {domain} tìm email phòng ban (Fallback)...", "website_fallback")
        step_fb_start = time.time()
        try:
            dept_contacts = await scrape_department_emails(domain)
            print(f"[Engine]   Fallback tìm được {len(dept_contacts)} email phòng ban")

            # Ghi lại chi tiết từng email tìm được
            fallback_emails = [
                {"email": c.email, "score": c.confidence_score}
                for c in dept_contacts
            ]

            if dept_contacts:
                primary_contact = dept_contacts[0]
                primary_contact.is_primary = True
                primary_email = primary_contact.email
                rule_applied = "BR-01.2"
                status = "success"
                all_contacts.extend(dept_contacts)
                print(f"[Engine] ✅ BR-01.2: Primary dept email = {primary_email}")
                if progress_callback:
                    progress_callback(85, f"✔ Website Fallback: Tìm thấy {len(dept_contacts)} email phòng ban (Email chính: {primary_email})", "website_fallback")
                debug_trace.append(DebugStep(
                    step="website_fallback",
                    status="success",
                    detail=f"BR-01.2: Quét website tìm được {len(dept_contacts)} email phòng ban",
                    duration_ms=_ms(step_fb_start),
                    data={
                        "rule": "BR-01.2",
                        "primary_email": primary_email,
                        "all_emails": fallback_emails,
                    }
                ))
            else:
                print(f"[Engine] ✗ Fallback không tìm được email nào từ website")
                if progress_callback:
                    progress_callback(85, f"✗ Website Fallback: Không tìm thấy email phòng ban trên website {domain}", "website_fallback")
                debug_trace.append(DebugStep(
                    step="website_fallback",
                    status="no_result",
                    detail="Quét website nhưng không tìm được email nào",
                    duration_ms=_ms(step_fb_start),
                    data={"urls_scanned": [], "all_emails": []}
                ))
        except Exception as e:
            print(f"[Engine] ❌ Fallback scrape error: {e}")
            debug_trace.append(DebugStep(
                step="website_fallback",
                status="failed",
                detail=f"Lỗi khi quét website: {e}",
                duration_ms=_ms(step_fb_start),
            ))
    else:
        print(f"[Engine] → check_website_fallback=False, bỏ qua quét website")
        debug_trace.append(DebugStep(
            step="website_fallback",
            status="skipped",
            detail="Bỏ qua — check_website_fallback=False",
        ))

    # 3.3 BR-01.3 — Missing Contact
    if not primary_email:
        rule_applied = "BR-01.3"
        status = "missing_contact"
        print(f"[Engine] ❌ BR-01.3: Missing Contact — không tìm được email nào")
        debug_trace.append(DebugStep(
            step="decision",
            status="failed",
            detail="BR-01.3: Không tìm được email nào sau tất cả các bước",
            data={"rule": "BR-01.3"}
        ))

    elapsed = round(time.time() - start_time, 2)
    greeting = format_greeting_name(primary_contact)

    # Xác định nguồn gốc chính xác của email chính và mô tả quy tắc
    primary_source = primary_contact.source if primary_contact else "none"
    if rule_applied == "BR-01.1":
        rule_description = "Tìm thấy email cá nhân cấp cao (Tier 1-3) qua Hunter.io / Apollo.io"
    elif rule_applied == "BR-01.2":
        rule_description = "Quét trực tiếp website tìm thấy email phòng ban chuyên trách (Tier 4)"
    else:
        rule_description = "Không tìm thấy thông tin liên hệ sau khi đã chạy tất cả phương thức"

    print(f"[Engine] ⏱ Hoàn thành trong {elapsed}s | status={status} | rule={rule_applied} | source={primary_source}")
    print(f"[Engine] Pipeline executed: {' -> '.join(methods_attempted)}")
    print(f"{'='*60}\n")

    if progress_callback:
        progress_callback(100, f"Hoàn tất làm giàu dữ liệu cho {company_name} ({status})", "completed")

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
        error_message=error_msg,
        methods_attempted=methods_attempted,
        primary_source=primary_source,
        rule_description=rule_description,
        debug_trace=debug_trace,
    )
