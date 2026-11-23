"""E2E-тесты: полные пользовательские сценарии через BLL.

Каждый тест — законченный путь пользователя: от создания до результата.
Проверяются не отдельные функции, а итоговое состояние БД и outbox.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from bll import events as events_bll
from bll import fees as fees_bll
from bll import linking as linking_bll
from bll import polls as polls_bll
from bll import profiles as profiles_bll
from bll import rsvp as rsvp_bll
from bll.announcements import publish_for_content
from bll.publication import event_vm
from bll.timeparse import parse_event_command
from config import Config
from dal import repositories as repo
from dal.database import Database
import json
from dal.models import Event, FeeEntry, OutboxJob, Poll, PollVote, Vote

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 11, 23, 12, 0, tzinfo=TZ)
MONTH = "2026-11"


# ═══════════════════════ Хелперы ═══════════════════════


def make_db(tmp_path):
    db = Database(str(tmp_path / "e2e.db"))
    db.create_all()
    return db


def make_cfg(**overrides):
    cfg = Config()
    cfg.fee_monthly_rub = 200
    cfg.debt_alert_limit_rub = 600
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def add_member(db, uid, name, platform="vk", subscribe=True):
    with db.session() as s:
        acc = repo.ensure_account(s, platform, uid, display_name=name)
        person = repo.get_or_create_person(s, display_name=name)
        acc.person_id = person.id
        if subscribe and platform == "vk":
            repo.upsert_subscription(s, acc.id, "active")
        s.commit()
        return acc.id


def add_admin(db, uid=1, name="Глава"):
    with db.session() as s:
        acc = repo.ensure_account(s, "vk", uid, display_name=name)
        s.commit()
        return acc.id


def create_and_publish_event(db, cfg, admin_id, title="Тренировка", when_offset_hours=48):
    starts = NOW + dt.timedelta(hours=when_offset_hours)
    cmd = f"/событие {title} - {starts.strftime('%d.%m %H:%M')}"
    parsed = parse_event_command(cmd, TZ, NOW)
    assert not parsed.missing, f"parser failed: {parsed.missing}"
    with db.session() as s:
        ev = events_bll.create_draft(s, cfg, admin_id, parsed)
        s.commit()
        eid = ev.id
    with db.session() as s:
        result = events_bll.publish(s, cfg, eid)
        s.commit()
        assert isinstance(result, dict), f"publish failed: {result}"
    return eid


def create_and_publish_poll(db, cfg, admin_id, question, options, multichoice=False):
    lines = [question] + options
    if multichoice:
        lines.append("несколько")
    cmd = "/опрос " + "\n".join(lines)
    parsed, err = polls_bll.parse_poll_command(cmd, cfg, NOW)
    assert err is None, f"poll parse failed: {err}"
    with db.session() as s:
        poll = polls_bll.create_draft(s, cfg, admin_id, parsed)
        s.commit()
        pid = poll.id
    with db.session() as s:
        result = polls_bll.publish(s, cfg, pid)
        s.commit()
        assert isinstance(result, dict), f"poll publish failed: {result}"
    return pid


def poll_option_ids(db, poll_id):
    """Опции — JSON в Poll.options, option_id = idx."""
    with db.session() as s:
        poll = s.get(Poll, poll_id)
        return [o['idx'] for o in json.loads(poll.options)]


def outbox_count(db):
    with db.session() as s:
        return len(list(s.scalars(select(OutboxJob))))


def vote_count(db, event_id):
    with db.session() as s:
        return len(list(s.scalars(select(Vote).where(Vote.event_id == event_id))))


# ═══════════════════════ 1. Событие: полный цикл ═══════════════════════


class TestEventLifecycle:

    def test_full_event_flow(self, tmp_path):
        """Один пользователь: создал, проголосовал, сменил, закрыто-завершено."""
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        eid = create_and_publish_event(db, cfg, admin)
        add_member(db, 100, "Аня")

        # голосование
        with db.session() as s:
            assert rsvp_bll.cast_vote(s, cfg, "vk", 100, eid, "yes") == "ok"
            s.commit()

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            v = repo.get_vote(s, eid, acc.id)
            assert v.answer == "yes" and v.prev_answer is None and v.changes_count == 0

        # смена
        with db.session() as s:
            assert rsvp_bll.cast_vote(s, cfg, "vk", 100, eid, "no") == "ok_no"
            s.commit()

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            v = repo.get_vote(s, eid, acc.id)
            assert v.answer == "no" and v.prev_answer == "yes" and v.changes_count == 1

        # идемпотентность
        with db.session() as s:
            assert rsvp_bll.cast_vote(s, cfg, "vk", 100, eid, "no") == "same"
            s.commit()

        # закрытие
        with db.session() as s:
            result = events_bll.close(s, cfg, eid)
            s.commit()
            assert result is not None

        # после закрытия голоса не принимаются
        with db.session() as s:
            assert rsvp_bll.cast_vote(s, cfg, "vk", 999, eid, "yes") == "closed"
            s.commit()

        # завершение
        with db.session() as s:
            events_bll.finish(s, cfg, eid, admins={1})
            s.commit()
            assert repo.get_event(s, eid).status == "finished"

    def test_multi_user_multi_platform(self, tmp_path):
        """VK + TG пользователи голосуют, счётчики корректны."""
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        eid = create_and_publish_event(db, cfg, admin)

        add_member(db, 100, "Аня")
        add_member(db, 200, "Боба", platform="tg")
        add_member(db, 300, "Вика")

        with db.session() as s:
            rsvp_bll.cast_vote(s, cfg, "vk", 100, eid, "yes")
            rsvp_bll.cast_vote(s, cfg, "tg", 200, eid, "yes")
            rsvp_bll.cast_vote(s, cfg, "vk", 300, eid, "maybe")
            rsvp_bll.cast_vote(s, cfg, "vk", 100, eid, "no")  # смена
            s.commit()

        assert vote_count(db, eid) == 3

        with db.session() as s:
            ev = repo.get_event(s, eid)
            vm = event_vm(s, cfg, ev)
            yes = [e for e in vm.lists[0].entries if not e.struck_at]
            maybe = [e for e in vm.lists[1].entries if not e.struck_at]
            no = [e for e in vm.lists[2].entries if not e.struck_at]
            assert len(yes) == 1 and len(maybe) == 1 and len(no) == 1
            # Аня сменила выбор — проверяем через БД
            acc100 = repo.get_account_by_platform_id(s, "vk", 100)
            v = repo.get_vote(s, eid, acc100.id)
            assert v.prev_answer == "yes" and v.changes_count == 1

    def test_cancel(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        eid = create_and_publish_event(db, cfg, admin)

        with db.session() as s:
            events_bll.cancel(s, cfg, eid)
            s.commit()
        with db.session() as s:
            ev = repo.get_event(s, eid)
            assert ev.status == "cancelled" and ev.cancelled

    def test_edit_place(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        eid = create_and_publish_event(db, cfg, admin)

        with db.session() as s:
            changed = events_bll.update_fields(s, cfg, eid, {"place": "Новый зал"})
            s.commit()
            assert any("место" in c for c in changed)

        with db.session() as s:
            assert repo.get_event(s, eid).place == "Новый зал"

    def test_delete(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        eid = create_and_publish_event(db, cfg, admin)

        with db.session() as s:
            events_bll.delete_event(s, cfg, eid)
            s.commit()
        with db.session() as s:
            assert repo.get_event(s, eid) is None

    def test_remove_vote(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        eid = create_and_publish_event(db, cfg, admin)
        add_member(db, 100, "Аня")

        with db.session() as s:
            rsvp_bll.cast_vote(s, cfg, "vk", 100, eid, "yes")
            s.commit()

        with db.session() as s:
            assert rsvp_bll.remove_vote(s, cfg, "vk", 100, eid) == "removed"
            s.commit()

        assert vote_count(db, eid) == 0


# ═══════════════════════ 2. Опрос: полный цикл ═══════════════════════


class TestPollLifecycle:

    def test_full_poll_flow(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        pid = create_and_publish_poll(db, cfg, admin, "Куда едем", ["Баня", "Каток", "Квартирник"], multichoice=True)

        opts = poll_option_ids(db, pid)
        assert len(opts) == 3
        add_member(db, 100, "Аня")

        # мультивыбор: голосуем за 2 варианта
        with db.session() as s:
            assert polls_bll.cast_poll_vote(s, cfg, "vk", 100, pid, opts[0]) == "ok"
            assert polls_bll.cast_poll_vote(s, cfg, "vk", 100, pid, opts[1]) == "ok"
            s.commit()

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            votes = list(s.scalars(select(PollVote).where(PollVote.poll_id == pid, PollVote.account_id == acc.id)))
            assert len(votes) == 2

        # закрытие
        with db.session() as s:
            polls_bll.close(s, cfg, pid)
            s.commit()
        with db.session() as s:
            assert s.get(Poll, pid).status == "closed"

    def test_poll_single_choice_replaces(self, tmp_path):
        """Одиночный выбор: set_poll_choices заменяет предыдущее."""
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        pid = create_and_publish_poll(db, cfg, admin, "Выбор", ["А", "Б"])
        opts = poll_option_ids(db, pid)
        add_member(db, 100, "Аня")

        with db.session() as s:
            polls_bll.set_poll_choices(s, cfg, "vk", 100, pid, {opts[0]})
            s.commit()
        with db.session() as s:
            polls_bll.set_poll_choices(s, cfg, "vk", 100, pid, {opts[1]})  # смена
            s.commit()

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            votes = list(s.scalars(select(PollVote).where(
                PollVote.poll_id == pid, PollVote.account_id == acc.id, PollVote.active == True)))
            assert len(votes) == 1 and votes[0].option_id == opts[1]

    def test_poll_close_and_reopen(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        pid = create_and_publish_poll(db, cfg, admin, "Тест", ["Да", "Нет"])
        opts = poll_option_ids(db, pid)
        add_member(db, 100, "Аня")

        with db.session() as s:
            polls_bll.close(s, cfg, pid)
            s.commit()
        # после закрытия голоса не принимаются
        with db.session() as s:
            result = polls_bll.cast_poll_vote(s, cfg, "vk", 100, pid, opts[0])
            assert result != "ok"
            s.commit()
        # reopen
        with db.session() as s:
            polls_bll.reopen(s, cfg, pid)
            s.commit()
        with db.session() as s:
            assert polls_bll.cast_poll_vote(s, cfg, "vk", 100, pid, opts[0]) == "ok"
            s.commit()

    def test_poll_cancel(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        pid = create_and_publish_poll(db, cfg, admin, "Тест", ["Да", "Нет"])

        with db.session() as s:
            polls_bll.cancel(s, cfg, pid)
            s.commit()
        with db.session() as s:
            assert s.get(Poll, pid).status == "cancelled"


# ═══════════════════════ 3. Оплата: полный цикл ═══════════════════════


class TestFeeLifecycle:

    def test_accrual_and_payment(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        add_member(db, 100, "Аня")

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            assert fees_bll.ensure_monthly_accrual(s, cfg, acc.person_id, MONTH) is True
            s.commit()
            assert fees_bll.debt_of(s, acc.person_id) == 200

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            err, alert = fees_bll.record_payment(s, cfg, acc.person_id, 200, "наличные")
            s.commit()
            assert err is None
            assert fees_bll.debt_of(s, acc.person_id) == 0

    def test_idempotent_accrual(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        add_member(db, 100, "Аня")

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            fees_bll.ensure_monthly_accrual(s, cfg, acc.person_id, MONTH)
            assert fees_bll.ensure_monthly_accrual(s, cfg, acc.person_id, MONTH) is False
            s.commit()
            assert fees_bll.debt_of(s, acc.person_id) == 200

    def test_debt_threshold(self, tmp_path):
        """4 месяца без оплаты → долг 800 → оповещение срабатывает."""
        db = make_db(tmp_path)
        cfg = make_cfg()
        add_member(db, 100, "Аня")

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            for i in range(4):
                month = (NOW - dt.timedelta(days=30 * i)).strftime("%Y-%m")
                fees_bll.ensure_monthly_accrual(s, cfg, acc.person_id, month)
            s.commit()
            assert fees_bll.debt_of(s, acc.person_id) == 800
            alert = fees_bll.check_debt_alert(s, cfg, acc.person_id)
            assert alert is not None

    def test_expense_increases_debt(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        add_member(db, 100, "Аня")

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            fees_bll.ensure_monthly_accrual(s, cfg, acc.person_id, MONTH)
            s.commit()
        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            fees_bll.record_expense(s, cfg, acc.person_id, 150, "костюм")
            s.commit()
            assert fees_bll.debt_of(s, acc.person_id) == 350

    def test_history(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        add_member(db, 100, "Аня")

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            fees_bll.ensure_monthly_accrual(s, cfg, acc.person_id, MONTH)
            fees_bll.record_payment(s, cfg, acc.person_id, 100, "частично")
            s.commit()

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            text = fees_bll.history_text(s, cfg, acc.person_id)
            assert "200" in text and "100" in text


# ═══════════════════════ 4. Линковка + дедуп голосов ═══════════════════════


class TestLinkingE2E:

    def test_link_merges_votes(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        eid = create_and_publish_event(db, cfg, admin)

        add_member(db, 100, "Аня")
        tg_acc_id = add_member(db, 200, "anny", platform="tg")
        # задаём username для линковки
        with db.session() as s:
            tg_acc = repo.get_account(s, tg_acc_id)
            tg_acc.username = "anny"
            s.commit()

        # оба голосуют (разные платформы)
        with db.session() as s:
            rsvp_bll.cast_vote(s, cfg, "vk", 100, eid, "yes")
            rsvp_bll.cast_vote(s, cfg, "tg", 200, eid, "no")
            s.commit()

        # до линковки — 2 голоса в VM
        with db.session() as s:
            ev = repo.get_event(s, eid)
            vm = event_vm(s, cfg, ev)
            total = sum(len([e for e in lst.entries if not e.struck_at]) for lst in vm.lists)
            assert total == 2

        # линковка
        with db.session() as s:
            vk_acc = repo.get_account_by_platform_id(s, "vk", 100)
            vk_acc.tg_nick = "anny"
            s.commit()
            result = linking_bll.try_link(s, cfg, vk_acc)
            s.commit()
            assert result == "linked"

        # после — 1 голос (актуальный "no" от TG)
        with db.session() as s:
            ev = repo.get_event(s, eid)
            vm = event_vm(s, cfg, ev)
            total = sum(len([e for e in lst.entries if not e.struck_at]) for lst in vm.lists)
            assert total == 1

    def test_admin_force_link(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        add_member(db, 100, "Аня")
        add_member(db, 200, "anny", platform="tg")

        with db.session() as s:
            linking_bll.admin_force_link(s, cfg, 100, 200)
            s.commit()
        with db.session() as s:
            vk = repo.get_account_by_platform_id(s, "vk", 100)
            tg = repo.get_account_by_platform_id(s, "tg", 200)
            assert vk.person_id == tg.person_id


# ═══════════════════════ 5. Объявления ═══════════════════════


class TestAnnouncements:

    def test_announcement_by_event(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        eid = create_and_publish_event(db, cfg, admin)
        add_member(db, 100, "Аня")

        with db.session() as s:
            admin_acc = repo.get_account_by_platform_id(s, "vk", 1)
            sent = publish_for_content(s, cfg, "event", eid, "берите перчатки",
                                       admin_account_id=admin_acc.id)
            s.commit()
            assert sent >= 1  # хотя бы одному


# ═══════════════════════ 6. Посещаемость ═══════════════════════


class TestAttendance:

    def test_toggle(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        admin = add_admin(db)
        eid = create_and_publish_event(db, cfg, admin)

        add_member(db, 100, "Аня")
        add_member(db, 300, "Вика")

        with db.session() as s:
            rsvp_bll.cast_vote(s, cfg, "vk", 100, eid, "yes")
            rsvp_bll.cast_vote(s, cfg, "vk", 300, eid, "yes")
            s.commit()

        vm = None
        with db.session() as s:
            vm = events_bll.attendance_vm(s, cfg, eid)
            assert vm is not None

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            key = f"a:{acc.id}"
            assert events_bll.toggle_attendance(s, eid, key) is True
            assert events_bll.toggle_attendance(s, eid, key) is False  # снять
            s.commit()


# ═══════════════════════ 7. Подписки ═══════════════════════


class TestSubscriptions:

    def test_unsubscribe_and_resubscribe(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        add_member(db, 100, "Аня")

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            profiles_bll.unsubscribe(s, acc.id)
            s.commit()
            assert repo.get_subscription(s, acc.id).status != "active"

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            profiles_bll.activate_subscription(s, cfg, acc, 100)
            s.commit()
            assert repo.get_subscription(s, acc.id).status == "active"

    def test_toggle_announcements(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()
        add_member(db, 100, "Аня")

        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            sub = repo.get_subscription(s, acc.id)
            before = sub.send_announcements
            profiles_bll.toggle_announcements(s, acc.id)
            s.commit()
            after = repo.get_subscription(s, acc.id).send_announcements
            assert after == (not before)


# ═══════════════════════ 8. Полный день клуба (кросс-фичи) ═══════════════════════


class TestFullDayE2E:
    """Интеграционный сценарий: событие + опрос + оплата + линковка + объявление + закрытие."""

    def test_full_day(self, tmp_path):
        db = make_db(tmp_path)
        cfg = make_cfg()

        # люди
        admin = add_admin(db, uid=1, name="Глава")
        add_member(db, 100, "Аня")
        add_member(db, 200, "anny", platform="tg")
        add_member(db, 300, "Вика")

        # событие
        eid = create_and_publish_event(db, cfg, admin, title="Общая тренировка")

        # опрос
        pid = create_and_publish_poll(db, cfg, admin, "Куда после", ["Пицца", "Суши"])

        # взносы всем
        with db.session() as s:
            for uid, platform in [(100, "vk"), (200, "tg"), (300, "vk")]:
                acc = repo.get_account_by_platform_id(s, platform, uid)
                fees_bll.ensure_monthly_accrual(s, cfg, acc.person_id, MONTH)
            s.commit()

        # голосование за событие
        with db.session() as s:
            rsvp_bll.cast_vote(s, cfg, "vk", 100, eid, "yes")
            rsvp_bll.cast_vote(s, cfg, "tg", 200, eid, "yes")
            rsvp_bll.cast_vote(s, cfg, "vk", 300, eid, "maybe")
            s.commit()

        # голосование в опросе
        opts = poll_option_ids(db, pid)
        with db.session() as s:
            polls_bll.cast_poll_vote(s, cfg, "vk", 100, pid, opts[0])
            polls_bll.cast_poll_vote(s, cfg, "tg", 200, pid, opts[1])
            s.commit()

        # линковка Аня (VK) + anny (TG)
        with db.session() as s:
            vk_acc = repo.get_account_by_platform_id(s, "vk", 100)
            vk_acc.tg_nick = "anny"
            s.commit()
            linking_bll.try_link(s, cfg, vk_acc)
            s.commit()

        # платёж от Ани
        with db.session() as s:
            acc = repo.get_account_by_platform_id(s, "vk", 100)
            fees_bll.record_payment(s, cfg, acc.person_id, 200, "перевод")
            s.commit()
            assert fees_bll.debt_of(s, acc.person_id) == 0

        # объявление
        with db.session() as s:
            admin_acc = repo.get_account_by_platform_id(s, "vk", 1)
            publish_for_content(s, cfg, "event", eid, "не опаздывайте!",
                                admin_account_id=admin_acc.id)
            s.commit()

        # проверка: событие активно, есть голоса
        with db.session() as s:
            ev = repo.get_event(s, eid)
            assert ev.status == "active"
            vm = event_vm(s, cfg, ev)
            yes = [e for e in vm.lists[0].entries if not e.struck_at]
            assert len(yes) >= 1

        # закрыть и завершить всё
        with db.session() as s:
            events_bll.close(s, cfg, eid)
            events_bll.finish(s, cfg, eid, admins={1})
            polls_bll.close(s, cfg, pid)
            s.commit()

        # финальная проверка
        with db.session() as s:
            assert repo.get_event(s, eid).status == "finished"
            assert s.get(Poll, pid).status == "closed"
