"""Тесты общих карточек беседы (chat_card): fan-out, счётчики, refresh."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll import events as events_bll
from bll import polls as polls_bll
from bll.publication import chat_event_vm, refresh_content
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


def test_event_chat_card_fanout(tmp_path):
    db = make_db(tmp_path)
    cfg = Config(card_chat_peer=2000000008)
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed = parse_event_command("/событие Кросс - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        counts = events_bll.publish(s, cfg, ev.id)
        s.commit()
    assert counts["chat"] == 1
    assert counts["dm"] == 0
    with db.session() as s:
        post = repo.get_chat_post(s, "event", ev.id)
        assert post is not None
        assert post.platform == "vk_chat" and post.chat_id == "2000000008"
        acc = repo.get_account_by_platform_id(s, "vk", 1)
        assert repo.get_post_for(s, "event", ev.id, "dm_card", account_id=acc.id) is None
        s.commit()


def test_event_chat_vm_counts(tmp_path):
    db = make_db(tmp_path)
    cfg = Config(card_chat_peer=2000000008)
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed = parse_event_command("/событие Кросс - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)
        from bll import rsvp as rsvp_bll
        rsvp_bll.cast_vote(s, cfg, "vk", 100, ev.id, "yes")
        rsvp_bll.cast_vote(s, cfg, "vk", 101, ev.id, "yes")
        vm = chat_event_vm(s, cfg, ev)
        assert "Придут (2)" in vm.text
        labels = [b.label for row in vm.buttons for b in row]
        assert any("Пойду (2)" in label for label in labels)
        s.commit()


def test_poll_chat_card_and_refresh(tmp_path):
    db = make_db(tmp_path)
    cfg = Config(card_chat_peer=2000000008)
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed, _ = polls_bll.parse_poll_command("/опрос В\nа\nб", cfg, NOW)
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        counts = polls_bll.publish(s, cfg, poll.id)
        assert counts["chat"] == 1
        polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll.id, 0)
        refresh_content(s, cfg, "poll", poll.id)
        jobs = repo.fetch_pending_jobs(s, limit=50)
        assert any(j.platform == "vk_chat" for j in jobs)
        vm = polls_bll.chat_poll_vm(s, cfg, poll.id)
        labels = [b.label for row in vm.buttons for b in row]
        assert any("(1)" in label for label in labels)
        s.commit()


def test_tg_group_card_fanout(tmp_path):
    db = make_db(tmp_path)
    cfg = Config(tg_card_chat_id=-1001234567890)
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed = parse_event_command("/событие Кросс - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        counts = events_bll.publish(s, cfg, ev.id)
        assert counts["tg_chat"] == 1
        # VK-карточки идут как обычно (CARD_CHAT_PEER выключен), TG-карточки в ЛС — нет
        assert counts["dm"] == 1
        post = repo.get_chat_post(s, "event", ev.id, "tg")
        assert post is not None
        assert post.platform == "tg" and post.chat_id == "-1001234567890"
        # опрос — та же схема
        parsed, _ = polls_bll.parse_poll_command("/опрос В\nа\nб", cfg, NOW)
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        counts2 = polls_bll.publish(s, cfg, poll.id)
        assert counts2["tg_chat"] == 1
        assert repo.get_chat_post(s, "poll", poll.id, "tg") is not None
        s.commit()
