"""
Utility functions for parsing and analyzing Google Maps scraper data.
"""

import json
import math
import re
from urllib.parse import urlparse
from typing import Optional

try:
    from . import config
except ImportError:
    import config


# ==============================================================================
# PARSING HELPERS
# ==============================================================================

def safe_json_parse(value) -> Optional[list | dict]:
    """Safely parse a JSON string, returning None on failure."""
    if pd_isna(value):
        return None
    try:
        return json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return None


def pd_isna(value) -> bool:
    """Check if value is NaN/None/empty without importing pandas at module level."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def parse_complete_address(raw_address) -> dict:
    """Parse the complete_address JSON field into a dict."""
    parsed = safe_json_parse(raw_address)
    if isinstance(parsed, dict):
        return parsed
    return {}


def parse_about_field(raw_about) -> dict:
    """
    Parse the 'about' JSON field and return a structured dict.
    Returns: {
        'online_appointments': bool,
        'on_site_services': bool,
        'credit_cards': bool,
        'debit_cards': bool,
        'nfc_payments': bool,
        'appointment_required': bool,
        'all_options': [(section_id, option_name, enabled), ...]
    }
    """
    result = {
        'online_appointments': False,
        'on_site_services': False,
        'credit_cards': False,
        'debit_cards': False,
        'nfc_payments': False,
        'appointment_required': False,
        'all_options': [],
    }

    sections = safe_json_parse(raw_about)
    if not isinstance(sections, list):
        return result

    for section in sections:
        section_id = section.get('id', '')
        for opt in section.get('options', []):
            name = opt.get('name', '')
            enabled = opt.get('enabled', False)
            result['all_options'].append((section_id, name, enabled))

            if enabled:
                name_lower = name.lower()
                if name_lower == 'online appointments':
                    result['online_appointments'] = True
                elif name_lower == 'on-site services':
                    result['on_site_services'] = True
                elif name_lower == 'credit cards':
                    result['credit_cards'] = True
                elif name_lower == 'debit cards':
                    result['debit_cards'] = True
                elif name_lower == 'nfc mobile payments':
                    result['nfc_payments'] = True
                elif name_lower == 'appointment required':
                    result['appointment_required'] = True

    return result


def extract_review_texts(raw_reviews) -> list[str]:
    """Extract all review description texts from user_reviews or user_reviews_extended."""
    reviews = safe_json_parse(raw_reviews)
    if not isinstance(reviews, list):
        return []
    texts = []
    for review in reviews:
        desc = review.get('Description', '')
        if desc:
            texts.append(str(desc))
    return texts


def extract_review_dates(raw_reviews) -> list[str]:
    """Extract review dates (When field) from user_reviews."""
    reviews = safe_json_parse(raw_reviews)
    if not isinstance(reviews, list):
        return []
    dates = []
    for review in reviews:
        when = review.get('When', '')
        if when:
            dates.append(str(when))
    return dates


def get_review_languages(review_texts: list[str]) -> set:
    """
    Simple heuristic to detect multiple languages in reviews.
    Returns a set of detected language hints.
    """
    languages = set()
    for text in review_texts:
        # Very basic heuristic based on character ranges
        if re.search(r'[\u0E00-\u0E7F]', text):
            languages.add('thai')
        if re.search(r'[\u4E00-\u9FFF]', text):
            languages.add('chinese')
        if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text):
            languages.add('japanese')
        if re.search(r'[\uAC00-\uD7AF]', text):
            languages.add('korean')
        if re.search(r'[\u0400-\u04FF]', text):
            languages.add('russian')
        if re.search(r'[\u0900-\u097F]', text):
            languages.add('hindi')
        if re.search(r'[\u0600-\u06FF]', text):
            languages.add('arabic')
        if re.search(r'[a-zA-Z]{3,}', text):
            languages.add('latin')  # English, French, Spanish, etc.
    return languages


# ==============================================================================
# WEBSITE ANALYSIS
# ==============================================================================

def parse_website(url) -> dict:
    """
    Analyze a website URL and return structured information.
    Returns: {
        'has_website': bool,
        'is_social_media': bool,
        'domain': str,
        'tld': str,
        'has_ota_keywords_strong': bool,
        'has_ota_keywords_weak': bool,
        'has_flight_keywords': bool,
        'is_proper_domain': bool,
        'is_known_ota_domain': bool,
        'matched_ota_domain': str,
    }
    """
    result = {
        'has_website': False,
        'is_social_media': False,
        'domain': '',
        'tld': '',
        'has_ota_keywords_strong': False,
        'has_ota_keywords_weak': False,
        'has_flight_keywords': False,
        'is_proper_domain': False,
        'is_known_ota_domain': False,
        'matched_ota_domain': '',
    }

    if pd_isna(url):
        return result

    url = str(url).strip()
    if not url:
        return result

    result['has_website'] = True

    # Parse URL
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or '').lower()
    except Exception:
        return result

    result['domain'] = hostname
    full_url_lower = url.lower()

    # Check social media
    for social in config.SOCIAL_MEDIA_DOMAINS:
        if social in hostname:
            result['is_social_media'] = True
            return result

    result['is_proper_domain'] = True

    # Check against known OTA domains (match against hostname only)
    for ota_domain in config.KNOWN_OTA_DOMAINS:
        # For patterns like "trip.com", require it to be at the END of hostname
        # or preceded by a dot, to avoid matching "phukettrip.com"
        if ota_domain.endswith('.com') or ota_domain.endswith('.asia') or ota_domain.endswith('.co'):
            # Exact domain match: hostname IS the domain, or is a subdomain of it
            if hostname == ota_domain or hostname.endswith('.' + ota_domain):
                result['is_known_ota_domain'] = True
                result['matched_ota_domain'] = ota_domain
                break
        else:
            # For partial patterns like "skyscanner.", match as substring of hostname
            if ota_domain in hostname:
                result['is_known_ota_domain'] = True
                result['matched_ota_domain'] = ota_domain
                break

    # Extract TLD
    parts = hostname.split('.')
    if len(parts) >= 2:
        if parts[-1] in ('th', 'vn', 'my', 'sg', 'ph', 'id', 'in', 'uk', 'au', 'nz', 'jp', 'kr', 'cn', 'hk', 'tw'):
            result['tld'] = '.' + '.'.join(parts[-2:])
        else:
            result['tld'] = '.' + parts[-1]

    # Check for STRONG OTA keywords in domain (booking, ticket, flight, etc.)
    domain_text = hostname.replace('.', ' ').replace('-', ' ').replace('_', ' ')
    for kw in config.OTA_WEBSITE_KEYWORDS_STRONG:
        if kw in domain_text:
            result['has_ota_keywords_strong'] = True
            break

    # Check for WEAK OTA keywords in domain (travel, tour, trip — too common)
    if not result['has_ota_keywords_strong']:
        for kw in config.OTA_WEBSITE_KEYWORDS_WEAK:
            if kw in domain_text:
                result['has_ota_keywords_weak'] = True
                break

    # Check for flight keywords in domain + path
    for kw in config.FLIGHT_KEYWORDS_PRIMARY:
        if kw.replace(' ', '') in full_url_lower.replace(' ', ''):
            result['has_flight_keywords'] = True
            break

    return result


def has_ota_review_signals(review_texts: list[str]) -> tuple[bool, list[str]]:
    """
    Check if reviews mention online booking behavior (not just 'we booked a tour').
    Returns (has_signals, matched_phrases).
    """
    matches = []
    combined = ' '.join(review_texts).lower()
    for kw in config.OTA_REVIEW_KEYWORDS:
        if kw in combined:
            matches.append(kw)
    return len(matches) > 0, matches


# ==============================================================================
# GEO HELPERS
# ==============================================================================

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Calculate distance in km between two lat/lon points."""
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def is_near_airport(lat, lon, country: str) -> tuple[bool, str]:
    """
    Check if coordinates are near any airport for the given country.
    Returns (is_near, nearest_airport_name).
    """
    airports = config.AIRPORTS.get(country.lower(), [])
    if pd_isna(lat) or pd_isna(lon):
        return False, ""

    try:
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        return False, ""

    for airport in airports:
        dist = haversine_km(lat, lon, airport['lat'], airport['lon'])
        if dist <= airport['radius_km']:
            return True, airport['name']

    return False, ""


def is_top_tourism_city(address_dict: dict, country: str) -> bool:
    """Check if the agency is located in a top tourism city."""
    cities = config.TOP_TOURISM_CITIES.get(country.lower(), [])
    if not cities:
        return False

    city = (address_dict.get('city', '') or '').lower()
    state = (address_dict.get('state', '') or '').lower()
    borough = (address_dict.get('borough', '') or '').lower()

    location_text = f"{city} {state} {borough}"
    for tourism_city in cities:
        if tourism_city in location_text:
            return True
    return False


# ==============================================================================
# TEXT ANALYSIS
# ==============================================================================

def has_flight_keywords_in_text(text: str, check_false_positives: bool = True) -> bool:
    """Check if text contains flight-related keywords, excluding false positives."""
    text_lower = text.lower()

    # First check false positives
    if check_false_positives:
        for fp in config.FLIGHT_FALSE_POSITIVES:
            if fp in text_lower:
                # Remove the false positive to avoid matching on remaining text
                text_lower = text_lower.replace(fp, '')

    for kw in config.FLIGHT_KEYWORDS_PRIMARY + config.FLIGHT_KEYWORDS_SECONDARY:
        if kw in text_lower:
            return True
    return False


def has_ota_keywords_in_title(title: str) -> bool:
    """Check if business title contains OTA-suggesting keywords."""
    title_lower = title.lower()
    for kw in config.OTA_TITLE_KEYWORDS:
        if kw in title_lower:
            return True
    return False


def is_airline_office(title: str, category: str) -> bool:
    """
    Check if the listing is an airline's own office/counter (not a third-party agency).
    These should be EXCLUDED from results.
    """
    title_lower = title.lower()
    category_lower = category.lower() if not pd_isna(category) else ''

    for airline in config.AIRLINE_OFFICE_KEYWORDS:
        if airline in title_lower:
            # Check if it matches airline office patterns
            for pattern in config.AIRLINE_OFFICE_TITLE_PATTERNS:
                if pattern in title_lower:
                    return True
            # If category is "Airline" (not "Airline ticket agency"), it's the airline itself
            if category_lower == 'airline':
                return True
    return False


def is_formal_company(title: str, address: str) -> bool:
    """Check if business appears to be a registered company."""
    text = f"{title} {address}".lower()
    patterns = ['co., ltd', 'co.,ltd', 'company limited', 'corp.', 'llc',
                'inc.', 'ltd.', 'limited', 'co. ltd', 'corporation',
                'บริษัท', 'จำกัด']  # Thai for company/limited
    return any(p in text for p in patterns)
