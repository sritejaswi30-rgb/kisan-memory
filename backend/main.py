import hashlib
import logging
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field as PydanticField
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import groq_agent, hindsight_client, seed
from backend.auth import (
    SESSION_COOKIE,
    _token_hash,
    clear_session_cookie,
    create_session,
    get_current_user,
    hash_password,
    optional_user,
    session_user,
    set_session_cookie,
    verify_password,
)
from backend.db import SessionLocal, get_db, init_db
from backend.models import Conversation, Field, Message, User, UserSession

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


class RegisterRequest(BaseModel):
    name: str = PydanticField(..., min_length=2, max_length=120)
    email: str = PydanticField(..., min_length=3, max_length=255)
    password: str = PydanticField(..., min_length=8, max_length=128)
    village: str | None = PydanticField(default=None, max_length=120)
    state: str | None = PydanticField(default=None, max_length=120)
    preferred_language: str = PydanticField(default="English", max_length=40)


class LoginRequest(BaseModel):
    email: str = PydanticField(..., min_length=3, max_length=255)
    password: str = PydanticField(..., min_length=1, max_length=128)


class ChatRequest(BaseModel):
    message: str = PydanticField(..., min_length=1)
    field_id: int | None = None
    farmer: str | None = PydanticField(default=None, min_length=1)
    field: str | None = PydanticField(default=None, min_length=1)
    language: str | None = PydanticField(default=None, max_length=40)


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
    conversation_id: int | None = None
    message_id: int | None = None
    response: str
    memories_used: list[MemoryUsed]
    memory_count: int
    memories_used_count: int = 0
    memory_facts_used: list[str] = PydanticField(default_factory=list)
    memory_unavailable: bool = False
    memory_saved: bool = False
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
    email: str | None = None
    village: str | None = None
    state: str | None = None
    preferred_language: str
    created_at: datetime
    bank_id: str
    is_demo: bool = False
    fields: list[FieldOut] = PydanticField(default_factory=list)


class CreateFieldRequest(BaseModel):
    name: str = PydanticField(..., min_length=1)
    crop: str = ""
    planting_date: date | None = None
    village: str | None = None
    state: str | None = None


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    field_id: int
    role: str
    message: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    field_id: int
    field_name: str = ""
    created_at: datetime
    message_count: int = 0


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


def _normalize_fact(text: str) -> str:
    lowered = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", lowered).strip()


def _count_used_memories(recalled: list[dict], reported: list[str]) -> int:
    """Memories the model actually drew on, matched back to what we retrieved.

    Not hardcoded: it comes from the model's `memory_facts_used`, which is
    produced from the memories we put in its reasoning context.
    """
    if not recalled:
        return 0
    reported_norm = sorted({fact for fact in map(_normalize_fact, reported) if fact})
    if not reported_norm:
        return len(recalled)

    used: set[int] = set()
    for index, memory in enumerate(recalled):
        key = _normalize_fact(memory.get("text"))
        if not key:
            continue
        if any(fact == key or fact in key or key in fact for fact in reported_norm):
            used.add(index)
    if used:
        return len(used)
    return min(len(reported_norm), len(recalled))


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


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        name=user.name,
        email=user.email,
        village=user.village,
        state=user.state,
        preferred_language=user.preferred_language,
        created_at=user.created_at,
        bank_id=hindsight_client.bank_for_user(user.id),
        is_demo=bool(user.is_demo),
        fields=[_field_out(field) for field in sorted(user.fields, key=lambda item: item.id)],
    )


async def _ensure_user_bank(bank: str) -> None:
    if bank in _ENSURED_BANKS:
        return
    await hindsight_client.ensure_bank(bank)
    _ENSURED_BANKS.add(bank)


def _get_or_create_conversation(db: Session, user_id: int, field_id: int) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.field_id == field_id)
        .order_by(Conversation.id.desc())
    )
    if conversation is None:
        conversation = Conversation(user_id=user_id, field_id=field_id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    return conversation


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


app = FastAPI(title="KisanMemory", version="0.4.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "hindsight": await hindsight_client.hindsight_available(),
        "llm": await groq_agent.llm_available(),
    }


@app.post("/auth/register", response_model=UserOut, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserOut:
    email = payload.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(
        name=payload.name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        village=(payload.village or "").strip() or None,
        state=(payload.state or "").strip() or None,
        preferred_language=payload.preferred_language.strip() or "English",
        is_demo=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_session(db, user.id)
    set_session_cookie(response, request, token)
    logger.info("registered user id=%s", user.id)
    return _user_out(user)


@app.post("/auth/login", response_model=UserOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserOut:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.password_hash:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    token = create_session(db, user.id)
    set_session_cookie(response, request, token)
    return _user_out(user)


@app.post("/auth/logout", status_code=200)
async def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        row = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
        if row is not None:
            db.delete(row)
            db.commit()
    clear_session_cookie(response)
    return {"status": "signed_out"}


@app.get("/auth/me", response_model=UserOut)
async def me(request: Request, db: Session = Depends(get_db)) -> UserOut:
    user = session_user(db, request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return _user_out(user)


@app.get("/users/me", response_model=UserOut)
async def users_me(
    user: User = Depends(get_current_user),
) -> UserOut:
    return _user_out(user)


@app.get("/fields", response_model=list[FieldOut])
async def list_fields(user: User = Depends(get_current_user)) -> list[FieldOut]:
    return [_field_out(field) for field in sorted(user.fields, key=lambda item: item.id)]


@app.post("/fields", response_model=FieldOut, status_code=201)
async def create_field(
    payload: CreateFieldRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FieldOut:
    field = Field(
        user_id=user.id,
        name=payload.name.strip(),
        crop=payload.crop.strip(),
        planting_date=payload.planting_date,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return _field_out(field)


@app.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    field_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationOut]:
    stmt = select(Conversation).where(Conversation.user_id == user.id)
    if field_id is not None:
        stmt = stmt.where(Conversation.field_id == field_id)
    conversations = db.scalars(stmt.order_by(Conversation.id.desc())).all()
    field_names = {field.id: field.name for field in user.fields}
    out: list[ConversationOut] = []
    for conversation in conversations:
        message_count = len(
            db.scalars(
                select(Message).where(Message.conversation_id == conversation.id)
            ).all()
        )
        out.append(
            ConversationOut(
                id=conversation.id,
                field_id=conversation.field_id,
                field_name=field_names.get(conversation.field_id, ""),
                created_at=conversation.created_at,
                message_count=message_count,
            )
        )
    return out


@app.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def conversation_messages(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Unknown conversation.")
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
    ).all()
    return [
        MessageOut(
            id=message.id,
            conversation_id=message.conversation_id,
            field_id=message.field_id,
            role=message.role,
            message=message.message,
            created_at=message.created_at,
        )
        for message in messages
    ]


@app.get("/timeline")
async def timeline(
    field_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    field_name: str | None = None
    crop: str | None = None
    if field_id is not None:
        field = _resolve_field(db, user, field_id)
        field_name, crop = field.name, field.crop
    try:
        return {
            "events": await hindsight_client.timeline_entries(
                bank=hindsight_client.bank_for_user(user.id),
                field=field_name,
                crop=crop,
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
    request_body: ChatRequest,
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    user_id: int | None = None
    field_id: int | None = None
    crop: str | None = None
    conversation: Conversation | None = None

    if request_body.field_id is None:
        if not (request_body.farmer and request_body.field):
            raise HTTPException(
                status_code=400,
                detail="Sign in and select a field, or send farmer/field for legacy demo mode.",
            )
        farmer, field_name = request_body.farmer, request_body.field
        bank = hindsight_client.bank_id()
    else:
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Sign in to chat about your own fields.",
            )
        field = _resolve_field(db, user, request_body.field_id)
        user_id, field_id = user.id, field.id
        farmer, field_name, crop = user.name, field.name, field.crop
        bank = hindsight_client.bank_for_user(user.id)
        try:
            await _ensure_user_bank(bank)
        except Exception:
            logger.warning("could not ensure user bank %s; continuing", bank, exc_info=True)
        conversation = _get_or_create_conversation(db, user.id, field.id)
        db.add(
            Message(
                conversation_id=conversation.id,
                user_id=user.id,
                field_id=field.id,
                role="user",
                message=request_body.message,
            )
        )
        db.commit()

    # A first-time user has an empty bank and Hindsight may also be briefly
    # unavailable. Neither is an error: recall degrades to an empty memory
    # context so the LLM still answers from the current question.
    memories_unavailable = False
    try:
        memories = await hindsight_client.recall_memories(
            farmer, field_name, request_body.message, bank=bank
        )
    except Exception:
        logger.warning("hindsight recall failed; answering without memories", exc_info=True)
        memories = []
        memories_unavailable = True

    try:
        result = await groq_agent.answer(
            farmer,
            field_name,
            request_body.message,
            memories,
            crop=crop,
            language=request_body.language,
        )
    except Exception:
        logger.exception("llm reasoning failed")
        raise HTTPException(
            status_code=502,
            detail="AI service is temporarily unavailable. Please try again.",
        )

    assistant_message_id: int | None = None
    if conversation is not None:
        assistant_message = Message(
            conversation_id=conversation.id,
            user_id=user.id,
            field_id=field.id,
            role="assistant",
            message=result["answer"],
        )
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)
        assistant_message_id = assistant_message.id

    retained: list[RetainedMemory] = []
    skipped: list[str] = []
    today = datetime.now(timezone.utc).date().isoformat()
    try:
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
    except Exception:
        # The answer is already stored; a retention failure must not fail
        # the request. It is retried naturally on the next useful message.
        logger.warning("hindsight retention failed; answer already saved", exc_info=True)

    return ChatResponse(
        user_id=str(user_id) if user_id is not None else None,
        field_id=str(field_id) if field_id is not None else None,
        conversation_id=conversation.id if conversation is not None else None,
        message_id=assistant_message_id,
        response=result["answer"],
        memories_used=[MemoryUsed(**memory) for memory in memories],
        memory_count=len(memories),
        memories_used_count=_count_used_memories(
            memories, result.get("memory_facts_used") or []
        ),
        memory_facts_used=result.get("memory_facts_used") or [],
        memory_unavailable=memories_unavailable,
        memory_saved=bool(retained),
        new_memories_stored=len(retained),
        retained_memories=retained,
        duplicates_skipped=len(skipped),
        skipped_experiences=skipped,
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
