"""
OTA & Air Ticketing Agency Identification Pipeline
===================================================

Usage:
    python pipeline.py --input <path_to_csv> --country <country_name>

Example:
    python pipeline.py --input ../data/thailand/raw_results.csv --country thailand

Output:
    Creates folder: ../results/<country>/
    With files:
        - ota_candidates.csv          (all OTA candidates, scored & ranked)
        - air_ticketing_candidates.csv (all air ticketing candidates, scored & ranked)
        - combined_candidates.csv      (union of both, deduplicated, with segment flags)
        - excluded_records.csv         (records filtered out in Stage 1, with reasons)
        - pipeline_summary.txt         (run summary with counts and statistics)
"""

import argparse
import csv
import os
import sys
from datetime import datetime

import pandas as pd

try:
    from . import config, utils
except ImportError:
    import config, utils


# ==============================================================================
# STAGE 1: EXCLUSION
# ==============================================================================

def stage1_exclude(df: pd.DataFrame, country: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Apply exclusion filters to remove irrelevant records.
    Returns (kept_df, excluded_df).
    """
    exclusion_reasons = []

    # Track indices to exclude
    exclude_mask = pd.Series(False, index=df.index)

    # --- Rule 1: Irrelevant categories ---
    cat_lower = df['category'].fillna('').str.lower()
    for exc_cat in config.EXCLUDE_CATEGORIES:
        match = cat_lower == exc_cat
        new_matches = match & ~exclude_mask
        for idx in df[new_matches].index:
            exclusion_reasons.append((idx, f"Excluded category: {exc_cat}"))
        exclude_mask |= match

    # --- Rule 2: Airline offices (not third-party agencies) ---
    for idx, row in df[~exclude_mask].iterrows():
        title = str(row.get('title', ''))
        category = str(row.get('category', ''))
        if utils.is_airline_office(title, category):
            exclude_mask[idx] = True
            exclusion_reasons.append((idx, f"Airline office: {title}"))

    # --- Rule 3: Permanently/temporarily closed ---
    if 'status' in df.columns:
        status_lower = df['status'].fillna('').str.lower()
        closed = status_lower.str.contains('permanently closed|temporarily closed', na=False)
        new_closed = closed & ~exclude_mask
        for idx in df[new_closed].index:
            exclusion_reasons.append((idx, "Business closed"))
        exclude_mask |= closed

    # --- Rule 4: Zero-signal records ---
    # No website AND no email AND review_count < 2 AND no phone
    no_website = df['website'].isna() | (df['website'].str.strip() == '')
    no_email = df['emails'].isna() | (df['emails'].str.strip() == '')
    no_phone = df['phone'].isna() | (df['phone'].str.strip() == '')
    low_reviews = df['review_count'].fillna(0) < 2
    zero_signal = no_website & no_email & low_reviews & no_phone
    new_zero = zero_signal & ~exclude_mask
    for idx in df[new_zero].index:
        exclusion_reasons.append((idx, "Zero-signal: no website, no email, no phone, <2 reviews"))
    exclude_mask |= zero_signal

    # --- Rule 5: Deduplicate by CID (keep first occurrence) ---
    if 'cid' in df.columns:
        dup_mask = df.duplicated(subset='cid', keep='first') & df['cid'].notna()
        new_dups = dup_mask & ~exclude_mask
        for idx in df[new_dups].index:
            exclusion_reasons.append((idx, "Duplicate CID"))
        exclude_mask |= dup_mask

    # Build excluded dataframe with reasons
    excluded_df = df[exclude_mask].copy()
    reason_map = {}
    for idx, reason in exclusion_reasons:
        if idx in reason_map:
            reason_map[idx] += f"; {reason}"
        else:
            reason_map[idx] = reason
    excluded_df['exclusion_reason'] = excluded_df.index.map(lambda x: reason_map.get(x, 'Unknown'))

    kept_df = df[~exclude_mask].copy()

    return kept_df, excluded_df


# ==============================================================================
# STAGE 2: FEATURE EXTRACTION
# ==============================================================================

def extract_features(df: pd.DataFrame, country: str) -> pd.DataFrame:
    """
    Parse all JSON fields and extract classification features for each record.
    """
    features = []

    for idx, row in df.iterrows():
        feat = {'original_index': idx}

        # --- Website analysis ---
        web = utils.parse_website(row.get('website'))
        feat['has_website'] = web['has_website']
        feat['is_social_media'] = web['is_social_media']
        feat['is_proper_domain'] = web['is_proper_domain']
        feat['website_domain'] = web['domain']
        feat['website_tld'] = web['tld']
        feat['website_has_ota_kw_strong'] = web['has_ota_keywords_strong']
        feat['website_has_ota_kw_weak'] = web['has_ota_keywords_weak']
        feat['website_has_flight_kw'] = web['has_flight_keywords']
        feat['is_known_ota_domain'] = web['is_known_ota_domain']
        feat['matched_ota_domain'] = web['matched_ota_domain']

        # --- About field ---
        about = utils.parse_about_field(row.get('about'))
        feat['online_appointments'] = about['online_appointments']
        feat['credit_cards'] = about['credit_cards']
        feat['nfc_payments'] = about['nfc_payments']

        # --- Address ---
        addr = utils.parse_complete_address(row.get('complete_address'))
        feat['city'] = addr.get('city', '')
        feat['state'] = addr.get('state', '')
        feat['country_code'] = addr.get('country', '')

        # --- Geo ---
        near_airport, airport_name = utils.is_near_airport(
            row.get('latitude'), row.get('longitude'), country
        )
        feat['near_airport'] = near_airport
        feat['nearest_airport'] = airport_name
        feat['is_top_tourism_city'] = utils.is_top_tourism_city(addr, country)

        # --- Title analysis ---
        title = str(row.get('title', ''))
        feat['title_has_ota_kw'] = utils.has_ota_keywords_in_title(title)
        feat['title_has_flight_kw'] = utils.has_flight_keywords_in_text(title)
        feat['is_formal_company'] = utils.is_formal_company(title, str(row.get('address', '')))

        # --- Review analysis ---
        review_texts_main = utils.extract_review_texts(row.get('user_reviews'))
        review_texts_ext = utils.extract_review_texts(row.get('user_reviews_extended'))
        all_review_texts = review_texts_main + review_texts_ext
        combined_review_text = ' '.join(all_review_texts)

        feat['flight_in_reviews'] = utils.has_flight_keywords_in_text(combined_review_text)
        feat['review_languages'] = utils.get_review_languages(all_review_texts)
        feat['has_international_reviews'] = len(feat['review_languages']) >= 2

        # OTA-specific: do reviews mention online booking behavior?
        ota_review_hit, ota_review_matches = utils.has_ota_review_signals(all_review_texts)
        feat['has_ota_review_signals'] = ota_review_hit
        feat['ota_review_matches'] = '; '.join(ota_review_matches) if ota_review_matches else ''

        # --- Contact ---
        feat['has_email'] = not utils.pd_isna(row.get('emails'))
        feat['has_phone'] = not utils.pd_isna(row.get('phone'))

        # --- Owner ---
        owner = utils.safe_json_parse(row.get('owner'))
        feat['owner_verified'] = isinstance(owner, dict) and bool(owner.get('id'))

        # --- Category ---
        feat['category_lower'] = str(row.get('category', '')).lower()

        # --- Review stats ---
        feat['review_count'] = int(row.get('review_count', 0) or 0)
        feat['review_rating'] = float(row.get('review_rating', 0) or 0)

        # --- Recent activity (check review dates) ---
        review_dates = utils.extract_review_dates(row.get('user_reviews'))
        feat['has_recent_reviews'] = False
        for d in review_dates:
            try:
                # Dates are like "2025-10-28" or "2023-4-2"
                parts = d.split('-')
                if len(parts) >= 1:
                    year = int(parts[0])
                    if year >= 2024:
                        feat['has_recent_reviews'] = True
                        break
            except (ValueError, IndexError):
                continue

        features.append(feat)

    return pd.DataFrame(features)


# ==============================================================================
# STAGE 2: CLASSIFICATION
# ==============================================================================

def classify_ota(feat: pd.Series) -> tuple[str, list[str]]:
    """
    Classify a record as OTA (Online Travel Agency).

    STRICT definition: a business with a transactional website where B2C
    customers can search and book travel products (flights, hotels, packages)
    online — like Booking.com, Agoda, Traveloka, 12Go.

    NOT: a tour operator with a brochure site, or a local agency that takes
    bookings via WhatsApp/phone/email only.

    Returns (classification, list_of_reasons).
    Classifications:
        'strong'    — Very likely a real OTA (known domain, booking URL, etc.)
        'moderate'  — Good signals, needs website verification
        'potential' — Weak signals, requires manual check
        'none'      — Not an OTA
    """
    reasons = []

    # ----- HARD REQUIREMENT: must have a proper website -----
    if not feat['is_proper_domain']:
        return 'none', ['No proper website domain']

    # =========================================================
    # SIGNAL 1: Known OTA domain (strongest signal)
    # =========================================================
    if feat['is_known_ota_domain']:
        reasons.append(f'Known OTA/booking platform: {feat["matched_ota_domain"]}')
        return 'strong', reasons

    # =========================================================
    # SIGNAL 2: Website URL contains booking/ticket/flight keywords
    # (domain like "edcbooking.com", "fly2thai.com", "booktouronline.com")
    # =========================================================
    has_booking_url = feat['website_has_ota_kw_strong']
    if has_booking_url:
        reasons.append('Website URL contains booking/ticket/flight keywords')

    # =========================================================
    # SIGNAL 3: Google Maps "Online Appointments" enabled
    # =========================================================
    if feat['online_appointments']:
        reasons.append('Google Maps: Online Appointments enabled')

    # =========================================================
    # SIGNAL 4: Reviews mention online booking behavior
    # =========================================================
    if feat['has_ota_review_signals']:
        reasons.append(f'Reviews mention online booking ({feat["ota_review_matches"]})')

    # =========================================================
    # SIGNAL 5: Title suggests booking platform
    # =========================================================
    if feat['title_has_ota_kw']:
        reasons.append('Business name contains booking/online keywords')

    # =========================================================
    # SIGNAL 6: Flight keywords in title or URL
    # =========================================================
    if feat['title_has_flight_kw']:
        reasons.append('Flight keywords in business name')
    if feat['website_has_flight_kw']:
        reasons.append('Flight keywords in website URL')

    # =========================================================
    # SUPPORTIVE signals (not enough alone, but boost confidence)
    # =========================================================
    supportive = 0
    if feat['is_formal_company']:
        supportive += 1
    if feat['has_email']:
        supportive += 1
    if feat['credit_cards'] or feat['nfc_payments']:
        supportive += 1
    if feat['has_international_reviews']:
        supportive += 1
    if feat['review_count'] >= 100:
        supportive += 1

    # =========================================================
    # CLASSIFICATION RULES (strict)
    # =========================================================

    # Count core OTA signals (not supportive)
    core_signals = sum([
        has_booking_url,
        feat['online_appointments'],
        feat['has_ota_review_signals'],
        feat['title_has_ota_kw'],
        feat['title_has_flight_kw'] or feat['website_has_flight_kw'],
    ])

    # STRONG: booking URL + at least one more signal
    if has_booking_url and core_signals >= 2:
        return 'strong', reasons

    # STRONG: flight keywords in both title AND URL
    if feat['title_has_flight_kw'] and feat['website_has_flight_kw']:
        return 'strong', reasons

    # MODERATE: has booking URL OR (online appointments + booking-related signal)
    if has_booking_url:
        return 'moderate', reasons
    if feat['online_appointments'] and (feat['has_ota_review_signals'] or feat['title_has_ota_kw']):
        return 'moderate', reasons
    if feat['title_has_flight_kw'] and feat['is_proper_domain']:
        return 'moderate', reasons
    if feat['website_has_flight_kw'] and feat['is_proper_domain']:
        return 'moderate', reasons

    # POTENTIAL: online appointments + formal company + good scale
    if feat['online_appointments'] and supportive >= 2:
        return 'potential', reasons + ['Online appointments + supportive signals; needs website check']

    # POTENTIAL: OTA review signals + proper website
    if feat['has_ota_review_signals'] and supportive >= 1:
        return 'potential', reasons + ['Booking behavior in reviews; needs website check']

    return 'none', reasons


def classify_air_ticketing(feat: pd.Series) -> tuple[str, list[str]]:
    """
    Classify a record for air ticketing: 'strong', 'moderate', 'potential', or 'none'.
    Returns (classification, list_of_reasons).
    """
    reasons = []

    # Strong category signal
    is_airline_cat = feat['category_lower'] in [c.lower() for c in config.FLIGHT_STRONG_CATEGORIES]
    if is_airline_cat:
        reasons.append(f'Category: {feat["category_lower"]}')

    if feat['title_has_flight_kw']:
        reasons.append('Flight keywords in title')

    if feat['website_has_flight_kw']:
        reasons.append('Flight keywords in website URL')

    if feat['flight_in_reviews']:
        reasons.append('Flight/airline mentioned in reviews')

    # Supportive signals
    supportive = 0
    if feat['near_airport']:
        supportive += 1
        reasons.append(f'Near airport: {feat["nearest_airport"]}')
    if feat['credit_cards'] or feat['nfc_payments']:
        supportive += 1
        reasons.append('Accepts card/NFC payments')
    if feat['review_count'] >= 30:
        supportive += 1
        reasons.append(f'Good review volume ({feat["review_count"]})')
    if feat['has_email']:
        supportive += 1
        reasons.append('Has email')
    if feat['is_proper_domain']:
        supportive += 1
        reasons.append('Has proper website')

    # Count strong flight signals
    strong_flight = sum([
        is_airline_cat,
        feat['title_has_flight_kw'],
        feat['website_has_flight_kw'],
        feat['flight_in_reviews'],
    ])

    # Classification rules
    if is_airline_cat or (feat['title_has_flight_kw'] and feat['is_proper_domain']):
        return 'strong', reasons
    elif feat['flight_in_reviews'] and (feat['is_proper_domain'] or feat['review_count'] >= 20):
        return 'moderate', reasons
    elif strong_flight >= 1 and supportive >= 2:
        return 'potential', reasons
    elif feat['category_lower'] == 'visa consulting service' and feat['flight_in_reviews']:
        return 'potential', reasons + ['Visa + flight combo']
    else:
        return 'none', reasons


# ==============================================================================
# STAGE 3: SCORING
# ==============================================================================

def compute_score(feat: pd.Series) -> dict:
    """
    Compute the Partner Priority Score (0-100) across 5 dimensions.
    Returns a dict with dimension scores and total.
    """
    s = config.SCORING
    scores = {}

    # 1. Digital Maturity (max 25)
    dm = 0
    if feat['is_proper_domain']:
        dm += s['has_proper_website']
    if feat['online_appointments']:
        dm += s['has_online_appointments']
    if feat['has_email']:
        dm += s['has_email']
    good_domain = feat['website_tld'] in ('.co.th', '.com', '.travel', '.tours', '.com.vn', '.vn')
    if good_domain:
        dm += s['has_good_domain']
    scores['digital_maturity'] = min(dm, 25)

    # 2. Business Scale (max 20)
    bs = 0
    rc = feat['review_count']
    if rc >= 100:
        bs += s['reviews_100_plus']
    elif rc >= 50:
        bs += s['reviews_50_99']
    elif rc >= 20:
        bs += s['reviews_20_49']
    elif rc >= 5:
        bs += s['reviews_5_19']

    rr = feat['review_rating']
    if rr >= 4.5:
        bs += s['rating_4_5_plus']
    elif rr >= 4.0:
        bs += s['rating_4_0_4_4']
    elif rr >= 3.5:
        bs += s['rating_3_5_3_9']
    scores['business_scale'] = min(bs, 20)

    # 3. Flight Relevance (max 25)
    fr = 0
    if feat['category_lower'] in [c.lower() for c in config.FLIGHT_STRONG_CATEGORIES]:
        fr += s['category_airline_ticket']
    if feat['title_has_flight_kw']:
        fr += s['flight_keywords_in_title']
    if feat['flight_in_reviews']:
        fr += s['flight_mentions_in_reviews']
    if feat['website_has_flight_kw']:
        fr += s['flight_keywords_in_website']
    scores['flight_relevance'] = min(fr, 25)

    # 4. Market Position (max 15)
    mp = 0
    if feat['is_top_tourism_city']:
        mp += s['top_tourism_city']
    if feat['near_airport']:
        mp += s['near_airport']
    if feat['has_international_reviews']:
        mp += s['international_reviews']
    scores['market_position'] = min(mp, 15)

    # 5. Contactability (max 15)
    ct = 0
    if feat['has_email']:
        ct += s['has_email_contact']
    if feat['has_phone']:
        ct += s['has_phone']
    if feat['is_proper_domain']:
        ct += s['has_website_contact']
    if feat['owner_verified']:
        ct += s['owner_verified']
    scores['contactability'] = min(ct, 15)

    scores['total'] = sum(scores.values())

    # Priority tier
    total = scores['total']
    if total >= 70:
        scores['tier'] = 'Tier 1'
    elif total >= 45:
        scores['tier'] = 'Tier 2'
    elif total >= 20:
        scores['tier'] = 'Tier 3'
    else:
        scores['tier'] = 'Tier 4'

    return scores


# ==============================================================================
# MAIN PIPELINE
# ==============================================================================

def run_pipeline(input_path: str, country: str, output_dir: str):
    """Execute the full pipeline."""

    print(f"\n{'='*70}")
    print(f"  OTA & Air Ticketing Identification Pipeline")
    print(f"  Country: {country.upper()}")
    print(f"  Input:   {input_path}")
    print(f"  Output:  {output_dir}")
    print(f"{'='*70}\n")

    # --- Load data ---
    print("[1/5] Loading data...")
    df = pd.read_csv(input_path)
    print(f"       Loaded {len(df)} records.")

    # --- Stage 1: Exclusion ---
    print("[2/5] Stage 1: Applying exclusion filters...")
    kept_df, excluded_df = stage1_exclude(df, country)
    print(f"       Excluded: {len(excluded_df)} records")
    print(f"       Remaining: {len(kept_df)} records")

    # --- Stage 2: Feature extraction ---
    print("[3/5] Stage 2: Extracting features...")
    features_df = extract_features(kept_df, country)

    # --- Stage 2: Classification ---
    print("[4/5] Stage 2: Classifying candidates...")
    ota_results = []
    air_results = []

    for feat_idx, feat in features_df.iterrows():
        orig_idx = feat['original_index']
        orig_row = kept_df.loc[orig_idx]

        # OTA classification
        ota_class, ota_reasons = classify_ota(feat)

        # Air ticketing classification
        air_class, air_reasons = classify_air_ticketing(feat)

        # Scoring
        scores = compute_score(feat)

        base_info = {
            'title': orig_row.get('title', ''),
            'category': orig_row.get('category', ''),
            'website': orig_row.get('website', ''),
            'phone': orig_row.get('phone', ''),
            'emails': orig_row.get('emails', ''),
            'address': orig_row.get('address', ''),
            'city': feat['city'],
            'state': feat['state'],
            'review_count': feat['review_count'],
            'review_rating': feat['review_rating'],
            'latitude': orig_row.get('latitude', ''),
            'longitude': orig_row.get('longitude', ''),
            'google_maps_link': orig_row.get('link', ''),
            'has_proper_website': feat['is_proper_domain'],
            'online_appointments': feat['online_appointments'],
            'accepts_credit_cards': feat['credit_cards'],
            'near_airport': feat['near_airport'],
            'nearest_airport': feat['nearest_airport'],
            'is_top_tourism_city': feat['is_top_tourism_city'],
            'has_international_reviews': feat['has_international_reviews'],
            'has_recent_reviews': feat['has_recent_reviews'],
            'is_known_ota_domain': feat['is_known_ota_domain'],
            'matched_ota_domain': feat['matched_ota_domain'],
            'has_ota_review_signals': feat['has_ota_review_signals'],
            'ota_review_matches': feat['ota_review_matches'],
            'owner_verified': feat['owner_verified'],
            'score_digital_maturity': scores['digital_maturity'],
            'score_business_scale': scores['business_scale'],
            'score_flight_relevance': scores['flight_relevance'],
            'score_market_position': scores['market_position'],
            'score_contactability': scores['contactability'],
            'score_total': scores['total'],
            'priority_tier': scores['tier'],
        }

        if ota_class != 'none':
            ota_entry = {**base_info}
            ota_entry['ota_classification'] = ota_class
            ota_entry['ota_reasons'] = '; '.join(ota_reasons)
            ota_results.append(ota_entry)

        if air_class != 'none':
            air_entry = {**base_info}
            air_entry['air_classification'] = air_class
            air_entry['air_reasons'] = '; '.join(air_reasons)
            air_results.append(air_entry)

    # --- Build output DataFrames ---
    ota_df = pd.DataFrame(ota_results).sort_values('score_total', ascending=False) if ota_results else pd.DataFrame()
    air_df = pd.DataFrame(air_results).sort_values('score_total', ascending=False) if air_results else pd.DataFrame()

    # Combined (union, deduplicated)
    combined_entries = []
    seen_titles = set()
    for entry in ota_results:
        key = entry['title']
        if key not in seen_titles:
            seen_titles.add(key)
            combined_entry = {**entry}
            combined_entry['segment'] = 'OTA'
            # Check if also in air
            for air_entry in air_results:
                if air_entry['title'] == key:
                    combined_entry['segment'] = 'OTA + Air Ticketing'
                    combined_entry['air_classification'] = air_entry['air_classification']
                    combined_entry['air_reasons'] = air_entry['air_reasons']
                    break
            combined_entries.append(combined_entry)

    for entry in air_results:
        key = entry['title']
        if key not in seen_titles:
            seen_titles.add(key)
            combined_entry = {**entry}
            combined_entry['segment'] = 'Air Ticketing'
            combined_entries.append(combined_entry)

    combined_df = pd.DataFrame(combined_entries).sort_values('score_total', ascending=False) if combined_entries else pd.DataFrame()

    # --- Stage 3: Save outputs ---
    print("[5/5] Saving results...")
    os.makedirs(output_dir, exist_ok=True)

    ota_path = os.path.join(output_dir, 'ota_candidates.csv')
    air_path = os.path.join(output_dir, 'air_ticketing_candidates.csv')
    combined_path = os.path.join(output_dir, 'combined_candidates.csv')
    excluded_path = os.path.join(output_dir, 'excluded_records.csv')
    summary_path = os.path.join(output_dir, 'pipeline_summary.txt')

    if not ota_df.empty:
        ota_df.to_csv(ota_path, index=False, quoting=csv.QUOTE_ALL)
    if not air_df.empty:
        air_df.to_csv(air_path, index=False, quoting=csv.QUOTE_ALL)
    if not combined_df.empty:
        combined_df.to_csv(combined_path, index=False, quoting=csv.QUOTE_ALL)

    # Save excluded with just key columns + reason
    if not excluded_df.empty:
        excl_cols = ['title', 'category', 'website', 'review_count', 'review_rating', 'exclusion_reason']
        excl_save = excluded_df[[c for c in excl_cols if c in excluded_df.columns]]
        excl_save.to_csv(excluded_path, index=False, quoting=csv.QUOTE_ALL)

    # --- Summary ---
    ota_strong = len(ota_df[ota_df['ota_classification'] == 'strong']) if not ota_df.empty else 0
    ota_moderate = len(ota_df[ota_df['ota_classification'] == 'moderate']) if not ota_df.empty else 0
    ota_potential = len(ota_df[ota_df['ota_classification'] == 'potential']) if not ota_df.empty else 0

    air_strong = len(air_df[air_df['air_classification'] == 'strong']) if not air_df.empty else 0
    air_moderate = len(air_df[air_df['air_classification'] == 'moderate']) if not air_df.empty else 0
    air_potential = len(air_df[air_df['air_classification'] == 'potential']) if not air_df.empty else 0

    tier1 = len(combined_df[combined_df['priority_tier'] == 'Tier 1']) if not combined_df.empty else 0
    tier2 = len(combined_df[combined_df['priority_tier'] == 'Tier 2']) if not combined_df.empty else 0
    tier3 = len(combined_df[combined_df['priority_tier'] == 'Tier 3']) if not combined_df.empty else 0
    tier4 = len(combined_df[combined_df['priority_tier'] == 'Tier 4']) if not combined_df.empty else 0

    both_count = len(combined_df[combined_df['segment'] == 'OTA + Air Ticketing']) if not combined_df.empty else 0

    summary = f"""
================================================================================
  PIPELINE SUMMARY — {country.upper()}
  Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
================================================================================

INPUT
  File:    {input_path}
  Records: {len(df)}

STAGE 1: EXCLUSION
  Excluded:  {len(excluded_df)}
  Remaining: {len(kept_df)}

STAGE 2: CLASSIFICATION

  OTA Candidates: {len(ota_df)}
    - Strong:    {ota_strong}
    - Moderate:  {ota_moderate}
    - Potential:  {ota_potential}

  Air Ticketing Candidates: {len(air_df)}
    - Strong:    {air_strong}
    - Moderate:  {air_moderate}
    - Potential:  {air_potential}

  Overlap (Both OTA + Air): {both_count}

STAGE 3: PRIORITY TIERS (Combined)
  Total unique candidates: {len(combined_df)}
    - Tier 1 (Score 70+):  {tier1}  ← Immediate outreach
    - Tier 2 (Score 45-69): {tier2}  ← Secondary outreach
    - Tier 3 (Score 20-44): {tier3}  ← Research queue
    - Tier 4 (Score <20):   {tier4}  ← Archive

OUTPUT FILES
  {ota_path}
  {air_path}
  {combined_path}
  {excluded_path}
  {summary_path}
================================================================================
"""

    with open(summary_path, 'w') as f:
        f.write(summary)

    print(summary)
    print("Done!\n")


# ==============================================================================
# CLI
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='OTA & Air Ticketing Agency Identification Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py --input ../data/thailand/raw_results.csv --country thailand
  python pipeline.py --input ../data/vietnam/raw_results.csv --country vietnam
  python pipeline.py --input data.csv --country thailand --output /custom/path
        """
    )
    parser.add_argument('--input', '-i', required=True,
                        help='Path to the Google Maps scraper CSV file')
    parser.add_argument('--country', '-c', required=True,
                        help='Country name (used for airport proximity, tourism cities config)')
    parser.add_argument('--output', '-o', default=None,
                        help='Output directory (default: ../results/<country>)')

    args = parser.parse_args()

    if args.output:
        output_dir = args.output
    else:
        # Default: ../results/<country>/  (sibling to data-processing)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(script_dir)
        output_dir = os.path.join(parent_dir, 'results', args.country.lower())

    run_pipeline(args.input, args.country, output_dir)


if __name__ == '__main__':
    main()
