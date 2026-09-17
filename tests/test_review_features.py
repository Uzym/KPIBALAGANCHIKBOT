"""Тесты ревью-доработок: удаление, wall-лог, посещаемость, экспорт, обращения, bulk."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

from bll import events as events_bll
from bll import polls as polls_bll
from bll import export as export_bll
from bll.publication import wall_log
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


def test_delete_event_removes_cards(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path)
    with db.session() as s:
        # карточка «доставлена»
        post = repo.get_post_for(s, "event", ev_id, "dm_card",
                                 account_id=repo.get_account_by_platform_id(s, "vk", 1).id)
        repo.update_post(s, post.id, message_id=111, status="ok")
        s.commit()
    with db.session() as s:
        err = events_bll.delete_event(s, cfg, ev_id)
        assert err is None
        assert repo.get_event(s, ev_id) is None
        assert repo.get_content(s, ev_id) is None
        jobs = repo.fetch_pending_jobs(s, limit=50)
        deletes = [j for j in jobs if j.op == "delete"]
        assert any(j.post_id == post.id for j in deletes)
        # данные вычищены
        assert repo.votes_with_accounts(s, ev_id) == []
        s.commit()


def test_delete_poll_removes_cards_and_rows(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        repo.upsert_subscription(s, admin.id, "active")
        parsed, _ = polls_bll.parse_poll_command("/создать опрос В; а; б", cfg, NOW)
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        polls_bll.publish(s, cfg, poll.id)
        polls_bll.cast_poll_vote(s, cfg, "vk", 1, poll.id, 0)
        post = repo.get_post_for(s, "poll", poll.id, "dm_card", account_id=admin.id)
        repo.update_post(s, post.id, message_id=222, status="ok")
        s.commit()
    with db.session() as s:
        err = polls_bll.delete_poll(s, cfg, poll.id)
        assert err is None
        assert repo.get_poll(s, poll.id) is None
        assert repo.get_content(s, poll.id) is None
        assert repo.poll_votes_with_accounts(s, poll.id) == []
        jobs = repo.fetch_pending_jobs(s, limit=50)
        assert any(j.op == "delete" and j.post_id == post.id for j in jobs)
        s.commit()


def test_wall_log_enqueue(tmp_path):
    db = make_db(tmp_path)
    cfg = Config(vk_group_id=123, wall_log=True)
    with db.session() as s:
        assert wall_log(s, cfg, "🏁 Завершено", unique="u1") is True
        jobs = repo.fetch_pending_jobs(s, limit=10)
        assert any(j.platform == "vk_wall" for j in jobs)
    db2 = make_db(tmp_path)
    cfg_off = Config(vk_group_id=123, wall_log=False)
    with db2.session() as s:
        assert wall_log(s, cfg_off, "x", unique="u2") is False


def test_announcements_duplicated_to_wall(tmp_path):
    from bll import announcements as ann_bll

    db, _, ev_id = setup_event(tmp_path)
    cfg = Config(vk_group_id=123, wall_log=True)
    with db.session() as s:
        ann_bll.publish_global(s, cfg, "Сбор в субботу")
        ann_bll.publish_for_content(s, cfg, "event", ev_id, "Перенос на час")
        jobs = repo.fetch_pending_jobs(s, limit=100)
        keys = {j.idempotency_key for j in jobs if j.platform == "vk_wall"}
        assert "walllog:ann1" in keys
        assert "walllog:ann2" in keys
        s.commit()
    cfg_off = Config(vk_group_id=123, wall_log=False)
    with db.session() as s:
        ann_bll.publish_global(s, cfg_off, "Тихое объявление")
        jobs = repo.fetch_pending_jobs(s, limit=100)
        keys = {j.idempotency_key for j in jobs if j.platform == "vk_wall"}
        assert "walllog:ann3" not in keys
        s.commit()


def test_attendance_toggle_and_vm(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path)
    with db.session() as s:
        acc = repo.get_account_by_platform_id(s, "vk", 1)
        rsvp = __import__("bll.rsvp", fromlist=["cast_vote"]).cast_vote
        rsvp(s, cfg, "vk", 1, ev_id, "yes")
        vm = events_bll.attendance_vm(s, cfg, ev_id)
        assert vm is not None and "Кто пришёл" in vm.text
        assert vm.buttons and vm.buttons[0][0].action == "attend"
        key = vm.buttons[0][0].value
        assert events_bll.toggle_attendance(s, ev_id, key) is True
        assert repo.attendance_for_event(s, ev_id)
        assert events_bll.toggle_attendance(s, ev_id, key) is False
        assert repo.attendance_for_event(s, ev_id) == []


def test_export_xlsx(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path)
    with db.session() as s:
        from bll import rsvp as rsvp_bll
        rsvp_bll.cast_vote(s, cfg, "vk", 1, ev_id, "yes")
        data = export_bll.build_export_xlsx(s, cfg)
        assert data[:2] == b"PK"  # zip/xlsx
        assert len(data) > 500


def test_appeal_persist_and_mark(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        a = repo.create_appeal(s, "vk", 100, "Аня")
        m = repo.create_appeal_message(s, a.id, 1, 555)
        assert repo.appeal_message_by_cmid(s, 555).appeal_id == a.id
        repo.mark_appeal_answered(s, m.id)
        assert repo.appeal_message_by_cmid(s, 555).answered is True
        assert repo.get_appeal(s, a.id).member_name == "Аня"


def test_bulk_notice_jobs(tmp_path):
    db, cfg, ev_id = setup_event(tmp_path)
    with db.session() as s:
        # подписчики без карточек-уведомлений → bulk
        acc2 = repo.ensure_account(s, "vk", 2, display_name="Боба")
        repo.upsert_subscription(s, acc2.id, "active")
        events_bll.apply_full_edit(s, cfg, ev_id, "Тренировка - 16.09 20:00")
        jobs = repo.fetch_pending_jobs(s, limit=50)
        bulk = [j for j in jobs if j.platform == "vk_bulk"]
        assert bulk, "свежие уведомления должны идти батчем"
        payload = json.loads(bulk[0].view_model)
        assert payload["users"] and len(payload["users"]) >= 1


def test_notice_admins_all(tmp_path):
    from bll.publication import notice_admins

    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        notice_admins(s, cfg, "текст", unique="u1", admins={10, 20})
        jobs = repo.fetch_pending_jobs(s, limit=50)
        chats = {int(j.chat_id) for j in jobs if j.platform == "vk"}
        assert chats == {10, 20}
