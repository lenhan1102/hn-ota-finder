import asyncio
import sys
sys.path.insert(0, ".")

from src.enrich.website_fallback import scrape_department_emails

async def main():
    contacts = await scrape_department_emails("vemaybaykhampha.com")
    print("Contacts found:", len(contacts))
    for c in contacts:
        print(f" - {c.full_name}: {c.email} (tier={c.tier}, score={c.confidence_score})")

if __name__ == "__main__":
    asyncio.run(main())
