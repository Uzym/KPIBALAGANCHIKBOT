"""Тесты оплаты: начисления, платежи, долги, порог оповещения, поиск персоны."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll import fees as fees_bll
from config import Config
from dal import repositories as repo
from dal.database import Database

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ)


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def member(db, uid=1, name="Аня"):
    with db.session() as s:
        acc = repo.ensure_account(s, "vk", uid, display_name=name)
        person = repo.get_or_create_person(s, display_name=name)
        acc.person_id = person.id
        repo.upsert_subscription(s, acc.id, "active")
        s.commit()
        return person.id


def test_monthly_accrual_idempotent(tmp_path):
    db = make_db(tmp_path)
    cfg = Config(fee_monthly_rub=200)
    pid = member(db)
    with db.session() as s:
        assert fees_bll.ensure_monthly_accrual(s, cfg, pid, "2026-09") is True
        assert fees_bll.ensure_monthly_accrual(s, cfg, pid, "2026-09") is False
        assert fees_bll.debt_of(s, pid) == 200
        s.commit()


def test_accruals_idempotent_across_restarts(tmp_path):
    """Повторные «релизы»/рестарты в одном месяце не дублируют начисления."""
    db = make_db(tmp_path)
    cfg = Config(fee_monthly_rub=200)
    member(db, uid=1, name="Аня")
    member(db, uid=2, name="Боря")
    with db.session() as s:
        assert fees_bll.ensure_accruals_for_active(s, cfg, NOW) == []
        s.commit()
    for _ in range(2):  # ещё два «релиза» в том же месяце
        with db.session() as s:
            assert fees_bll.ensure_accruals_for_active(s, cfg, NOW) == []
            s.commit()
    with db.session() as s:
        for pid in (1, 2):
            assert fees_bll.debt_of(s, pid) == 200
        s.commit()


def test_record_expense(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    pid = member(db)
    with db.session() as s:
        err, _ = fees_bll.record_expense(s, cfg, pid, 150, "экипировка")
        assert err is None
        assert fees_bll.debt_of(s, pid) == 150
        err, _ = fees_bll.record_expense(s, cfg, pid, -5, "x")
        assert err is not None
        s.commit()


def test_payment_and_correction(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    pid = member(db)
    with db.session() as s:
        for m in ("2026-09", "2026-10", "2026-11"):
            fees_bll.ensure_monthly_accrual(s, cfg, pid, m)
        assert fees_bll.debt_of(s, pid) == 600
        err, _ = fees_bll.record_payment(s, cfg, pid, 200, "взнос")
        assert err is None
        assert fees_bll.debt_of(s, pid) == 400
        err, _ = fees_bll.record_payment(s, cfg, pid, -50, "перерасчёт")
        assert err is None
        assert fees_bll.debt_of(s, pid) == 450  # минус = отмена/возврат (долг растёт)
        err, _ = fees_bll.record_payment(s, cfg, pid, 0, "пусто")
        assert err is not None
        s.commit()


def test_debt_alert_crossing(tmp_path):
    db = make_db(tmp_path)
    cfg = Config(fee_monthly_rub=200, debt_alert_limit_rub=600)
    pid = member(db)
    with db.session() as s:
        for m in ("2026-09", "2026-10", "2026-11"):
            fees_bll.ensure_monthly_accrual(s, cfg, pid, m)
        assert fees_bll.check_debt_alert(s, cfg, pid) is None  # 600 не больше порога
        fees_bll.ensure_monthly_accrual(s, cfg, pid, "2026-12")
        alert = fees_bll.check_debt_alert(s, cfg, pid)
        assert alert and "800" in alert
        assert fees_bll.check_debt_alert(s, cfg, pid) is None  # повторно — тишина
        fees_bll.record_payment(s, cfg, pid, 300, "взнос")
        assert fees_bll.debt_of(s, pid) == 500
        p = repo.get_person(s, pid)
        assert p.fee_alerted is False  # флаг сброшен, алерт сработает снова
        s.commit()


def test_debtors_and_history(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    pid1 = member(db, uid=1, name="Аня")
    pid2 = member(db, uid=2, name="Боря")
    with db.session() as s:
        fees_bll.ensure_monthly_accrual(s, cfg, pid1, "2026-09")
        fees_bll.ensure_monthly_accrual(s, cfg, pid1, "2026-10")
        fees_bll.ensure_monthly_accrual(s, cfg, pid2, "2026-09")
        fees_bll.record_payment(s, cfg, pid2, 200, "взнос")
        s.commit()
    with db.session() as s:
        rows = repo.persons_with_debt(s)
        assert [(p.display_name, d) for p, d in rows] == [("Аня", 400)]
        text = fees_bll.debtors_text(s, cfg)
        assert "Аня: 400" in text
        hist = fees_bll.history_text(s, cfg, pid1)
        assert "400" in hist and "взнос" in hist
        ov = fees_bll.debt_overview(s, cfg, pid1)
        assert "400 ₽" in ov and "Ежемесячный взнос: 200" in ov
        s.commit()


def test_find_person_by_ref(tmp_path):
    db = make_db(tmp_path)
    pid = member(db, uid=42, name="Петя")
    with db.session() as s:
        assert repo.find_person_by_ref(s, "42").id == pid
        assert repo.find_person_by_ref(s, "петя").id == pid
        p = repo.get_person(s, pid)
        p.display_override = "Пётр Первый"
        assert repo.find_person_by_ref(s, "пётр первый").id == pid
        assert repo.find_person_by_ref(s, "нет такого") is None
        s.commit()


def test_find_persons_by_ref_multi(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        # Аня из ВК
        a1 = repo.ensure_account(s, "vk", 100, display_name="Аня")
        p1 = repo.get_or_create_person(s, display_name="Аня")
        a1.person_id = p1.id
        # Аня из TG с логином @anya
        a2 = repo.ensure_account(s, "tg", 200, display_name="Аня", username="anya")
        p2 = repo.get_or_create_person(s, display_name="Аня")
        a2.person_id = p2.id
        s.commit()

        both = repo.find_persons_by_ref(s, "аня")
        assert {p.id for p in both} == {p1.id, p2.id}
        # логин — только TG-персона
        tg_only = repo.find_persons_by_ref(s, "@anya")
        assert [p.id for p in tg_only] == [p2.id]
        # числа — точный аккаунт
        assert [p.id for p in repo.find_persons_by_ref(s, "100")] == [p1.id]
        assert [p.id for p in repo.find_persons_by_ref(s, "200")] == [p2.id]
        # переопределённое имя тоже ищется
        p1.display_override = "Анна К."
        assert [p.id for p in repo.find_persons_by_ref(s, "анна")] == [p1.id]
        assert repo.find_persons_by_ref(s, "ктулху") == []
        s.commit()
