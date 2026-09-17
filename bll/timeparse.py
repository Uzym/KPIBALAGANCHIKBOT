"""BLL: разбор команды создания события и дат на естественном языке.

Поддерживаемые форматы (таймзона клуба):
  15.09 19:00 · 15.09.2026 19:00 · 2026-09-15 19:00 · 2026-09-15T19:00
  15.09 (время по умолчанию 19:00) · 19:00 (сегодня, если не прошло — завтра)
  сегодня 19:00 · завтра 18:00 · послезавтра 19:00 · вт 19:00 / вторник 19:00
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

WEEKDAYS = {
    "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
    "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3,
    "пятница": 4, "суббота": 5, "воскресенье": 6,
}
DEFAULT_TIME = dt.time(19, 0)

RE_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")
RE_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$")
RE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?$")
RE_WORD = re.compile(r"^(сегодня|завтра|послезавтра|[а-яё]+)$", re.IGNORECASE)


@dataclass
class ParsedEvent:
    title: str | None = None
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    note: str | None = None
    missing: list[str] = field(default_factory=list)   # что переспросить
    assumed_time: bool = False                          # время подставлено по умолчанию


def _norm_token(t: str) -> str:
    return t.replace("—", "-").replace("–", "-").replace("−", "-").strip()


def _mk(dt_local_naive: dt.datetime, tz: dt.tzinfo) -> dt.datetime:
    return dt_local_naive.replace(tzinfo=tz)


def parse_time(token: str) -> dt.time | None:
    m = RE_TIME.match(token.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return dt.time(h, mi)


def _parse_date_token(token: str) -> dt.date | None:
    m = RE_DATE.match(token)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = m.group(3)
        if y:
            y = int(y)
            if y < 100:
                y += 2000
        else:
            y = None
        try:
            base = dt.date(y or 2026, mo, d) if y else dt.date(2026, mo, d)
            return base
        except ValueError:
            return None
    m = RE_ISO.match(token)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _resolve_year(d: dt.date, now: dt.datetime) -> dt.date:
    """Год не указан — берём ближайший будущий."""
    if d.year == 2026 and (d.month < now.month or (d.month == now.month and d.day < now.day)):
        return d.replace(year=now.year + 1)
    if d.year == 2026:
        return d.replace(year=now.year)
    return d


def parse_when(token: str, tz: dt.tzinfo, now: dt.datetime,
               base: dt.datetime | None = None) -> tuple[dt.datetime, bool] | None:
    """Парсит поле времени. base — дата начала (для «конец: 21:00»).

    Возвращает (aware datetime, assumed_time) или None.
    """
    token = _norm_token(token)
    if not token:
        return None

    # один токен: ISO с временем
    m = RE_ISO.match(token)
    if m and m.group(4):
        try:
            t = dt.time(int(m.group(4)), int(m.group(5)))
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return _mk(dt.datetime.combine(d, t), tz), False
        except ValueError:
            return None

    parts = token.split()
    # только время
    if len(parts) == 1 and RE_TIME.match(parts[0]):
        t = parse_time(parts[0])
        if t is None:
            return None
        if base is not None:
            return _mk(dt.datetime.combine(base.astimezone(tz).date(), t), tz), False
        d = now.astimezone(tz).date()
        if dt.datetime.combine(d, t, tzinfo=tz) <= now:
            d += dt.timedelta(days=1)
        return _mk(dt.datetime.combine(d, t), tz), False

    # слова: сегодня/завтра/послезавтра/день недели [+ время]
    if RE_WORD.match(parts[0]) and parts[0].lower() in (
        {"сегодня", "завтра", "послезавтра"} | set(WEEKDAYS)
    ):
        word = parts[0].lower()
        today = now.astimezone(tz).date()
        if word == "сегодня":
            d = today
        elif word == "завтра":
            d = today + dt.timedelta(days=1)
        elif word == "послезавтра":
            d = today + dt.timedelta(days=2)
        else:
            target = WEEKDAYS[word]
            delta = (target - today.weekday()) % 7
            if delta == 0:
                delta = 7
            d = today + dt.timedelta(days=delta)
        if len(parts) > 1:
            t = parse_time(parts[1])
            if t is None:
                return None
            result = _mk(dt.datetime.combine(d, t), tz)
            if result <= now and word == "сегодня":
                return None
            return result, False
        # время не указано
        t = base.astimezone(tz).time() if base else DEFAULT_TIME
        result = _mk(dt.datetime.combine(d, t), tz)
        if result <= now:
            return None
        return result, True

    # дата [+ время]
    date_part = parts[0]
    if len(parts) > 1 and RE_TIME.match(parts[1]):
        d = _parse_date_token(date_part)
        t = parse_time(parts[1])
        if d is None or t is None:
            return None
        d = _resolve_year(d, now)
        return _mk(dt.datetime.combine(d, t), tz), False
    d = _parse_date_token(token)
    if d is not None:
        d = _resolve_year(d, now)
        t = base.astimezone(tz).time() if base else DEFAULT_TIME
        return _mk(dt.datetime.combine(d, t), tz), True

    return None


def parse_event_command(text: str, tz: dt.tzinfo, now: dt.datetime) -> ParsedEvent:
    """«/событие Название - 15.09 19:00 - 15.09 21:00 - описание»."""
    res = ParsedEvent()
    raw = text.strip()
    # срезаем команду
    raw = re.sub(r"^/(событие|event)\s*", "", raw, flags=re.IGNORECASE).strip()
    raw = _norm_token(raw)
    if not raw:
        res.missing.append("всё")
        return res

    parts = [p.strip() for p in re.split(r"\s+-\s+", raw) if p.strip()]
    res.title = parts[0] or None
    if len(parts) < 2:
        res.missing.append("дата и время начала")
        return res

    parsed = parse_when(parts[1], tz, now)
    if parsed is None:
        res.missing.append("дата и время начала")
        # всё равно пытаемся разобрать хвост, чтобы вернуть максимум
        if len(parts) >= 4:
            res.note = " - ".join(parts[3:])
        return res
    res.starts_at, res.assumed_time = parsed

    if len(parts) >= 3:
        parsed = parse_when(parts[2], tz, now, base=res.starts_at)
        if parsed is None:
            res.missing.append("дата и время конца")
        elif parsed[0] <= res.starts_at:
            res.missing.append("конец должен быть позже начала")
        else:
            res.ends_at = parsed[0]
    else:
        res.ends_at = res.starts_at + dt.timedelta(hours=1)

    if len(parts) >= 4:
        res.note = " - ".join(parts[3:]) or None
    return res
