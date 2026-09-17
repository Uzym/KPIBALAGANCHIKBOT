"""DAL: движок БД и сессии.

Время в БД хранится как naive-UTC; в доменном коде — aware (UTC или таймзона клуба).
"""
from __future__ import annotations

import datetime as dt
import pathlib

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

UTC = dt.timezone.utc


def now_utc() -> dt.datetime:
    """Naive-UTC «сейчас» (для записи в БД)."""
    return dt.datetime.now(UTC).replace(tzinfo=None)


def to_db(d: dt.datetime) -> dt.datetime:
    if d.tzinfo is None:
        return d
    return d.astimezone(UTC).replace(tzinfo=None)


def from_db(d: dt.datetime) -> dt.datetime:
    return d.replace(tzinfo=UTC)


class Database:
    def __init__(self, path: str):
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
        self.engine = create_engine(url, future=True)
        event.listen(self.engine, "connect", self._set_pragmas)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)

    @staticmethod
    def _set_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.close()

    def create_all(self) -> None:
        from . import models  # noqa: F401
        from sqlalchemy.orm import DeclarativeBase
        from .models import Base
        Base.metadata.create_all(self.engine)

    def session(self):
        return self.session_factory()
