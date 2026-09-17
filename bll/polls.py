"""BLL: опросы — создание, публикация, голоса-тумблеры, закрытие."""
from __future__ import annotations

import datetime as dt
import json
import re

from sqlalchemy import select

from dal import repositories as repo
from dal.database import from_db, now_utc, to_db
from dal.models import Poll, PollVote

from config import Config
from .contracts import ButtonVM, OutMessageVM, vm_hash
from .publication import (
    announcement_section,
    display_for,
    notice_admins,
    notice_dm_tracked,
    wall_log,
)
from .summary import PollRow, build_poll_vm, fmt_time
from .timeparse import parse_when

TOASTS = {
    "ok": "Выбрано ✅",
    "off": "Выбор снят",
    "cleared": "Выборы сняты",
    "closed": "🔒 Опрос закрыт",
    "not_active": "Опрос не активен",
    "no_poll": "Опрос не найден",
    "bad_option": "Нет такого варианта",
}

POLL_STATUS_LINES = {"closed": "🔒 Опрос закрыт", "cancelled": "❌ ОТМЕНЕНО"}


def parse_poll_command(text: str, cfg: Config, now: dt.datetime) -> tuple[dict | None, str | None]:
    """«/создать опрос Вопрос; вариант1; …; [несколько]; [до 20.09 19:00]»"""
    raw = re.sub(r"^/(создать\s+опрос|опрос|poll)\s*", "", text.strip(),
                 flags=re.IGNORECASE).strip()
    if not raw:
        return None, "пустой запрос: /создать опрос Вопрос; вариант1; вариант2; …"
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    if len(parts) < 3:
        return None, "нужны вопрос и минимум 2 варианта"
    title = parts[0]
    multichoice = False
    closes_at: dt.datetime | None = None
    options: list[dict] = []
    for p in parts[1:]:
        low = p.lower()
        if low in ("несколько", "multi", "несколько вариантов"):
            multichoice = True
        elif low.startswith("до "):
            parsed = parse_when(p[3:].strip(), cfg.tz, now)
            if parsed is None:
                return None, f"не поняла срок «{p}»"
            closes_at = parsed[0]
        elif len(options) >= cfg.poll_max_options:
            return None, f"вариантов не больше {cfg.poll_max_options}"
        else:
            options.append({"idx": len(options), "text": p})
    if len(options) < 2:
        return None, "нужно минимум 2 варианта"
    return {
        "title": title, "options": options,
        "multichoice": multichoice, "closes_at": closes_at,
    }, None


def create_draft(s, cfg: Config, admin_account_id: int | None, parsed: dict) -> Poll:
    return repo.create_poll(
        s, title=parsed["title"], options=parsed["options"],
        multichoice=parsed["multichoice"],
        closes_at=to_db(parsed["closes_at"]) if parsed["closes_at"] else None,
        created_by=admin_account_id,
    )


def load_poll_rows(s, poll_id: int) -> list[PollRow]:
    rows = []
    for v, a in repo.poll_votes_with_accounts(s, poll_id):
        name, tag = display_for(s, a)
        rows.append(PollRow(
            option_id=v.option_id, active=v.active, updated_at=from_db(v.updated_at),
            display_name=name, tag=tag, platform=a.platform, person_id=a.person_id,
        ))
    return rows


def closes_line(poll: Poll, cfg: Config) -> str | None:
    if poll.closes_at is None:
        return None
    return f"до {from_db(poll.closes_at).astimezone(cfg.tz).strftime('%d.%m %H:%M')}"


def poll_vm(s, cfg: Config, poll: Poll):
    return build_poll_vm(
        poll_id=poll.id, title=poll.title, multichoice=poll.multichoice,
        closes_line=closes_line(poll, cfg),
        status_line=POLL_STATUS_LINES.get(poll.status) or ("❌ ОТМЕНЕНО" if poll.cancelled else None),
        options=json.loads(poll.options or "[]"),
        rows=load_poll_rows(s, poll.id),
        tz=cfg.tz,
    )


def poll_buttons(poll: Poll, selected: set[int]) -> list[list[ButtonVM]]:
    rows: list[list[ButtonVM]] = []
    options = json.loads(poll.options or "[]")
    for i in range(0, len(options), 2):
        row = []
        for o in options[i:i + 2]:
            mark = "✅ " if o["idx"] in selected else ""
            row.append(ButtonVM(
                action="poll", label=f"{mark}{o['idx'] + 1} {o['text']}",
                value=str(o["idx"]), event_id=poll.id,
            ))
        rows.append(row)
    rows.append([ButtonVM(action="poll_clear", label="🗑 Снять выборы", event_id=poll.id)])
    return rows


def vm_for_poll_post(s, cfg: Config, poll_id: int, kind: str,
                     account_id: int | None = None) -> OutMessageVM | None:
    poll = repo.get_poll(s, poll_id)
    if poll is None:
        return None
    vm = OutMessageVM(kind=kind, poll=poll_vm(s, cfg, poll))
    section = announcement_section(s, cfg, "poll", poll.id)
    if section:
        vm.text = section
    if kind == "dm_card" and poll.status == "active":
        # ✅ на кнопках — выбор ПЕРСОНЫ (её VK- и TG-аккаунтов вместе)
        acc = repo.get_account(s, account_id) if account_id is not None else None
        selected = repo.selected_poll_options_for_person(s, poll.id, acc) if acc else set()
        vm.buttons = poll_buttons(poll, selected)
    return vm


def preview_vm(s, cfg: Config, poll: Poll) -> OutMessageVM:
    vm = OutMessageVM(kind="preview", poll=poll_vm(s, cfg, poll))
    vm.text = (
        "Проверь опрос. Если что-то не так — «Отмена» и пришли команду заново.\n"
        f"ID: #{poll.id}"
    )
    vm.buttons = [
        [ButtonVM(action="publish", label="🚀 Опубликовать", event_id=poll.id)],
        [ButtonVM(action="cancel_draft", label="🗑 Отмена", event_id=poll.id)],
    ]
    return vm


def publish(s, cfg: Config, poll_id: int) -> dict[str, int] | str:
    poll = repo.get_poll(s, poll_id)
    if poll is None or poll.status != "draft":
        return "Черновик не найден (возможно, уже опубликован)."
    repo.update_poll(s, poll_id, {"status": "active"})
    poll = repo.get_poll(s, poll_id)
    counts = fan_out_new(s, cfg, poll)
    _schedule_poll_reminders(s, cfg, poll)
    return counts


def fan_out_new(s, cfg: Config, poll: Poll) -> dict[str, int]:
    counts = {"dm": 0}

    for sub, acc in repo.active_subscriptions(s):
        post = repo.create_post(s, "poll", poll.id, "dm_card", "vk",
                                acc.platform_user_id, account_id=acc.id)
        vm = vm_for_poll_post(s, cfg, poll.id, "dm_card", acc.id)
        repo.enqueue_job(
            s, op="send", platform="vk", chat_id=acc.platform_user_id,
            account_id=acc.id, post_id=post.id, view_model=vm.to_dict(),
            idempotency_key=f"send:{post.id}",
        )
        repo.update_post(s, post.id, vm_hash=vm_hash(vm))
        counts["dm"] += 1

    for acc in repo.tg_linked_accounts(s):
        post = repo.create_post(s, "poll", poll.id, "dm_card", "tg",
                                acc.platform_user_id, account_id=acc.id)
        vm = vm_for_poll_post(s, cfg, poll.id, "dm_card", acc.id)
        repo.enqueue_job(
            s, op="send", platform="tg", chat_id=acc.platform_user_id,
            account_id=acc.id, post_id=post.id, view_model=vm.to_dict(),
            idempotency_key=f"send:{post.id}",
        )
        repo.update_post(s, post.id, vm_hash=vm_hash(vm))
        counts["dm"] += 1

    return counts


def ensure_poll_card(s, cfg: Config, poll_id: int, account_id: int,
                     platform: str, chat_id: str) -> None:
    """Карточка опроса для подписчика (подписка/возврат/линковка)."""
    from .publication import ensure_dm_card_content
    vm = vm_for_poll_post(s, cfg, poll_id, "dm_card", account_id)
    ensure_dm_card_content(s, cfg, "poll", poll_id, account_id, platform, chat_id, vm)


def _schedule_poll_reminders(s, cfg: Config, poll: Poll) -> None:
    if poll.closes_at is None:
        return
    now = now_utc()
    items = []
    for h in cfg.reminder_hours:
        at = poll.closes_at - dt.timedelta(hours=h)
        if at > now:
            items.append((f"h{h:g}", at))
    repo.replace_reminders(s, "poll", poll.id, items)


# --- голоса -----------------------------------------------------------------------


def cast_poll_vote(s, cfg: Config, platform: str, user_id: int, poll_id: int,
                   option_id: int) -> str:
    poll = repo.get_poll(s, poll_id)
    if poll is None:
        return "no_poll"
    if poll.cancelled or poll.status in ("cancelled",):
        return "not_active"
    if poll.status != "active":
        return "closed"
    options = json.loads(poll.options or "[]")
    if not any(o["idx"] == option_id for o in options):
        return "bad_option"

    acc = repo.ensure_account(s, platform, user_id)
    if not poll.multichoice:
        # одиночный выбор — один на ПЕРСОНУ: гасим варианты других аккаунтов тоже
        person_ids = _person_account_ids(s, acc)
        for v, _a in repo.poll_votes_with_accounts(s, poll_id):
            if v.account_id in person_ids and v.active and v.option_id != option_id:
                repo.toggle_poll_vote(s, poll_id, v.account_id, v.option_id)
    v, changed, now_active = repo.toggle_poll_vote(s, poll_id, acc.id, option_id)
    if changed:
        from .publication import refresh_content
        refresh_content(s, cfg, "poll", poll_id)
    return "ok" if now_active else "off"


def _person_account_ids(s, acc) -> set[int]:
    """Все аккаунты персоны (для кросс-платформенных снятий/выборов)."""
    ids = {acc.id}
    if acc.person_id:
        for a in repo.accounts_for_persons(s, [acc.person_id]):
            ids.add(a.id)
    return ids


def clear_poll_votes(s, cfg: Config, platform: str, user_id: int, poll_id: int) -> str:
    poll = repo.get_poll(s, poll_id)
    if poll is None:
        return "no_poll"
    if poll.status != "active":
        return "closed"
    acc = repo.ensure_account(s, platform, user_id)
    person_ids = _person_account_ids(s, acc)
    changed = False
    for v, _a in repo.poll_votes_with_accounts(s, poll_id):
        if v.account_id in person_ids and v.active:
            repo.toggle_poll_vote(s, poll_id, v.account_id, v.option_id)
            changed = True
    if changed:
        from .publication import refresh_content
        refresh_content(s, cfg, "poll", poll_id)
    return "cleared" if changed else "cleared"


def set_poll_choices(s, cfg: Config, platform: str, user_id: int, poll_id: int,
                     idxs: set[int]) -> str:
    """Текстовый fallback: «2» или «1,3» — выставить выборы."""
    poll = repo.get_poll(s, poll_id)
    if poll is None:
        return "no_poll"
    if poll.cancelled or poll.status != "active":
        return "closed"
    options = json.loads(poll.options or "[]")
    valid = {o["idx"] for o in options}
    idxs = idxs & valid
    if not idxs:
        return "bad_option"
    if not poll.multichoice:
        idxs = {sorted(idxs)[0]}
    acc = repo.ensure_account(s, platform, user_id)
    person_ids = _person_account_ids(s, acc)
    changed = False
    # снять активные (у всех аккаунтов персоны), которых нет в запрошенных
    for v, _a in repo.poll_votes_with_accounts(s, poll_id):
        if v.account_id in person_ids and v.active and v.option_id not in idxs:
            repo.toggle_poll_vote(s, poll_id, v.account_id, v.option_id)
            changed = True
    for idx in idxs:
        row = s.scalar(
            select(PollVote).where(
                PollVote.poll_id == poll_id, PollVote.account_id == acc.id,
                PollVote.option_id == idx,
            )
        )
        if row is None or not row.active:
            repo.toggle_poll_vote(s, poll_id, acc.id, idx)
            changed = True
    if changed:
        from .publication import refresh_content
        refresh_content(s, cfg, "poll", poll_id)
    return "ok"


# --- жизненный цикл ------------------------------------------------------------------


def close(s, cfg: Config, poll_id: int, auto: bool = False,
          admins: set[int] | None = None) -> str | None:
    poll = repo.get_poll(s, poll_id)
    if poll is None or poll.status != "active":
        return None
    repo.update_poll(s, poll_id, {"status": "closed", "closed_at": now_utc(),
                                  "auto_closed": poll.auto_closed or auto})
    poll = repo.get_poll(s, poll_id)
    from .publication import refresh_content
    refresh_content(s, cfg, "poll", poll_id)
    text = f"🔒 Опрос закрыт: #{poll.id} «{poll.title}»." + poll_summary_line(s, cfg, poll)
    wall_log(s, cfg, text + f"\n#{poll.id}", unique=f"poll{poll_id}:closed")
    notice_dm_tracked(s, cfg, text,
                      content_type="poll", content_id=poll_id)
    notice_admins(s, cfg, text, unique=f"poll{poll_id}:closed", admins=admins)
    return text


def reopen(s, cfg: Config, poll_id: int) -> str | None:
    """Открыть опрос заново (после ручного/авто-закрытия)."""
    poll = repo.get_poll(s, poll_id)
    if poll is None or poll.status != "closed":
        return None
    if poll.closes_at is not None and poll.closes_at <= now_utc():
        return "Срок опроса уже прошёл — открыть его нельзя."
    repo.update_poll(s, poll_id, {"status": "active", "closed_at": None})
    poll = repo.get_poll(s, poll_id)
    from .publication import refresh_content
    refresh_content(s, cfg, "poll", poll_id)
    text = f"🔓 Опрос снова открыт: #{poll.id} «{poll.title}»."
    notice_dm_tracked(s, cfg, text,
                      content_type="poll", content_id=poll_id)
    return text


def cancel(s, cfg: Config, poll_id: int, admins: set[int] | None = None) -> None:
    poll = repo.get_poll(s, poll_id)
    if poll is None or poll.status in ("cancelled",):
        return
    repo.update_poll(s, poll_id, {"status": "cancelled", "cancelled": True})
    poll = repo.get_poll(s, poll_id)
    from .publication import refresh_content
    refresh_content(s, cfg, "poll", poll_id)
    text = f"❌ Опрос #{poll.id} «{poll.title}» отменён."
    notice_dm_tracked(s, cfg, text,
                      content_type="poll", content_id=poll_id)
    notice_admins(s, cfg, text, unique=f"poll{poll_id}:cancel", admins=admins)


def poll_summary_line(s, cfg: Config, poll: Poll) -> str:
    vm = poll_vm(s, cfg, poll)
    parts = [f"{o.idx + 1} {o.text} — {len([e for e in o.entries if not e.struck_at])}"
             for o in vm.options]
    return "\nИтоги: " + " · ".join(parts) if parts else ""


def listing_text(s, cfg: Config) -> str:
    polls = repo.open_polls(s)
    if not polls:
        return "Активных опросов нет."
    lines = []
    for p in sorted(polls, key=lambda x: x.id):
        vm = poll_vm(s, cfg, p)
        total = sum(len([e for e in o.entries if not e.struck_at]) for o in vm.options)
        flag = "🔒 " if p.status == "closed" else ""
        line = f"{flag}#{p.id}. 🗳 «{p.title}»"
        if p.closes_at:
            line += f" — {closes_line(p, cfg)}"
        line += f" · голосов: {total}"
        lines.append(line)
    return "\n".join(lines)


def admin_listing_vm(s, cfg: Config) -> OutMessageVM:
    """Компактный список опросов админа со ссылками и [⚙️ #id]."""
    polls = repo.open_polls(s)
    if not polls:
        return OutMessageVM(kind="menu", text="Активных опросов нет.")
    lines: list[str] = []
    buttons: list[list[ButtonVM]] = []
    for p in sorted(polls, key=lambda x: x.id)[:9]:
        vm = poll_vm(s, cfg, p)
        total = sum(len([e for e in o.entries if not e.struck_at]) for o in vm.options)
        reach = len([x for x in repo.posts_for_content(s, "poll", p.id, ["dm_card"])
                     if x.status != "deleted"])
        flag = "🔒 " if p.status == "closed" else ""
        line = f"{flag}#{p.id} 🗳 «{p.title}»"
        if p.closes_at:
            line += f" · {closes_line(p, cfg)}"
        lines.append(line + f" · голосов: {total} · 👀{reach}")
        buttons.append([ButtonVM(action="panel", label=f"⚙️ #{p.id}", event_id=p.id)])
    if len(polls) > 9:
        lines.append(f"…и ещё {len(polls) - 9}")
    return OutMessageVM(kind="menu", text="\n".join(lines), buttons=buttons)


def apply_poll_values(s, cfg: Config, poll_id: int, values: dict) -> tuple[list[str], str | None]:
    """Применить готовые значения (из /edit)."""
    poll = repo.get_poll(s, poll_id)
    if poll is None or poll.status not in ("active", "closed"):
        return [], "Опрос не найден или неактивен."
    human: list[str] = []
    if values.get("title") is not None and values["title"] != poll.title:
        human.append(f"вопрос → {values['title']}")
    if values.get("multichoice") is not None and values["multichoice"] != poll.multichoice:
        human.append("несколько вариантов" if values["multichoice"] else "один вариант")
    if "closes_at" in values and values["closes_at"] != poll.closes_at:
        human.append("срок обновлён")
    repo.update_poll(s, poll_id, values)
    poll = repo.get_poll(s, poll_id)
    from .publication import refresh_content
    refresh_content(s, cfg, "poll", poll_id)
    _schedule_poll_reminders(s, cfg, poll)
    text_notice = f"⚠️ Изменение опроса #{poll.id} «{poll.title}»"
    if human:
        text_notice += ": " + "; ".join(human)
    notice_dm_tracked(s, cfg, text_notice,
                      content_type="poll", content_id=poll_id)
    return human, None


def apply_poll_edit(s, cfg: Config, poll_id: int, text: str) -> tuple[list[str] | None, str | None]:
    """«/edit 13 Вопрос; [несколько]; [до 20.09 19:00]» — варианты не редактируются."""
    poll = repo.get_poll(s, poll_id)
    if poll is None or poll.status not in ("active", "closed"):
        return None, "Опрос не найден или неактивен."
    parts = [p.strip() for p in text.split(";") if p.strip()]
    if not parts:
        return None, f"Формат: /edit {poll_id} Вопрос; [несколько|один]; [до 20.09 19:00]"
    title = parts[0]
    multichoice = poll.multichoice
    closes_at = poll.closes_at
    for p in parts[1:]:
        low = p.lower()
        if low in ("несколько", "multi", "несколько вариантов"):
            multichoice = True
        elif low in ("один", "один вариант"):
            multichoice = False
        elif low.startswith("до "):
            parsed = parse_when(p[3:].strip(), cfg.tz, dt.datetime.now(cfg.tz))
            if parsed is None:
                return None, f"не поняла срок «{p}»"
            closes_at = to_db(parsed[0])
        else:
            return None, "Варианты после публикации не редактируются."
    return apply_poll_values(
        s, cfg, poll_id,
        {"title": title, "multichoice": multichoice, "closes_at": closes_at},
    )


def delete_draft(s, poll_id: int) -> None:
    poll = repo.get_poll(s, poll_id)
    if poll is not None and poll.status == "draft":
        s.delete(poll)
        s.flush()  # сначала ребёнок (polls), затем родитель (contents)
        content = repo.get_content(s, poll_id)
        if content is not None:
            s.delete(content)


def delete_poll(s, cfg: Config, poll_id: int) -> str | None:
    """Полное удаление опроса: карточки удаляются у всех, данные — из БД."""
    poll = repo.get_poll(s, poll_id)
    if poll is None:
        return "Опрос не найден."
    for post in repo.posts_for_content(s, "poll", poll_id, ["dm_card", "dm_notice"]):
        repo.cancel_pending_jobs_for_post(s, post.id)
        if post.message_id and post.status == "ok":
            repo.enqueue_job(
                s, op="delete", platform=post.platform, chat_id=post.chat_id,
                post_id=post.id, view_model={"kind": "notice"},
                idempotency_key=f"del:{post.id}",
            )
        repo.update_post(s, post.id, status="deleted", vm_hash=None)
    from sqlalchemy import delete as sa_delete
    from dal.models import Announcement, Reminder

    s.execute(sa_delete(PollVote).where(PollVote.poll_id == poll_id))
    s.execute(sa_delete(Announcement).where(Announcement.content_type == "poll",
                                            Announcement.content_id == poll_id))
    s.execute(sa_delete(Reminder).where(Reminder.content_type == "poll",
                                        Reminder.content_id == poll_id))
    s.delete(poll)
    s.flush()  # polls.id → contents.id: удаляем родителя ПОСЛЕ ребёнка, явно
    content = repo.get_content(s, poll_id)
    if content is not None:
        s.delete(content)
    return None


def poll_reminder_text(s, cfg: Config, poll: Poll, hours: str) -> str:
    vm = poll_vm(s, cfg, poll)
    total = sum(len([e for e in o.entries if not e.struck_at]) for o in vm.options)
    return f"⏰ Через {hours} ч закроется опрос «{poll.title}» (голосов: {total})."
