"""BLL: жизненный цикл события (создание/публикация/изменение/закрытие/завершение)."""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import delete as sa_delete

from dal import repositories as repo
from dal.database import from_db, now_utc, to_db
from dal.models import Event, Vote

from config import Config
from .contracts import ButtonVM, OutMessageVM
from .publication import (
    display_for,
    event_vm,
    fan_out_new,
    notice_admins,
    notice_dm_tracked,
    refresh_content,
    wall_log,
)
from .summary import fmt_when
from .timeparse import ParsedEvent, parse_event_command, parse_when

FIELD_ALIASES = {
    "название": "title",
    "заголовок": "title",
    "начало": "starts_at",
    "старт": "starts_at",
    "конец": "ends_at",
    "финиш": "ends_at",
    "место": "place",
    "описание": "note",
}


def create_draft(s, cfg: Config, admin_account_id: int | None, parsed: ParsedEvent) -> Event:
    ev = repo.create_event(
        s,
        title=parsed.title or "Событие",
        starts_at=to_db(parsed.starts_at),
        ends_at=to_db(parsed.ends_at or parsed.starts_at + dt.timedelta(hours=1)),
        place=None,
        note=parsed.note,
        status="draft",
        created_by=admin_account_id,
    )
    return ev


def preview_vm(s, cfg: Config, event: Event) -> OutMessageVM:
    vm = OutMessageVM(kind="preview", event=event_vm(s, cfg, event))
    vm.text = (
        "Проверь поля. Если что-то не так — нажми «Отмена» и пришли команду заново.\n"
        f"ID: #{event.id}"
    )
    vm.buttons = [
        [ButtonVM(action="publish", label="🚀 Опубликовать", event_id=event.id)],
        [ButtonVM(action="cancel_draft", label="🗑 Отмена", event_id=event.id)],
    ]
    return vm


def publish(s, cfg: Config, event_id: int) -> dict[str, int] | str:
    event = repo.get_event(s, event_id)
    if event is None or event.status != "draft":
        return "Черновик не найден (возможно, уже опубликован)."
    repo.update_event(s, event_id, {"status": "active"})
    event = repo.get_event(s, event_id)
    counts = fan_out_new(s, cfg, event)
    return counts


def parse_field_updates(text: str, cfg: Config, event: Event) -> tuple[dict, list[str]]:
    """«/edit 12 начало=16.09 19:00; место=Зал 3» — старый формат (запасной)."""
    values: dict = {}
    errors: list[str] = []
    body = re.sub(r"^/изменить\s*", "", text.strip(), flags=re.IGNORECASE)
    now = dt.datetime.now(cfg.tz)
    starts = from_db(event.starts_at)
    for chunk in body.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, val = chunk.partition("=")
        key = key.strip().lower()
        val = val.strip()
        field = FIELD_ALIASES.get(key)
        if not field:
            errors.append(f"не знаю поле «{key}»")
            continue
        if field in ("starts_at", "ends_at"):
            base = starts if field == "ends_at" else None
            parsed = parse_when(val, cfg.tz, now, base=base)
            if parsed is None:
                errors.append(f"не поняла «{key}={val}»")
                continue
            value = parsed[0]
            if field == "ends_at" and value <= from_db(event.starts_at):
                errors.append("конец должен быть позже начала")
                continue
            if field == "starts_at" and from_db(event.ends_at) <= value:
                values.setdefault("ends_at", to_db(value + dt.timedelta(hours=1)))
            values[field] = to_db(value)
        else:
            values[field] = val or None
    return values, errors


def update_fields(s, cfg: Config, event_id: int, values: dict) -> list[str]:
    """Применяет изменения, обновляет посты, шлёт «⚠️ Изменение»."""
    event = repo.get_event(s, event_id)
    if event is None or event.status not in ("active", "closed"):
        return []
    human = []
    labels = {"title": "название", "starts_at": "начало", "ends_at": "конец",
              "place": "место", "note": "описание"}
    for k, v in values.items():
        if k in ("starts_at", "ends_at"):
            v = from_db(v).astimezone(cfg.tz).strftime("%d.%m %H:%M")
        human.append(f"{labels.get(k, k)} → {v}")
    repo.update_event(s, event_id, values)
    event = repo.get_event(s, event_id)
    refresh_content(s, cfg, "event", event_id)
    if "starts_at" in values or "ends_at" in values:
        _schedule_reminders_again(s, cfg, event)
    text = f"⚠️ Изменение #{event.id} «{event.title}»: " + "; ".join(human)
    notice_dm_tracked(s, cfg, text,
                      content_type="event", content_id=event_id)
    return human


def apply_full_edit(s, cfg: Config, event_id: int, text: str) -> list[str] | str:
    """«/edit 12 Тренировка - 15.09 19:00 - 15.09 21:00 - описание» — формат создания."""
    event = repo.get_event(s, event_id)
    if event is None or event.status not in ("active", "closed"):
        return "Событие не найдено или неактивно (правятся только активные/закрытые)."
    parsed = parse_event_command(f"/событие {text}", cfg.tz, dt.datetime.now(cfg.tz))
    if parsed.missing or not parsed.title or not parsed.starts_at:
        missing = ", ".join(parsed.missing) if parsed.missing else "формат"
        return f"Не получилось: {missing}. Формат: /edit {event_id} Название - 15.09 19:00 - 15.09 21:00 - описание"
    values = {"title": parsed.title, "starts_at": to_db(parsed.starts_at)}
    if parsed.ends_at and parsed.ends_at > parsed.starts_at:
        values["ends_at"] = to_db(parsed.ends_at)
    elif from_db(event.ends_at) <= parsed.starts_at:
        values["ends_at"] = to_db(parsed.starts_at + dt.timedelta(hours=1))
    if parsed.note is not None:
        values["note"] = parsed.note
    return update_fields(s, cfg, event_id, values)


def _schedule_reminders_again(s, cfg: Config, event: Event) -> None:
    from .publication import _schedule_reminders

    _schedule_reminders(s, cfg, event)


def close(s, cfg: Config, event_id: int, auto: bool = False) -> str | None:
    event = repo.get_event(s, event_id)
    if event is None or event.status != "active":
        return None
    repo.update_event(s, event_id, {"status": "closed", "closed_at": now_utc(),
                                    "auto_closed": event.auto_closed or auto})
    event = repo.get_event(s, event_id)
    refresh_content(s, cfg, "event", event_id)
    vm = event_vm(s, cfg, event)
    yes = len([e for e in vm.lists[0].entries if not e.struck_at])
    maybe = len([e for e in vm.lists[1].entries if not e.struck_at])
    text = f"🔒 Запись закрыта: #{event.id} «{event.title}». Придут {yes}, возможно {maybe}."
    notice_dm_tracked(s, cfg, text,
                      content_type="event", content_id=event_id)
    return text


def reopen(s, cfg: Config, event_id: int) -> str | None:
    """Открыть запись заново (после ручного или авто-закрытия)."""
    event = repo.get_event(s, event_id)
    if event is None or event.status != "closed":
        return None
    if event.starts_at <= now_utc():  # naive-UTC в БД
        return "Событие уже началось — открыть запись нельзя."
    repo.update_event(s, event_id, {"status": "active", "closed_at": None})
    event = repo.get_event(s, event_id)
    refresh_content(s, cfg, "event", event_id)
    text = f"🔓 Запись снова открыта: #{event.id} «{event.title}»."
    notice_dm_tracked(s, cfg, text,
                      content_type="event", content_id=event_id)
    return text


def cancel(s, cfg: Config, event_id: int) -> None:
    event = repo.get_event(s, event_id)
    if event is None or event.status in ("cancelled", "finished"):
        return
    repo.update_event(s, event_id, {"status": "cancelled", "cancelled": True})
    event = repo.get_event(s, event_id)
    refresh_content(s, cfg, "event", event_id)
    text = (f"❌ Событие #{event.id} «{event.title}» "
            f"({fmt_when(from_db(event.starts_at), from_db(event.ends_at), cfg.tz)}) отменено.")
    notice_dm_tracked(s, cfg, text,
                      content_type="event", content_id=event_id)


def finish(s, cfg: Config, event_id: int, admins: set[int] | None = None) -> None:
    event = repo.get_event(s, event_id)
    if event is None or event.status not in ("active", "closed"):
        return
    if event.status == "active":  # забыли закрыть — закрываем молча
        repo.update_event(s, event_id, {"status": "closed", "closed_at": now_utc()})
    repo.update_event(s, event_id, {"status": "finished", "finished_at": now_utc()})
    event = repo.get_event(s, event_id)
    refresh_content(s, cfg, "event", event_id)
    from .summary import final_summary_text

    text = final_summary_text(event_vm(s, cfg, event))
    # лог в сообщество ВК (только создание постов — доступно сообществу)
    wall_log(s, cfg, text + f"\n#{event.id}", unique=f"ev{event_id}:finish")
    notice_dm_tracked(s, cfg, text,
                      content_type="event", content_id=event_id)
    notice_admins(s, cfg, text, unique=f"finish{event_id}", admins=admins)


def listing_text(s, cfg: Config) -> str:
    events = repo.open_events(s)
    if not events:
        return "Активных событий нет."
    lines = []
    for e in sorted(events, key=lambda x: x.starts_at):
        vm = event_vm(s, cfg, e)
        yes = len([x for x in vm.lists[0].entries if not x.struck_at])
        maybe = len([x for x in vm.lists[1].entries if not x.struck_at])
        no = len([x for x in vm.lists[2].entries if not x.struck_at])
        flag = "🔒 " if e.status == "closed" else ""
        lines.append(f"{flag}#{e.id}. «{e.title}» — {vm.when_line} · ✅{yes} 🤔{maybe} ❌{no}")
    return "\n".join(lines)


def admin_listing_vm(s, cfg: Config) -> OutMessageVM:
    """Компактный список админа: строки со ссылками + кнопка [⚙️ #id] на строку."""
    events = repo.open_events(s)
    if not events:
        return OutMessageVM(kind="menu", text="Активных событий нет.")
    lines: list[str] = []
    buttons: list[list[ButtonVM]] = []
    for e in sorted(events, key=lambda x: x.starts_at)[:9]:
        vm = event_vm(s, cfg, e)
        yes = len([x for x in vm.lists[0].entries if not x.struck_at])
        maybe = len([x for x in vm.lists[1].entries if not x.struck_at])
        no = len([x for x in vm.lists[2].entries if not x.struck_at])
        reach = len([p for p in repo.posts_for_content(s, "event", e.id, ["dm_card"])
                     if p.status != "deleted"])
        flag = "🔒 " if e.status == "closed" else ""
        lines.append(f"{flag}#{e.id} 📋 «{e.title}» · {vm.when_line} · ✅{yes} 🤔{maybe} ❌{no} · 👀{reach}")
        buttons.append([ButtonVM(action="panel", label=f"⚙️ #{e.id}", event_id=e.id)])
    if len(events) > 9:
        lines.append(f"…и ещё {len(events) - 9} (полный список — /события)")
    return OutMessageVM(kind="menu", text="\n".join(lines), buttons=buttons)


def resolve_event_by_reply(s, platform: str, chat_id: str, message_id: int) -> Event | None:
    post = repo.find_post_by_message(s, platform, chat_id, message_id)
    if post is None or post.content_type != "event":
        return None
    return repo.get_event(s, post.content_id)


def delete_draft(s, event_id: int) -> None:
    event = repo.get_event(s, event_id)
    if event is not None and event.status == "draft":
        s.delete(event)
        s.flush()  # сначала ребёнок (events), затем родитель (contents)
        content = repo.get_content(s, event_id)
        if content is not None:
            s.delete(content)


def delete_event(s, cfg: Config, event_id: int) -> str | None:
    """Полное удаление события: карточки удаляются у всех, данные — из БД."""
    event = repo.get_event(s, event_id)
    if event is None:
        return "Событие не найдено."
    # карточки/уведомления — удалить у всех через outbox
    for post in repo.posts_for_content(s, "event", event_id, ["dm_card", "dm_notice"]):
        repo.cancel_pending_jobs_for_post(s, post.id)
        if post.message_id and post.status == "ok":
            repo.enqueue_job(
                s, op="delete", platform=post.platform, chat_id=post.chat_id,
                post_id=post.id, view_model={"kind": "notice"},
                idempotency_key=f"del:{post.id}",
            )
        repo.update_post(s, post.id, status="deleted", vm_hash=None)
    # данные
    from dal.models import Announcement, Attendance, Reminder

    s.execute(sa_delete(Vote).where(Vote.event_id == event_id))
    s.execute(sa_delete(Attendance).where(Attendance.event_id == event_id))
    s.execute(sa_delete(Announcement).where(Announcement.content_type == "event",
                                            Announcement.content_id == event_id))
    s.execute(sa_delete(Reminder).where(Reminder.content_type == "event",
                                        Reminder.content_id == event_id))
    s.delete(event)
    s.flush()  # events.id → contents.id: удаляем ребёнка раньше родителя, явно
    content = repo.get_content(s, event_id)
    if content is not None:
        s.delete(content)
    return None


# --- посещаемость («кто реально пришёл») -------------------------------------------


def attendance_vm(s, cfg: Config, event_id: int) -> OutMessageVM | None:
    event = repo.get_event(s, event_id)
    if event is None:
        return None
    merged: dict[str, str] = {}
    for v, a in repo.votes_with_accounts(s, event_id):
        if v.answer != "yes":
            continue
        name, _tag = display_for(s, a)
        key = f"p:{a.person_id}" if a.person_id else f"a:{a.id}"
        merged.setdefault(key, name)
    marked: set[str] = set()
    for att in repo.attendance_for_event(s, event_id):
        if att.person_id is not None:
            marked.add(f"p:{att.person_id}")
        elif att.account_id is not None:
            marked.add(f"a:{att.account_id}")
    lines = [f"✅ Кто пришёл — #{event.id} «{event.title}»"]
    buttons: list[list[ButtonVM]] = []
    row: list[ButtonVM] = []
    for key, name in sorted(merged.items(), key=lambda kv: kv[1].lower()):
        mark = "✅ " if key in marked else ""
        lines.append(f"{mark}{name}")
        row.append(ButtonVM(action="attend", label=f"{mark}{name[:24]}", value=key,
                            event_id=event_id))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if len(buttons) > 9:  # лимит VK: 10 рядов
        buttons = buttons[:9]
        lines.append("…остальных отметь позже (сообщение ограничено кнопками)")
    if not merged:
        lines.append("Записавшихся «приду» не было.")
    vm = OutMessageVM(kind="menu", text="\n".join(lines))
    vm.buttons = buttons
    return vm


def toggle_attendance(s, event_id: int, key: str) -> bool:
    """key: 'p:<person_id>' или 'a:<account_id>'. True — отмечен."""
    if key.startswith("p:"):
        return repo.toggle_attendance(s, event_id, int(key[2:]), None)
    return repo.toggle_attendance(s, event_id, None, int(key[2:]))
