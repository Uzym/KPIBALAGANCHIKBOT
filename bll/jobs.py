"""BLL: фоновые задачи — напоминания, авто-закрытие, авто-завершение, членство,
TTL-очистка уведомлений и сверка карточек (v5: только ЛС)."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time

from sqlalchemy import select

from dal import repositories as repo
from dal.database import now_utc
from dal.models import Post

from config import Config
from . import events as events_bll
from . import maintenance as maintenance_bll
from . import polls as polls_bll
from . import profiles as profiles_bll
from .publication import (
    ensure_dm_card,
    ensure_dm_cards_for_tg,
    event_vm,
    notice_dm_reply_cards,
    refresh_content,
)

log = logging.getLogger("jobs")

TICK_SECONDS = 30
FINISH_GRACE_MINUTES = 5
SYNC_INTERVAL_SECONDS = 3600  # синк админов/членства — раз в час


async def scheduler_loop(app) -> None:
    last_sync = 0.0
    last_backup_day: dt.date | None = None
    last_cleanup_day: dt.date | None = None
    while True:
        try:
            await _tick(app)
            now_m = time.monotonic()
            if now_m - last_sync >= SYNC_INTERVAL_SECONDS:
                last_sync = now_m
                lines = await profiles_bll.sync_people(app)
                app.membership_cache.clear()
                if lines:
                    log.info("синк людей: %s", "; ".join(lines))
            today = dt.datetime.now(app.cfg.tz).date()
            if last_backup_day != today:
                last_backup_day = today
                _backup_db(app.cfg)
            if last_cleanup_day != today:
                last_cleanup_day = today
                with app.db.session() as s:
                    lines = maintenance_bll.cleanup_old_records(s, app.cfg)
                    s.commit()
                if lines:
                    log.info("retention: %s", "; ".join(lines))
                if today.weekday() == 0:  # по понедельникам сжимаем файл БД
                    maintenance_bll.vacuum_db(app.db.engine)
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


def _backup_db(cfg: Config) -> None:
    """Ночной (раз в сутки) бэкап БД с ротацией 7 копий."""
    import pathlib
    import sqlite3

    try:
        dest_dir = pathlib.Path(cfg.db_path).parent / "backups"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"kpibalaganchikbot-{dt.datetime.now(cfg.tz):%Y%m%d}.db"
        if dest.exists():
            return
        src = sqlite3.connect(cfg.db_path)
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        files = sorted(dest_dir.glob("kpibalaganchikbot-*.db"))
        for f in files[:-7]:
            f.unlink(missing_ok=True)
        log.info("бэкап БД: %s", dest.name)
    except Exception:
        log.exception("бэкап БД не удался")


async def _tick(app) -> None:
    cfg: Config = app.cfg
    with app.db.session() as s:
        now = now_utc()

        # напоминания (события и опросы) — reply'ем на карточку
        for r in repo.due_reminders(s, now):
            if r.content_type == "poll":
                poll = repo.get_poll(s, r.content_id)
                if poll is not None and poll.status == "active" and not poll.cancelled:
                    hours = r.kind.lstrip("h")
                    text = polls_bll.poll_reminder_text(s, cfg, poll, hours)
                    notice_dm_reply_cards(s, cfg, text, content_type="poll",
                                          content_id=poll.id, unique=f"rem{r.id}")
            else:
                event = repo.get_event(s, r.content_id)
                if event is not None and event.status == "active" and not event.cancelled:
                    vm = event_vm(s, cfg, event)
                    yes = len([e for e in vm.lists[0].entries if not e.struck_at])
                    hours = r.kind.lstrip("h")
                    text = f"⏰ Через {hours} ч — «{event.title}». Придут: {yes}."
                    notice_dm_reply_cards(s, cfg, text, content_type="event",
                                          content_id=event.id, unique=f"rem{r.id}")
            repo.mark_reminder_done(s, r.id)
        s.commit()

    # авто-закрытие опросов (по сроку; один раз — после переоткрытия не долбим)
    with app.db.session() as s:
        now = now_utc()
        due_polls = repo.polls_due_close(s, now)
        for p in due_polls:
            if p.auto_closed:
                continue
            polls_bll.close(s, cfg, p.id, auto=True, admins=app.admins_vk)
        if due_polls:
            s.commit()

    # TTL-очистка уведомлений (объявления/изменения в ЛС)
    with app.db.session() as s:
        now = now_utc()
        cutoff = now - dt.timedelta(hours=cfg.announce_notice_ttl_hours)
        stale = s.scalars(
            select(Post).where(
                Post.kind == "dm_notice",
                Post.status == "ok",
                Post.message_id.is_not(None),
                Post.created_at < cutoff,
            )
        ).all()
        for p in stale:
            repo.enqueue_job(
                s, op="delete", platform=p.platform, chat_id=p.chat_id,
                post_id=p.id, view_model={"kind": "notice"},
                idempotency_key=f"del:{p.id}",
            )
        s.commit()

    # сверка витрин: контент актуален, карточки есть у всех подписчиков.
    # refresh_content — батчами (K контентов за тик, полный круг за 2–3 тика)
    RECONCILE_BATCH = 30
    with app.db.session() as s:
        contents = ([( "event", e.id) for e in repo.open_events(s)]
                    + [("poll", p.id) for p in repo.open_polls(s)])
        cursor = getattr(app, "reconcile_cursor", 0)
        if contents:
            if cursor >= len(contents):
                cursor = 0
            batch = contents[cursor:cursor + RECONCILE_BATCH]
            if len(batch) < RECONCILE_BATCH and cursor > 0:
                batch += contents[:RECONCILE_BATCH - len(batch)]
            app.reconcile_cursor = (cursor + RECONCILE_BATCH) % len(contents)
            for ctype, cid in batch:
                refresh_content(s, cfg, ctype, cid)
        for sub, acc in repo.active_subscriptions(s):
            for ev in repo.open_events(s):
                ensure_dm_card(s, cfg, ev, acc.id, acc.platform_user_id)
            for p in repo.open_polls(s):
                polls_bll.ensure_poll_card(s, cfg, p.id, acc.id, "vk",
                                           str(acc.platform_user_id))
        for acc in repo.tg_linked_accounts(s):
            if acc.tg_dm_notifications:
                ensure_dm_cards_for_tg(s, cfg, acc)
        s.commit()

    # авто-закрытие записи (срабатывает один раз: после переоткрытия не долбим)
    with app.db.session() as s:
        now = now_utc()
        if cfg.autoclose_mode == "before_start":
            delta = dt.timedelta(minutes=cfg.autoclose_minutes)
            due = repo.events_past_start(s, now + delta)
        else:
            due = repo.events_past_start(s, now)
        for e in due:
            if e.auto_closed:
                continue
            events_bll.close(s, cfg, e.id, auto=True)
        if due:
            s.commit()

    # авто-завершение (через 5 минут после конца)
    with app.db.session() as s:
        now = now_utc()
        grace = dt.timedelta(minutes=FINISH_GRACE_MINUTES)
        for e in repo.events_past_end(s, now - grace):
            events_bll.finish(s, cfg, e.id, admins=app.admins_vk)
        s.commit()
