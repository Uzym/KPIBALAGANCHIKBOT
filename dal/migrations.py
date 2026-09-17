"""DAL: последовательные миграции схемы БД.

Как выпускать изменения схемы (правило релиза):

1. Измени models.py (новые таблицы/колонки) — create_all покроет свежие БД.
2. Напиши функцию-миграцию и добавь в MIGRATIONS с номером CURRENT_VERSION+1.
3. Подними CURRENT_VERSION.

ВАЖНО: операторы миграций обязаны быть **идемпотентными** (SQLite через
pysqlite неявно коммитит DDL — откат транзакции не гарантирован). Используй
хелперы add_column_if_missing / create_index_if_missing — тогда повторный
запуск после частичного сбоя безопасно доделает недостающее. Версия
повышается только после успешного применения всей миграции.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

Migration = Callable[[Connection], None]

# (версия, имя, функция) — только ДОБАВЛЯЮЩИЕ идемпотентные изменения
def _m2_auto_closed(conn: Connection) -> None:
    add_column_if_missing(
        conn, "events", "auto_closed",
        "ALTER TABLE events ADD COLUMN auto_closed BOOLEAN NOT NULL DEFAULT 0",
    )
    add_column_if_missing(
        conn, "polls", "auto_closed",
        "ALTER TABLE polls ADD COLUMN auto_closed BOOLEAN NOT NULL DEFAULT 0",
    )


MIGRATIONS: list[tuple[int, str, Migration]] = [
    (2, "auto_closed (переоткрытие записи)", _m2_auto_closed),
]

CURRENT_VERSION = 2


def add_column_if_missing(conn: Connection, table: str, column: str, ddl: str) -> None:
    cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
    if column not in cols:
        conn.execute(text(ddl))


def create_index_if_missing(conn: Connection, name: str, ddl: str) -> None:
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"), {"n": name}
    ).fetchall()
    if not rows:
        conn.execute(text(ddl))


def apply_migrations(engine: Engine) -> list[str]:
    """Применяет недостающие миграции. Возвращает имена применённых.

    Свежая БД: create_all уже создал актуальную схему — фиксируем CURRENT_VERSION
    без применения. Существующая: применяем по порядку всё > текущей версии.
    """
    applied: list[str] = []
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "id INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
        ))
        row = conn.execute(
            text("SELECT version FROM schema_version WHERE id = 1")
        ).fetchone()
        current = row[0] if row else None
        if current is None:
            # БД без отметки версии: либо свежая (схема уже актуальна),
            # либо создана до механизма миграций — фиксируем текущую.
            conn.execute(
                text("INSERT INTO schema_version (id, version) VALUES (1, :v)"),
                {"v": CURRENT_VERSION},
            )
            return applied

    for version, name, fn in MIGRATIONS:
        if version <= current:
            continue
        with engine.begin() as conn:
            fn(conn)
            conn.execute(
                text("UPDATE schema_version SET version = :v WHERE id = 1"),
                {"v": version},
            )
        applied.append(name)
    return applied
