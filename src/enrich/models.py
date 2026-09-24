from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class DiscoveryMethod(str, Enum):
    GOOGLE_DORKING = "google_dorking"
    PLAYWRIGHT_LINKEDIN = "playwright_linkedin"


class EnrichmentProvider(str, Enum):
    AUTO = "auto"
    HUNTER = "hunter"
    APOLLO = "apollo"
    INTERNAL_SMTP = "internal_smtp"


class ContactTier(int, Enum):
    TIER_1 = 1  # CEO, Founder, Co-Founder, Managing Director, Owner
    TIER_2 = 2  # Head of BD, Head of Partnerships, BD Director
    TIER_3 = 3  # Head of Flight, Air Ticketing Manager, Head of Ticketing
    TIER_4 = 4  # Fallback: partnerships@, contracting@, b2b@


class ContactPerson(BaseModel):
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    tier: int = Field(description="Tier 1, 2, 3 or 4")
    tier_label: str = Field(description="e.g. 'Tier 1: CEO', 'Tier 2: Head of BD', 'Fallback Department Contact'")
    email: Optional[str] = None
    is_primary: bool = False
    linkedin_url: Optional[str] = None
    source: str = Field(description="google_dorking | playwright_linkedin | hunter | apollo | website_fallback")
    verification_status: str = Field(default="unverified", description="verified | unverified | catch_all | invalid | fallback")
    confidence_score: float = Field(default=0.0, description="0.0 - 100.0 score")


class EnrichmentOptions(BaseModel):
    discovery_method: DiscoveryMethod = Field(
        default=DiscoveryMethod.GOOGLE_DORKING,
        description="Option for FE: 'google_dorking' (Recommended, fast, safe) or 'playwright_linkedin' (Deep scan browser)"
    )
    provider: EnrichmentProvider = Field(
        default=EnrichmentProvider.AUTO,
        description="Option for FE: 'hunter', 'apollo', 'internal_smtp', or 'auto'"
    )
    linkedin_cookie: Optional[str] = Field(
        default=None,
        description="Optional LinkedIn 'li_at' session cookie if using playwright_linkedin"
    )
    check_website_fallback: bool = Field(
        default=True,
        description="If True, automatically scrape website for Tier 4 emails (partnerships@) when personal email not found"
    )


class SingleEnrichRequest(BaseModel):
    company_name: str
    domain: str
    country: Optional[str] = "vietnam"
    options: Optional[EnrichmentOptions] = Field(default_factory=EnrichmentOptions)


class BatchEnrichRequest(BaseModel):
    leads: List[SingleEnrichRequest]
    options: Optional[EnrichmentOptions] = Field(default_factory=EnrichmentOptions)


class EnrichmentResult(BaseModel):
    company_name: str
    domain: str
    country: Optional[str] = None
    primary_email: Optional[str] = None
    primary_contact: Optional[ContactPerson] = None
    all_contacts: List[ContactPerson] = Field(default_factory=list)
    rule_applied: str = Field(description="BR-01.1 | BR-01.2 | BR-01.3")
    status: str = Field(description="success | missing_contact | failed")
    greeting_name: str = Field(default="Team", description="e.g. 'Mr. Tan', 'Ms. Aye', or 'Team'")
    discovery_method_used: str
    provider_used: str
    execution_time_seconds: float = 0.0
    error_message: Optional[str] = None


class EnrichmentOptionsMetadata(BaseModel):
    discovery_methods: List[dict]
    enrichment_providers: List[dict]
    tier_definitions: List[dict]
