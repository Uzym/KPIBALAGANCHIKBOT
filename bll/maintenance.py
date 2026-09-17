"""BLL: гигиена хранения — retention старых записей и VACUUM.

Бот долгоживущий: outbox-задания, посты и обращения копятся. Чистим старьё,
чтобы БД не росла бесконечно (важно в Docker, где всё в одном volume).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import delete as sa_delete, select

from dal import repositories as repo
from dal.database import now_utc
from dal.models import Appeal, AppealMessage, OutboxJob, Post, Reminder

from config import Config

JOBS_RETENTION_DAYS = 30    # done/failed-задания outbox
POSTS_RETENTION_DAYS = 7    # удалённые карточки/уведомления
APPEALS_RETENTION_DAYS = 90  # обращения с ответами
REMINDERS_RETENTION_DAYS = 30


def cleanup_old_records(s, cfg: Config) -> list[str]:
    """Удаляет устаревшие служебные записи. Возвращает строки отчёта."""
    now = now_utc()
    lines: list[str] = []

    jobs_cutoff = now - dt.timedelta(days=JOBS_RETENTION_DAYS)
    r = s.execute(
        sa_delete(OutboxJob).where(
            OutboxJob.status.in_(["done", "failed"]),
            OutboxJob.created_at < jobs_cutoff,
        )
    )
    if r.rowcount:
        lines.append(f"outbox −{r.rowcount}")

    posts_cutoff = now - dt.timedelta(days=POSTS_RETENTION_DAYS)
    # удаляем только посты, на которые больше нет заданий outbox
    referenced = select(OutboxJob.post_id).where(OutboxJob.post_id.is_not(None))
    r = s.execute(
        sa_delete(Post).where(
            Post.status == "deleted",
            Post.created_at < posts_cutoff,
            Post.id.not_in(referenced),
        )
    )
    if r.rowcount:
        lines.append(f"posts −{r.rowcount}")

    appeals_cutoff = now - dt.timedelta(days=APPEALS_RETENTION_DAYS)
    old_appeals = select(Appeal.id).where(Appeal.created_at < appeals_cutoff)
    r = s.execute(sa_delete(AppealMessage).where(AppealMessage.appeal_id.in_(old_appeals)))
    r2 = s.execute(sa_delete(Appeal).where(Appeal.created_at < appeals_cutoff))
    if r.rowcount or r2.rowcount:
        lines.append(f"appeals −{r2.rowcount}")

    rem_cutoff = now - dt.timedelta(days=REMINDERS_RETENTION_DAYS)
    r = s.execute(sa_delete(Reminder).where(Reminder.done == True, Reminder.at < rem_cutoff))  # noqa: E712
    if r.rowcount:
        lines.append(f"reminders −{r.rowcount}")

    return lines


def vacuum_db(engine) -> None:
    """Сжимает файл БД (вне транзакции)."""
    with engine.connect() as conn:
        conn.exec_driver_sql("VACUUM")
