"""
Configuration for OTA & Air Ticketing Agency Identification Pipeline.
Adjust these settings per-country as needed.
"""

# ==============================================================================
# STAGE 1: EXCLUSION FILTERS
# ==============================================================================

# Google Maps categories to EXCLUDE (not relevant to OTA or air ticketing)
EXCLUDE_CATEGORIES = [
    "car rental agency",
    "motorcycle rental agency",
    "boat tour agency",
    "diving center",
    "taxi service",
    "airport shuttle service",
    "resort hotel",
    "hotel",
    "hostel",
    "guest house",
    "restaurant",
    "spa",
    "education center",
    "ferry service",
    "bus station",
    "bus company",
    "tourist attraction",
    "temple",
    "shopping mall",
    "campground",
    "event ticket seller",
    "auto repair shop",
    "car repair and maintenance service",
    "travel lounge",          # airline lounges, not agencies
    "transportation service",
    "trucking company",
    "moving company",
    "storage facility",
    "parking lot",
    "gas station",
    "atm",
    "bank",
    "hospital",
    "pharmacy",
    "school",
    "university",
    "gym",
    "fitness center",
    "laundry service",
    "real estate agency",
    "insurance agency",
    "law firm",
    "accounting firm",
]

# Airline brand keywords - these are airline OFFICES, not third-party agencies
# We exclude listings that ARE the airline's own office/counter
AIRLINE_OFFICE_KEYWORDS = [
    "thai airways",
    "bangkok airways",
    "nok air",
    "nokair",
    "airasia",
    "air asia",
    "lion air",
    "thai lion",
    "vietjet",
    "aeroflot",
    "japan airlines",
    "air france",
    "emirates",
    "qatar airways",
    "singapore airlines",
    "korean air",
    "cathay pacific",
    "china airlines",
    "eva air",
    "garuda indonesia",
    "batik air",
    "citilink",
    "sriwijaya air",
    "wings air",
    "super air jet",
    "malaysia airlines",
    "philippine airlines",
    "cebu pacific",
    "scoot",
    "jetstar",
    "peach aviation",
    "spring airlines",
    "lufthansa",
    "british airways",
    "klm",
    "united airlines",
    "delta airlines",
    "american airlines",
]

# If the title matches an airline keyword AND one of these patterns,
# it's likely the airline's own office (exclude it)
AIRLINE_OFFICE_TITLE_PATTERNS = [
    "office",
    "counter",
    "lounge",
    "station",
    "operations",
    "complex",
    "ticketing service",  # e.g., "Thai Airways Ticketing Service"
    "sale counter",
]

# Social media domains (websites pointing here are NOT proper business sites)
SOCIAL_MEDIA_DOMAINS = [
    "facebook.com",
    "fb.com",
    "instagram.com",
    "line.me",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "linkedin.com",
    "pinterest.com",
]


# ==============================================================================
# STAGE 2: CLASSIFICATION SIGNALS
# ==============================================================================

# --- Segment A: OTA Identification ---
#
# DEFINITION: An OTA is a company with a transactional website/app where
# B2C customers can search, compare, and BOOK travel products (flights,
# hotels, packages) online — like Booking.com, Agoda, Traveloka, 12Go.
#
# This is NOT: a tour operator with a brochure site, a DMC with a contact
# form, or a local agency that takes bookings via WhatsApp/phone.

# Categories considered as primary OTA candidates
OTA_PRIMARY_CATEGORIES = [
    "travel agency",
    "tour agency",
    "tour operator",
    "travel services",
    "airline ticket agency",
    "visa consulting service",
    "sightseeing tour agency",
    "corporate office",
    "bus ticket agency",
    "vacation home rental agency",
    # Tiếng Việt
    "đại lý du lịch",
    "đại lý vé máy bay",
    "nhà điều hành du lịch",
    "công ty du lịch",
    "dịch vụ du lịch",
    "phòng vé máy bay",
    "phòng vé",
    "đại lý lữ hành",
    "công ty lữ hành",
]

# Website domain keywords that STRONGLY suggest a booking platform
# (not just a travel brochure site)
OTA_WEBSITE_KEYWORDS_STRONG = [
    "booking", "book", "ticket", "flight", "fare", "fly",
    "reserve", "checkout", "pay",
    # Tiếng Việt không dấu trong domain
    "vemaybay", "phongve", "bay", "datve", "banve", "hangkhong", "airticket",
]

# Website domain keywords that are WEAK signals (travel brochure sites also use these)
OTA_WEBSITE_KEYWORDS_WEAK = [
    "travel", "tour", "trip", "holiday",
    "voyage", "hotel", "resort", "vacation",
    "dulich", "luhanh",
]

# TLDs that suggest travel industry
OTA_TLDS = [".travel", ".tours", ".holiday", ".booking", ".flights"]

# Business name keywords suggesting OTA nature
OTA_TITLE_KEYWORDS = [
    "online", "booking", "e-travel", "digital", ".com", "platform",
    "app", "ota", "etravel", "e-ticket",
    # Tiếng Việt
    "trực tuyến", "đặt vé", "vé máy bay", "phòng vé", "vé giá rẻ",
]

# Known OTA / booking platform domains — if a website uses one of these,
# the agency is either an OTA itself or resells through one
# Known OTA / booking platform domains.
# IMPORTANT: These are matched against the HOSTNAME only (not the full URL),
# and require the pattern to appear as a distinct part (not inside another word).
# Use the full hostname fragment to avoid false positives.
KNOWN_OTA_DOMAINS = [
    # Global OTAs
    "traveloka.com", "klook.com", "agoda.com", "booking.com",
    "expedia.com", "skyscanner.", "kiwi.com",
    "kayak.com", "momondo.", "cheapflights.",
    "wego.com", "jetradar.", "aviasales.", "wingie.",
    "airpaz.com", "orbitz.com", "priceline.com", "hopper.com",
    "gotogate.", "edreams.", "opodo.", "lastminute.",
    "bravofly.", "cheapoair.",
    # Asia-focused & Vietnam OTAs
    "12go.asia", "12go.co", "baolau.com", "bookaway.com", "rome2rio.com",
    "busbud.com", "omio.com", "trainline.",
    "trip.com",  # will be matched against hostname to avoid "phukettrip.com"
    "ctrip.com", "qunar.com", "fliggy.com", "tongcheng.",
    "vemaybay.vn", "abay.vn", "bestprice.vn", "gotadi.com", "dlink.vn",
    "datve247.vn", "ve24h.vn", "atadi.vn", "alove.vn", "sanvemaybay.vn",
    # India
    "makemytrip.com", "goibibo.com", "yatra.com", "cleartrip.com", "ixigo.com",
    # Indonesia
    "tiket.com", "pegipegi.com", "nusatrip.com",
    # Accommodation
    "hostelworld.com", "trivago.", "hotels.com",
    # Booking platforms / white-label
    "securedirectbookings.com", "zoombookdirect.com", "mybooking.myontour.com",
    "booktouronline.com", "edcbooking.com", "tmgticket.com",
    # Thailand-specific OTAs
    "fly2thai.com",
]

# Keywords that appear in reviews when customers BOOKED ONLINE through a platform
OTA_REVIEW_KEYWORDS = [
    "booked online", "book online", "online booking", "booking system",
    "booking platform", "booked through the website", "booked on the website",
    "booked via", "easy to book", "website booking", "app booking",
    "booked through their site", "instant confirmation", "e-ticket",
    "search and book", "compare prices", "payment online", "pay online",
    "checkout", "booking confirmation", "reservation system",
    # Tiếng Việt
    "đặt online", "đặt qua mạng", "đặt trên web", "đặt vé online",
    "đặt vé máy bay", "mua vé máy bay", "xuất vé", "vé điện tử",
    "thanh toán online", "hệ thống đặt vé", "đặt qua website",
]

# --- Segment B: Air Ticketing Identification ---

# Flight-related keywords (for title, website URL, review text)
FLIGHT_KEYWORDS_PRIMARY = [
    "flight", "airline", "air ticket", "airticket", "airfare",
    "ticketing", "aviation", "boarding pass", "air booking",
    # Tiếng Việt
    "vé máy bay", "ve may bay", "vé máy bay giá rẻ", "ve may bay gia re",
    "phòng vé", "phong ve", "hàng không", "hang khong", "chuyến bay", "chuyen bay",
    "đặt vé máy bay", "dat ve may bay", "bán vé máy bay", "ban ve may bay",
    "đại lý vé", "dai ly ve", "săn vé", "san ve",
]

FLIGHT_KEYWORDS_SECONDARY = [
    "domestic flight", "international flight", "flight booking",
    "plane ticket", "fly ", "airport transfer",
    "book flight", "booked flight", "air travel",
    # Tiếng Việt
    "vé quốc tế", "vé nội địa", "đặt vé", "đặt chuyến bay",
    "chặng bay", "bay thẳng", "hãng bay", "vé đoàn",
]

# FALSE POSITIVE flight keywords to EXCLUDE
FLIGHT_FALSE_POSITIVES = [
    "flight simulator",
    "zipline flight",
    "jungle flight",
    "flight of the gibbon",
    "air conditioning",
    "air freshener",
    "air purifier",
    "air bnb",
    "airbnb",
    "fresh air",
    "open air",
    "air con",
]

# Categories that strongly indicate flight ticketing
FLIGHT_STRONG_CATEGORIES = [
    "airline ticket agency",
    "airline",
    "đại lý vé máy bay",
    "phòng vé máy bay",
    "phòng vé",
    "vé máy bay",
    "bán vé máy bay",
]


# ==============================================================================
# STAGE 3: SCORING WEIGHTS
# ==============================================================================

SCORING = {
    # Digital Maturity (max 25)
    "has_proper_website": 10,
    "has_online_appointments": 8,
    "has_email": 4,
    "has_good_domain": 3,       # .co.th, .com (not social media)

    # Business Scale (max 20)
    "reviews_100_plus": 10,
    "reviews_50_99": 7,
    "reviews_20_49": 4,
    "reviews_5_19": 2,
    "rating_4_5_plus": 5,
    "rating_4_0_4_4": 3,
    "rating_3_5_3_9": 2,

    # Flight Relevance (max 25)
    "category_airline_ticket": 15,
    "flight_keywords_in_title": 10,
    "flight_mentions_in_reviews": 8,
    "flight_keywords_in_website": 5,

    # Market Position (max 15)
    "top_tourism_city": 5,
    "near_airport": 5,
    "international_reviews": 5,

    # Contactability (max 15)
    "has_email_contact": 6,
    "has_phone": 3,
    "has_website_contact": 3,
    "owner_verified": 3,
}


# ==============================================================================
# AIRPORT COORDINATES (per country)
# Add more countries as needed
# ==============================================================================

AIRPORTS = {
    "thailand": [
        {"name": "Suvarnabhumi", "iata": "BKK", "lat": 13.6900, "lon": 100.7501, "radius_km": 10},
        {"name": "Don Mueang", "iata": "DMK", "lat": 13.9126, "lon": 100.6070, "radius_km": 10},
        {"name": "Phuket", "iata": "HKT", "lat": 8.1132, "lon": 98.3169, "radius_km": 8},
        {"name": "Chiang Mai", "iata": "CNX", "lat": 18.7669, "lon": 98.9625, "radius_km": 8},
        {"name": "Hat Yai", "iata": "HDY", "lat": 6.9333, "lon": 100.3928, "radius_km": 8},
        {"name": "Krabi", "iata": "KBV", "lat": 8.0995, "lon": 98.9862, "radius_km": 8},
        {"name": "Koh Samui", "iata": "USM", "lat": 9.5478, "lon": 100.0623, "radius_km": 5},
        {"name": "U-Tapao", "iata": "UTP", "lat": 12.6800, "lon": 100.9998, "radius_km": 10},
        {"name": "Chiang Rai", "iata": "CEI", "lat": 19.9523, "lon": 99.8828, "radius_km": 8},
        {"name": "Surat Thani", "iata": "URT", "lat": 9.1326, "lon": 99.1356, "radius_km": 8},
        {"name": "Udon Thani", "iata": "UTH", "lat": 17.3864, "lon": 102.7883, "radius_km": 8},
        {"name": "Khon Kaen", "iata": "KKC", "lat": 16.4667, "lon": 102.7836, "radius_km": 8},
        {"name": "Ubon Ratchathani", "iata": "UBP", "lat": 15.2513, "lon": 104.8701, "radius_km": 8},
    ],
    "vietnam": [
        {"name": "Tan Son Nhat", "iata": "SGN", "lat": 10.8188, "lon": 106.6520, "radius_km": 10},
        {"name": "Noi Bai", "iata": "HAN", "lat": 21.2212, "lon": 105.8070, "radius_km": 10},
        {"name": "Da Nang", "iata": "DAD", "lat": 16.0439, "lon": 108.1992, "radius_km": 8},
        {"name": "Cam Ranh", "iata": "CXR", "lat": 11.9982, "lon": 109.2194, "radius_km": 8},
        {"name": "Phu Quoc", "iata": "PQC", "lat": 10.1698, "lon": 103.9931, "radius_km": 5},
    ],
    "indonesia": [
        {"name": "Soekarno-Hatta", "iata": "CGK", "lat": -6.1256, "lon": 106.6559, "radius_km": 12},
        {"name": "Halim Perdanakusuma", "iata": "HLP", "lat": -6.2666, "lon": 106.8909, "radius_km": 8},
        {"name": "Ngurah Rai", "iata": "DPS", "lat": -8.7482, "lon": 115.1672, "radius_km": 10},
        {"name": "Juanda", "iata": "SUB", "lat": -7.3798, "lon": 112.7869, "radius_km": 10},
        {"name": "Kualanamu", "iata": "KNO", "lat": 3.6422, "lon": 98.8854, "radius_km": 10},
        {"name": "Sultan Hasanuddin", "iata": "UPG", "lat": -5.0617, "lon": 119.5544, "radius_km": 8},
        {"name": "Yogyakarta International", "iata": "YIA", "lat": -7.9056, "lon": 110.0575, "radius_km": 8},
        {"name": "Adisutjipto", "iata": "JOG", "lat": -7.7882, "lon": 110.4317, "radius_km": 8},
        {"name": "Husein Sastranegara", "iata": "BDO", "lat": -6.9006, "lon": 107.5763, "radius_km": 8},
        {"name": "Sultan Aji Muhammad Sulaiman", "iata": "BPN", "lat": -1.2683, "lon": 116.8945, "radius_km": 8},
        {"name": "Lombok International", "iata": "LOP", "lat": -8.7573, "lon": 116.2766, "radius_km": 8},
        {"name": "Hang Nadim", "iata": "BTH", "lat": 1.1211, "lon": 104.1188, "radius_km": 8},
        {"name": "Sam Ratulangi", "iata": "MDC", "lat": 1.5493, "lon": 124.9266, "radius_km": 8},
    ],
    "philippines": [
        {"name": "Ninoy Aquino", "iata": "MNL", "lat": 14.5086, "lon": 121.0198, "radius_km": 10},
        {"name": "Mactan-Cebu", "iata": "CEB", "lat": 10.3075, "lon": 123.9794, "radius_km": 8},
        {"name": "Francisco Bangoy (Davao)", "iata": "DVO", "lat": 7.1255, "lon": 125.6456, "radius_km": 8},
        {"name": "Clark International", "iata": "CRK", "lat": 15.1860, "lon": 120.5601, "radius_km": 10},
        {"name": "Iloilo International", "iata": "ILO", "lat": 10.8330, "lon": 122.4933, "radius_km": 8},
        {"name": "Puerto Princesa", "iata": "PPS", "lat": 9.7421, "lon": 118.7587, "radius_km": 6},
        {"name": "Bacolod-Silay", "iata": "BCD", "lat": 10.7764, "lon": 123.0145, "radius_km": 8},
        {"name": "Kalibo", "iata": "KLO", "lat": 11.6794, "lon": 122.3759, "radius_km": 6},
        {"name": "Godofredo P. Ramos (Caticlan)", "iata": "MPH", "lat": 11.9245, "lon": 121.9542, "radius_km": 5},
        {"name": "Laguindingan", "iata": "CGY", "lat": 8.6122, "lon": 124.4564, "radius_km": 8},
        {"name": "General Santos", "iata": "GES", "lat": 6.0580, "lon": 125.0962, "radius_km": 8},
        {"name": "Zamboanga", "iata": "ZAM", "lat": 6.9224, "lon": 122.0599, "radius_km": 8},
        {"name": "Bohol-Panglao", "iata": "TAG", "lat": 9.6644, "lon": 123.8493, "radius_km": 6},
        {"name": "Siargao", "iata": "IAO", "lat": 9.8591, "lon": 126.0142, "radius_km": 5},
    ],
    "hongkong": [
        {"name": "Hong Kong International", "iata": "HKG", "lat": 22.3080, "lon": 113.9185, "radius_km": 8},
    ],
    # Add more countries here as you expand
}

# Top tourism cities per country (for scoring bonus)
TOP_TOURISM_CITIES = {
    "thailand": [
        "bangkok", "phra nakhon", "ratchathewi", "bang rak", "pathum wan",
        "chiang mai", "mueang chiang mai",
        "phuket", "kathu", "mueang phuket",
        "pattaya", "bang lamung",
        "krabi", "mueang krabi",
        "koh samui", "ko samui",
        "hua hin",
        "chiang rai", "mueang chiang rai",
        "surat thani",
    ],
    "vietnam": [
        "ho chi minh", "hanoi", "da nang", "hoi an", "nha trang",
        "phu quoc", "ha long", "hue", "sapa", "dalat",
    ],
    "indonesia": [
        "jakarta", "denpasar", "kuta", "seminyak", "ubud", "canggu", "sanur",
        "nusa dua", "badung", "gianyar", "yogyakarta", "bandung", "surabaya",
        "lombok", "mataram", "labuan bajo", "medan", "makassar", "batam",
        "manado", "malang", "balikpapan",
    ],
    "philippines": [
        "manila", "makati", "taguig", "pasay", "quezon city", "cebu",
        "cebu city", "lapu-lapu", "mactan", "boracay", "malay", "kalibo",
        "puerto princesa", "el nido", "palawan", "davao", "bohol", "panglao",
        "tagbilaran", "baguio", "tagaytay", "siargao", "iloilo", "bacolod",
        "dumaguete", "angeles", "cagayan de oro",
    ],
    "hongkong": [
        "central", "tsim sha tsui", "causeway bay", "mong kok", "wan chai",
        "sheung wan", "jordan", "yau ma tei", "admiralty", "north point",
        "kowloon", "hong kong island", "tung chung", "aberdeen",
    ],
}
