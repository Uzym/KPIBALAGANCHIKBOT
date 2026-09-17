"""Тесты v5-членства: авто-подписка, академ (paused), возврат, уведомления."""
import asyncio
import datetime as dt
import json
import logging
from zoneinfo import ZoneInfo

from bll import events as events_bll
from bll import profiles as profiles_bll
from bll.timeparse import parse_event_command
from config import Config
from dal import repositories as repo
from dal.database import Database

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ)


class FakeVK:
    def __init__(self, members: set[int]):
        self.members = set(members)

    async def is_member(self, uid: int) -> bool:
        return uid in self.members


class FakeApp:
    def __init__(self, members: set[int]):
        self.vk = FakeVK(members)
        self.log = logging.getLogger("fakeapp")
        self.admins_vk: set[int] = set()
        self.membership_cache: dict = {}


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def setup_event(db, cfg):
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        parsed = parse_event_command("/событие Тренировка - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)
        s.commit()
        return ev.id


def test_on_member_message_newcomer(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    ev_id = setup_event(db, cfg)
    with db.session() as s:
        acc = repo.ensure_account(s, "vk", 100, display_name="Аня")
        reply = profiles_bll.on_member_message(s, cfg, acc, 100)
        assert reply and "Доступ открыт" in reply and "1" in reply
        sub = repo.get_subscription(s, acc.id)
        assert sub.status == "active"
        # карточка события создана
        post = repo.get_post_for(s, "event", ev_id, "dm_card", account_id=acc.id)
        assert post is not None


def test_on_member_message_return_from_academ(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    ev_id = setup_event(db, cfg)
    with db.session() as s:
        acc = repo.ensure_account(s, "vk", 100, display_name="Аня")
        repo.upsert_subscription(s, acc.id, "paused")
        reply = profiles_bll.on_member_message(s, cfg, acc, 100)
        assert reply and "С возвращением" in reply
        assert repo.get_subscription(s, acc.id).status == "active"


def test_on_member_message_stopped(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        acc = repo.ensure_account(s, "vk", 100)
        repo.upsert_subscription(s, acc.id, "stopped")
        reply = profiles_bll.on_member_message(s, cfg, acc, 100)
        assert reply and "/start" in reply
        assert repo.get_subscription(s, acc.id).status == "stopped"


def test_revalidate_academ_notice(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    ev_id = setup_event(db, cfg)
    app = FakeApp({1})  # 100 — не член
    with db.session() as s:
        acc = repo.ensure_account(s, "vk", 100, display_name="Аня")
        repo.upsert_subscription(s, acc.id, "active")
        # карточка была
        repo.create_post(s, "event", ev_id, "dm_card", "vk", "100", account_id=acc.id)
        s.commit()
    with db.session() as s:
        lines = asyncio.run(profiles_bll.revalidate_membership(app, s, cfg))
        assert any("академ" in l for l in lines)
        assert repo.get_subscription(s, repo.get_account_by_platform_id(s, "vk", 100).id).status == "paused"
        # карточки сняты
        post = repo.get_post_for(s, "event", ev_id, "dm_card",
                                 account_id=repo.get_account_by_platform_id(s, "vk", 100).id)
        assert post is None or post.status == "deleted"
        # уведомление об академе поставлено
        jobs = repo.fetch_pending_jobs(s, limit=50)
        notices = [j for j in jobs if json.loads(j.view_model).get("text", "").startswith("📴")]
        assert notices
        s.commit()


def test_revalidate_return_from_academ(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    ev_id = setup_event(db, cfg)
    app = FakeApp({100})  # 100 — снова член
    with db.session() as s:
        acc = repo.ensure_account(s, "vk", 100, display_name="Аня")
        repo.upsert_subscription(s, acc.id, "paused")
        s.commit()
    with db.session() as s:
        lines = asyncio.run(profiles_bll.revalidate_membership(app, s, cfg))
        assert any("paused→active" in l for l in lines)
        acc = repo.get_account_by_platform_id(s, "vk", 100)
        assert repo.get_subscription(s, acc.id).status == "active"
        post = repo.get_post_for(s, "event", ev_id, "dm_card", account_id=acc.id)
        assert post is not None
        s.commit()
