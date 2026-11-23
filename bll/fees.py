"""BLL: оплата — ежемесячные взносы, платежи, долги, оповещение о пороге."""
from __future__ import annotations

import datetime as dt

from dal import repositories as repo
from dal.database import from_db
from dal.models import FeeEntry, Person

from config import Config


def month_key(now: dt.datetime, cfg: Config) -> str:
    return now.astimezone(cfg.tz).strftime("%Y-%m")


def debt_of(s, person_id: int) -> int:
    return repo.fee_debt_total(s, person_id)


def display_name(p: Person) -> str:
    return p.display_override or p.display_name or f"#{p.id}"


def ensure_monthly_accrual(s, cfg: Config, person_id: int,
                           month: str) -> bool:
    """Начислить взнос за месяц, если ещё не начислен. True — начислили."""
    if repo.has_fee_accrual(s, person_id, month):
        return False
    repo.add_fee_entry(s, person_id, "accrual", cfg.fee_monthly_rub, month,
                       f"взнос за {month}")
    return True


def ensure_accruals_for_active(s, cfg: Config, now: dt.datetime) -> list[tuple[int, str]]:
    """Взносы за текущий месяц всем активным подпискам. Возвращает (person_id, текст алерта)."""
    month = month_key(now, cfg)
    alerts: list[tuple[int, str]] = []
    for _sub, acc in repo.active_subscriptions(s):
        if acc.person_id is None:
            continue
        if ensure_monthly_accrual(s, cfg, acc.person_id, month):
            alert = check_debt_alert(s, cfg, acc.person_id)
            if alert:
                alerts.append((acc.person_id, alert))
    return alerts


def check_debt_alert(s, cfg: Config, person_id: int) -> str | None:
    """При пересечении порога долга — текст оповещения админам (однократно).

    Сброс флага — когда долг опустился ниже порога (алерт сработает снова).
    """
    p = repo.get_person(s, person_id)
    if p is None:
        return None
    debt = debt_of(s, person_id)
    if debt > cfg.debt_alert_limit_rub:
        if not p.fee_alerted:
            p.fee_alerted = True
            return (f"⚠️ Долг {display_name(p)}: {debt} ₽ "
                    f"(порог {cfg.debt_alert_limit_rub} ₽).")
    elif p.fee_alerted:
        p.fee_alerted = False
    return None


def record_payment(s, cfg: Config, person_id: int, amount_rub: int,
                   label: str, created_by: int | None = None) -> tuple[str | None, str | None]:
    """Фиксация платежа. Возвращает (ошибка, алерт).

    amount > 0 — платёж (минус к долгу); amount < 0 — отмена платежа (долг растёт).
    """
    if amount_rub == 0:
        return "Сумма не может быть нулевой.", None
    kind = "payment"
    signed = -abs(amount_rub) if amount_rub > 0 else abs(amount_rub)
    repo.add_fee_entry(s, person_id, kind, signed, None,
                       label or ("платёж" if amount_rub > 0 else "возврат"),
                       created_by=created_by)
    alert = check_debt_alert(s, cfg, person_id)
    return None, alert


def record_expense(s, cfg: Config, person_id: int, amount_rub: int,
                   label: str, created_by: int | None = None) -> tuple[str | None, str | None]:
    """Трата/ручное начисление (долг растёт). Возвращает (ошибка, алерт)."""
    if amount_rub <= 0:
        return "Сумма должна быть положительной.", None
    repo.add_fee_entry(s, person_id, "accrual", abs(amount_rub), None,
                       label or "трата", created_by=created_by)
    alert = check_debt_alert(s, cfg, person_id)
    return None, alert


def debt_overview(s, cfg: Config, person_id: int) -> str:
    """Для участника: сколько должен и за что + последние операции."""
    debt = debt_of(s, person_id)
    lines = ["💰 Оплата"]
    if debt > 0:
        lines.append(f"Твой долг: {debt} ₽.")
    else:
        lines.append("Долгов нет 🎉")
    lines.append(f"Ежемесячный взнос: {cfg.fee_monthly_rub} ₽ "
                 "(начисляется автоматически в начале месяца).")
    recent = repo.recent_fee_entries(s, person_id, limit=5)
    if recent:
        lines.append("Последние операции:")
        for e in reversed(recent):
            sign = "+" if e.amount_rub > 0 else "−"
            when = from_db(e.created_at).astimezone(cfg.tz).strftime("%d.%m %H:%M")
            lines.append(f"  {sign}{abs(e.amount_rub)} ₽ — {e.label or '—'} ({when})")
    return "\n".join(lines)


def debtors_text(s, cfg: Config) -> str:
    rows = repo.persons_with_debt(s)
    if not rows:
        return "Должников нет 🎉"
    lines = ["💰 Долги:"]
    for p, debt in rows:
        flag = " ⚠️" if debt > cfg.debt_alert_limit_rub else ""
        lines.append(f"• {display_name(p)}: {debt} ₽{flag}")
    return "\n".join(lines)


def history_text(s, cfg: Config, person_id: int, limit: int = 15) -> str:
    p = repo.get_person(s, person_id)
    name = display_name(p) if p else f"#{person_id}"
    entries = repo.recent_fee_entries(s, person_id, limit=limit)
    if not entries:
        return f"У {name} нет операций по оплате."
    lines = [f"💰 История {name} (долг: {debt_of(s, person_id)} ₽):"]
    for e in reversed(entries):
        sign = "+" if e.amount_rub > 0 else "−"
        when = from_db(e.created_at).astimezone(cfg.tz).strftime("%d.%m %H:%M")
        month = f" [{e.month}]" if e.month else ""
        lines.append(f"  {sign}{abs(e.amount_rub)} ₽ — {e.label or '—'}{month} ({when})")
    return "\n".join(lines)
