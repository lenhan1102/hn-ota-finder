#!/usr/bin/env python3
"""
reverify_browser.py — Re-verify bang trinh duyet that (Playwright Chromium).

WebFetch/requests that bai rat nhieu voi: site JS-only, TLS het han, chan bot 403,
chan theo vung. Script nay dung Chromium that de phan biet "site chet that" voi
"WebFetch khong vao duoc".

  python3 reverify_browser.py --input sites.csv --output reverify.json

Input CSV can 2 cot: name,url   (hoac doc truc tiep sheet "Qualified leads" cua
{country}_ndc_leads.xlsx bang --xlsx, loc cac dong site_reachable = False)

Output JSON moi site: loaded / final_url / status / title / flight_form /
iata_found / iata_number / snippet — dung lam dau vao cho ndc_tiering.py --reverify.

Cai dat:  pip install playwright openpyxl && playwright install chromium
"""
import argparse, csv, json, re, sys, time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Thieu playwright. Chay: pip install playwright && playwright install chromium")

# ============================================================================
# Bo selector nhan dien form tim chuyen bay.
# Muon ho tro them ngon ngu ban dia thi bo sung placeholder/label vao cac hang duoi.
# ============================================================================
_FLIGHT_ORIGIN_SELECTORS = ", ".join([
    "input[placeholder*='airport' i]",
    "input[placeholder*='origin airport' i]",
    "input[placeholder*='departure airport' i]",
    "input[placeholder*='flying from' i]",
    "input[placeholder*='depart from' i]",
    "input[placeholder*='from city' i]",
    "input[placeholder*='departure city' i]",
    "input[placeholder*='nhập điểm đi' i]",
    "input[placeholder*='điểm đi' i]",
    "input[placeholder*='chọn điểm đi' i]",
    "input[id*='origin' i]",
    "input[name*='origin' i]",
    "input[id*='departure_city' i]",
    "input[name*='departure_city' i]",
    "input[id*='from_airport' i]",
    "input[name*='from_airport' i]",
    "[class*='origin-input']",
    "[class*='from-airport']",
    "[class*='departure-input']",
    "[class*='originInput']",
    "[class*='fromAirport']",
])

# Selectors that strongly indicate a flight-specific destination field
_FLIGHT_DEST_SELECTORS = ", ".join([
    "input[placeholder*='destination airport' i]",
    "input[placeholder*='arrival airport' i]",
    "input[placeholder*='flying to' i]",
    "input[placeholder*='going to' i]",
    "input[placeholder*='to city' i]",
    "input[placeholder*='arrival city' i]",
    "input[placeholder*='nhập điểm đến' i]",
    "input[placeholder*='điểm đến' i]",
    "input[placeholder*='chọn điểm đến' i]",
    "input[id*='destination' i]",
    "input[name*='destination' i]",
    "input[id*='arrival_city' i]",
    "input[name*='arrival_city' i]",
    "input[id*='to_airport' i]",
    "input[name*='to_airport' i]",
    "[class*='destination-input']",
    "[class*='to-airport']",
    "[class*='arrival-input']",
    "[class*='destinationInput']",
    "[class*='toAirport']",
])

# Date selectors — constrained to departure/return context
_FLIGHT_DATE_SELECTORS = ", ".join([
    "input[type='date']",
    "input[placeholder*='departure date' i]",
    "input[placeholder*='depart date' i]",
    "input[placeholder*='return date' i]",
    "input[placeholder*='ngày đi' i]",
    "input[placeholder*='ngày về' i]",
    "input[placeholder*='dd/mm/yyyy' i]",
    "input[id*='depart_date' i]",
    "input[name*='depart_date' i]",
    "input[id*='departure_date' i]",
    "input[name*='departure_date' i]",
    "input[id*='return_date' i]",
    "input[name*='return_date' i]",
    "[class*='departure-date']",
    "[class*='departureDate']",
    "[class*='depart-date']",
    ".datepicker",
    "[class*='date-picker']",
    "[class*='datePicker']",
])

# Passenger/cabin selectors
_FLIGHT_PAX_SELECTORS = ", ".join([
    "input[name*='passenger' i]",
    "input[id*='passenger' i]",
    "select[name*='passenger' i]",
    "select[id*='passenger' i]",
    "[class*='passenger' i]",
    "input[name*='adults' i]",
    "input[id*='adults' i]",
    "select[name*='adults' i]",
    "select[id*='adults' i]",
    "[class*='adult-count' i]",
    "[class*='adultCount' i]",
    "select[name*='cabin' i]",
    "select[id*='cabin' i]",
    "select[name*='class' i]",
    "[class*='cabin-class' i]",
    "[class*='cabinClass' i]",
])

# Round-trip / one-way toggle
_TRIP_TYPE_SELECTORS = ", ".join([
    "input[value*='round' i]",
    "input[value*='one way' i]",
    "input[value*='oneway' i]",
    "input[value*='roundtrip' i]",
    "label:has-text('Round Trip')",
    "label:has-text('One Way')",
    "label:has-text('Round-trip')",
    "label:has-text('Một chiều')",
    "label:has-text('Khứ hồi')",
    "[class*='round-trip' i]",
    "[class*='roundTrip' i]",
    "[class*='one-way' i]",
    "[class*='oneWay' i]",
])

# Dedicated flight search form/widget container
_FLIGHT_FORM_SELECTORS = ", ".join([
    "form[id*='flight' i]",
    "form[class*='flight' i]",
    "form[action*='flight' i]",
    "div[id*='flight-search' i]",
    "div[class*='flight-search' i]",
    "div[id*='flightSearch' i]",
    "div[class*='flightSearch' i]",
    "div[id*='flight-booking' i]",
    "div[class*='flight-booking' i]",
    "div[id*='flightBooking' i]",
    "div[class*='flightBooking' i]",
    "section[class*='flight-search' i]",
    "section[id*='flight-search' i]",
    "[data-widget*='flight' i]",
])

# Known external flight booking widget iframes
_FLIGHT_IFRAME_SRCS = [
    "skyscanner", "aviasales", "wego", "kiwi.com", "momondo",
    "kayak", "cheapflights", "jetcost", "travelpayouts",
    "flights.google", "expedia", "booking.com/flights",
    "iata", "amadeus", "sabre", "galileo",
    "vemaybay", "traveloka", "airpaz", "mytour",
]

# Search/find flights button
_SEARCH_BTN_SELECTORS = ", ".join([
    "button:has-text('Search Flights')",
    "button:has-text('Find Flights')",
    "button:has-text('Search')",
    "button:has-text('Tìm chuyến bay')",
    "button:has-text('Tìm vé')",
    "input[type='submit'][value*='flight' i]",
    "input[type='submit'][value*='search' i]",
    "button[type='submit'][class*='flight' i]",
    "button[type='submit'][id*='flight' i]",
    "[class*='search-btn'][class*='flight' i]",
    "[id*='searchFlight' i]",
    "[class*='searchFlight' i]",
])


def _count(page, selector):
    try:
        return len(page.query_selector_all(selector))
    except Exception:
        return 0


def _has_flight_iframe(page):
    """Check if page embeds a known flight booking widget via iframe."""
    try:
        iframes = page.query_selector_all("iframe[src], iframe[data-src]")
        for iframe in iframes:
            src = (iframe.get_attribute("src") or "") + (iframe.get_attribute("data-src") or "")
            if any(widget in src.lower() for widget in _FLIGHT_IFRAME_SRCS):
                return True
    except Exception:
        pass
    return False

# Bo sung selector tieng Trung (thi truong HK/TW) — khong co trong ban goc
_CJK_FLIGHT_SELECTORS = ", ".join([
    "input[placeholder*='出發地']", "input[placeholder*='目的地']",
    "input[placeholder*='出发地']", "input[placeholder*='目的地']",
    "[class*='機票']", "[id*='機票']",
    "a:has-text('機票')", "button:has-text('搜尋')", "button:has-text('查詢')",
])


def check_flight_form(page):
    """Tra ve (has_full_engine, has_basic_form, detail_str)."""
    has_widget_container = _count(page, _FLIGHT_FORM_SELECTORS) > 0
    has_origin      = _count(page, _FLIGHT_ORIGIN_SELECTORS) > 0
    has_destination = _count(page, _FLIGHT_DEST_SELECTORS) > 0
    has_date        = _count(page, _FLIGHT_DATE_SELECTORS) > 0
    has_pax         = _count(page, _FLIGHT_PAX_SELECTORS) > 0
    has_trip_type   = _count(page, _TRIP_TYPE_SELECTORS) > 0
    has_search_btn  = _count(page, _SEARCH_BTN_SELECTORS) > 0
    has_iframe      = _has_flight_iframe(page)
    has_cjk         = _count(page, _CJK_FLIGHT_SELECTORS) > 0

    # Full engine: origin + destination + date + nut search + it nhat 1 tin hieu phu
    has_full_engine = (
        has_origin and has_destination and has_date and has_search_btn
        and (has_pax or has_trip_type or has_widget_container)
    )
    # Basic form: co widget/iframe + (origin hoac destination) + date
    has_basic_form = (
        (has_widget_container or has_iframe)
        and (has_origin or has_destination)
        and has_date
    )
    details = {"widget": has_widget_container, "origin": has_origin, "dest": has_destination,
               "date": has_date, "pax": has_pax, "trip_type": has_trip_type,
               "search_btn": has_search_btn, "iframe": has_iframe, "cjk": has_cjk}
    return has_full_engine, has_basic_form, ", ".join(k for k, v in details.items() if v)


# ============================================================================
# Do site
# ============================================================================
IATA_RE  = re.compile(r"iata|asita", re.I)
IATA_NUM = re.compile(r"iata[^0-9]{0,20}(\d{7,8})", re.I)


def check_domain_resolves(url_or_domain: str, timeout: float = 1.0) -> bool:
    """Kiem tra nhanh DNS cua domain truoc khi cho Chromium load de tranh timeout vo tan."""
    import socket
    from urllib.parse import urlparse
    try:
        d = str(url_or_domain).strip().lower()
        if "://" in d:
            host = urlparse(d).netloc.split(":")[0]
        else:
            host = d.split("/")[0].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        if not host:
            return False
        socket.setdefaulttimeout(timeout)
        try:
            socket.getaddrinfo(host, None)
            return True
        except Exception:
            socket.getaddrinfo("www." + host, None)
            return True
    except Exception:
        return False


def probe(page, url, timeout_ms: int = 8000):
    """Thu lan luot https:// -> https://www. -> http:// truoc khi ket luan site chet."""
    if not check_domain_resolves(url):
        return {"loaded": False, "error": "DNS_PROBE_FINISHED_NXDOMAIN (Tên miền không tồn tại hoặc chết DNS)"}

    last = "all variants failed"
    for u in (url, url.replace("https://", "https://www."), url.replace("https://", "http://")):
        try:
            resp = page.goto(u, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                pass
            time.sleep(1.0)
            title = (page.title() or "").strip()
            try:
                body = (page.inner_text("body") or "")[:7000]
            except Exception:
                body = ""
            
            import os
            title_lower = title.lower()
            body_lower = body.lower()
            _block_keywords_title = ["just a moment", "cloudflare", "attention required", "access denied", "403 forbidden", "security challenge"]
            _block_keywords_body  = ["cf-browser-verification", "captcha", "enable javascript and cookies", "checking your browser"]
            if any(k in title_lower for k in _block_keywords_title) or any(k in body_lower for k in _block_keywords_body):
                try:
                    os.makedirs("debug_screenshots", exist_ok=True)
                    safe_domain = u.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
                    screenshot_path = f"debug_screenshots/blocked_{safe_domain}.png"
                    page.screenshot(path=screenshot_path)
                    print(f"\n[PHÁT HIỆN CHẶN/CAPTCHA] Đã chụp ảnh màn hình lưu tại: {screenshot_path}")
                except Exception as ex:
                    print(f"\n[LỖI CHỤP ẢNH] Không thể chụp ảnh màn hình cho {u}: {ex}")
                # Dừng lại ngay — không phân tích trang block vì sẽ cho kết quả sai
                return {
                    "loaded": False,
                    "error": f"Bot/Cloudflare block (title: '{title[:60]}')",
                    "final_url": page.url,
                    "status": resp.status if resp else None,
                    "title": title[:120],
                }

            if not title and len(body) < 40:
                continue  # render rong -> thu bien the tiep theo

            # Phát hiện trang lỗi server kỹ thuật (PHP error, WordPress crash, maintenance...)
            # → loaded=False để ngăn LLM phân loại sai dựa vào tên domain
            _server_error_patterns = [
                "your server is running php version",       # WordPress PHP incompatible
                "wordpress requires at least php",
                "fatal error",                              # PHP fatal error
                "parse error",                              # PHP parse error
                "site is undergoing maintenance",           # WordPress maintenance mode
                "briefly unavailable for scheduled maintenance",
                "error establishing a database connection", # WordPress DB error
                "database error",
                "this site can't be reached",
                "http error 500",
            ]
            if any(p in body_lower for p in _server_error_patterns):
                err_reason = next(p for p in _server_error_patterns if p in body_lower)
                print(f"\n[PHÁT HIỆN LỖI SERVER] {u}: '{err_reason[:60]}'")
                return {
                    "loaded": False,
                    "error": f"Server error ('{err_reason[:60]}')",
                    "final_url": page.url,
                    "status": resp.status if resp else None,
                    "title": title[:120],
                    "snippet": body[:200].replace("\n", " "),
                }

            full, basic, detail = check_flight_form(page)
            m = IATA_NUM.search(body.replace("\n", " "))
            return {"loaded": True, "final_url": page.url,
                    "status": resp.status if resp else None, "title": title[:120],
                    "flight_form": bool(full or basic), "flight_form_detail": detail,
                    "iata_found": bool(IATA_RE.search(body)),
                    "iata_number": m.group(1) if m else "",
                    "snippet": body[:400].replace("\n", " ")}
        except Exception as e:
            err_str = str(e)
            last = err_str[:120]
            # Neu loi DNS hoac tu choi ket noi thi cac bien the khac cung se loi -> break ngay
            if any(k in err_str for k in ["ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_REFUSED", "NXDOMAIN", "ERR_ADDRESS_UNREACHABLE", "ERR_CONNECTION_RESET"]):
                break
    return {"loaded": False, "error": last}


def load_targets(args):
    if args.xlsx:
        import openpyxl
        ws = openpyxl.load_workbook(args.xlsx)["Qualified leads"]
        hdr = [c.value for c in ws[1]]
        ni, wi, ri = hdr.index("name"), hdr.index("website"), hdr.index("site_reachable")
        return [(r[ni], r[wi]) for r in ws.iter_rows(min_row=2, values_only=True)
                if r[ri] is False or str(r[ri]).lower() == "false"]
    with open(args.input, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [(r.get("name") or r.get("domain") or "", r.get("url") or ("https://" + r["domain"]))
            for r in rows]


def main():
    ap = argparse.ArgumentParser(description="Re-verify site bang Chromium that")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--input", help="CSV co cot name,url (hoac domain)")
    g.add_argument("--xlsx",  help="{country}_ndc_leads.xlsx — chi lay dong site_reachable=False")
    ap.add_argument("--output", default="reverify.json")
    ap.add_argument("--locale", default="en-HK", help="vd en-HK, vi-VN, en-SG")
    args = ap.parse_args()

    targets = load_targets(args)
    print(f"Re-verify {len(targets)} site bang trinh duyet that...\n")

    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            ignore_https_errors=True,            # bo qua TLS het han
            viewport={"width": 1280, "height": 800}, locale=args.locale,
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"))
        ctx.set_default_timeout(25000)
        for i, (name, url) in enumerate(targets, 1):
            page = ctx.new_page()
            try:
                r = probe(page, url)
            except Exception as e:
                r = {"loaded": False, "error": str(e)[:120]}
            r["name"], r["url"] = name, url
            if r["loaded"]:
                extra_s = (f"flight={r['flight_form']} iata={r['iata_found']}"
                           + (f"({r['iata_number']})" if r["iata_number"] else ""))
            else:
                extra_s = r.get("error", "")
            print(f"[{i}/{len(targets)}] {'LOADED' if r['loaded'] else 'DEAD':6} "
                  f"{str(name)[:34]:<34} {extra_s}")
            out.append(r)
            page.close()
        browser.close()

    json.dump(out, open(args.output, "w"), ensure_ascii=False, indent=1)
    loaded = sum(1 for r in out if r["loaded"])
    print(f"\n=== {loaded}/{len(out)} site vao duoc bang trinh duyet that "
          f"({len(out) - loaded} chet that) -> {args.output} ===")
    print("Buoc tiep: ndc_tiering.py --reverify " + args.output)


if __name__ == "__main__":
    main()
