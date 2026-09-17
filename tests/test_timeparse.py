"""Тесты парсера дат и команды создания события."""
import datetime as dt
from zoneinfo import ZoneInfo

from bll.timeparse import parse_event_command, parse_when

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ)  # воскресенье


def test_date_time():
    res = parse_when("15.09 19:00", TZ, NOW)
    assert res is not None
    d, assumed = res
    assert (d.year, d.month, d.day, d.hour) == (2026, 9, 15, 19)
    assert assumed is False


def test_date_defaults_time():
    d, assumed = parse_when("15.09", TZ, NOW)
    assert d.hour == 19 and d.minute == 0
    assert assumed is True


def test_time_only_today():
    d, _ = parse_when("18:00", TZ, NOW)
    assert d.date() == NOW.date()  # 18:00 ещё не прошло
    d2, _ = parse_when("10:00", TZ, NOW)
    assert d2.date() == NOW.date() + dt.timedelta(days=1)  # 10:00 прошло — завтра


def test_time_only_with_base():
    start, _ = parse_when("15.09 19:00", TZ, NOW)
    end, _ = parse_when("21:00", TZ, NOW, base=start)
    assert end.date() == start.date() and end.hour == 21


def test_tomorrow():
    d, _ = parse_when("завтра 18:30", TZ, NOW)
    assert d.date() == NOW.date() + dt.timedelta(days=1)
    assert (d.hour, d.minute) == (18, 30)


def test_weekday_next():
    # вс 13.09, «вт» -> 15.09
    d, _ = parse_when("вт 19:00", TZ, NOW)
    assert d.weekday() == 1
    assert d.date() == dt.date(2026, 9, 15)


def test_iso():
    d, _ = parse_when("2026-10-01 19:00", TZ, NOW)
    assert (d.month, d.day, d.hour) == (10, 1, 19)


def test_full_command():
    p = parse_event_command(
        "/событие Тренировка - 15.09 19:00 - 15.09 21:00 - спарринг, брать перчатки", TZ, NOW
    )
    assert p.title == "Тренировка"
    assert p.starts_at.day == 15 and p.starts_at.hour == 19
    assert p.ends_at.hour == 21
    assert p.note == "спарринг, брать перчатки"
    assert p.missing == []


def test_command_minimal():
    p = parse_event_command("/событие Плавание - завтра 7:00", TZ, NOW)
    assert p.title == "Плавание"
    assert p.ends_at == p.starts_at + dt.timedelta(hours=1)
    assert p.note is None


def test_command_with_em_dash():
    p = parse_event_command("/событие Игры — 20.09 15:00 — 2ч занятия", TZ, NOW)
    assert p.title == "Игры"
    assert p.starts_at.day == 20


def test_command_missing_start():
    p = parse_event_command("/событие Только название", TZ, NOW)
    assert "дата и время начала" in p.missing


def test_command_bad_start():
    p = parse_event_command("/событие Х - когда-нибудь - 2ч", TZ, NOW)
    assert "дата и время начала" in p.missing


def test_end_before_start_rejected():
    p = parse_event_command("/событие Х - 20.09 19:00 - 20.09 10:00", TZ, NOW)
    assert any("конец" in m or "позже" in m for m in p.missing)
