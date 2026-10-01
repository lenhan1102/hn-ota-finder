import urllib.request
import re
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

url = "https://vemaybaykhampha.com/about-us"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
        html = r.read().decode("utf-8", errors="ignore")
        print("Status 200, length:", len(html))
        
        # All @ strings
        ats = re.findall(r"[\w\.\+\-]+@[\w\.\-]+\.[a-zA-Z]{2,}", html)
        print("Found @ regex:", set(ats))
        
        mailtos = re.findall(r"mailto:([^\s\"\'\?]+)", html, re.I)
        print("Found mailto:", set(mailtos))
except Exception as e:
    print("Fetch error:", e)
