from datetime import date, datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    village: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(40), nullable=False, default="Telugu")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    fields: Mapped[list["Field"]] = relationship(
        "Field", back_populates="owner", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """Server-side login session; only the SHA-256 of the cookie token is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Field(Base):
    __tablename__ = "fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    crop: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    planting_date: Mapped[date | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    owner: Mapped[User] = relationship("User", back_populates="fields")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
