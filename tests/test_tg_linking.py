"""Тесты этапов 6–7: TG-карточки при линковке, уведомления TG, текстовые выборы."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll import events as events_bll
from bll import linking as linking_bll
from bll import polls as polls_bll
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


def setup_linked(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed = parse_event_command("/событие Тренировка - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)
        vk_acc = repo.ensure_account(s, "vk", 100, display_name="Аня")
        vk_acc.tg_nick = "anny"
        tg_acc = repo.ensure_account(s, "tg", 200, display_name="anny", username="anny")
        s.flush()
        result = linking_bll.try_link(s, cfg, vk_acc)
        assert result == "linked"
        s.commit()
        return db, cfg, ev.id, vk_acc.id, tg_acc.id


def test_link_creates_tg_cards(tmp_path):
    db, cfg, ev_id, vk_acc_id, tg_acc_id = setup_linked(tmp_path)
    with db.session() as s:
        posts = repo.posts_for_content(s, "event", ev_id, ["dm_card"])
        tg_posts = [p for p in posts if p.platform == "tg"]
        assert len(tg_posts) == 1
        assert tg_posts[0].account_id == tg_acc_id


def test_change_notice_goes_to_tg(tmp_path):
    db, cfg, ev_id, vk_acc_id, tg_acc_id = setup_linked(tmp_path)
    with db.session() as s:
        events_bll.apply_full_edit(s, cfg, ev_id, "Тренировка - 16.09 20:00")
        notices = repo.posts_for_content(s, "event", ev_id, ["dm_notice"])
        plats = {p.platform for p in notices}
        assert {"vk", "tg"} <= plats


def test_tg_notifications_off(tmp_path):
    db, cfg, ev_id, vk_acc_id, tg_acc_id = setup_linked(tmp_path)
    with db.session() as s:
        tg = repo.get_account(s, tg_acc_id)
        tg.tg_dm_notifications = False
        events_bll.apply_full_edit(s, cfg, ev_id, "Тренировка - 17.09 20:00")
        notices = repo.posts_for_content(s, "event", ev_id, ["dm_notice"])
        assert all(p.platform != "tg" for p in notices)


def test_set_poll_choices_single(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        parsed, _ = polls_bll.parse_poll_command("/создать опрос В; а; б; в", cfg, NOW)
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        polls_bll.publish(s, cfg, poll.id)
        # текст «2» → вариант с idx 1
        key = polls_bll.set_poll_choices(s, cfg, "vk", 100, poll.id, {1})
        assert key == "ok"
        acc = repo.get_account_by_platform_id(s, "vk", 100)
        assert repo.selected_poll_options(s, poll.id, acc.id) == {1}
        # текст «1,3» в одиночном — берётся первый
        polls_bll.set_poll_choices(s, cfg, "vk", 100, poll.id, {0, 2})
        assert repo.selected_poll_options(s, poll.id, acc.id) == {0}


def test_set_poll_choices_multi(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        parsed, _ = polls_bll.parse_poll_command("/создать опрос В; а; б; в; несколько", cfg, NOW)
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        polls_bll.publish(s, cfg, poll.id)
        polls_bll.set_poll_choices(s, cfg, "vk", 100, poll.id, {0, 2})
        acc = repo.get_account_by_platform_id(s, "vk", 100)
        assert repo.selected_poll_options(s, poll.id, acc.id) == {0, 2}
