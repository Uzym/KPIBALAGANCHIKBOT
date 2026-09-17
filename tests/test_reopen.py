"""Тесты переоткрытия записи/опроса и однократного авто-закрытия."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll import events as events_bll
from bll import polls as polls_bll
from bll import rsvp as rsvp_bll
from bll.publication import vm_for_post
from bll.timeparse import parse_event_command
from config import Config
from dal import repositories as repo
from dal.database import Database, now_utc, to_db

TZ = ZoneInfo("Europe/Moscow")


def _fmt(days: int) -> str:
    return (dt.datetime.now(TZ) + dt.timedelta(days=days)).strftime("%d.%m %H:%M")


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def setup_event(tmp_path, starts: str):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed = parse_event_command(f"/событие Тренировка - {starts}", TZ,
                                     dt.datetime.now(TZ))
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)
        s.commit()
        return db, cfg, ev.id


def test_event_close_reopen_restores_voting(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path, _fmt(+2))
    with db.session() as s:
        rsvp_bll.cast_vote(s, cfg, "vk", 1, ev_id, "yes")
        events_bll.close(s, cfg, ev_id)
        ev = repo.get_event(s, ev_id)
        assert ev.status == "closed"
        vm = vm_for_post(s, cfg, ev, "dm_card")
        assert vm.buttons == []  # кнопки сняты
        assert rsvp_bll.cast_vote(s, cfg, "vk", 1, ev_id, "no") == "closed"
        # переоткрытие
        result = events_bll.reopen(s, cfg, ev_id)
        assert result and "снова открыта" in result
        ev = repo.get_event(s, ev_id)
        assert ev.status == "active" and ev.closed_at is None
        vm = vm_for_post(s, cfg, ev, "dm_card")
        assert vm.buttons  # кнопки вернулись
        assert rsvp_bll.cast_vote(s, cfg, "vk", 1, ev_id, "no") == "ok_no"
        s.commit()


def test_reopen_denied_after_start(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path, _fmt(+2))
    with db.session() as s:
        # «событие уже началось»: выставляем время в прошлое напрямую
        # (парсер дат без года уводит прошлое в следующий год)
        repo.update_event(s, ev_id, {
            "starts_at": to_db(now_utc() - dt.timedelta(hours=2)),
            "ends_at": to_db(now_utc() - dt.timedelta(hours=1)),
        })
        events_bll.close(s, cfg, ev_id)
        result = events_bll.reopen(s, cfg, ev_id)
        assert result and "уже началось" in result
        assert repo.get_event(s, ev_id).status == "closed"
        s.commit()


def test_auto_close_flag_prevents_reclose_loop(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path, _fmt(+2))
    with db.session() as s:
        events_bll.close(s, cfg, ev_id, auto=True)
        ev = repo.get_event(s, ev_id)
        assert ev.auto_closed is True
        events_bll.reopen(s, cfg, ev_id)
        ev = repo.get_event(s, ev_id)
        assert ev.status == "active"
        assert ev.auto_closed is True  # джоба авто-закрытия пропустит (один раз сработала)
        s.commit()


def test_poll_reopen_before_deadline(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        parsed, _ = polls_bll.parse_poll_command("/создать опрос В; а; б", cfg, dt.datetime.now(TZ))
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        polls_bll.publish(s, cfg, poll.id)
        repo.update_poll(s, poll.id, {"closes_at": to_db(now_utc() + dt.timedelta(days=2))})
        polls_bll.close(s, cfg, poll.id)
        result = polls_bll.reopen(s, cfg, poll.id)
        assert result and "снова открыт" in result
        assert repo.get_poll(s, poll.id).status == "active"
        assert polls_bll.cast_poll_vote(s, cfg, "vk", 1, poll.id, 0) == "ok"
        s.commit()


def test_poll_reopen_denied_after_deadline(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        parsed, _ = polls_bll.parse_poll_command("/создать опрос В; а; б", cfg, dt.datetime.now(TZ))
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        polls_bll.publish(s, cfg, poll.id)
        repo.update_poll(s, poll.id, {"closes_at": to_db(now_utc() - dt.timedelta(days=1))})
        polls_bll.close(s, cfg, poll.id, auto=True)
        result = polls_bll.reopen(s, cfg, poll.id)
        assert result and "уже прошёл" in result
        assert repo.get_poll(s, poll.id).status == "closed"
        assert repo.get_poll(s, poll.id).auto_closed is True
        s.commit()
