#!/usr/bin/env python3
"""
ndc_tiering.py — Ap quy tac Tier cho NDC leads va xuat {country}_ndc_leads.xlsx

Tong quat hoa tu ban Hong Kong (data/_ndc/build_leads_hk.py, run 2026-07-01).

Dau vao:
  --verdicts  CSV 11 cot tu AI deep-dive (xem verdict-template.csv)
  --contacts  bang danh ba da lam sach (.xlsx hoac .csv) de ghep
              name/city/phone/emails/review_count theo domain — tuy chon
  --reverify  reverify.json tu reverify_browser.py (tuy chon nhung rat nen co)

Dau ra: Excel 2 sheet "Qualified leads" + "Dropped", website la hyperlink bam duoc.
Mac dinh ghi ra ./{country}_ndc_leads.xlsx — moi duong dan deu la duong dan
cuc bo, script khong phu thuoc vao bat ky thu muc dong bo dam may nao.

  python3 ndc_tiering.py --verdicts hongkong_verdicts.csv --country hongkong \
      --contacts hongkong_clean.xlsx --reverify reverify.json

Quy tac Tier (ban Hong Kong — cong qualify la "co ban ve may bay"):
  DROP   : peer B2B | hang bay | khong phai site that | khong phai dai ly
           | tour thuan / khong ban ve | domain da chet
  Tier 3 : ban ve nhung site khong vao duoc / conf thap / offline & khong ro IATA
  Tier 2 : ban ve + (online flight search HOAC IATA hien thi)
  Tier 1 : ban ve + online flight search + IATA hien thi

Doi sang chuan Indonesia/Philippines (thi truong OTA-first): dat
REQUIRE_ONLINE_SEARCH = True ben duoi — khi do khong co online search se bi DROP.
"""
import argparse, csv, io, json, pathlib, sys
from urllib.parse import urlparse

try:
    import pandas as pd
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
except ImportError:
    sys.exit("Thieu thu vien. Chay: pip install pandas openpyxl")

# ============================================================================
# CAU HINH THEO THI TRUONG — sua o day
# ============================================================================

# False = chuan Hong Kong: chi can co ban ve may bay la qualify (thi truong consolidator).
# True  = chuan Indonesia/Philippines: bat buoc co online flight search moi qualify.
REQUIRE_ONLINE_SEARCH = False

# Peer B2B / travel-tech / wholesaler — doi thu hoac dong nghiep, khong phai khach cuoi.
PEERS = {
    "business.unififi.com", "travelconnect.co", "heytripgo.com",
    "miki.travel", "g2-travel.com", "mikitravel.asia",
}

# Mega-OTA qua lon de la muc tieu BD thuc te.
# HK de rong (set() ) vi boi canh thi truong khac; ID/PH dung danh sach duoi.
EXCLUDE_BIG: set[str] = set()
# EXCLUDE_BIG = {"traveloka.com","trip.com","klook.com","agoda.com","booking.com","expedia.com"}

# Ten GMaps thuong sai hoac la ten chi nhanh -> map domain sang ten thuong hieu dung.
# Thi truong CJK nen ghi song ngu de sales tra cuu duoc.
NAME_MAP = {
    "wingontravel.com": "Wing On Travel 永安旅遊", "hutchgo.com.hk": "hutchgo.com",
    "egltours.com": "EGL Tours 東瀛遊", "nanhwa.com": "NanHwa Travel 南華",
    "ctshk.com": "CTS (HK) 中國旅行社", "ww1.ctshk.com": "CTS (HK) 中國旅行社",
    "h5.ctshk.com": "CTS (HK) 中國旅行社", "iwanttotravel.cc": "和記旅遊 iWantToTravel",
    "texpert.com": "Travel Expert 專業旅運", "travelexpert.com.hk": "Travel Expert 專業旅運",
    "goldjoy.com": "Goldjoy 金怡假期", "morningstartravel.com.hk": "Morning Star 星晨旅遊",
    "fourseastravel.com": "Four Seas Tours 四海", "lotustours.com.hk": "Lotus Tours 蓮花",
    "myeebus.com": "Eternal East 永東", "asia.travelctm.com": "CTM (Corporate Travel Mgmt)",
    "lastminuteglobal.com": "lastminute.com HK",
    # Indonesia / Philippines
    "traveloka.com": "Traveloka", "tiket.com": "Tiket.com", "airpaz.com": "Airpaz",
    "nusatrip.com": "NusaTrip", "klikmbc.co.id": "MMBC Tour & Travel",
    "biyaheroes.com": "BiyaHeroes",
}

COLS = ["domain", "real", "ota", "airline", "flightticketing", "onlinesearch",
        "iata", "iata_ev", "puretour", "conf", "evidence", "reachable", "db_place_id"]


# ============================================================================
# QUY TAC TIER — day la "tieu chi" duoi dang code
# ============================================================================
def classify(r):
    if getattr(r, "domain", "") == "-":
        return "DROP", "Ứng viên không có website"
    
    work_dom = norm_domain(getattr(r, "workurl", ""))
    if work_dom in {"klook.com", "traveloka.com", "trip.com", "agoda.com", "booking.com", "expedia.com", "skyscanner.com", "kayak.com", "kkday.com"}:
        return "DROP", f"Website thực tế là Mega-OTA/Nền tảng du lịch ({work_dom}) — chỉ là link affiliate hoặc không độc lập"
        
    if r.domain in PEERS:
        return "DROP", "Đối tác B2B / Wholesaler / Travel-tech (không phải đại lý bán vé lẻ cho khách)"
    if r.airline:
        return "DROP", "Chính hãng hàng không (nguồn cung NDC, không phải đại lý khách hàng)"
    if not r.real:
        return "DROP", "Không phải website công ty thực tế / không thể truy cập"
    if not r.ota:
        return "DROP", "Không phải đại lý du lịch / OTA"
    if r.puretour or not r.flightticketing:
        return "DROP", "Không bán vé máy bay (tour thuần túy / phi hàng không)"
    if getattr(r, "dead", False):
        return "DROP", "Tên miền không còn phân giải DNS — website đã chết"
    if REQUIRE_ONLINE_SEARCH and not r.onlinesearch:
        return "DROP", "Không có công cụ tìm kiếm vé trực tuyến (đặt chỗ thủ công / liên hệ)"

    # --- Đã qualify: có bán vé máy bay ---
    if not getattr(r, "reach", True):
        return "Tier 3", ("Bán vé máy bay nhưng website không vào được kể cả bằng trình duyệt thực (chặn bot/vùng hoặc down) — cần kiểm tra tay")
    if r.onlinesearch and r.iata:
        return "Tier 1", "Tìm kiếm vé trực tuyến + Có chứng nhận IATA hiển thị"
    if r.onlinesearch:
        return "Tier 2", "Tìm kiếm vé trực tuyến (đã kiểm chứng trên website thực tế)"
    if r.iata:
        return "Tier 2", "Đại lý vé máy bay IATA-accredited (đã kiểm chứng trên website thực tế)"
    if r.conf < 0.5:
        return "Tier 3", "Bán vé máy bay — độ tin cậy thấp, cần xác minh thủ công"
    return "Tier 3", "Consolidator vé máy bay (website hoạt động; offline / không hiển thị IATA) — Tiềm năng NDC"


# ============================================================================
def norm_domain(u):
    u = str(u or "")
    host = urlparse(u if u.startswith("http") else "https://" + u).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def load_verdicts(verdicts_input):
    if isinstance(verdicts_input, pd.DataFrame):
        rows = verdicts_input.fillna("").to_dict(orient="records")
    elif isinstance(verdicts_input, list):
        rows = verdicts_input
    else:
        path = str(verdicts_input)
        if path.endswith(".json"):
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
        else:
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
    recs = []
    for r in rows:
        recs.append({
            "db_place_id": r.get("db_place_id"),
            "domain": norm_domain(r.get("domain", "")) or str(r.get("domain", "")).strip().lower(),
            "real": int(r.get("real", 0)),
            "ota": int(r.get("ota", 0)),
            "airline": int(r.get("airline", 0)),
            "flightticketing": int(r.get("flightticketing", 0)),
            "onlinesearch": int(r.get("onlinesearch", 0)),
            "iata": int(r.get("iata", 0)),
            "iata_ev": r.get("iata_ev", ""),
            "puretour": int(r.get("puretour", 0)),
            "conf": float(r.get("conf", 0.0)),
            "evidence": r.get("evidence", ""),
            "reachable": int(r.get("reachable", 1) if r.get("reachable") is not None else 1),
        })
    return pd.DataFrame(recs, columns=COLS)


def apply_reverify(vdf, reverify_input):
    """Ghi de ket qua WebFetch bang ket qua trinh duyet that (tu list dict hoac file)."""
    rv = {}
    if reverify_input is not None:
        if isinstance(reverify_input, list):
            items = reverify_input
        else:
            p = pathlib.Path(reverify_input)
            items = json.load(open(p, encoding="utf-8")) if p.exists() else []
        for x in items:
            u = x.get("url") or x.get("domain") or ""
            rv[norm_domain(u)] = x

    def one(r):
        reach, dead = bool(r.reachable), False
        iata, osrch = r.iata, r.onlinesearch
        workurl, https_ok = "https://" + r.domain, True
        v = rv.get(r.domain)
        if v is not None:
            if v.get("loaded"):
                reach = True
                workurl = v.get("final_url") or workurl
                https_ok = str(workurl).startswith("https")
                if v.get("iata_found"):
                    iata = 1
                if v.get("flight_form"):
                    osrch = 1
            else:
                reach, https_ok = False, False
                dead = "NAME_NOT_RESOLVED" in (v.get("error") or "")
        return pd.Series({"reach": reach, "dead": dead, "iata": iata,
                          "onlinesearch": osrch, "workurl": workurl, "https_ok": https_ok})

    if vdf.empty:
        for c in ["reach", "dead", "iata", "onlinesearch", "workurl", "https_ok"]:
            vdf[c] = None
    else:
        vdf[["reach", "dead", "iata", "onlinesearch", "workurl", "https_ok"]] = vdf.apply(one, axis=1)
    return vdf


CONTACT_COLS = ["title", "city", "phone", "emails", "review_count"]


def join_contacts(vdf, contacts_input):
    """Ghep name/city/phone/emails/review_count tu danh ba (list dict, df hoac file)."""
    for c in CONTACT_COLS:
        vdf[c] = None
    if contacts_input is None:
        return vdf

    if isinstance(contacts_input, pd.DataFrame):
        tpl = contacts_input.copy()
    elif isinstance(contacts_input, list):
        tpl = pd.DataFrame(contacts_input)
    else:
        p = pathlib.Path(contacts_input)
        if not p.exists():
            return vdf
        if str(p).lower().endswith(".json"):
            tpl = pd.DataFrame(json.load(open(p, encoding="utf-8")))
        elif str(p).lower().endswith(".csv"):
            tpl = pd.read_csv(p)
        else:
            tpl = pd.read_excel(p)

    col = "website_clean" if "website_clean" in tpl.columns else ("website" if "website" in tpl.columns else ("domain" if "domain" in tpl.columns else None))
    if not col:
        return vdf

    for c in CONTACT_COLS:
        if c not in tpl.columns:
            tpl[c] = None
    tpl["_dom"] = tpl[col].fillna("").apply(norm_domain)
    tpl["_rc"] = pd.to_numeric(tpl.get("review_count"), errors="coerce").fillna(0)
    info = (tpl.sort_values("_rc", ascending=False).drop_duplicates("_dom")
            .set_index("_dom")[CONTACT_COLS])
    return vdf.drop(columns=CONTACT_COLS).join(info, on="domain")


def build_leads_workbook(qual_df: pd.DataFrame, drop_df: pd.DataFrame) -> Workbook:
    """Tao Workbook openpyxl chua 2 sheet Qualified va Dropped."""
    wb = Workbook()
    wb.remove(wb.active)
    hf = PatternFill("solid", fgColor="1F4E78")
    hfont = Font(color="FFFFFF", bold=True)
    linkfont = Font(color="0563C1", underline="single")
    W = {"name": 32, "website": 30, "evidence": 74, "iata_ev": 34, "reason": 46,
         "emails": 22, "phone": 15, "city": 14, "gmaps_name": 30}

    def sheet(name, df):
        ws = wb.create_sheet(name)
        ws.append(list(df.columns))
        for c in ws[1]:
            c.fill, c.font = hf, hfont
        wi = list(df.columns).index("website") + 1 if "website" in df.columns else None
        for _, row in df.iterrows():
            formatted_row = []
            for v in row:
                if isinstance(v, list):
                    formatted_row.append(", ".join(str(x) for x in v))
                elif isinstance(v, dict):
                    formatted_row.append(json.dumps(v, ensure_ascii=False))
                elif pd.isna(v):
                    formatted_row.append("")
                else:
                    formatted_row.append(v)
            ws.append(formatted_row)
        for r in ws.iter_rows(min_row=2):
            if wi and r[wi - 1].value:
                r[wi - 1].hyperlink = str(r[wi - 1].value)
                r[wi - 1].font = linkfont
        for i, cn in enumerate(df.columns, 1):
            ws.column_dimensions[get_column_letter(i)].width = W.get(cn, 12)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    sheet("Qualified leads", qual_df)
    sheet("Dropped", drop_df)
    return wb


def export_leads_to_excel_buffer(leads_data: dict) -> io.BytesIO:
    """Chuyen doi object leads_data (dict) sang file Excel luu truc tiep trong RAM (BytesIO)."""
    qual_df = pd.DataFrame(leads_data.get("qualified_leads", []))
    drop_df = pd.DataFrame(leads_data.get("dropped_leads", []))
    wb = build_leads_workbook(qual_df, drop_df)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def write_xlsx(out, path):
    out["_r"] = out.tier.map({"Tier 1": 0, "Tier 2": 1, "Tier 3": 2, "DROP": 3})
    out = out.sort_values(["_r", "site_reachable", "conf"], ascending=[True, False, False])
    out = out.rename(columns={"onlinesearch": "online_flight_search",
                              "flightticketing": "sells_air_tickets",
                              "iata": "iata_visible"})
    qcols = ["name", "website", "site_reachable", "https_ok", "reason", "sells_air_tickets",
             "online_flight_search", "iata_visible", "iata_ev", "city", "phone", "emails",
             "review_count", "conf", "gmaps_name", "evidence", "db_place_id"]
    dcols = ["reason", "name", "website", "conf", "gmaps_name", "evidence", "db_place_id"]
    qual, drop = out[out.tier != "DROP"][qcols], out[out.tier == "DROP"][dcols]

    wb = build_leads_workbook(qual, drop)
    wb.save(path)
    return qual, drop, out


def run_tiering(verdicts_data, country, output_json=None, output_xlsx=None, reverify_data=None, contacts_data=None, require_online_search=False):
    global REQUIRE_ONLINE_SEARCH
    REQUIRE_ONLINE_SEARCH = require_online_search

    vdf = load_verdicts(verdicts_data)
    print(f"Đang xử lý {len(vdf)} kết quả thẩm định cho quốc gia {country}...")
    if EXCLUDE_BIG:
        before = len(vdf)
        vdf = vdf[~vdf.domain.isin(EXCLUDE_BIG)].copy()
        print(f"  Đã loại {before - len(vdf)} mega-OTA")

    vdf = apply_reverify(vdf, reverify_data)
    if vdf.empty:
        vdf["tier"] = []
        vdf["reason"] = []
    else:
        vdf[["tier", "reason"]] = vdf.apply(lambda r: pd.Series(classify(r)), axis=1)

    out = join_contacts(vdf, contacts_data)
    out["name"] = out.apply(
        lambda r: NAME_MAP.get(r.domain, r.title if pd.notna(r.title) else r.domain), axis=1)
    out["gmaps_name"] = out["title"]
    out["website"] = out["workurl"]
    out["site_reachable"] = out["reach"]

    out["_r"] = out.tier.map({"Tier 1": 0, "Tier 2": 1, "Tier 3": 2, "DROP": 3})
    out = out.sort_values(["_r", "site_reachable", "conf"], ascending=[True, False, False])
    out = out.rename(columns={"onlinesearch": "online_flight_search",
                              "flightticketing": "sells_air_tickets",
                              "iata": "iata_visible"})
    qcols = ["name", "website", "site_reachable", "https_ok", "reason", "sells_air_tickets",
             "online_flight_search", "iata_visible", "iata_ev", "city", "phone", "emails",
             "review_count", "conf", "gmaps_name", "evidence", "db_place_id"]
    dcols = ["reason", "name", "website", "conf", "gmaps_name", "evidence", "db_place_id"]
    qual = out[out.tier != "DROP"][qcols]
    drop = out[out.tier == "DROP"][dcols]

    print(f"\n--- [KẾT QUẢ PHÂN TIER & LỌC LEADS CHI TIẾT] ---")
    for _, row in out.iterrows():
        tier_val = row.get("tier", "")
        name_val = str(row.get("name", ""))[:32]
        dom_val = row.get("domain", "")
        reason_val = row.get("reason", "")
        if tier_val == "DROP":
            print(f"       [-] BỊ LOẠI [Phân Tier - DROP]: {name_val:<32} | Domain: {dom_val} | Lý do: {reason_val}")
        else:
            print(f"       [+] ĐẠT CHUẨN [{tier_val}]: {name_val:<32} | Domain: {dom_val} | Lý do: {reason_val}")

    from datetime import datetime

    def clean_records_for_json(df_obj):
        clean_df = df_obj.copy().fillna("")
        records = clean_df.to_dict(orient="records")
        for r in records:
            for k, v in r.items():
                if pd.isna(v):
                    r[k] = ""
        return records

    leads_data = {
        "country": country,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "qualified_count": len(qual),
            "dropped_count": len(drop),
            "total_leads": len(qual) + len(drop),
        },
        "qualified_leads": clean_records_for_json(qual),
        "dropped_leads": clean_records_for_json(drop),
    }

    if output_json:
        p_json = pathlib.Path(output_json)
        p_json.parent.mkdir(parents=True, exist_ok=True)
        with open(p_json, "w", encoding="utf-8") as f:
            json.dump(leads_data, f, ensure_ascii=False, indent=2)
        print(f"Đã lưu kết quả JSON tại {output_json}")

    if output_xlsx:
        wb = build_leads_workbook(qual, drop)
        wb.save(output_xlsx)
        print(f"Đã lưu file Excel tại {output_xlsx}")

    print(f"\n{country.upper()}: ĐẠT CHUẨN (QUALIFIED)={len(qual)}  BỊ LOẠI (DROPPED)={len(drop)}  | {out.tier.value_counts().to_dict()}")
    return qual, drop, leads_data

def main():
    ap = argparse.ArgumentParser(description="Tier hoa NDC leads va xuat Excel")
    ap.add_argument("--verdicts", required=True, help="CSV verdict 11 cot tu AI deep-dive")
    ap.add_argument("--country", required=True, help="slug, vd hongkong")
    ap.add_argument("--reverify", help="reverify.json tu reverify_browser.py")
    ap.add_argument("--contacts", help="bang danh ba da lam sach (.xlsx/.csv) de ghep "
                                       "name/city/phone/emails/review_count theo domain")
    ap.add_argument("--out", help="duong dan Excel dau ra "
                                  "(mac dinh: ./{country}_ndc_leads.xlsx)")
    args = ap.parse_args()

    outp = args.out or f"{args.country}_ndc_leads.xlsx"

    vdf = load_verdicts(args.verdicts)
    print(f"Doc {len(vdf)} verdict tu {args.verdicts}")
    if EXCLUDE_BIG:
        before = len(vdf)
        vdf = vdf[~vdf.domain.isin(EXCLUDE_BIG)].copy()
        print(f"  loai {before - len(vdf)} mega-OTA")

    vdf = apply_reverify(vdf, args.reverify)
    if vdf.empty:
        vdf["tier"] = []
        vdf["reason"] = []
    else:
        vdf[["tier", "reason"]] = vdf.apply(lambda r: pd.Series(classify(r)), axis=1)

    out = join_contacts(vdf, args.contacts)
    out["name"] = out.apply(
        lambda r: NAME_MAP.get(r.domain, r.title if pd.notna(r.title) else r.domain), axis=1)
    out["gmaps_name"] = out["title"]
    out["website"] = out["workurl"]
    out["site_reachable"] = out["reach"]

    qual, drop, out = write_xlsx(out, outp)
    print(f"\n{args.country}: QUALIFIED={len(qual)}  DROPPED={len(drop)}  "
          f"| {out.tier.value_counts().to_dict()}")
    print("\nTier 1-2 (manh nhat):")
    for _, r in out[out.tier.isin(["Tier 1", "Tier 2"])].iterrows():
        print(f"  {r.tier} | {str(r['name'])[:34]:<34} {r.website}")
    print("\nDa luu:", outp)


if __name__ == "__main__":
    main()
