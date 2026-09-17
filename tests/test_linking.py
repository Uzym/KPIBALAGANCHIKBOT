"""Тесты линковки аккаунтов и RSVP на реальной SQLite (in-memory)."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll import events as events_bll
from bll import linking as linking_bll
from bll import rsvp as rsvp_bll
from bll.timeparse import parse_event_command
from config import Config
from dal import repositories as repo
from dal.database import Database

TZ = ZoneInfo("Europe/Moscow")


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def test_rsvp_flow(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        parsed = parse_event_command("/событие Тренировка - 15.09 19:00", TZ,
                                     dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ))
        ev = events_bll.create_draft(s, Config(), admin.id, parsed)
        events_bll.publish(s, Config(), ev.id)

        assert rsvp_bll.cast_vote(s, Config(), "vk", 100, ev.id, "yes") == "ok"
        assert rsvp_bll.cast_vote(s, Config(), "tg", 200, ev.id, "yes") == "ok"
        # смена выбора
        assert rsvp_bll.cast_vote(s, Config(), "vk", 100, ev.id, "no") == "ok_no"
        v = repo.get_vote(s, ev.id, repo.get_account_by_platform_id(s, "vk", 100).id)
        assert v.prev_answer == "yes" and v.changes_count == 1
        # повтор того же ответа — идемпотентно
        assert rsvp_bll.cast_vote(s, Config(), "vk", 100, ev.id, "no") == "same"


def test_linking_by_nick(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        vk_acc = repo.ensure_account(s, "vk", 100, display_name="Аня")
        vk_acc.tg_nick = "anny"
        # tg-аккаунт появляется позже
        repo.ensure_account(s, "tg", 200, display_name="anny", username="@Anny")
        result = linking_bll.try_link(s, cfg, vk_acc)
        assert result == "linked"
        tg_acc = repo.get_account_by_platform_id(s, "tg", 200)
        assert tg_acc.person_id == vk_acc.person_id and vk_acc.person_id is not None


def test_linking_merges_votes(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        parsed = parse_event_command("/событие Тренировка - 15.09 19:00", TZ,
                                     dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ))
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)

        rsvp_bll.cast_vote(s, cfg, "vk", 100, ev.id, "yes")
        rsvp_bll.cast_vote(s, cfg, "tg", 200, ev.id, "no")

        vk_acc = repo.get_account_by_platform_id(s, "vk", 100)
        tg_acc = repo.get_account_by_platform_id(s, "tg", 200)
        tg_acc.username = "anny"
        vk_acc.tg_nick = "anny"
        linking_bll.try_link(s, cfg, vk_acc)
        assert tg_acc.person_id == vk_acc.person_id

        # сводка: один человек, актуальный голос «нет» (TG позже)
        from bll.publication import event_vm

        vm = event_vm(s, cfg, repo.get_event(s, ev.id))
        yes_current = [e for e in vm.lists[0].entries if not e.struck_at]
        no_current = [e for e in vm.lists[2].entries if not e.struck_at]
        assert len(yes_current) == 0
        assert len(no_current) == 1
        assert no_current[0].tag is None  # слинкован — без метки платформы
