"""BLL: построение ViewModel контента и fan-out через outbox.

v5 — чисто ЛС-модель: карточки (dm_card) и уведомления (dm_notice) в ЛС ботов
(VK-подписчики + слинкованные TG). Стены и канала нет.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import update

from dal import repositories as repo
from dal.database import from_db, now_utc, to_db
from dal.models import Account, Event, Post

from config import Config
from .contracts import ButtonVM, OutMessageVM, vm_hash
from .summary import VoteRow, build_event_vm

ALL_POST_KINDS = ["dm_card"]


def display_for(s, account) -> tuple[str, str | None]:
    """Имя для списков: у слинкованной персоны — имя ВК-аккаунта, без метки."""
    if account.person_id:
        vk = repo.vk_account_for_person(s, account.person_id)
        if vk is not None:
            return vk.display_name or str(vk.platform_user_id), None
    if account.platform == "vk":
        return account.display_name or str(account.platform_user_id), None
    return account.display_name or str(account.platform_user_id), "TG"


def load_vote_rows(s, event_id: int) -> list[VoteRow]:
    rows = repo.votes_with_accounts(s, event_id)
    person_ids = [a.person_id for _, a in rows if a.person_id]
    counts: dict[int, int] = {}
    if person_ids:
        for acc in repo.accounts_for_persons(s, list(set(person_ids))):
            counts[acc.person_id] = counts.get(acc.person_id, 0) + 1
    out = []
    for v, a in rows:
        name, tag = display_for(s, a)
        out.append(
            VoteRow(
                answer=v.answer,
                prev_answer=v.prev_answer if v.changes_count else None,
                changes_count=v.changes_count or 0,
                updated_at=from_db(v.updated_at),
                display_name=name,
                platform=a.platform,
                person_id=a.person_id,
                person_accounts_count=counts.get(a.person_id, 1) if a.person_id else 1,
                tag=tag,
            )
        )
    return out


def event_vm(s, cfg: Config, event: Event):
    return build_event_vm(
        event_id=event.id,
        title=event.title,
        starts_at=from_db(event.starts_at),
        ends_at=from_db(event.ends_at),
        status=event.status,
        cancelled=event.cancelled,
        place=event.place,
        note=event.note,
        votes=load_vote_rows(s, event.id),
        tz=cfg.tz,
    )


def _vote_buttons(event: Event) -> list[list[ButtonVM]]:
    if event.status != "active":
        return []
    return [
        [
            ButtonVM(action="vote", label="✅ Приду", value="yes", event_id=event.id),
            ButtonVM(action="vote", label="🤔 Возможно", value="maybe", event_id=event.id),
        ],
        [
            ButtonVM(action="vote", label="❌ Не приду", value="no", event_id=event.id),
            ButtonVM(action="remove_vote", label="🗑 Снять ответ", event_id=event.id),
        ],
    ]


def announcement_section(s, cfg: Config, content_type: str, content_id: int) -> str | None:
    """Секция «📢 Объявления» для карточки (последние 5)."""
    anns = repo.announcements_for(s, content_type, content_id)
    if not anns:
        return None
    lines = [f"• {a.text[:120]}" for a in anns[:5]]
    if len(anns) > 5:
        lines.append(f"…и ещё {len(anns) - 5}")
    return "📢 Объявления:\n" + "\n".join(lines)


def vm_for_post(s, cfg: Config, event: Event, kind: str) -> OutMessageVM:
    vm = OutMessageVM(kind=kind, event=event_vm(s, cfg, event))
    section = announcement_section(s, cfg, "event", event.id)
    if section:
        vm.text = section
    if kind == "dm_card":
        vm.buttons = _vote_buttons(event)
    return vm


# --- fan-out ------------------------------------------------------------------


def fan_out_new(s, cfg: Config, event: Event) -> dict[str, int]:
    """Публикация события: карточки в ЛС (VK-подписчики + слинкованные TG) + напоминания."""
    counts = {"dm": 0}

    for sub, acc in repo.active_subscriptions(s):
        post = repo.create_post(s, "event", event.id, "dm_card", "vk",
                                acc.platform_user_id, account_id=acc.id)
        vm = vm_for_post(s, cfg, event, "dm_card")
        repo.enqueue_job(
            s, op="send", platform="vk", chat_id=acc.platform_user_id,
            account_id=acc.id, post_id=post.id, view_model=vm.to_dict(),
            idempotency_key=f"send:{post.id}",
        )
        repo.update_post(s, post.id, vm_hash=vm_hash(vm))
        counts["dm"] += 1

    for acc in repo.tg_linked_accounts(s):
        post = repo.create_post(s, "event", event.id, "dm_card", "tg",
                                acc.platform_user_id, account_id=acc.id)
        vm = vm_for_post(s, cfg, event, "dm_card")
        repo.enqueue_job(
            s, op="send", platform="tg", chat_id=acc.platform_user_id,
            account_id=acc.id, post_id=post.id, view_model=vm.to_dict(),
            idempotency_key=f"send:{post.id}",
        )
        repo.update_post(s, post.id, vm_hash=vm_hash(vm))
        counts["dm"] += 1

    _schedule_reminders(s, cfg, event)
    return counts


def _schedule_reminders(s, cfg: Config, event: Event) -> None:
    now = now_utc()
    starts = event.starts_at  # naive UTC в БД
    items = []
    for h in cfg.reminder_hours:
        at = starts - dt.timedelta(hours=h)
        if at > now:
            items.append((f"h{h:g}", at))
    repo.replace_reminders(s, "event", event.id, items)


def ensure_dm_card_content(
    s, cfg: Config, content_type: str, content_id: int, account_id: int,
    platform: str, chat_id: str, vm: OutMessageVM,
) -> None:
    """Карточка контента для подписчика (создание/восстановление, без дублей)."""
    post = repo.get_post_for(s, content_type, content_id, "dm_card", account_id=account_id)
    if post is None:
        post = repo.create_post(s, content_type, content_id, "dm_card", platform,
                                chat_id, account_id=account_id)
    if post.status == "blocked":
        return
    if post.status == "deleted" or (post.status == "ok" and not post.message_id):
        h = vm_hash(vm)
        repo.enqueue_job(
            s, op="send", platform=platform, chat_id=chat_id,
            account_id=account_id, post_id=post.id, view_model=vm.to_dict(),
            idempotency_key=f"send:{post.id}:{h}",
        )
        repo.update_post(s, post.id, vm_hash=h, status="pending")
        return
    if post.status == "ok":
        return
    # pending: если задания ещё нет — ставим
    if repo.get_pending_send_for_post(s, post.id) is None:
        h = vm_hash(vm)
        repo.enqueue_job(
            s, op="send", platform=platform, chat_id=chat_id,
            account_id=account_id, post_id=post.id, view_model=vm.to_dict(),
            idempotency_key=f"send:{post.id}:{h}",
        )
        repo.update_post(s, post.id, vm_hash=h, status="pending")


def ensure_dm_card(s, cfg: Config, event: Event, account_id: int, vk_user_id: int) -> None:
    """Карточка события для VK-подписчика (при подписке/возврате)."""
    ensure_dm_card_content(
        s, cfg, "event", event.id, account_id, "vk", str(vk_user_id),
        vm_for_post(s, cfg, event, "dm_card"),
    )


def ensure_dm_cards_for_tg(s, cfg: Config, tg_account) -> None:
    """Все активные карточки для слинкованного TG-аккаунта (при линковке)."""
    for ev in repo.open_events(s):
        vm = vm_for_post(s, cfg, ev, "dm_card")
        ensure_dm_card_content(
            s, cfg, "event", ev.id, tg_account.id, "tg",
            str(tg_account.platform_user_id), vm,
        )
    from .polls import vm_for_poll_post
    for p in repo.open_polls(s):
        vm = vm_for_poll_post(s, cfg, p.id, "dm_card", tg_account.id)
        ensure_dm_card_content(
            s, cfg, "poll", p.id, tg_account.id, "tg",
            str(tg_account.platform_user_id), vm,
        )


def drop_dm_cards(s, account_id: int) -> None:
    """Карточки отписавшегося/вышедшего больше не редактируем."""
    s.execute(
        update(Post).where(Post.account_id == account_id, Post.kind == "dm_card")
        .values(status="deleted")
    )


def vm_for_content_post(s, cfg: Config, content_type: str, content_id: int,
                        post: Post) -> OutMessageVM | None:
    """ViewModel карточки контента (событие или опрос; персональная)."""
    if content_type == "poll":
        from .polls import vm_for_poll_post
        return vm_for_poll_post(s, cfg, content_id, post.kind, post.account_id)
    event = repo.get_event(s, content_id)
    if event is None:
        return None
    return vm_for_post(s, cfg, event, post.kind)


def refresh_content(s, cfg: Config, content_type: str, content_id: int) -> None:
    """Обновить карточки контента (edit существующих / отправка утраченных).

    Одно pending-задание на пост: свежая версия обновляет VM на месте.
    """
    for post in repo.posts_for_content(s, content_type, content_id, ALL_POST_KINDS):
        if post.status == "blocked":
            continue
        vm = vm_for_content_post(s, cfg, content_type, content_id, post)
        if vm is None:
            continue
        h = vm_hash(vm)
        if post.status == "ok" and post.message_id and post.vm_hash == h:
            continue
        if post.status == "ok" and post.message_id:
            in_flight = repo.get_sending_job_for_post(s, post.id, "edit")
            if in_flight is None:
                existing = repo.get_pending_job_for_post(s, post.id, "edit")
                if existing is not None:
                    repo.update_job_vm(s, existing.id, vm.to_dict(), f"edit:{post.id}:cur")
                else:
                    repo.enqueue_job(
                        s, op="edit", platform=post.platform, chat_id=post.chat_id,
                        account_id=post.account_id, post_id=post.id,
                        view_model=vm.to_dict(), idempotency_key=f"edit:{post.id}:{h}",
                    )
            else:
                # правка уже в полёте — кладём отдельное задание с финальным
                # состоянием: оно уйдёт следом (иначе карточка останется устаревшей)
                repo.enqueue_job(
                    s, op="edit", platform=post.platform, chat_id=post.chat_id,
                    account_id=post.account_id, post_id=post.id,
                    view_model=vm.to_dict(), idempotency_key=f"edit:{post.id}:{h}",
                )
        else:
            existing = repo.get_pending_send_for_post(s, post.id)
            if existing is not None:
                repo.update_job_vm(s, existing.id, vm.to_dict(), f"send:{post.id}:cur")
            else:
                repo.enqueue_job(
                    s, op="send", platform=post.platform, chat_id=post.chat_id,
                    account_id=post.account_id, post_id=post.id,
                    view_model=vm.to_dict(), idempotency_key=f"send:{post.id}:{h}",
                )
        repo.update_post(s, post.id, vm_hash=h)


# --- уведомления ----------------------------------------------------------------


def notice_dm_tracked(
    s, cfg: Config, text: str, *, announcements_only: bool = False,
    content_type: str = "announcement", content_id: int = 0,
    media: list | None = None,
) -> int:
    """Уведомление в ЛС с TTL-трекингом: пост dm_notice на подписчика.

    Схлопывание: повторное уведомление по тому же контенту редактирует
    предыдущее сообщение (одно уведомление на контент на подписчика).
    Ключ идемпотентности — по хешу текста (одинаковый текст не дублируется).
    """
    sent = 0
    vm = OutMessageVM(
        kind="announcement" if announcements_only else "notice",
        text=text, media=media or [],
    )
    h = vm_hash(vm)
    fresh: list[tuple[Post, Account]] = []
    for sub, acc in repo.active_subscriptions(s):
        if announcements_only and not sub.send_announcements:
            continue
        key = f"dm:{content_type}:{content_id}:{acc.id}:{h[:12]}"
        post = repo.get_post_for(s, content_type, content_id, "dm_notice", account_id=acc.id)
        if post is None:
            post = repo.create_post(s, content_type, content_id, "dm_notice", "vk",
                                    acc.platform_user_id, account_id=acc.id)
        if post.status == "ok" and post.message_id:
            existing = repo.get_pending_job_for_post(s, post.id, "edit")
            if existing is not None:
                repo.update_job_vm(s, existing.id, vm.to_dict(), key)
            else:
                repo.enqueue_job(
                    s, op="edit", platform="vk", chat_id=acc.platform_user_id,
                    account_id=acc.id, post_id=post.id, view_model=vm.to_dict(),
                    idempotency_key=key,
                )
            repo.update_post(s, post.id, vm_hash=h)
            sent += 1
        else:
            existing = repo.get_pending_send_for_post(s, post.id)
            if existing is not None:
                repo.update_job_vm(s, existing.id, vm.to_dict(), key)
            else:
                fresh.append((post, acc))
            repo.update_post(s, post.id, vm_hash=h)
            sent += 1

    # свежие VK-уведомления без медиа — батчами до 100 адресатов (user_ids)
    if fresh and not media:
        for i in range(0, len(fresh), 100):
            batch = fresh[i:i + 100]
            bulk_vm = {
                "kind": vm.kind,
                "text": text,
                "users": [[acc.id, acc.platform_user_id, post.id] for post, acc in batch],
            }
            repo.enqueue_job(
                s, op="send", platform="vk_bulk", chat_id="bulk",
                view_model=bulk_vm,
                idempotency_key=f"bulk:{h[:12]}:{batch[0][0].id}",
            )
    else:
        for post, acc in fresh:
            repo.enqueue_job(
                s, op="send", platform="vk", chat_id=acc.platform_user_id,
                account_id=acc.id, post_id=post.id, view_model=vm.to_dict(),
                idempotency_key=f"dm:{content_type}:{content_id}:{acc.id}:{h[:12]}",
            )

    # TG: слинкованным, если уведомления включены
    for acc in repo.tg_linked_accounts(s):
        if not acc.tg_dm_notifications:
            continue
        key = f"dm:{content_type}:{content_id}:{acc.id}:{h[:12]}"
        post = repo.get_post_for(s, content_type, content_id, "dm_notice", account_id=acc.id)
        if post is None:
            post = repo.create_post(s, content_type, content_id, "dm_notice", "tg",
                                    acc.platform_user_id, account_id=acc.id)
        if post.status == "ok" and post.message_id:
            existing = repo.get_pending_job_for_post(s, post.id, "edit")
            if existing is not None:
                repo.update_job_vm(s, existing.id, vm.to_dict(), key)
            else:
                repo.enqueue_job(
                    s, op="edit", platform="tg", chat_id=acc.platform_user_id,
                    account_id=acc.id, post_id=post.id, view_model=vm.to_dict(),
                    idempotency_key=key,
                )
        else:
            existing = repo.get_pending_send_for_post(s, post.id)
            if existing is not None:
                repo.update_job_vm(s, existing.id, vm.to_dict(), key)
            else:
                repo.enqueue_job(
                    s, op="send", platform="tg", chat_id=acc.platform_user_id,
                    account_id=acc.id, post_id=post.id, view_model=vm.to_dict(),
                    idempotency_key=key,
                )
        repo.update_post(s, post.id, vm_hash=h)
        sent += 1
    return sent


def notice_dm_reply_cards(
    s, cfg: Config, text: str, *, content_type: str, content_id: int, unique: str,
) -> int:
    """Напоминание reply'ем на карточку каждого подписчика (VK + TG)."""
    sent = 0
    for sub, acc in repo.active_subscriptions(s):
        post = repo.get_post_for(s, content_type, content_id, "dm_card", account_id=acc.id)
        reply_to = post.message_id if (post and post.status == "ok" and post.message_id) else None
        vm = OutMessageVM(kind="notice", text=text, reply_to=reply_to)
        repo.enqueue_job(
            s, op="send", platform="vk", chat_id=acc.platform_user_id,
            account_id=acc.id, view_model=vm.to_dict(),
            idempotency_key=f"rem:{unique}:{acc.id}",
        )
        sent += 1
    for acc in repo.tg_linked_accounts(s):
        if not acc.tg_dm_notifications:
            continue
        post = repo.get_post_for(s, content_type, content_id, "dm_card", account_id=acc.id)
        reply_to = post.message_id if (post and post.status == "ok" and post.message_id) else None
        vm = OutMessageVM(kind="notice", text=text, reply_to=reply_to)
        repo.enqueue_job(
            s, op="send", platform="tg", chat_id=acc.platform_user_id,
            account_id=acc.id, view_model=vm.to_dict(),
            idempotency_key=f"rem:{unique}:{acc.id}",
        )
        sent += 1
    return sent


def ensure_all_cards_for_user(s, cfg: Config, acc, platform: str, chat_id: str) -> int:
    """Единая точка актуализации карточек пользователя (все активные контенты).

    Используется при подписке/возврате из академа/линковке и периодической
    джобой сверки — в одном месте решает «что у пользователя есть и актуально».
    """
    given = 0
    for ev in repo.open_events(s):
        ensure_dm_card_content(
            s, cfg, "event", ev.id, acc.id, platform, chat_id,
            vm_for_post(s, cfg, ev, "dm_card"),
        )
        given += 1
    from .polls import vm_for_poll_post
    for p in repo.open_polls(s):
        ensure_dm_card_content(
            s, cfg, "poll", p.id, acc.id, platform, chat_id,
            vm_for_poll_post(s, cfg, p.id, "dm_card", acc.id),
        )
        given += 1
    return given


def wall_log(s, cfg: Config, text: str, unique: str) -> bool:
    """Лог завершённых событий/опросов постом в сообщество ВК (только создание)."""
    if not (cfg.vk_group_id and cfg.wall_log):
        return False
    vm = OutMessageVM(kind="notice", text=text)
    repo.enqueue_job(
        s, op="send", platform="vk_wall", chat_id=f"-{cfg.vk_group_id}",
        view_model=vm.to_dict(), idempotency_key=f"walllog:{unique}",
    )
    return True


def notice_admins(s, cfg: Config, text: str, unique: str,
                  admins: set[int] | None = None) -> None:
    """Уведомление всем текущим админам (руководители из API + конфиг)."""
    targets = admins if admins is not None else set(cfg.admin_vk_ids)
    for uid in targets:
        acc = repo.ensure_account(s, "vk", uid)
        vm = OutMessageVM(kind="notice", text=text)
        repo.enqueue_job(
            s, op="send", platform="vk", chat_id=uid, account_id=acc.id,
            view_model=vm.to_dict(), idempotency_key=f"admin:{unique}:{uid}",
        )
