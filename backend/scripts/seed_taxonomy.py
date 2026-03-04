from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import AsyncSessionLocal
from app.models import all_models as _all_models  # noqa: F401
from app.models.taxonomy import TaxonomyCategory, TaxonomyNode

BASELINE_REQUIREMENTS = [
    {
        "category": TaxonomyCategory.CERTIFICATION,
        "name": "ISO 9001",
        "description": "Quality management system certification.",
        "impact_weight": 50,
        "is_fatal": False,
    },
    {
        "category": TaxonomyCategory.LICENSE,
        "name": "Construction License Category A",
        "description": "Primary construction license required for category A works.",
        "impact_weight": 100,
        "is_fatal": True,
    },
    {
        "category": TaxonomyCategory.FINANCIAL,
        "name": "Minimum Turnover 1B UZS",
        "description": "Minimum annual turnover threshold of 1 billion UZS.",
        "impact_weight": 80,
        "is_fatal": True,
    },
    {
        "category": TaxonomyCategory.CERTIFICATION,
        "name": "ISO 14001",
        "description": "Environmental management system certification.",
        "impact_weight": 45,
        "is_fatal": False,
    },
    {
        "category": TaxonomyCategory.CERTIFICATION,
        "name": "ISO 45001",
        "description": "Occupational health and safety management certification.",
        "impact_weight": 55,
        "is_fatal": False,
    },
    {
        "category": TaxonomyCategory.FINANCIAL,
        "name": "No Outstanding Tax Debt",
        "description": "Proof of zero overdue tax liabilities.",
        "impact_weight": 85,
        "is_fatal": True,
    },
    {
        "category": TaxonomyCategory.ESG,
        "name": "ESG Compliance Statement",
        "description": "Formal statement confirming ESG policy adherence.",
        "impact_weight": 40,
        "is_fatal": False,
    },
    {
        "category": TaxonomyCategory.TECHNICAL,
        "name": "BIM Capability",
        "description": "Demonstrated Building Information Modeling capability.",
        "impact_weight": 35,
        "is_fatal": False,
    },
    {
        "category": TaxonomyCategory.PERSONNEL,
        "name": "Qualified Safety Engineer on Staff",
        "description": "At least one certified safety engineer employed full-time.",
        "impact_weight": 70,
        "is_fatal": True,
    },
    {
        "category": TaxonomyCategory.TECHNICAL,
        "name": "Three Completed Similar Projects",
        "description": "Track record of at least three relevant completed projects.",
        "impact_weight": 60,
        "is_fatal": False,
    },
]


async def seed_taxonomy(session: AsyncSession) -> int:
    names = [item["name"] for item in BASELINE_REQUIREMENTS]
    result = await session.execute(
        select(TaxonomyNode.name).where(TaxonomyNode.name.in_(names))
    )
    existing_names = set(result.scalars().all())

    nodes_to_insert = [
        TaxonomyNode(**item)
        for item in BASELINE_REQUIREMENTS
        if item["name"] not in existing_names
    ]

    if nodes_to_insert:
        session.add_all(nodes_to_insert)
        await session.commit()

    return len(nodes_to_insert)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        inserted = await seed_taxonomy(session)
        print(f"Inserted {inserted} taxonomy node(s).")


if __name__ == "__main__":
    asyncio.run(main())
