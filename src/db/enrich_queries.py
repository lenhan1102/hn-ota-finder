"""
Queries cho module Enrich: lưu và lấy kết quả enrich từ MySQL.
"""
import json
import uuid
from datetime import datetime
from typing import List, Optional

from .db_connection import get_db_connection


def save_enrich_result(
    lead_id: str,
    result,  # EnrichmentResult
    enriched_by: Optional[str] = "system"
) -> Optional[str]:
    """
    Lưu kết quả enrich vào bảng enrich_results + enrich_contacts.
    Nếu lead_id đã có enrich trước -> cập nhật (UPSERT theo lead_id).
    Trả về enrich_id (UUID).
    """
    enrich_id = str(uuid.uuid4())
    execution_ms = int(result.execution_time_seconds * 1000)
    debug_trace_json = json.dumps(
        [s.model_dump() for s in result.debug_trace],
        ensure_ascii=False
    )

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # ── 1. Xóa kết quả enrich cũ của lead này (nếu có) ────────
                cur.execute(
                    "SELECT id FROM enrich_results WHERE lead_id = %s ORDER BY created_at DESC LIMIT 1",
                    (lead_id,)
                )
                existing = cur.fetchone()
                if existing:
                    old_id = existing[0]
                    cur.execute("DELETE FROM enrich_contacts WHERE enrich_id = %s", (old_id,))
                    cur.execute("DELETE FROM enrich_results WHERE id = %s", (old_id,))

                # ── 2. Insert enrich_results ───────────────────────────────
                cur.execute("""
                    INSERT INTO enrich_results (
                        id, lead_id, company_name, domain, country,
                        primary_email, greeting_name, rule_applied, status,
                        discovery_method, provider_used, execution_time_ms,
                        debug_trace, error_message, enriched_by
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                """, (
                    enrich_id, lead_id, result.company_name, result.domain, result.country,
                    result.primary_email, result.greeting_name, result.rule_applied, result.status,
                    result.discovery_method_used, result.provider_used, execution_ms,
                    debug_trace_json, result.error_message, enriched_by
                ))

                # ── 3. Insert enrich_contacts (từng email/người) ───────────
                for contact in result.all_contacts:
                    contact_id = str(uuid.uuid4())
                    cur.execute("""
                        INSERT INTO enrich_contacts (
                            id, enrich_id, lead_id, domain,
                            full_name, first_name, last_name, title, linkedin_url,
                            email, verification_status, confidence_score,
                            tier, tier_label, is_primary, source
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s
                        )
                    """, (
                        contact_id, enrich_id, lead_id, result.domain,
                        contact.full_name, contact.first_name, contact.last_name,
                        contact.title, contact.linkedin_url,
                        contact.email, contact.verification_status, contact.confidence_score,
                        contact.tier, contact.tier_label, 1 if contact.is_primary else 0,
                        contact.source
                    ))

            conn.commit()
            print(f"[EnrichDB] ✅ Đã lưu enrich_id={enrich_id} cho lead_id={lead_id} | status={result.status}")
            return enrich_id

    except Exception as e:
        print(f"[EnrichDB] ❌ Lỗi lưu enrich result: {e}")
        return None


def get_enrich_result(lead_id: str) -> Optional[dict]:
    """
    Lấy kết quả enrich mới nhất của một lead.
    Trả về dict đầy đủ để FE hiển thị.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Lấy enrich_results
                cur.execute("""
                    SELECT
                        id, lead_id, company_name, domain, country,
                        primary_email, greeting_name, rule_applied, status,
                        discovery_method, provider_used, execution_time_ms,
                        debug_trace, error_message, enriched_by, created_at
                    FROM enrich_results
                    WHERE lead_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (lead_id,))
                row = cur.fetchone()
                if not row:
                    return None

                (enrich_id, lead_id_, company_name, domain, country,
                 primary_email, greeting_name, rule_applied, status,
                 discovery_method, provider_used, execution_time_ms,
                 debug_trace_raw, error_message, enriched_by, created_at) = row

                # Lấy enrich_contacts
                cur.execute("""
                    SELECT
                        id, full_name, first_name, last_name, title, linkedin_url,
                        email, verification_status, confidence_score,
                        tier, tier_label, is_primary, source
                    FROM enrich_contacts
                    WHERE enrich_id = %s
                    ORDER BY is_primary DESC, tier ASC, confidence_score DESC
                """, (enrich_id,))
                contacts_rows = cur.fetchall()

                contacts = []
                for c in contacts_rows:
                    contacts.append({
                        "id": c[0],
                        "full_name": c[1],
                        "first_name": c[2],
                        "last_name": c[3],
                        "title": c[4],
                        "linkedin_url": c[5],
                        "email": c[6],
                        "verification_status": c[7],
                        "confidence_score": float(c[8]) if c[8] else 0.0,
                        "tier": c[9],
                        "tier_label": c[10],
                        "is_primary": bool(c[11]),
                        "source": c[12],
                    })

                try:
                    debug_trace = json.loads(debug_trace_raw) if debug_trace_raw else []
                except Exception:
                    debug_trace = []

                return {
                    "enrich_id": enrich_id,
                    "lead_id": lead_id_,
                    "company_name": company_name,
                    "domain": domain,
                    "country": country,
                    "primary_email": primary_email,
                    "greeting_name": greeting_name,
                    "rule_applied": rule_applied,
                    "status": status,
                    "discovery_method": discovery_method,
                    "provider_used": provider_used,
                    "execution_time_ms": execution_time_ms,
                    "debug_trace": debug_trace,
                    "error_message": error_message,
                    "enriched_by": enriched_by,
                    "enriched_at": created_at.isoformat() if created_at else None,
                    "all_contacts": contacts,
                    "primary_contact": next((c for c in contacts if c["is_primary"]), None),
                }

    except Exception as e:
        print(f"[EnrichDB] ❌ Lỗi lấy enrich result: {e}")
        return None


def list_enrich_results(
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    domain_filter: Optional[str] = None,
) -> List[dict]:
    """
    Liệt kê các kết quả enrich (cho trang danh sách của FE).
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                where_clauses = []
                params = []
                if status_filter:
                    where_clauses.append("status = %s")
                    params.append(status_filter)
                if domain_filter:
                    where_clauses.append("domain LIKE %s")
                    params.append(f"%{domain_filter}%")

                where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                params.extend([limit, offset])

                cur.execute(f"""
                    SELECT
                        id, lead_id, company_name, domain, country,
                        primary_email, greeting_name, rule_applied, status,
                        discovery_method, provider_used, execution_time_ms,
                        enriched_by, created_at
                    FROM enrich_results
                    {where_sql}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, params)

                rows = cur.fetchall()
                return [
                    {
                        "enrich_id": r[0],
                        "lead_id": r[1],
                        "company_name": r[2],
                        "domain": r[3],
                        "country": r[4],
                        "primary_email": r[5],
                        "greeting_name": r[6],
                        "rule_applied": r[7],
                        "status": r[8],
                        "discovery_method": r[9],
                        "provider_used": r[10],
                        "execution_time_ms": r[11],
                        "enriched_by": r[12],
                        "enriched_at": r[13].isoformat() if r[13] else None,
                    }
                    for r in rows
                ]
    except Exception as e:
        print(f"[EnrichDB] ❌ Lỗi list enrich: {e}")
        return []
