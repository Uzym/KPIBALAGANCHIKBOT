"""Тесты механизма миграций: применение, трекинг, идемпотентность, доделка после сбоя."""
import pytest
from sqlalchemy import text

from dal import migrations as mig
from dal.database import Database


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def _columns(db, table):
    with db.engine.connect() as c:
        return [r[1] for r in c.execute(text(f"PRAGMA table_info({table})"))]


def _set_version(db, version):
    with db.engine.begin() as c:
        c.execute(text("DELETE FROM schema_version"))
        c.execute(text("INSERT INTO schema_version (id, version) VALUES (1, :v)"),
                  {"v": version})


def _add_col(col_name):
    def fn(conn):
        mig.add_column_if_missing(
            conn, "persons", col_name,
            f"ALTER TABLE persons ADD COLUMN {col_name} TEXT",
        )
    return fn


def test_fresh_db_stamps_current(monkeypatch, tmp_path):
    db = make_db(tmp_path)
    monkeypatch.setattr(mig, "CURRENT_VERSION", 5)
    assert mig.apply_migrations(db.engine) == []
    with db.engine.connect() as c:
        v = c.execute(text("SELECT version FROM schema_version WHERE id=1")).scalar()
    assert v == 5


def test_migration_applied_and_tracked(monkeypatch, tmp_path):
    db = make_db(tmp_path)
    _set_version(db, 1)
    monkeypatch.setattr(mig, "MIGRATIONS", [(2, "add extra", _add_col("extra_note"))])
    monkeypatch.setattr(mig, "CURRENT_VERSION", 2)

    assert mig.apply_migrations(db.engine) == ["add extra"]
    assert "extra_note" in _columns(db, "persons")
    with db.engine.connect() as c:
        v = c.execute(text("SELECT version FROM schema_version WHERE id=1")).scalar()
    assert v == 2
    # повторный запуск — no-op
    assert mig.apply_migrations(db.engine) == []


def test_v2_migration_idempotent_on_fresh_schema(tmp_path):
    """Реальная миграция v2 на «старой» БД: колонки уже есть (create_all) — no-op, версия растёт."""
    db = make_db(tmp_path)
    _set_version(db, 1)  # имитируем БД до релиза v2
    assert mig.apply_migrations(db.engine) == ["auto_closed (переоткрытие записи)"]
    assert "auto_closed" in _columns(db, "events")
    assert "auto_closed" in _columns(db, "polls")
    with db.engine.connect() as c:
        v = c.execute(text("SELECT version FROM schema_version WHERE id=1")).scalar()
    assert v == 2
    # повторный запуск — no-op
    assert mig.apply_migrations(db.engine) == []


def test_failed_migration_retries_cleanly(monkeypatch, tmp_path):
    """Сбой внутри миграции: версия не повышается, повторный запуск доделывает."""
    db = make_db(tmp_path)
    _set_version(db, 1)

    def broken(conn):
        mig.add_column_if_missing(
            conn, "persons", "partial_col",
            "ALTER TABLE persons ADD COLUMN partial_col TEXT",
        )
        raise RuntimeError("boom")

    monkeypatch.setattr(mig, "MIGRATIONS", [(2, "broken", broken)])
    monkeypatch.setattr(mig, "CURRENT_VERSION", 2)

    with pytest.raises(RuntimeError):
        mig.apply_migrations(db.engine)
    with db.engine.connect() as c:
        v = c.execute(text("SELECT version FROM schema_version WHERE id=1")).scalar()
    assert v == 1  # версия не повышена

    # «починили»: идемпотентный хелпер переживает уже добавленную колонку
    def fixed(conn):
        mig.add_column_if_missing(
            conn, "persons", "partial_col",
            "ALTER TABLE persons ADD COLUMN partial_col TEXT",
        )
        mig.add_column_if_missing(
            conn, "persons", "extra_note",
            "ALTER TABLE persons ADD COLUMN extra_note TEXT",
        )

    monkeypatch.setattr(mig, "MIGRATIONS", [(2, "fixed", fixed)])
    assert mig.apply_migrations(db.engine) == ["fixed"]
    cols = _columns(db, "persons")
    assert "partial_col" in cols and "extra_note" in cols
    with db.engine.connect() as c:
        v = c.execute(text("SELECT version FROM schema_version WHERE id=1")).scalar()
    assert v == 2
