import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

SQLITE_FALLBACK_URL = "sqlite:///./kissanmemory.db"


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLITE_FALLBACK_URL
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _build_engine():
    url = database_url()
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
    return create_engine(url, **kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Columns added after the first release; applied additively so existing rows
# (including the seeded demo farmers) are never dropped or rewritten.
UPGRADES: dict[str, list[tuple[str, str]]] = {
    "users": [
        ("email", "VARCHAR(255)"),
        ("password_hash", "VARCHAR(255)"),
        ("village", "VARCHAR(120)"),
        ("state", "VARCHAR(120)"),
        ("is_demo", "BOOLEAN DEFAULT FALSE"),
    ],
}


def _apply_upgrades() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in UPGRADES.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl_type in columns:
                if name in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))


def init_db() -> None:
    from backend import models  # noqa: F401  (registers tables on Base)

    Base.metadata.create_all(engine)
    _apply_upgrades()


def get_db():
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
