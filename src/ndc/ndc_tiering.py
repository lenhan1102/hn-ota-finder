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
import argparse, csv, json, pathlib, sys
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
        "iata", "iata_ev", "puretour", "conf", "evidence", "reachable"]


# ============================================================================
# QUY TAC TIER — day la "tieu chi" duoi dang code
# ============================================================================
def classify(r):
    if r.domain in PEERS:
        return "DROP", "Peer B2B/wholesaler/travel-tech (khong phai dai ly cuoi)"
    if r.airline:
        return "DROP", "Chinh hang bay (nguon NDC, khong phai khach)"
    if not r.real:
        return "DROP", "Khong phai site cong ty that / khong truy cap duoc"
    if not r.ota:
        return "DROP", "Khong phai dai ly du lich/OTA"
    if r.puretour or not r.flightticketing:
        return "DROP", "Khong ban ve may bay (tour thuan / phi hang khong)"
    if getattr(r, "dead", False):
        return "DROP", "Domain khong con phan giai — site da chet (kiem tra bang trinh duyet that)"
    if REQUIRE_ONLINE_SEARCH and not r.onlinesearch:
        return "DROP", "Khong co online flight search (dat cho thu cong/lien he)"

    # --- Da qualify: co ban ve may bay ---
    if not getattr(r, "reach", True):
        return "Tier 3", ("Ban ve may bay nhung site khong vao duoc ke ca bang trinh duyet that "
                          "(chan bot/chan vung hoac down) — kiem tra tay")
    if r.onlinesearch and r.iata:
        return "Tier 1", "Online flight search + IATA hien thi (da kiem chung tren site that)"
    if r.onlinesearch:
        return "Tier 2", "Online flight search (da kiem chung tren site that)"
    if r.iata:
        return "Tier 2", "Dai ly ve IATA-accredited (da kiem chung tren site that)"
    if r.conf < 0.5:
        return "Tier 3", "Ban ve may bay — do tin cay thap, can xac minh"
    return "Tier 3", "Consolidator ve may bay (site song; offline / khong hien thi IATA) — NDC prospect"


# ============================================================================
def norm_domain(u):
    u = str(u or "")
    host = urlparse(u if u.startswith("http") else "https://" + u).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def load_verdicts(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    recs = []
    for r in rows:
        recs.append({
            "domain": norm_domain(r["domain"]) or r["domain"].strip().lower(),
            "real": int(r["real"]), "ota": int(r["ota"]), "airline": int(r["airline"]),
            "flightticketing": int(r["flightticketing"]), "onlinesearch": int(r["onlinesearch"]),
            "iata": int(r["iata"]), "iata_ev": r.get("iata_ev", ""),
            "puretour": int(r["puretour"]), "conf": float(r["conf"]),
            "evidence": r.get("evidence", ""),
            # cot tuy chon: 0 neu AI deep-dive khong tai duoc site (403/TLS/JS trong/down).
            # Mac dinh 1. Ket qua reverify_browser.py se ghi de gia tri nay.
            "reachable": int(r.get("reachable") or 1),
        })
    return pd.DataFrame(recs, columns=COLS)


def apply_reverify(vdf, reverify_path):
    """Ghi de ket qua WebFetch bang ket qua trinh duyet that."""
    rv = {}
    if reverify_path:
        for x in json.load(open(reverify_path)):
            rv[norm_domain(x["url"])] = x

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

    vdf[["reach", "dead", "iata", "onlinesearch", "workurl", "https_ok"]] = vdf.apply(one, axis=1)
    return vdf


CONTACT_COLS = ["title", "city", "phone", "emails", "review_count"]


def join_contacts(vdf, contacts_path):
    """Ghep name/city/phone/emails/review_count tu bang danh ba (neu co).

    Bang danh ba la .xlsx hoac .csv, can toi thieu mot cot website
    ('website_clean' hoac 'website') de match theo domain.
    """
    for c in CONTACT_COLS:
        vdf[c] = None
    if not contacts_path:
        print("  (bo qua ghep lien he: khong truyen --contacts)")
        return vdf
    if not pathlib.Path(contacts_path).exists():
        print(f"  (bo qua ghep lien he: khong thay file {contacts_path})")
        return vdf
    tpl = (pd.read_csv(contacts_path) if str(contacts_path).lower().endswith(".csv")
           else pd.read_excel(contacts_path))
    col = "website_clean" if "website_clean" in tpl.columns else "website"
    if col not in tpl.columns:
        print(f"  (bo qua ghep lien he: {contacts_path} khong co cot website/website_clean)")
        return vdf
    for c in CONTACT_COLS:
        if c not in tpl.columns:
            tpl[c] = None
    tpl["_dom"] = tpl[col].fillna("").apply(norm_domain)
    tpl["_rc"] = pd.to_numeric(tpl.get("review_count"), errors="coerce").fillna(0)
    # mot domain nhieu dong GMaps -> giu dong co nhieu review nhat
    info = (tpl.sort_values("_rc", ascending=False).drop_duplicates("_dom")
            .set_index("_dom")[CONTACT_COLS])
    return vdf.drop(columns=CONTACT_COLS).join(info, on="domain")


def write_xlsx(out, path):
    out["_r"] = out.tier.map({"Tier 1": 0, "Tier 2": 1, "Tier 3": 2, "DROP": 3})
    out = out.sort_values(["_r", "site_reachable", "conf"], ascending=[True, False, False])
    out = out.rename(columns={"onlinesearch": "online_flight_search",
                              "flightticketing": "sells_air_tickets",
                              "iata": "iata_visible"})
    qcols = ["name", "website", "site_reachable", "https_ok", "reason", "sells_air_tickets",
             "online_flight_search", "iata_visible", "iata_ev", "city", "phone", "emails",
             "review_count", "conf", "gmaps_name", "evidence"]
    dcols = ["reason", "name", "website", "conf", "gmaps_name", "evidence"]
    qual, drop = out[out.tier != "DROP"][qcols], out[out.tier == "DROP"][dcols]

    wb = Workbook(); wb.remove(wb.active)
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
            ws.append(["" if pd.isna(v) else v for v in row])
        for r in ws.iter_rows(min_row=2):
            if wi and r[wi - 1].value:
                r[wi - 1].hyperlink = r[wi - 1].value
                r[wi - 1].font = linkfont
        for i, cn in enumerate(df.columns, 1):
            ws.column_dimensions[get_column_letter(i)].width = W.get(cn, 12)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    sheet("Qualified leads", qual)
    sheet("Dropped", drop)
    wb.save(path)
    return qual, drop, out



def run_tiering(verdicts_csv, country, output_xlsx, reverify_json=None, contacts_csv=None, require_online_search=False):
    global REQUIRE_ONLINE_SEARCH
    REQUIRE_ONLINE_SEARCH = require_online_search

    vdf = load_verdicts(verdicts_csv)
    print(f"Doc {len(vdf)} verdict tu {verdicts_csv}")
    if EXCLUDE_BIG:
        before = len(vdf)
        vdf = vdf[~vdf.domain.isin(EXCLUDE_BIG)].copy()
        print(f"  loai {before - len(vdf)} mega-OTA")

    vdf = apply_reverify(vdf, reverify_json)
    vdf[["tier", "reason"]] = vdf.apply(lambda r: pd.Series(classify(r)), axis=1)

    out = join_contacts(vdf, contacts_csv)
    out["name"] = out.apply(
        lambda r: NAME_MAP.get(r.domain, r.title if pd.notna(r.title) else r.domain), axis=1)
    out["gmaps_name"] = out["title"]
    out["website"] = out["workurl"]
    out["site_reachable"] = out["reach"]

    qual, drop, out = write_xlsx(out, output_xlsx)
    print(f"\n{country}: QUALIFIED={len(qual)}  DROPPED={len(drop)}  "
          f"| {out.tier.value_counts().to_dict()}")
    return qual, drop, out

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
