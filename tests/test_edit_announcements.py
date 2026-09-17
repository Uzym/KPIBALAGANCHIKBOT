"""Тесты этапа 4: /edit, секция объявлений, схлопывание уведомлений, списки."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll import announcements as ann_bll
from bll import events as events_bll
from bll import polls as polls_bll
from bll import publication
from bll.timeparse import parse_event_command
from config import Config
from dal import repositories as repo
from dal.database import Database, from_db

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ)


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def setup_event(tmp_path, cfg=None):
    db = make_db(tmp_path)
    cfg = cfg or Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed = parse_event_command("/событие Тренировка - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)
        s.commit()
    return db, cfg, ev.id


def test_apply_full_edit(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path)
    with db.session() as s:
        result = events_bll.apply_full_edit(s, cfg, ev_id,
                                            "Спарринг - 16.09 20:00 - 16.09 22:00 - в зале 2")
        assert isinstance(result, list)
        ev = repo.get_event(s, ev_id)
        assert ev.title == "Спарринг"
        starts = from_db(ev.starts_at).astimezone(TZ)
        ends = from_db(ev.ends_at).astimezone(TZ)
        assert (starts.day, starts.hour) == (16, 20)
        assert ends.hour == 22
        assert ev.note == "в зале 2"
        # tracked-уведомление: один пост dm_notice на подписчика
        notices = repo.posts_for_content(s, "event", ev_id, ["dm_notice"])
        assert len(notices) == 1


def test_edit_errors(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path)
    with db.session() as s:
        assert isinstance(events_bll.apply_full_edit(s, cfg, 999, "Х - 15.09 19:00"), str)
        assert isinstance(events_bll.apply_full_edit(s, cfg, ev_id, "Х - когда-нибудь"), str)


def test_change_notice_collapse(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path)
    with db.session() as s:
        events_bll.apply_full_edit(s, cfg, ev_id, "Тренировка - 16.09 20:00")
        notices = repo.posts_for_content(s, "event", ev_id, ["dm_notice"])
        # «доставлено»: отметим пост как отправленный с message_id
        repo.update_post(s, notices[0].id, message_id=100, status="ok")
        s.commit()
    with db.session() as s:
        events_bll.apply_full_edit(s, cfg, ev_id, "Тренировка - 17.09 20:00")
        notices = repo.posts_for_content(s, "event", ev_id, ["dm_notice"])
        assert len(notices) == 1  # одно уведомление на подписчика — схлопывание
        # второе изменение — edit существующего, а не новое сообщение
        jobs = repo.fetch_pending_jobs(s, limit=50)
        edits = [j for j in jobs if j.op == "edit" and j.post_id == notices[0].id]
        assert len(edits) >= 1


def test_announcement_section(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path)
    with db.session() as s:
        ev = repo.get_event(s, ev_id)
        ann_bll.publish_for_content(s, cfg, "event", ev_id, "Берите перчатки")
        ann_bll.publish_for_content(s, cfg, "event", ev_id, "Зал поменялся")
        vm = publication.vm_for_post(s, cfg, ev, "dm_card")
        assert "📢 Объявления" in vm.text
        assert "Берите перчатки" in vm.text and "Зал поменялся" in vm.text


def test_poll_apply_edit(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        parsed, _ = polls_bll.parse_poll_command("/создать опрос В; а; б", cfg, NOW)
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        polls_bll.publish(s, cfg, poll.id)
        human, err = polls_bll.apply_poll_edit(s, cfg, poll.id, "Новый вопрос; до 21.09 19:00")
        assert err is None and human
        p = repo.get_poll(s, poll.id)
        assert p.title == "Новый вопрос"
        assert p.closes_at.day == 21
        # варианты не редактируются
        _, err = polls_bll.apply_poll_edit(s, cfg, poll.id, "Вопрос; а; б")
        assert err and "не редактируются" in err


def test_admin_listing_vm(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path)
    with db.session() as s:
        vm = events_bll.admin_listing_vm(s, cfg)
        assert f"#{ev_id}" in vm.text
        assert "👀" in vm.text  # охват рассылки (карточки)
        assert vm.buttons and vm.buttons[0][0].action == "panel"
