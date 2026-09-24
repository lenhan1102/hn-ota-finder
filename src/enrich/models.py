"""
models.py — Data models và Enums cho module Enrich (Contact Discovery & Email Finder).
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class DiscoveryMethod(str, Enum):
    """Phương pháp tìm kiếm nhân sự."""
    GOOGLE_DORKING = "google_dorking"
    PLAYWRIGHT_LINKEDIN = "playwright_linkedin"


class EnrichmentProvider(str, Enum):
    """Nhà cung cấp API tìm email."""
    HUNTER = "hunter"
    APOLLO = "apollo"
    INTERNAL_SMTP = "internal_smtp"
    AUTO = "auto"


class ContactTier(str, Enum):
    """Phân loại mức độ ưu tiên của contact."""
    TIER_1 = "tier_1"   # C-level: CEO, Founder, MD
    TIER_2 = "tier_2"   # Head of Business Development, Partnerships, Ticketing
    TIER_3 = "tier_3"   # Manager, Supervisor
    TIER_4 = "tier_4"   # Email phòng ban (sales@, booking@, info@...)


class ContactPerson(BaseModel):
    """Thông tin một nhân sự được tìm thấy."""
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    tier: ContactTier = ContactTier.TIER_4
    email: str = ""
    confidence_score: float = 0.0
    source: str = ""          # "google_dorking" | "playwright_linkedin" | "website_fallback"
    linkedin_url: str = ""
    discovery_method: str = ""
    provider_used: str = ""   # "hunter" | "apollo" | "internal_smtp"


class EnrichmentOptions(BaseModel):
    """Tuỳ chọn do FE gửi lên để điều phối luồng enrich."""
    discovery_method: DiscoveryMethod = DiscoveryMethod.GOOGLE_DORKING
    provider: EnrichmentProvider = EnrichmentProvider.AUTO
    linkedin_cookie: str = ""    # cookie 'li_at' nếu dùng Playwright
    max_contacts: int = Field(default=5, ge=1, le=20)
    country: str = "vietnam"


class SingleEnrichRequest(BaseModel):
    """Request enrich một lead duy nhất."""
    company_name: str
    domain: str
    country: str = "vietnam"
    options: Optional[EnrichmentOptions] = None


class BatchEnrichRequest(BaseModel):
    """Request enrich nhiều lead cùng lúc."""
    leads: List[SingleEnrichRequest]
    options: Optional[EnrichmentOptions] = None  # override mặc định cho toàn batch


class EnrichmentResult(BaseModel):
    """Kết quả enrich một lead."""
    company_name: str
    domain: str
    primary_contact: Optional[ContactPerson] = None
    all_contacts: List[ContactPerson] = []
    primary_email: str = ""
    discovery_used: str = ""
    provider_used: str = ""
    rule_applied: str = ""      # BR-01.1 / BR-01.2 / BR-01.3
    status: str = "ok"          # "ok" | "missing_contact" | "error"
    error_message: str = ""
    elapsed_sec: float = 0.0


class EnrichmentOptionsMetadata(BaseModel):
    """Metadata mô tả các tuỳ chọn có sẵn — dùng để render FE form."""
    discovery_methods: List[str] = [m.value for m in DiscoveryMethod]
    providers: List[str] = [p.value for p in EnrichmentProvider]
    has_hunter_key: bool = False
    has_apollo_key: bool = False
    has_serper_key: bool = False
    has_serpapi_key: bool = False
    has_linkedin_cookie: bool = False
