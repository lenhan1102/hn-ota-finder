import asyncio
import httpx

async def test():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True, verify=False) as client:
        for url in [
            "https://vemaybaykhampha.com",
            "http://vemaybaykhampha.com",
            "https://www.vemaybaykhampha.com",
            "https://vemaybaykhampha.com/about-us"
        ]:
            try:
                res = await client.get(url)
                print(f"✔ {url} -> {res.status_code}")
            except Exception as e:
                print(f"❌ {url} -> {type(e).__name__}: {e}")

asyncio.run(test())
