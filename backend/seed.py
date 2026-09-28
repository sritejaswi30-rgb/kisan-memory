"""Demo seed data: two farmers in PostgreSQL/SQLite and one Hindsight bank each."""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import hindsight_client
from backend.models import Field, User

logger = logging.getLogger("kissanmemory.seed")

DEMO_USERS = [
    {
        "id": 1001,
        "name": "Ravi",
        "preferred_language": "Telugu",
        "fields": [
            {"name": "Field A", "crop": "Tomato", "planting_date": date(2026, 6, 5)},
        ],
    },
    {
        "id": 1002,
        "name": "Sita",
        "preferred_language": "Telugu",
        "fields": [
            {"name": "Field B", "crop": "Paddy", "planting_date": date(2026, 6, 10)},
        ],
    },
]

DEMO_MEMORIES: dict[int, list[tuple[str, str]]] = {
    1001: [
        ("Farmer Ravi planted tomatoes in Field A on 2026-06-05.", "Field A"),
        ("Heavy rain on 2026-06-18 caused waterlogging in Field A.", "Field A"),
        (
            "Fungal symptoms appeared on the tomato plants in Field A on 2026-06-23 "
            "after the waterlogging.",
            "Field A",
        ),
        (
            "Ravi applied Treatment A to Field A on 2026-06-24 and the fungal symptoms "
            "reduced by 2026-07-02.",
            "Field A",
        ),
        (
            "Ravi re-applied Treatment A to Field A on 2026-09-28 but it did not help "
            "this time.",
            "Field A",
        ),
    ],
    1002: [
        ("Farmer Sita planted paddy in Field B on 2026-06-10.", "Field B"),
        (
            "Field B had an irrigation problem: water supply was irregular in July 2026.",
            "Field B",
        ),
        (
            "Soil moisture in Field B dropped in early August 2026 and the paddy leaves "
            "turned yellow.",
            "Field B",
        ),
        (
            "Sita applied Treatment C for soil moisture in Field B on 2026-08-12 and "
            "the soil moisture improved by 2026-08-26.",
            "Field B",
        ),
        (
            "Sita tried Treatment D on Field B on 2026-09-05 but the leaf yellowing "
            "did not improve.",
            "Field B",
        ),
    ],
}

SEED_MARKER = "demo-seed-v1"

NAME_BY_ID = {spec["id"]: spec["name"] for spec in DEMO_USERS}


def ensure_demo_users(session: Session) -> list[User]:
    users: list[User] = []
    for spec in DEMO_USERS:
        user = session.get(User, spec["id"])
        if user is None:
            user = User(
                id=spec["id"],
                name=spec["name"],
                preferred_language=spec["preferred_language"],
            )
            session.add(user)
            session.flush()
        for field_spec in spec["fields"]:
            existing = session.scalars(
                select(Field).where(Field.user_id == user.id, Field.name == field_spec["name"])
            ).first()
            if existing is None:
                session.add(
                    Field(
                        user_id=user.id,
                        name=field_spec["name"],
                        crop=field_spec["crop"],
                        planting_date=field_spec["planting_date"],
                    )
                )
        users.append(user)
    session.commit()
    return users


async def seed_hindsight_memories() -> None:
    for user_id, memories in DEMO_MEMORIES.items():
        bank = hindsight_client.bank_for_user(user_id)
        try:
            await hindsight_client.ensure_bank(bank)
            existing = await hindsight_client.recent_memories(bank=bank)
        except Exception:
            logger.warning("skipping seed for %s: hindsight unreachable", bank, exc_info=True)
            continue
        if any((item["metadata"] or {}).get("seed") == SEED_MARKER for item in existing):
            continue
        already = {item["text"].strip() for item in existing}
        for text, field_name in memories:
            if text.strip() in already:
                continue
            await hindsight_client.retain_memory(
                text,
                context=f"Farmer {NAME_BY_ID[user_id]}, {field_name}",
                metadata={
                    "seed": SEED_MARKER,
                    "field": field_name,
                    "user_id": str(user_id),
                },
                bank=bank,
            )
        logger.info("seeded %s memories into %s", len(memories), bank)
