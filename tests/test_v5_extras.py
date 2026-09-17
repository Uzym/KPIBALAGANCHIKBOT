"""Тесты v5-доделок: дедуп нажатий и медиа в уведомлениях объявлений."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

from api.vk_handlers import _dedup_ok
from bll import announcements as ann_bll
from bll import events as events_bll
from bll.contracts import MediaRef
from bll.timeparse import parse_event_command
from config import Config
from dal import repositories as repo
from dal.database import Database

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ)


def test_dedup_window():
    key = ("u", "poll", 12, "0")
    assert _dedup_ok(key) is True
    assert _dedup_ok(key) is False          # повтор в окне — отбрасываем
    assert _dedup_ok(("u", "poll", 12, "1")) is True   # другой вариант — можно
    assert _dedup_ok(("u2", "poll", 12, "0")) is True


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def test_announcement_media_in_notice(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed = parse_event_command("/событие Тренировка - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)
        media = [MediaRef(kind="photo", url="https://example.com/p.jpg")]
        ann_bll.publish_for_content(s, cfg, "event", ev.id, "Смотри фото", media=media)
        jobs = repo.fetch_pending_jobs(s, limit=50)
        notice_jobs = [j for j in jobs if json.loads(j.view_model).get("kind") == "announcement"]
        assert notice_jobs
        vm = json.loads(notice_jobs[0].view_model)
        assert vm["media"] and vm["media"][0]["kind"] == "photo"
        # запись объявления хранит медиа в JSON
        anns = repo.announcements_for(s, "event", ev.id)
        assert anns and anns[0].media and "example.com" in anns[0].media
