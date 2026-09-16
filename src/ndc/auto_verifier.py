#!/usr/bin/env python3
"""
auto_verifier.py — Tu dong tham dinh website (AI Deep-dive & Browser Probe)
Ket hop Playwright Chromium va tuy chon LLM (OpenAI / Gemini) de tao:
1. verdicts.csv (11 cot chuan de ndc_tiering.py phan loai Tier)
2. reverify.json (du lieu kiem tra thuc te tu trinh duyet)
"""

import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

try:
    from .reverify_browser import probe, check_flight_form, check_domain_resolves
except ImportError:
    from reverify_browser import probe, check_flight_form, check_domain_resolves


# Danh sach tu khoa nhan dien ve may bay
FLIGHT_KEYWORDS = re.compile(
    r"(flight|air ticket|airline ticket|book flight|vé máy bay|ve may bay|機票|机票|"
    r"tiket pesawat|penerbangan|flights booking|airfare|flight search)",
    re.IGNORECASE
)

AIRLINE_KEYWORDS = re.compile(
    r"(vietnam airlines|vietjet|bamboo airways|cathay pacific|singapore airlines|"
    r"thai airways|airasia|malaysia airlines|garuda indonesia|cebu pacific|"
    r"emirates|qatar airways|ana |japan airlines|korean air|asiana)",
    re.IGNORECASE
)


def norm_domain(url_or_domain: str) -> str:
    if not url_or_domain:
        return ""
    d = str(url_or_domain).strip().lower()
    if "://" not in d:
        d = "http://" + d
    netloc = urlparse(d).netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.split(":")[0]


def call_llm_for_verdict(domain: str, title: str, snippet: str, api_key: str, provider: str = "openai") -> dict | None:
    prompt = f"""
Ban la chuyen vien tham dinh dai ly du lich de ban noi dung ve may bay qua NDC/IATA.
Danh gia domain: {domain}
Title: {title}
Snippet: {snippet}

Tra ve DUY NHAT 1 JSON object co dung cac truong sau (gia tri 0 hoac 1, rieng conf la so thuc 0.0-1.0, evidence va iata_ev la chuoi):
{{
  "domain": "{domain}",
  "real": 0 hoac 1,
  "ota": 0 hoac 1,
  "airline": 0 hoac 1,
  "flightticketing": 0 hoac 1,
  "onlinesearch": 0 hoac 1,
  "iata": 0 hoac 1,
  "iata_ev": "not found" hoac chuoi so IATA,
  "puretour": 0 hoac 1,
  "conf": 0.85,
  "evidence": "tom tat bang chung"
}}
"""
    try:
        if provider == "openai":
            import httpx
            resp = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        elif provider == "gemini":
            import httpx
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            resp = httpx.post(
                url,
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt + "\nTra ve JSON hop le."}]}]},
                timeout=30.0,
            )
            if resp.status_code == 200:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                clean_json = re.search(r"\{.*\}", text, re.DOTALL)
                if clean_json:
                    return json.loads(clean_json.group(0))
    except Exception as e:
        print(f"    [WARN] Loi goi LLM cho {domain}: {e}")
    return None


def run_auto_verification(
    candidates_data,
    output_verdicts_json: str | Path = None,
    output_reverify_json: str | Path = None,
    locale: str = "en-US",
    max_sites: int = 0,
    headless: bool = True,
) -> tuple[list[dict], list[dict]]:
    if isinstance(candidates_data, pd.DataFrame):
        df = candidates_data.copy()
    elif isinstance(candidates_data, list):
        df = pd.DataFrame(candidates_data)
    else:
        in_str = str(candidates_data)
        if in_str.endswith(".json"):
            import json
            try:
                with open(in_str, "r", encoding="utf-8") as f:
                    df = pd.DataFrame(json.load(f))
            except Exception:
                with open(in_str, "r", encoding="utf-8") as f:
                    df = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        else:
            df = pd.read_csv(in_str)

    if "proper_domain" in df.columns:
        domain_col = "proper_domain"
    elif "domain" in df.columns:
        domain_col = "domain"
    elif "website_domain" in df.columns:
        domain_col = "website_domain"
    elif "website" in df.columns:
        df["_domain"] = df["website"].apply(norm_domain)
        domain_col = "_domain"
    else:
        # Neu rong, tao danh sach rong
        if df.empty:
            return [], []
        raise ValueError("Khong tim thay cot domain hoac website trong candidates")

    unique_sites = []
    seen = set()
    for _, row in df.iterrows():
        dom = norm_domain(row[domain_col])
        if dom and dom not in seen:
            seen.add(dom)
            raw_url = str(row.get("website") or f"https://{dom}")
            if not raw_url.startswith("http"):
                raw_url = "https://" + raw_url
            name = str(row.get("title") or dom)
            category = str(row.get("category") or "")
            unique_sites.append({
                "domain": dom,
                "url": raw_url,
                "name": name,
                "category": category,
            })

    if max_sites > 0:
        unique_sites = unique_sites[:max_sites]

    print(f"\n{'='*70}")
    print(f"  BẮT ĐẦU THẨM ĐỊNH {len(unique_sites)} WEBSITE BẰNG PLAYWRIGHT CHROMIUM")
    print(f"  Headless: {headless} (Cửa sổ trình duyệt: {'ẨN' if headless else 'HIỆN THỰC TẾ'})")
    print(f"{'='*70}")

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    llm_provider = "openai" if openai_key else ("gemini" if gemini_key else None)
    api_key = openai_key or gemini_key

    if llm_provider:
        print(f"    Da kich hoat tham dinh bang AI ({llm_provider.upper()})")
    else:
        print("    Khong co AI API Key -> Dung thuat toan phan tich Playwright Offline")

    reverify_records = []
    verdicts = []

    if sync_playwright is None:
        raise RuntimeError("Playwright chua duoc cai dat.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        ctx = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 800},
            locale=locale,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        )
        ctx.set_default_timeout(8000)

        for i, item in enumerate(unique_sites, 1):
            dom = item["domain"]
            url = item["url"]
            print(f"  [{i}/{len(unique_sites)}] Dang kiem tra: {dom}...", end=" ", flush=True)

            # DNS Pre-check sieu nhanh (0.02s) de tranh ngam timeout vo tan tren site chet/NXDOMAIN
            if not check_domain_resolves(dom):
                print(f"[LOAD_FAILED] (Domain chet / DNS NXDOMAIN - Bo qua ngay lap tuc)")
                probe_res = {
                    "loaded": False,
                    "error": "DNS_PROBE_FINISHED_NXDOMAIN (Tên miền không tồn tại hoặc chết DNS)",
                    "name": item["name"],
                    "url": url,
                    "domain": dom,
                }
                reverify_records.append(probe_res)
                verdicts.append({
                    "domain": dom,
                    "real": 0,
                    "ota": 0,
                    "airline": 0,
                    "flightticketing": 0,
                    "onlinesearch": 0,
                    "iata": 0,
                    "iata_ev": "not found",
                    "puretour": 0,
                    "conf": 0.0,
                    "evidence": "Site chet (NXDOMAIN / DNS resolve failed)",
                    "reachable": 0,
                })
                continue

            page = ctx.new_page()
            try:
                probe_res = probe(page, url, timeout_ms=8000)
            except Exception as e:
                probe_res = {"loaded": False, "error": str(e)[:100]}
            finally:
                page.close()

            probe_res["name"] = item["name"]
            probe_res["url"] = url
            probe_res["domain"] = dom
            reverify_records.append(probe_res)

            verdict = None
            if probe_res.get("loaded") and llm_provider and api_key:
                verdict = call_llm_for_verdict(
                    domain=dom,
                    title=probe_res.get("title", ""),
                    snippet=probe_res.get("snippet", ""),
                    api_key=api_key,
                    provider=llm_provider,
                )

            if not verdict:
                loaded = bool(probe_res.get("loaded"))
                title = probe_res.get("title", "")
                snippet = probe_res.get("snippet", "")
                full_text = f"{title} {snippet}".lower()
                flight_form = bool(probe_res.get("flight_form"))
                iata_found = bool(probe_res.get("iata_found"))
                iata_num = probe_res.get("iata_number") or ""

                is_airline = bool(AIRLINE_KEYWORDS.search(dom) or AIRLINE_KEYWORDS.search(item["name"]))
                has_flight_kw = bool(FLIGHT_KEYWORDS.search(full_text))

                flight_ticketing = 1 if (flight_form or has_flight_kw) else 0
                online_search = 1 if flight_form else 0
                pure_tour = 1 if ("tour" in item["category"].lower() and not flight_ticketing) else 0

                verdict = {
                    "domain": dom,
                    "real": 1 if loaded else 0,
                    "ota": 1 if (loaded and not is_airline and not pure_tour) else 0,
                    "airline": 1 if is_airline else 0,
                    "flightticketing": flight_ticketing,
                    "onlinesearch": online_search,
                    "iata": 1 if iata_found else 0,
                    "iata_ev": iata_num if iata_found else "not found",
                    "puretour": pure_tour,
                    "conf": 0.85 if loaded else 0.2,
                    "evidence": "Status: " + str(probe_res.get("status")) + ", Flight form: " + str(flight_form) + ", IATA: " + str(iata_found),
                }

            verdict["reachable"] = 1 if probe_res.get("loaded") else 0
            verdicts.append(verdict)

            status_str = "LOAD_OK" if probe_res.get("loaded") else "LOAD_FAILED"
            flight_str = "CÓ BÁN VÉ (Qualified)" if verdict.get("flightticketing") else "KHÔNG BÁN VÉ"
            ev_str = verdict.get("evidence", "")
            title_p = probe_res.get("title", "")[:40]
            print(f"[{status_str}] | Title: '{title_p}' -> {flight_str}")
            if probe_res.get("flight_form"):
                print(f"      -> Phát hiện Form vé: {probe_res.get('flight_form_detail')}")
            if probe_res.get("iata_found"):
                print(f"      -> Phát hiện IATA: {probe_res.get('iata_number') or 'Có'}")

        browser.close()

    if output_reverify_json:
        output_reverify_json = Path(output_reverify_json)
        output_reverify_json.parent.mkdir(parents=True, exist_ok=True)
        with open(output_reverify_json, "w", encoding="utf-8") as f:
            json.dump(reverify_records, f, ensure_ascii=False, indent=2)
        print(f"Da luu reverify.json tai {output_reverify_json}")

    if output_verdicts_json:
        output_verdicts_json = Path(output_verdicts_json)
        output_verdicts_json.parent.mkdir(parents=True, exist_ok=True)
        with open(output_verdicts_json, "w", encoding="utf-8") as f:
            json.dump(verdicts, f, ensure_ascii=False, indent=2)
        print(f"Da luu verdicts.json tai {output_verdicts_json}")

    return verdicts, reverify_records
