"""Тесты имён: display_override используется во всех текстовках."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll import events as events_bll
from bll import rsvp as rsvp_bll
from bll.publication import event_vm, person_name
from bll.timeparse import parse_event_command
from config import Config
from dal import repositories as repo
from dal.database import Database

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ)


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def test_display_override_used_in_lists(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        acc = repo.ensure_account(s, "vk", 100, display_name="Шурик")
        person = repo.get_or_create_person(s, display_name="Шурик")
        acc.person_id = person.id
        s.commit()

        assert person_name(s, person.id) == "Шурик"  # из ВК

        # админ переименовал
        person.display_override = "Александр"
        s.commit()
        assert person_name(s, person.id) == "Александр"

        # голос в событии → в списке переопределённое имя
        parsed = parse_event_command("/событие Кросс - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)
        rsvp_bll.cast_vote(s, cfg, "vk", 100, ev.id, "yes")
        vm = event_vm(s, cfg, ev)
        names = [e.name for e in vm.lists[0].entries]
        assert names == ["Александр"]

        # сброс: вернулось имя из ВК
        person.display_override = None
        s.commit()
        assert person_name(s, person.id) == "Шурик"
        s.commit()


def test_display_override_export_and_fees(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        acc = repo.ensure_account(s, "vk", 200, display_name="Наташа")
        person = repo.get_or_create_person(s, display_name="Наташа")
        acc.person_id = person.id
        person.display_override = "Натали"
        s.commit()
        from bll import fees as fees_bll
        fees_bll.ensure_monthly_accrual(s, cfg, person.id, "2026-09")
        text = fees_bll.debtors_text(s, cfg)
        assert "Натали" in text
        hist = fees_bll.history_text(s, cfg, person.id)
        assert "Натали" in hist
        s.commit()
