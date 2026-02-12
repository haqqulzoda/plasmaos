import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from app.db.session import engine
from app.models.all_models import TenderStatus

# Mock Data representing UzEx Tenders
MOCK_TENDERS = [
    {
        "id": uuid.uuid4(),
        "external_id": "998231",
        "source_url": "https://etender.uzex.uz/lot/998231",
        "title": "Current repair of the roof of School No. 45 in Chilanzar district",
        "description": "Demolition of old slate, installation of profnastil, wood processing with fire protection...",
        "budget": 450_000_000.0,
        "currency": "UZS",
        "region": "Tashkent City",
        "deadline": datetime.now(timezone.utc) + timedelta(days=5),
        "status": TenderStatus.OPEN.value,
    },
    {
        "id": uuid.uuid4(),
        "external_id": "998232",
        "source_url": "https://etender.uzex.uz/lot/998232",
        "title": "Supply of Office Equipment (Laptops, Printers) for Ministry of Health",
        "description": "Core i5 Gen 12, 16GB RAM, 512GB SSD. Quantity: 50 sets.",
        "budget": 620_000_000.0,
        "currency": "UZS",
        "region": "Tashkent City",
        "deadline": datetime.now(timezone.utc) + timedelta(days=2),
        "status": TenderStatus.OPEN.value,
    },
    {
        "id": uuid.uuid4(),
        "external_id": "998233",
        "source_url": "https://etender.uzex.uz/lot/998233",
        "title": "Construction of internal roads in mahalla 'Dustlik'",
        "description": "Asphalting of internal roads, 4cm layer, total area 2000 m2.",
        "budget": 1_200_000_000.0,
        "currency": "UZS",
        "region": "Samarkand",
        "deadline": datetime.now(timezone.utc) + timedelta(days=10),
        "status": TenderStatus.OPEN.value,
    },
    {
        "id": uuid.uuid4(),
        "external_id": "998234",
        "source_url": "https://etender.uzex.uz/lot/998234",
        "title": "Supply of Medical Equipment for Regional Hospital",
        "description": "MRI machine, X-ray equipment, and ultrasound devices for district hospital modernization.",
        "budget": 2_500_000_000.0,
        "currency": "UZS",
        "region": "Fergana",
        "deadline": datetime.now(timezone.utc) + timedelta(days=15),
        "status": TenderStatus.OPEN.value,
    },
    {
        "id": uuid.uuid4(),
        "external_id": "998235",
        "source_url": "https://etender.uzex.uz/lot/998235",
        "title": "Road Repair Works - M39 Highway Section",
        "description": "Asphalt resurfacing for 12km section of M39 highway including drainage improvements.",
        "budget": 1_800_000_000.0,
        "currency": "UZS",
        "region": "Navoi",
        "deadline": datetime.now(timezone.utc) + timedelta(days=7),
        "status": TenderStatus.OPEN.value,
    },
]

async def seed_data():
    async with engine.begin() as conn:
        print("--- SEEDING TENDERS ---")
        for t in MOCK_TENDERS:
            try:
                await conn.execute(
                    text(
                        "INSERT INTO tenders (id, external_id, source_url, title, description, budget, currency, region, deadline, status, created_at) "
                        "VALUES (:id, :eid, :url, :title, :desc, :budget, :currency, :region, :dl, :status, NOW())"
                    ),
                    {
                        "id": t["id"],
                        "eid": t["external_id"],
                        "url": t["source_url"],
                        "title": t["title"],
                        "desc": t["description"],
                        "budget": t["budget"],
                        "currency": t["currency"],
                        "region": t["region"],
                        "dl": t["deadline"],
                        "status": t["status"],
                    },
                )
                print(f"Inserted: {t['title'][:40]}...")
            except Exception as e:
                print(f"Skipped {t['external_id']} - {e}")
        print("--- SEED COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(seed_data())