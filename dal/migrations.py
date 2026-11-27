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


def _m3_v6(conn: Connection) -> None:
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS fee_entries ("
        "id INTEGER PRIMARY KEY, "
        "person_id INTEGER NOT NULL REFERENCES persons(id), "
        "kind VARCHAR(8) NOT NULL, "
        "amount_rub INTEGER NOT NULL, "
        "month VARCHAR(7), "
        "label VARCHAR(300) NOT NULL DEFAULT '', "
        "created_by INTEGER REFERENCES accounts(id), "
        "created_at DATETIME NOT NULL)"
    ))
    add_column_if_missing(
        conn, "persons", "display_override",
        "ALTER TABLE persons ADD COLUMN display_override VARCHAR(200)",
    )
    add_column_if_missing(
        conn, "persons", "fee_alerted",
        "ALTER TABLE persons ADD COLUMN fee_alerted BOOLEAN NOT NULL DEFAULT 0",
    )
    add_column_if_missing(
        conn, "subscriptions", "banned",
        "ALTER TABLE subscriptions ADD COLUMN banned BOOLEAN NOT NULL DEFAULT 0",
    )


def _m4_meta(conn: Connection) -> None:
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS app_meta ("
        "key VARCHAR(64) PRIMARY KEY, value TEXT NOT NULL DEFAULT '')"
    ))


def _m5_panel(conn: Connection) -> None:
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS panel_sessions ("
        "id INTEGER PRIMARY KEY, "
        "token_hash VARCHAR(64), "
        "label VARCHAR(200) NOT NULL DEFAULT '', "
        "ip VARCHAR(64) NOT NULL DEFAULT '', "
        "ua VARCHAR(300) NOT NULL DEFAULT '', "
        "status VARCHAR(16) NOT NULL DEFAULT 'pending', "
        "created_at DATETIME NOT NULL, "
        "approved_by BIGINT, "
        "approved_at DATETIME)"
    ))


def _m6_dm_messages(conn: Connection) -> None:
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS dm_messages ("
        "id INTEGER PRIMARY KEY, "
        "platform VARCHAR(8) NOT NULL, "
        "chat_id VARCHAR(32) NOT NULL, "
        "direction VARCHAR(4) NOT NULL, "  # in | out
        "text TEXT NOT NULL DEFAULT '', "
        "media TEXT, "
        "created_at DATETIME NOT NULL)"
    ))
    create_index_if_missing(
        conn, "idx_dm_messages_chat",
        "CREATE INDEX idx_dm_messages_chat ON dm_messages (platform, chat_id, id)",
    )


def _m7_web_sessions(conn: Connection) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS web_sessions (
            id INTEGER PRIMARY KEY,
            login_token VARCHAR(64) UNIQUE NOT NULL,
            session_key VARCHAR(64) UNIQUE,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            login_used BOOLEAN DEFAULT 0
        )
    """))


MIGRATIONS: list[tuple[int, str, Migration]] = [
    (2, "auto_closed (переоткрытие записи)", _m2_auto_closed),
    (3, "v6: оплата/имена/заявки TG (fee_entries, display_override, fee_alerted, banned)", _m3_v6),
    (4, "app_meta (мемоизация админов)", _m4_meta),
    (5, "panel_sessions (вход в админ-панель по одобрению)", _m5_panel),
    (6, "dm_messages (переписка с админом в панели)", _m6_dm_messages),
    (7, "web_sessions (вход в веб-панель по ссылке из бота)", _m7_web_sessions),
]

CURRENT_VERSION = 7


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
