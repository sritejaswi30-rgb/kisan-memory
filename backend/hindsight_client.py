import os
import re

from dotenv import load_dotenv
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ApiException

load_dotenv()

_client: Hindsight | None = None

DATE_PATTERN = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def bank_id() -> str:
    return os.getenv("HINDSIGHT_BANK_ID", "").strip() or "kisan-memory"


def bank_for_user(user_id: int | str) -> str:
    """One isolated Hindsight bank per farmer, e.g. 1001 -> kisan-user-1001."""
    return f"kisan-user-{str(user_id).strip()}"


def get_client() -> Hindsight:
    global _client
    if _client is None:
        base_url = os.getenv("HINDSIGHT_BASE_URL", "").strip()
        api_key = os.getenv("HINDSIGHT_API_KEY", "").strip()
        if not base_url or not api_key:
            raise RuntimeError("HINDSIGHT_BASE_URL and HINDSIGHT_API_KEY must be set in .env")
        _client = Hindsight(base_url=base_url, api_key=api_key, timeout=120.0)
    return _client


def build_query(farmer: str, field: str, message: str) -> str:
    return f"Farmer {farmer}, field {field}: {message}"


async def recall_memories(
    farmer: str, field: str, message: str, bank: str | None = None
) -> list[dict]:
    response = await get_client().arecall(
        bank_id=bank or bank_id(),
        query=build_query(farmer, field, message),
        budget="mid",
        max_tokens=4096,
    )
    memories = []
    for result in response.results:
        text = result.text or ""
        match = DATE_PATTERN.search(str(result.occurred_start or "")) or DATE_PATTERN.search(text)
        memories.append(
            {"type": result.type or "memory", "text": text, "date": match.group(1) if match else None}
        )
    return memories


async def retain_memory(
    content: str,
    context: str | None = None,
    metadata: dict | None = None,
    bank: str | None = None,
) -> bool:
    try:
        await get_client().aretain(
            bank_id=bank or bank_id(), content=content, context=context, metadata=metadata
        )
        return True
    except ApiException:
        return False


async def recent_memories(limit: int = 200, bank: str | None = None) -> list[dict]:
    response = await get_client().alist_memories(bank_id=bank or bank_id(), limit=limit)
    return [
        {"text": item.text or "", "metadata": item.metadata or {}}
        for item in response.items
    ]


async def ensure_bank(bank: str | None = None) -> None:
    try:
        await get_client().acreate_bank(bank_id=bank or bank_id(), name="KisanMemory")
    except ApiException:
        pass


def _memory_date(item) -> str | None:
    for value in (item.occurred_start, item.var_date, item.mentioned_at):
        if value:
            match = DATE_PATTERN.match(str(value))
            if match:
                return match.group(1)
    match = DATE_PATTERN.search(item.text or "")
    return match.group(1) if match else None


def _matches_field(metadata: dict, text: str, field: str) -> bool:
    recorded = str(metadata.get("field") or "").strip()
    if recorded:
        return recorded.lower() == field.strip().lower()
    return field.strip().lower() in text.lower()


async def timeline_entries(bank: str | None = None, field: str | None = None) -> list[dict]:
    response = await get_client().alist_memories(bank_id=bank or bank_id(), limit=200)

    grouped: dict[str | None, list[dict]] = {}
    for item in response.items:
        text = (item.text or "").strip()
        if not text:
            continue
        if field and not _matches_field(item.metadata or {}, text, field):
            continue
        grouped.setdefault(_memory_date(item), []).append(
            {"type": item.fact_type or "memory", "text": text}
        )

    events = []
    for date, entries in grouped.items():
        primary = next(
            (entry for entry in entries if entry["type"] == "observation"), entries[0]
        )
        events.append(
            {
                "date": date,
                "type": primary["type"],
                "text": primary["text"],
                "count": len(entries),
            }
        )

    events.sort(key=lambda event: (event["date"] is None, event["date"] or ""))
    return events


async def hindsight_available() -> bool:
    try:
        await get_client().aget_version()
        return True
    except Exception:
        return False


async def close() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        finally:
            _client = None
