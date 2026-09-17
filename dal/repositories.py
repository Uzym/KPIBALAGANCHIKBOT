"""DAL: репозитории — только доступ к данным, без бизнес-правил."""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import func, select, update

from .database import now_utc
from .models import (
    Account,
    Announcement,
    Appeal,
    AppealMessage,
    Attendance,
    Content,
    Event,
    OutboxJob,
    Person,
    Poll,
    PollVote,
    Post,
    Reminder,
    Subscription,
    Vote,
)

# --- contents ------------------------------------------------------------------


def create_content(s, kind: str) -> Content:
    """Сквозной id карточек: единая нумерация для событий и опросов."""
    c = Content(kind=kind)
    s.add(c)
    s.flush()
    return c


def get_content(s, content_id: int) -> Content | None:
    return s.get(Content, content_id)


# --- persons / accounts ---------------------------------------------------------


def get_or_create_person(s, display_name: str = "") -> Person:
    p = Person(display_name=display_name or "Без имени")
    s.add(p)
    s.flush()
    return p


def ensure_account(
    s,
    platform: str,
    platform_user_id: int,
    display_name: str | None = None,
    username: str | None = None,
) -> Account:
    acc = s.scalar(
        select(Account).where(
            Account.platform == platform, Account.platform_user_id == platform_user_id
        )
    )
    if acc is None:
        acc = Account(platform=platform, platform_user_id=platform_user_id,
                      display_name=display_name or "", username=username)
        s.add(acc)
    else:
        if display_name and acc.display_name != display_name:
            acc.display_name = display_name
        if username and acc.username != username:
            acc.username = username
    s.flush()
    return acc


def get_account_by_platform_id(s, platform: str, platform_user_id: int) -> Account | None:
    return s.scalar(
        select(Account).where(
            Account.platform == platform, Account.platform_user_id == platform_user_id
        )
    )


def get_account(s, account_id: int) -> Account | None:
    return s.get(Account, account_id)


def set_account_mode(s, account_id: int, mode: str) -> None:
    s.execute(update(Account).where(Account.id == account_id).values(mode=mode))


def find_tg_accounts_by_username(s, username: str) -> list[Account]:
    u = username.strip().lstrip("@").lower()
    return list(
        s.scalars(
            select(Account).where(
                Account.platform == "tg", func.lower(func.replace(Account.username, "@", "")) == u
            )
        )
    )


def accounts_for_persons(s, person_ids: list[int]) -> list[Account]:
    if not person_ids:
        return []
    return list(s.scalars(select(Account).where(Account.person_id.in_(person_ids))))


def vk_account_for_person(s, person_id: int) -> Account | None:
    """ВК-аккаунт персоны — имена в списках берутся из ВК."""
    return s.scalar(
        select(Account).where(Account.person_id == person_id, Account.platform == "vk")
    )


def tg_linked_accounts(s) -> list[Account]:
    """Слинкованные TG-аккаунты (получают карточки/уведомления в ЛС)."""
    return list(
        s.scalars(select(Account).where(Account.platform == "tg", Account.person_id.is_not(None)))
    )


# --- subscriptions ----------------------------------------------------------------


def get_subscription(s, account_id: int) -> Subscription | None:
    return s.scalar(select(Subscription).where(Subscription.account_id == account_id))


def upsert_subscription(s, account_id: int, status: str = "active",
                        send_announcements: bool = True) -> Subscription:
    sub = get_subscription(s, account_id)
    if sub is None:
        sub = Subscription(account_id=account_id, status=status,
                           send_announcements=send_announcements, validated_at=now_utc())
        s.add(sub)
    else:
        sub.status = status
        sub.validated_at = now_utc()
    s.flush()
    return sub


def set_subscription_status(s, account_id: int, status: str) -> None:
    s.execute(
        update(Subscription).where(Subscription.account_id == account_id).values(
            status=status, updated_at=now_utc()
        )
    )


def set_send_announcements(s, account_id: int, value: bool) -> None:
    s.execute(
        update(Subscription).where(Subscription.account_id == account_id).values(
            send_announcements=value, updated_at=now_utc()
        )
    )


def active_subscriptions(s) -> list[tuple[Subscription, Account]]:
    rows = s.execute(
        select(Subscription, Account)
        .join(Account, Subscription.account_id == Account.id)
        .where(Subscription.status == "active", Account.platform == "vk")
    ).all()
    return [(sub, acc) for sub, acc in rows]


def subscription_stats(s) -> dict[str, int]:
    rows = s.execute(select(Subscription.status, func.count()).group_by(Subscription.status)).all()
    return dict(rows)


# --- events ------------------------------------------------------------------------


def create_event(s, **kw) -> Event:
    c = create_content(s, "event")
    ev = Event(id=c.id, **kw)
    s.add(ev)
    s.flush()
    return ev


def get_event(s, event_id: int) -> Event | None:
    return s.get(Event, event_id)


def update_event(s, event_id: int, values: dict) -> None:
    if values:
        s.execute(update(Event).where(Event.id == event_id).values(**values, updated_at=now_utc()))


def open_events(s) -> list[Event]:
    """События, которые видны участникам (не черновики, не отменённые/завершённые)."""
    return list(s.scalars(select(Event).where(Event.status.in_(["active", "closed"]))))


def all_events(s) -> list[Event]:
    return list(s.scalars(select(Event).order_by(Event.id)))


def all_polls(s) -> list[Poll]:
    return list(s.scalars(select(Poll).order_by(Poll.id)))


def events_past_start(s, now: dt.datetime) -> list[Event]:
    return list(s.scalars(select(Event).where(Event.status == "active", Event.starts_at <= now)))


def events_past_end(s, now: dt.datetime) -> list[Event]:
    return list(
        s.scalars(
            select(Event).where(
                Event.status.in_(["active", "closed"]), Event.ends_at <= now, Event.cancelled == False  # noqa: E712
            )
        )
    )


# --- votes --------------------------------------------------------------------------


def get_vote(s, event_id: int, account_id: int) -> Vote | None:
    return s.scalar(
        select(Vote).where(Vote.event_id == event_id, Vote.account_id == account_id)
    )


def upsert_vote(s, event_id: int, account_id: int, answer: str) -> tuple[Vote, bool]:
    """Возвращает (голос, changed). Меняет prev_answer/changes_count."""
    v = get_vote(s, event_id, account_id)
    if v is None:
        v = Vote(event_id=event_id, account_id=account_id, answer=answer)
        s.add(v)
        s.flush()
        return v, True
    if v.answer == answer:
        return v, False
    v.prev_answer = v.answer
    v.answer = answer
    v.changes_count = (v.changes_count or 0) + 1
    v.updated_at = now_utc()
    return v, True


def delete_vote(s, event_id: int, account_id: int) -> bool:
    v = get_vote(s, event_id, account_id)
    if v is None:
        return False
    s.delete(v)
    return True


def votes_with_accounts(s, event_id: int) -> list[tuple[Vote, Account]]:
    rows = s.execute(
        select(Vote, Account).join(Account, Vote.account_id == Account.id).where(Vote.event_id == event_id)
    ).all()
    return [(v, a) for v, a in rows]


# --- polls ----------------------------------------------------------------------------


def create_poll(s, *, title: str, options: list[dict], multichoice: bool,
                closes_at: dt.datetime | None, created_by: int | None) -> Poll:
    c = create_content(s, "poll")
    p = Poll(
        id=c.id, title=title,
        options=json.dumps(options, ensure_ascii=False),
        multichoice=multichoice, closes_at=closes_at, created_by=created_by,
        status="draft",
    )
    s.add(p)
    s.flush()
    return p


def get_poll(s, poll_id: int) -> Poll | None:
    return s.get(Poll, poll_id)


def update_poll(s, poll_id: int, values: dict) -> None:
    if values:
        s.execute(update(Poll).where(Poll.id == poll_id).values(**values, updated_at=now_utc()))


def open_polls(s) -> list[Poll]:
    return list(s.scalars(select(Poll).where(Poll.status.in_(["active", "closed"]))))


def polls_due_close(s, now: dt.datetime) -> list[Poll]:
    return list(
        s.scalars(
            select(Poll).where(
                Poll.status == "active", Poll.closes_at.is_not(None), Poll.closes_at <= now
            )
        )
    )


def toggle_poll_vote(s, poll_id: int, account_id: int, option_id: int) -> tuple[PollVote, bool, bool]:
    """Тумблер выбора варианта. Возвращает (строка, changed, now_active)."""
    v = s.scalar(
        select(PollVote).where(
            PollVote.poll_id == poll_id, PollVote.account_id == account_id,
            PollVote.option_id == option_id,
        )
    )
    if v is None:
        v = PollVote(poll_id=poll_id, account_id=account_id, option_id=option_id, active=True)
        s.add(v)
        s.flush()
        return v, True, True
    v.active = not v.active
    v.changes_count = (v.changes_count or 0) + 1
    v.updated_at = now_utc()
    s.flush()
    return v, True, v.active


def poll_votes_with_accounts(s, poll_id: int) -> list[tuple[PollVote, Account]]:
    rows = s.execute(
        select(PollVote, Account).join(Account, PollVote.account_id == Account.id)
        .where(PollVote.poll_id == poll_id)
    ).all()
    return [(v, a) for v, a in rows]


def selected_poll_options(s, poll_id: int, account_id: int | None) -> set[int]:
    if account_id is None:
        return set()
    rows = s.scalars(
        select(PollVote.option_id).where(
            PollVote.poll_id == poll_id,
            PollVote.account_id == account_id,
            PollVote.active == True,  # noqa: E712
        )
    ).all()
    return set(rows)


def selected_poll_options_for_person(s, poll_id: int, account: Account) -> set[int]:
    """Выбранные варианты персоны (все её аккаунты) — для ✅ на кнопках карточки."""
    ids = {account.id}
    if account.person_id:
        for a in accounts_for_persons(s, [account.person_id]):
            ids.add(a.id)
    rows = s.scalars(
        select(PollVote.option_id).where(
            PollVote.poll_id == poll_id,
            PollVote.account_id.in_(ids),
            PollVote.active == True,  # noqa: E712
        )
    ).all()
    return set(rows)


# --- posts -----------------------------------------------------------------------------


def create_post(s, content_type: str, content_id: int, kind: str, platform: str,
                chat_id: str, account_id: int | None = None) -> Post:
    p = Post(content_type=content_type, content_id=content_id, kind=kind, platform=platform,
             chat_id=str(chat_id), account_id=account_id, status="pending")
    s.add(p)
    s.flush()
    return p


def posts_for_content(s, content_type: str, content_id: int,
                      kinds: list[str] | None = None) -> list[Post]:
    q = select(Post).where(Post.content_type == content_type, Post.content_id == content_id)
    if kinds:
        q = q.where(Post.kind.in_(kinds))
    return list(s.scalars(q))


def get_post_for(s, content_type: str, content_id: int, kind: str,
                 account_id: int | None = None) -> Post | None:
    q = select(Post).where(Post.content_type == content_type, Post.content_id == content_id,
                           Post.kind == kind)
    if account_id is None:
        q = q.where(Post.account_id.is_(None))
    else:
        q = q.where(Post.account_id == account_id)
    return s.scalar(q)


def find_post_by_message(s, platform: str, chat_id: str, message_id: int) -> Post | None:
    return s.scalar(
        select(Post).where(
            Post.platform == platform,
            Post.chat_id == str(chat_id),
            Post.message_id == message_id,
        )
    )


def posts_with_message_ids(s) -> list[Post]:
    return list(s.scalars(select(Post).where(Post.message_id.is_not(None))))


def update_post(s, post_id: int, **values) -> None:
    if values:
        s.execute(update(Post).where(Post.id == post_id).values(**values))


# --- announcements -----------------------------------------------------------------------


def create_announcement(s, content_type: str, content_id: int | None,
                        created_by: int | None, text: str, media: str | None = None) -> Announcement:
    a = Announcement(content_type=content_type, content_id=content_id,
                     created_by=created_by, text=text, media=media)
    s.add(a)
    s.flush()
    return a


def announcements_for(s, content_type: str, content_id: int | None) -> list[Announcement]:
    q = select(Announcement).where(Announcement.content_type == content_type)
    if content_id is None:
        q = q.where(Announcement.content_id.is_(None))
    else:
        q = q.where(Announcement.content_id == content_id)
    return list(s.scalars(q.order_by(Announcement.id.desc())))


# --- outbox --------------------------------------------------------------------------------


def enqueue_job(s, *, op: str, platform: str, chat_id: str, view_model: dict,
                idempotency_key: str, thread_id: int | None = None,
                account_id: int | None = None, post_id: int | None = None) -> OutboxJob | None:
    """Идемпотентно среди активных заданий.

    Если задание с ключом ещё pending/sending — дубль, не создаём. Если старое
    уже done/failed — новый ключ получает суффикс `:N` (возврат к ранее бывшему
    состоянию контента должен порождать новую правку).
    """
    key = idempotency_key
    for attempt in range(1, 1000):
        exists = s.scalar(select(OutboxJob.id).where(OutboxJob.idempotency_key == key))
        if exists is None:
            break
        status = s.scalar(select(OutboxJob.status).where(OutboxJob.idempotency_key == key))
        if status in ("pending", "sending"):
            return None
        key = f"{idempotency_key}:{attempt}"
    job = OutboxJob(
        op=op, platform=platform, chat_id=str(chat_id), thread_id=thread_id,
        account_id=account_id, post_id=post_id,
        view_model=json.dumps(view_model, ensure_ascii=False),
        idempotency_key=key,
    )
    s.add(job)
    s.flush()
    return job


def get_pending_job_for_post(s, post_id: int, op: str) -> OutboxJob | None:
    return s.scalar(
        select(OutboxJob).where(
            OutboxJob.post_id == post_id,
            OutboxJob.op == op,
            OutboxJob.status == "pending",
        )
    )


def get_sending_job_for_post(s, post_id: int, op: str) -> OutboxJob | None:
    return s.scalar(
        select(OutboxJob).where(
            OutboxJob.post_id == post_id,
            OutboxJob.op == op,
            OutboxJob.status == "sending",
        )
    )


def get_pending_send_for_post(s, post_id: int) -> OutboxJob | None:
    return get_pending_job_for_post(s, post_id, "send")


def update_job_vm(s, job_id: int, view_model: dict, idempotency_key: str) -> None:
    s.execute(
        update(OutboxJob).where(OutboxJob.id == job_id).values(
            view_model=json.dumps(view_model, ensure_ascii=False),
            idempotency_key=idempotency_key,
        )
    )


def fetch_pending_jobs(s, limit: int = 25) -> list[OutboxJob]:
    now = now_utc()
    jobs = list(
        s.scalars(
            select(OutboxJob)
            .where(OutboxJob.status == "pending", OutboxJob.next_attempt_at <= now)
            .order_by(OutboxJob.id)
            .limit(limit)
        )
    )
    for j in jobs:
        j.status = "sending"
    s.flush()
    return jobs


def reset_sending_jobs(s) -> int:
    """После рестарта «sending»-задания не могли дослаться — возвращаем в pending."""
    r = s.execute(
        update(OutboxJob).where(OutboxJob.status == "sending").values(status="pending")
    )
    return r.rowcount


def finish_job(s, job_id: int, *, sent_message_id: int | None = None,
               retry_in: float | None = None, error: str | None = None,
               fail: bool = False) -> str:
    """Отмечает результат; возвращает 'done' | 'retry' | 'failed' | 'missing'."""
    job = s.get(OutboxJob, job_id)
    if job is None:
        return "missing"
    if fail:
        job.status = "failed"
        job.error = (error or "")[:1000]
        return "failed"
    if retry_in is None:
        job.status = "done"
        job.sent_message_id = sent_message_id
        job.error = None
        return "done"
    job.attempts += 1
    job.error = (error or "")[:1000]
    if job.attempts >= 5:
        job.status = "failed"
        return "failed"
    job.status = "pending"
    job.next_attempt_at = now_utc() + dt.timedelta(seconds=min(3600, 15 * 2 ** job.attempts))
    return "retry"


# --- reminders ------------------------------------------------------------------------------


def replace_reminders(s, content_type: str, content_id: int, items: list[tuple[str, dt.datetime]]) -> None:
    s.query(Reminder).filter(
        Reminder.content_type == content_type,
        Reminder.content_id == content_id,
        Reminder.done == False,  # noqa: E712
    ).delete()
    for kind, at in items:
        s.add(Reminder(content_type=content_type, content_id=content_id, kind=kind, at=at))
    s.flush()


def due_reminders(s, now: dt.datetime) -> list[Reminder]:
    return list(
        s.scalars(
            select(Reminder).where(Reminder.done == False, Reminder.at <= now)  # noqa: E712
        )
    )


def mark_reminder_done(s, reminder_id: int) -> None:
    s.execute(update(Reminder).where(Reminder.id == reminder_id).values(done=True))


# --- обращения -------------------------------------------------------------------


def create_appeal(s, platform: str, member_id: int, member_name: str) -> Appeal:
    a = Appeal(platform=platform, member_id=member_id, member_name=member_name)
    s.add(a)
    s.flush()
    return a


def create_appeal_message(s, appeal_id: int, admin_id: int, message_id: int) -> AppealMessage:
    m = AppealMessage(appeal_id=appeal_id, admin_id=admin_id, message_id=message_id)
    s.add(m)
    s.flush()
    return m


def appeal_message_by_cmid(s, message_id: int) -> AppealMessage | None:
    return s.scalar(select(AppealMessage).where(AppealMessage.message_id == message_id))


def get_appeal(s, appeal_id: int) -> Appeal | None:
    return s.get(Appeal, appeal_id)


def appeal_messages(s, appeal_id: int) -> list[AppealMessage]:
    return list(s.scalars(select(AppealMessage).where(AppealMessage.appeal_id == appeal_id)))


def mark_appeal_answered(s, appeal_message_id: int) -> None:
    s.execute(
        update(AppealMessage).where(AppealMessage.id == appeal_message_id).values(answered=True)
    )


# --- посещаемость -------------------------------------------------------------------


def get_attendance(s, event_id: int, person_id: int | None, account_id: int | None) -> Attendance | None:
    q = select(Attendance).where(Attendance.event_id == event_id)
    if person_id is not None:
        q = q.where(Attendance.person_id == person_id)
    else:
        q = q.where(Attendance.person_id.is_(None), Attendance.account_id == account_id)
    return s.scalar(q)


def toggle_attendance(s, event_id: int, person_id: int | None, account_id: int | None) -> bool:
    """True — отмечен, False — снят."""
    a = get_attendance(s, event_id, person_id, account_id)
    if a is not None:
        s.delete(a)
        return False
    s.add(Attendance(event_id=event_id, person_id=person_id, account_id=account_id))
    s.flush()
    return True


def attendance_for_event(s, event_id: int) -> list[Attendance]:
    return list(s.scalars(select(Attendance).where(Attendance.event_id == event_id)))


# --- служебное ------------------------------------------------------------------------


def cancel_pending_jobs_for_post(s, post_id: int) -> None:
    """Снять pending-задания поста (перед удалением контента/карточек)."""
    s.execute(
        update(OutboxJob).where(
            OutboxJob.post_id == post_id, OutboxJob.status == "pending"
        ).values(status="failed", error="отменено: контент удалён")
    )
