import os
import re
from datetime import date

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


MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_ISO_IN_TEXT = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
DATE_MONTH_FIRST = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b", re.I
)
DATE_DAY_FIRST = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\.?,?\s+(20\d{{2}})\b", re.I
)
DATE_RANGE_ISO = re.compile(
    r"\b(?:between|from)\s+(20\d{2}-\d{2}-\d{2})\s+(?:and|to|-)\s+(20\d{2}-\d{2}-\d{2})\b",
    re.I,
)
DATE_RANGE_TEXT = re.compile(
    rf"\b(?:between|from)\s+({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?"
    rf"\s+(?:and|to|-)\s+({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b",
    re.I,
)
PIPE_METADATA = re.compile(r"\s*\|\s*[^|]+")
FAIL_WORDS = re.compile(
    r"did not|didn'?t|failed|ineffective|no effect|not help|not improv|not effective"
    r"|no improvement|no benefit|without (?:improvement|success|benefit)|unsuccessful",
    re.I,
)
SUCCESS_WORDS = re.compile(
    r"reduc|improv|recover|lessen|helped|worked|effective|success|better|resolved", re.I
)
APPLIED_WORDS = re.compile(r"\b(?:applied|re-applied|tried|sprayed|treated|used)\b", re.I)
INTENT_WORDS = re.compile(
    r"\b(?:to|in order to|aimed at|so as to)\s+(?:improv|reduc|help|recover|resolve|control|prevent)",
    re.I,
)
OBJECT_WORDS = (
    "soil moisture", "leaf yellowing", "yellowing", "fungal symptoms", "disease symptoms",
    "waterlogging", "irrigation", "aphids", "pest damage", "yield",
)


def _safe_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _explicit_dates(text: str) -> list[tuple[int, int, str]]:
    """Every reliably readable full date in the text: (start, end, ISO date).

    A range ("between July 1 and July 31, 2026") contributes its start date only,
    and the rest of the range is masked so its end date is not counted twice.
    """
    found: list[tuple[int, int, str]] = []
    seen: set[int] = set()
    masked = text

    def add(match: "re.Match[str]", iso: str | None) -> None:
        nonlocal masked
        if not iso or match.start() in seen:
            return
        seen.add(match.start())
        found.append((match.start(), match.end(), iso))
        masked = masked[: match.start()] + " " * (match.end() - match.start()) + masked[match.end():]

    for match in DATE_RANGE_ISO.finditer(masked):
        year, month, day = (int(part) for part in match.group(1).split("-"))
        add(match, _safe_date(year, month, day))
    for match in DATE_RANGE_TEXT.finditer(masked):
        add(match, _safe_date(int(match.group(5)), MONTHS[match.group(1).lower()], int(match.group(2))))

    candidates = (
        (DATE_ISO_IN_TEXT, lambda m: (m.group(1), m.group(2), m.group(3))),
        (DATE_MONTH_FIRST, lambda m: (m.group(3), MONTHS[m.group(1).lower()], m.group(2))),
        (DATE_DAY_FIRST, lambda m: (m.group(3), MONTHS[m.group(2).lower()], m.group(1))),
    )
    for pattern, parts in candidates:
        for match in pattern.finditer(masked):
            if match.start() in seen:
                continue
            iso = _safe_date(int(parts(match)[0]), int(parts(match)[1]), int(parts(match)[2]))
            if iso:
                seen.add(match.start())
                found.append((match.start(), match.end(), iso))
    return sorted(found)


def _title(text: str) -> str:
    return " ".join(part.capitalize() for part in text.split())


def _object_phrase(clause_lower: str) -> str:
    for word in OBJECT_WORDS:
        if word in clause_lower:
            return _title(word)
    return ""


def _outcome_label(clause: str, treatment: str, status: str) -> str:
    name = _title(treatment)
    lowered = clause.lower()
    index = lowered.find(treatment.lower())
    prefix = clause[:index].strip(" ,") if index >= 0 else ""
    subject_is_treatment = 0 <= index and len(prefix.split()) <= 3
    subject = _object_phrase(lowered)
    if status == "failure":
        if subject_is_treatment:
            return f"{name} failed"
        return f"{subject} did not improve" if subject else f"{name} failed"
    if subject_is_treatment:
        return f"{name} helped"
    return f"{subject} improved" if subject else f"{name} helped"


def _classify_event(
    clause: str, crop: str | None, carry: str | None = None
) -> tuple[str, str, str | None, str | None]:
    """Map one dated clause to (kind, label, treatment, status). Never invents dates.

    `carry` is the treatment named in an earlier clause of the same memory, so an
    outcome sentence that only says "the soil moisture improved" is still attributed
    to the treatment that caused it.
    """
    lowered = clause.lower()
    treatment_match = re.search(r"\b(treatment\s+[a-z0-9]+)\b", lowered)
    named = treatment_match.group(1) if treatment_match else None
    failed = bool(FAIL_WORDS.search(lowered))
    succeeded = (
        not failed
        and not INTENT_WORDS.search(lowered)
        and bool(SUCCESS_WORDS.search(lowered))
    )
    status = "failure" if failed else ("success" if succeeded else None)
    applied = bool(APPLIED_WORDS.search(lowered))
    treatment = named or (carry if (failed or succeeded or applied) else None)
    dropped = bool(re.search(r"\bdrop(?:ped)?\b|\bfell\b|\blow\b|\bdeclin|\bdry\b", lowered))

    if re.search(r"\bplant(?:ed|ing)?\b|\bsow(?:n|ing)?\b|\btransplant", lowered):
        label = f"{crop.strip()} planted" if crop and crop.strip() else "Crop planted"
        return "planting", label, treatment, None

    if treatment and applied and status is None:
        return "treatment", f"{_title(treatment)} applied", treatment, None

    if re.search(r"\bfung|\bdisease|\bblight|\bpathogen", lowered):
        if succeeded:
            return "outcome_ok", "Fungal symptoms reduced", treatment, "success"
        if failed:
            return "outcome_fail", "Fungal symptoms worsened", treatment, "failure"
        return "disease", "Fungal symptoms recorded", treatment, None

    if re.search(r"\brain|\bflood|waterlog|water-log", lowered):
        has_rain = bool(re.search(r"\brain", lowered))
        has_water = bool(re.search(r"waterlog|water-log|\bflood", lowered))
        if has_rain and has_water:
            label = "Heavy rain caused waterlogging"
        elif has_water:
            label = "Waterlogging recorded"
        else:
            label = "Heavy rain recorded"
        return "weather", label, treatment, None

    if "irrigat" in lowered:
        if failed or re.search(r"problem|issue|irregular|poor", lowered):
            return "irrigation", "Irrigation problem", treatment, status
        return "irrigation", "Irrigation recorded", treatment, status

    if "soil moisture" in lowered:
        if succeeded:
            return "outcome_ok", "Soil moisture improved", treatment, "success"
        if failed or dropped:
            label = (
                "Soil moisture dropped"
                if (dropped or re.search(r"reduc|fell", lowered))
                else "Soil moisture problem"
            )
            return "soil", label, treatment, status
        return "soil", "Soil moisture recorded", treatment, None

    if treatment and failed:
        return "outcome_fail", _outcome_label(clause, treatment, "failure"), treatment, "failure"
    if treatment and succeeded:
        return "outcome_ok", _outcome_label(clause, treatment, "success"), treatment, "success"
    if treatment and applied:
        return "treatment", f"{_title(treatment)} applied", treatment, None
    if treatment:
        return "treatment", f"{_title(treatment)} recorded", treatment, None
    return "other", clause.strip()[:90], None, None


def _memory_date(item) -> str | None:
    for value in (item.occurred_start, item.var_date, item.mentioned_at):
        if value:
            match = DATE_PATTERN.match(str(value))
            if match:
                return match.group(1)
    text = item.text or ""
    match = DATE_PATTERN.search(text)
    if match:
        return match.group(1)
    explicit = _explicit_dates(text)
    return explicit[0][2] if explicit else None


def _split_events(text: str, fallback_date: str | None) -> list[tuple[str | None, str]]:
    """Split one Hindsight memory into individually dated events.

    Each date in the text governs the words written before it, so
    "...applied Treatment C on 2026-08-12 and the soil moisture improved by
    2026-08-26" becomes two events. A date is only ever taken from the text
    itself or from Hindsight metadata (`fallback_date`); dates are never guessed.
    """
    cleaned = PIPE_METADATA.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []
    dates = _explicit_dates(cleaned)
    if not dates:
        return [(fallback_date, cleaned)]

    events: list[tuple[str | None, str]] = []
    previous_end = 0
    for start, end, iso in dates:
        clause = cleaned[previous_end:end].strip()
        previous_end = end
        if len(re.sub(r"[^a-z]", "", clause.lower())) < 4:
            continue
        events.append((iso, clause))

    trailing = cleaned[previous_end:].strip()
    if trailing and re.search(r"[a-z]", trailing, re.I):
        if events:
            last_date, last_clause = events[-1]
            events[-1] = (last_date, f"{last_clause} {trailing}".strip())
        else:
            events = [(fallback_date, cleaned)]

    if not events:
        return [(fallback_date, cleaned)]

    lead_in = re.compile(r"^(?:and|but|then|so|later)\s+", re.I)
    cleaned_events = []
    for date_value, clause in events:
        clause = lead_in.sub("", clause).strip()
        clause = re.sub(r"\s+([.,;])", r"\1", clause)
        clause = re.sub(r"\s+$", "", clause).strip()
        cleaned_events.append((date_value, clause))
    return cleaned_events


def _matches_field(metadata: dict, text: str, field: str) -> bool:
    recorded = str(metadata.get("field") or "").strip()
    if recorded:
        return recorded.lower() == field.strip().lower()
    return field.strip().lower() in text.lower()


async def timeline_entries(
    bank: str | None = None, field: str | None = None, crop: str | None = None
) -> list[dict]:
    response = await get_client().alist_memories(bank_id=bank or bank_id(), limit=200)

    grouped: dict[tuple, dict] = {}
    for item in response.items:
        text = (item.text or "").strip()
        if not text:
            continue
        if field and not _matches_field(item.metadata or {}, text, field):
            continue
        fallback_date = _memory_date(item)
        carry: str | None = None
        for date_value, clause in _split_events(text, fallback_date):
            named = re.search(r"\b(treatment\s+[a-z0-9]+)\b", clause.lower())
            if named:
                carry = named.group(1)
            kind, label, treatment, status = _classify_event(clause, crop, carry)
            # Merge the same event recalled from several near-duplicate memories.
            key = (date_value, kind, "" if kind == "other" else label.lower())
            if key in grouped:
                grouped[key]["count"] += 1
                continue
            grouped[key] = {
                "date": date_value,
                "type": item.fact_type or "memory",
                "kind": kind,
                "label": label,
                "treatment": treatment,
                "status": status,
                "text": clause,
                "count": 1,
            }

    events = list(grouped.values())
    events.sort(
        key=lambda event: (event["date"] is None, event["date"] or "", event["label"])
    )
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
