"""Тест: снятие голоса слинкованной персоной убирает голоса всех её аккаунтов."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll import events as events_bll
from bll import linking as linking_bll
from bll import rsvp as rsvp_bll
from bll.publication import event_vm
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


def test_remove_vote_cross_platform(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        parsed = parse_event_command("/событие Т - 15.09 19:00", TZ, NOW)
        ev = events_bll.create_draft(s, cfg, admin.id, parsed)
        events_bll.publish(s, cfg, ev.id)
        vk_acc = repo.ensure_account(s, "vk", 100, display_name="Аня")
        vk_acc.tg_nick = "anny"
        tg_acc = repo.ensure_account(s, "tg", 200, display_name="anny", username="anny")
        s.flush()
        linking_bll.try_link(s, cfg, vk_acc)
        # голоса с обоих аккаунтов одной персоны
        rsvp_bll.cast_vote(s, cfg, "vk", 100, ev.id, "yes")
        rsvp_bll.cast_vote(s, cfg, "tg", 200, ev.id, "no")
        s.commit()

    with db.session() as s:
        # «Снять ответ» из ВК — убирает голоса персоны целиком (и TG-голос тоже)
        key = rsvp_bll.remove_vote(s, cfg, "vk", 100, ev.id)
        assert key == "removed"
        assert repo.votes_with_accounts(s, ev.id) == []
        vm = event_vm(s, cfg, repo.get_event(s, ev.id))
        assert all(not lst.entries for lst in vm.lists)
        s.commit()


def test_poll_keyboard_person_level(tmp_path):
    from bll import polls as polls_bll

    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        parsed, _ = polls_bll.parse_poll_command("/создать опрос В; а; б", cfg, NOW)
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        polls_bll.publish(s, cfg, poll.id)
        vk_acc = repo.ensure_account(s, "vk", 100, display_name="Аня")
        vk_acc.tg_nick = "anny"
        tg_acc = repo.ensure_account(s, "tg", 200, display_name="anny", username="anny")
        s.flush()
        linking_bll.try_link(s, cfg, vk_acc)
        # одиночный выбор: голос из TG гасит выбор, сделанный в VK (уровень персоны)
        polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll.id, 0)
        polls_bll.cast_poll_vote(s, cfg, "tg", 200, poll.id, 1)
        sel = repo.selected_poll_options_for_person(s, poll.id, vk_acc)
        assert sel == {1}
        vm = polls_bll.vm_for_poll_post(s, cfg, poll.id, "dm_card", vk_acc.id)
        labels = [b.label for row in vm.buttons for b in row]
        assert any(l.startswith("✅") and "2" in l for l in labels)
        assert not any(l.startswith("✅") and l.split()[0] == "1" for l in labels)
        s.commit()
