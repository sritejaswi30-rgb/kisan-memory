import hashlib
import logging
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field as PydanticField
from sqlalchemy.orm import Session

from backend import groq_agent, hindsight_client, seed
from backend.db import SessionLocal, get_db, init_db
from backend.models import Field, User

logger = logging.getLogger("kissanmemory")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

GENERIC_PHRASES = (
    "as an ai",
    "as a helpful",
    "kisanmemory",
    "the assistant",
    "in general",
    "generally speaking",
    "always consult",
    "consult a local",
    "recommend consulting",
    "best practice",
    "i recommend",
    "you should consider",
)


class ChatRequest(BaseModel):
    message: str = PydanticField(..., min_length=1)
    field_id: int | None = None
    farmer: str | None = PydanticField(default=None, min_length=1)
    field: str | None = PydanticField(default=None, min_length=1)


class MemoryUsed(BaseModel):
    type: str
    text: str
    date: str | None = None


class RetainedMemory(BaseModel):
    text: str
    date: str
    field: str


class ChatResponse(BaseModel):
    user_id: str | None = None
    field_id: str | None = None
    response: str
    memories_used: list[MemoryUsed]
    memory_count: int
    new_memories_stored: int
    retained_memories: list[RetainedMemory] = PydanticField(default_factory=list)
    duplicates_skipped: int = 0
    skipped_experiences: list[str] = PydanticField(default_factory=list)


class FieldOut(BaseModel):
    id: int
    user_id: str
    name: str
    crop: str
    planting_date: str | None = None
    created_at: datetime


class UserOut(BaseModel):
    id: str
    name: str
    preferred_language: str
    created_at: datetime
    bank_id: str
    fields: list[FieldOut] = PydanticField(default_factory=list)


class CreateFieldRequest(BaseModel):
    name: str = PydanticField(..., min_length=1)
    crop: str = ""
    planting_date: date | None = None


_RETAINED_SESSION: dict[str, set[str]] = defaultdict(set)
_RETAINED_SIGNATURES: dict[str, set[str]] = defaultdict(set)
_ENSURED_BANKS: set[str] = set()


def _experience_key(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"^farmer\s+[^:,]+,\s*[^:]+:\s*", "", lowered)
    lowered = re.sub(r"\s*\|\s*when:\s*\d{4}-\d{2}-\d{2}", " ", lowered)
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _experience_hash(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _experience_signature(content: str, field: str) -> str | None:
    key = _experience_key(content)
    if not key:
        return None
    treatment = re.search(r"treatment\s+[a-z0-9]+", key)
    if not treatment:
        return None
    day = datetime.now(timezone.utc).date().isoformat()
    return f"{day}|{field.strip().lower()}|{treatment.group(0)}"


def _remember(key: str, signature: str | None, bank: str | None = None) -> None:
    scope = bank or hindsight_client.bank_id()
    _RETAINED_SESSION[scope].add(key)
    if signature:
        _RETAINED_SIGNATURES[scope].add(signature)


async def is_duplicate_experience(
    content: str, field: str, bank: str | None = None
) -> bool:
    key = _experience_key(content)
    if not key:
        return True
    scope = bank or hindsight_client.bank_id()
    signature = _experience_signature(content, field)
    if key in _RETAINED_SESSION[scope]:
        return True
    if signature and signature in _RETAINED_SIGNATURES[scope]:
        return True

    try:
        recent = await hindsight_client.recent_memories(bank=scope)
    except Exception:
        logger.debug("recent memory lookup failed", exc_info=True)
        return False

    digest = _experience_hash(key)
    for memory in recent:
        metadata = memory["metadata"]
        if metadata.get("experience_hash") == digest:
            _remember(key, signature, scope)
            return True
        if signature and metadata.get("experience_sig") == signature:
            _remember(key, signature, scope)
            return True
        if memory["text"] and _experience_key(memory["text"]) == key:
            _remember(key, signature, scope)
            return True
    return False


def _is_new_farmer_experience(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 15:
        return False
    low = cleaned.lower()
    return not any(phrase in low for phrase in GENERIC_PHRASES)


def _with_context(text: str, farmer: str, field: str) -> str:
    low = text.lower()
    if farmer.lower() in low and field.lower() in low:
        return text
    return f"Farmer {farmer}, {field}: {text}"


def _require_user_id(x_user_id: str | None) -> int:
    if x_user_id is None or not x_user_id.strip():
        raise HTTPException(
            status_code=400,
            detail="X-User-ID header is required (for example X-User-ID: 1001).",
        )
    try:
        return int(x_user_id.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="X-User-ID must be a numeric user id.")


def _resolve_user(db: Session, x_user_id: str | None) -> User:
    user = db.get(User, _require_user_id(x_user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="Unknown user id.")
    return user


def _resolve_field(db: Session, user: User, field_id: int) -> Field:
    field = db.get(Field, field_id)
    if field is None or field.user_id != user.id:
        raise HTTPException(status_code=404, detail="Unknown field for this user.")
    return field


def _field_out(field: Field) -> FieldOut:
    return FieldOut(
        id=field.id,
        user_id=str(field.user_id),
        name=field.name,
        crop=field.crop,
        planting_date=field.planting_date.isoformat() if field.planting_date else None,
        created_at=field.created_at,
    )


async def _ensure_user_bank(bank: str) -> None:
    if bank in _ENSURED_BANKS:
        return
    await hindsight_client.ensure_bank(bank)
    _ENSURED_BANKS.add(bank)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
        session = SessionLocal()
        try:
            seed.ensure_demo_users(session)
        finally:
            session.close()
    except Exception:
        logger.exception("database initialization failed")
    try:
        await hindsight_client.ensure_bank()
        await seed.seed_hindsight_memories()
    except Exception:
        logger.exception("hindsight seeding failed")
    yield
    await hindsight_client.close()


app = FastAPI(title="KisanMemory", version="0.3.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "hindsight": await hindsight_client.hindsight_available(),
        "llm": await groq_agent.llm_available(),
    }


@app.get("/users/me", response_model=UserOut)
async def users_me(x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)) -> UserOut:
    user = _resolve_user(db, x_user_id)
    return UserOut(
        id=str(user.id),
        name=user.name,
        preferred_language=user.preferred_language,
        created_at=user.created_at,
        bank_id=hindsight_client.bank_for_user(user.id),
        fields=[_field_out(field) for field in sorted(user.fields, key=lambda item: item.id)],
    )


@app.get("/fields", response_model=list[FieldOut])
async def list_fields(x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)) -> list[FieldOut]:
    user = _resolve_user(db, x_user_id)
    return [_field_out(field) for field in sorted(user.fields, key=lambda item: item.id)]


@app.post("/fields", response_model=FieldOut, status_code=201)
async def create_field(
    payload: CreateFieldRequest,
    x_user_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> FieldOut:
    user = _resolve_user(db, x_user_id)
    field = Field(user_id=user.id, name=payload.name.strip(), crop=payload.crop.strip(), planting_date=payload.planting_date)
    db.add(field)
    db.commit()
    db.refresh(field)
    return _field_out(field)


@app.get("/timeline")
async def timeline(
    field_id: int | None = Query(default=None),
    x_user_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    user = _resolve_user(db, x_user_id)
    field_name: str | None = None
    if field_id is not None:
        field_name = _resolve_field(db, user, field_id).name
    try:
        return {
            "events": await hindsight_client.timeline_entries(
                bank=hindsight_client.bank_for_user(user.id), field=field_name
            )
        }
    except Exception:
        logger.exception("timeline lookup failed")
        raise HTTPException(
            status_code=502,
            detail="The field timeline is unavailable right now. Please try again.",
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_user_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ChatResponse:
    user_id: int | None = None
    field_id: int | None = None

    if request.field_id is None:
        if not (request.farmer and request.field):
            raise HTTPException(
                status_code=400,
                detail="Send field_id with an X-User-ID header, or farmer/field for legacy mode.",
            )
        farmer, field_name = request.farmer, request.field
        bank = hindsight_client.bank_id()
    else:
        user = _resolve_user(db, x_user_id)
        field = _resolve_field(db, user, request.field_id)
        user_id, field_id = user.id, field.id
        farmer, field_name = user.name, field.name
        bank = hindsight_client.bank_for_user(user.id)
        await _ensure_user_bank(bank)

    try:
        memories = await hindsight_client.recall_memories(farmer, field_name, request.message, bank=bank)
    except Exception:
        logger.exception("hindsight recall failed")
        raise HTTPException(
            status_code=502,
            detail="The field memory could not be reached right now. Please try again.",
        )

    try:
        result = await groq_agent.answer(farmer, field_name, request.message, memories)
    except Exception:
        logger.exception("groq reasoning failed")
        raise HTTPException(
            status_code=502,
            detail="The AI assistant is unavailable right now. Please try again.",
        )

    retained: list[RetainedMemory] = []
    skipped: list[str] = []
    today = datetime.now(timezone.utc).date().isoformat()
    for candidate in result["new_memory_candidates"]:
        if not _is_new_farmer_experience(candidate):
            continue
        content = _with_context(candidate, farmer, field_name)
        if await is_duplicate_experience(content, field_name, bank=bank):
            skipped.append(content)
            continue
        key = _experience_key(content)
        signature = _experience_signature(content, field_name)
        metadata: dict = {"experience_hash": _experience_hash(key), "field": field_name}
        if signature:
            metadata["experience_sig"] = signature
        if user_id is not None:
            metadata["user_id"] = str(user_id)
        if field_id is not None:
            metadata["field_id"] = str(field_id)
        if await hindsight_client.retain_memory(
            content,
            context=f"Farmer {farmer}, {field_name}",
            metadata=metadata,
            bank=bank,
        ):
            _remember(key, signature, bank)
            retained.append(RetainedMemory(text=content, date=today, field=field_name))

    return ChatResponse(
        user_id=str(user_id) if user_id is not None else None,
        field_id=str(field_id) if field_id is not None else None,
        response=result["answer"],
        memories_used=[MemoryUsed(**memory) for memory in memories],
        memory_count=len(memories),
        new_memories_stored=len(retained),
        retained_memories=retained,
        duplicates_skipped=len(skipped),
        skipped_experiences=skipped,
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
