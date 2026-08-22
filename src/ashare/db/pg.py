from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def database_url_from_env(cfg: dict[str, Any] | None = None) -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url and cfg:
        url = str(cfg.get("storage", {}).get("database_url", ""))
    if not url:
        url = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/ashare"
    return _normalize_db_url(url)


def admin_url(db_url: str) -> str:
    """Point at 'postgres' DB for CREATE DATABASE."""
    raw = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(raw)
    admin_parts = parsed._replace(path="/postgres")
    rebuilt = urlunparse(admin_parts)
    return rebuilt.replace("postgresql://", "postgresql+psycopg://", 1)


def db_name(db_url: str) -> str:
    raw = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    path = urlparse(raw).path.lstrip("/") or "ashare"
    return path.split("?")[0]


@lru_cache(maxsize=4)
def get_engine(db_url: str) -> Engine:
    return create_engine(db_url, pool_pre_ping=True, pool_size=5)


def ensure_database(db_url: str) -> None:
    name = db_name(db_url)
    eng = create_engine(admin_url(db_url), isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    eng.dispose()


def init_schema(db_url: str) -> None:
    ensure_database(db_url)
    base = Path(__file__).parent
    parts = [
        (base / "schema.sql").read_text(encoding="utf-8"),
        (base / "schema_research.sql").read_text(encoding="utf-8"),
        (base / "schema_news.sql").read_text(encoding="utf-8"),
    ]
    eng = get_engine(db_url)
    with eng.begin() as conn:
        for schema in parts:
            conn.execute(text(schema))


def ping_db(db_url: str) -> bool:
    try:
        eng = get_engine(db_url)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
