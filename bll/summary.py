"""BLL: сборка ViewModel событий (списки, зачёркивания, статусы)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .contracts import EntryVM, EventVM, ListVM

ANSWER_TITLES = {"yes": "✅ Придут", "maybe": "🤔 Возможно", "no": "❌ Не придут"}
ANSWER_ICONS = {"yes": "✅", "maybe": "🤔", "no": "❌"}

WEEKDAY_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


@dataclass
class VoteRow:
    """Подготовленная строка голоса для сводки (BLL собирает из БД)."""
    answer: str
    prev_answer: str | None
    changes_count: int
    updated_at: dt.datetime  # aware
    display_name: str
    platform: str            # vk | tg
    person_id: int | None
    person_accounts_count: int  # сколько аккаунтов у person (1 — не слинкован)
    tag: str | None = ""     # "" — вычислять по платформе; None — без метки


def fmt_time(d: dt.datetime, tz: dt.tzinfo) -> str:
    return d.astimezone(tz).strftime("%H:%M")


def fmt_when(starts_at: dt.datetime, ends_at: dt.datetime, tz: dt.tzinfo) -> str:
    s = starts_at.astimezone(tz)
    e = ends_at.astimezone(tz)
    if s.date() == e.date():
        return f"{WEEKDAY_RU[s.weekday()]} {s.strftime('%d.%m')}, {s.strftime('%H:%M')}–{e.strftime('%H:%M')}"
    return (
        f"{WEEKDAY_RU[s.weekday()]} {s.strftime('%d.%m %H:%M')} — "
        f"{WEEKDAY_RU[e.weekday()]} {e.strftime('%d.%m %H:%M')}"
    )


def status_line(status: str, cancelled: bool) -> str | None:
    if cancelled or status == "cancelled":
        return "❌ ОТМЕНЕНО"
    if status == "closed":
        return "🔒 Запись закрыта"
    if status == "finished":
        return "🏁 Завершено"
    return None


def build_event_vm(
    *,
    event_id: int,
    title: str,
    starts_at: dt.datetime,
    ends_at: dt.datetime,
    status: str,
    cancelled: bool,
    place: str | None,
    note: str | None,
    votes: list[VoteRow],
    tz: dt.tzinfo,
) -> EventVM:
    lists = {k: ListVM(answer=k, title=ANSWER_TITLES[k]) for k in ("yes", "maybe", "no")}

    # объединение аккаунтов одного person: актуальный голос — последний по времени
    merged: dict[tuple, VoteRow] = {}
    for v in votes:
        key: tuple = ("p", v.person_id) if v.person_id else ("a", v.display_name, v.platform)
        cur = merged.get(key)
        if cur is None or v.updated_at > cur.updated_at:
            merged[key] = v

    for v in merged.values():
        if v.tag != "":
            tag = v.tag
        else:
            tag = v.platform.upper() if v.person_accounts_count <= 1 else None
        entry = EntryVM(name=v.display_name or "?", tag=tag)
        lists[v.answer].entries.append(entry)
        # история смены выбора хранится в votes.prev_answer, но не отображается

    for lst in lists.values():
        lst.entries.sort(key=lambda e: e.name.lower())

    return EventVM(
        event_id=event_id,
        title=title,
        when_line=fmt_when(starts_at, ends_at, tz),
        place=place,
        note=note,
        status_line=status_line(status, cancelled),
        lists=[lists[k] for k in ("yes", "maybe", "no")],
    )


def final_summary_text(vm: EventVM) -> str:
    """Текст финальной сводки (🏁 Завершено)."""
    parts = [f"🏁 Завершено: «{vm.title}»"]
    for lst in vm.lists:
        names = ", ".join(e.name for e in lst.entries if not e.struck_at)
        parts.append(f"{lst.title} ({len([e for e in lst.entries if not e.struck_at])}): "
                     f"{names or '—'}")
    return "\n".join(parts)


# --- опросы ---------------------------------------------------------------------


@dataclass
class PollRow:
    option_id: int
    active: bool
    updated_at: dt.datetime
    display_name: str
    tag: str | None
    platform: str
    person_id: int | None


def build_poll_vm(
    *,
    poll_id: int,
    title: str,
    multichoice: bool,
    closes_line: str | None,
    status_line: str | None,
    options: list[dict],
    rows: list[PollRow],
    tz: dt.tzinfo,
) -> "PollVM":
    from .contracts import EntryVM, PollOptionVM, PollVM

    # слияние по персоне/аккаунту: последнее состояние каждого варианта по времени
    merged: dict[tuple, dict[int, tuple[bool, dt.datetime]]] = {}
    names: dict[tuple, tuple[str, str | None]] = {}
    for r in rows:
        key: tuple = ("p", r.person_id) if r.person_id else ("a", r.display_name, r.platform)
        cur = merged.setdefault(key, {})
        existing = cur.get(r.option_id)
        if existing is None or r.updated_at > existing[1]:
            cur[r.option_id] = (r.active, r.updated_at)
        names.setdefault(key, (r.display_name, r.tag))

    opt_vms: list[PollOptionVM] = []
    for o in options:
        entries: list[EntryVM] = []
        idx = o["idx"]
        for key, sel in merged.items():
            state = sel.get(idx)
            if state is None:
                continue
            active, updated = state
            if not active:
                continue  # снятые выборы не отображаем (история — в poll_votes)
            name, tag = names[key]
            entries.append(EntryVM(name=name or "?", tag=tag))
        entries.sort(key=lambda e: e.name.lower())
        opt_vms.append(PollOptionVM(idx=idx, text=o["text"], entries=entries))

    return PollVM(
        poll_id=poll_id, title=title, multichoice=multichoice,
        closes_line=closes_line, status_line=status_line, options=opt_vms,
    )
