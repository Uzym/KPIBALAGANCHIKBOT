"""Регрессия: возврат к ранее бывшему состоянию должен создавать новое edit-задание."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll import events as events_bll
from bll import rsvp as rsvp_bll
from bll.timeparse import parse_event_command
from config import Config
from dal import repositories as repo
from dal.database import Database
from dal.models import OutboxJob
from sqlalchemy import select

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ)


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def _pending_edits(s, post_id):
    return list(s.scalars(select(OutboxJob).where(
        OutboxJob.post_id == post_id, OutboxJob.op == "edit",
        OutboxJob.status.in_(["pending", "sending"]),
    )))


def test_toggle_back_creates_new_edit(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed = parse_event_command("/событие Т - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)
        post = repo.get_post_for(s, "event", ev.id, "dm_card", account_id=admin.id)
        repo.update_post(s, post.id, message_id=100, status="ok")
        s.commit()

    # А → Б → снова А
    with db.session() as s:
        rsvp_bll.cast_vote(s, cfg, "vk", 1, ev.id, "yes")
        s.commit()
    with db.session() as s:
        j1 = _pending_edits(s, post.id)
        assert j1, "первый голос должен дать edit"
        repo.finish_job(s, j1[0].id)  # «доставлено»
        s.commit()
    with db.session() as s:
        rsvp_bll.cast_vote(s, cfg, "vk", 1, ev.id, "no")
        j2 = _pending_edits(s, post.id)
        assert j2, "второй голос должен дать edit"
        repo.finish_job(s, j2[0].id)
        s.commit()
    with db.session() as s:
        rsvp_bll.cast_vote(s, cfg, "vk", 1, ev.id, "yes")  # возврат к первому состоянию
        j3 = _pending_edits(s, post.id)
        assert j3, "возврат к ранее бывшему состоянию должен дать НОВЫЙ edit (регрессия)"
        s.commit()
