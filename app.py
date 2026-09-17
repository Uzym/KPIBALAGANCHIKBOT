"""Сборка приложения: конфиг, БД, клиенты, сервисы, запуск всех задач."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from api import tg_handlers, vk_handlers
from api.senders import run_outbox
from api.sslctx import build_ssl_context
from api.tg_client import TGClient
from api.vk_client import VKClient
from bll.jobs import scheduler_loop
from config import Config
from dal import repositories as repo
from dal.database import Database

log = logging.getLogger("app")


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.log = logging.getLogger("app")
        self.db = Database(cfg.db_path)
        ssl_ctx = build_ssl_context(cfg.ssl_ca_bundle, cfg.ssl_verify)
        self.vk = VKClient(cfg.vk_token, cfg.vk_group_id, cfg.vk_api_version,
                           ssl_ctx=ssl_ctx)
        self.tg = TGClient(cfg.tg_token, ssl_ctx=ssl_ctx)
        self.dialog_states: dict[tuple, str] = {}
        # админы: руководители сообщества (этап 1, обновление раз в час) + ADMIN_VK_IDS
        self.admins_vk: set[int] = set(cfg.admin_vk_ids)
        # кэши
        self.membership_cache: dict[int, tuple[float, bool]] = {}  # uid -> (ts, member)
        self.attendance_msgs: dict[tuple[int, int], int] = {}  # (admin_uid, event_id) -> cmid

    def bootstrap(self) -> None:
        self.db.create_all()
        from dal import migrations

        applied = migrations.apply_migrations(self.db.engine)
        if applied:
            log.warning("миграции БД применены: %s", "; ".join(applied))
        with self.db.session() as s:
            for uid in self.cfg.admin_vk_ids:
                acc = repo.ensure_account(s, "vk", uid)
                if acc.display_name in ("", str(uid)):
                    acc.display_name = "Глава клуба"
            stuck = repo.reset_sending_jobs(s)  # после рестарта «sending» = застрявшие
            s.commit()
            if stuck:
                log.warning("восстановлено застрявших заданий outbox: %d", stuck)
        log.info("БД готова: %s", self.cfg.db_path)

    async def refresh_admins(self) -> list[str]:
        """Админы = руководители сообщества (API) + ADMIN_VK_IDS.

        Возвращает строки изменений (для отчёта админу).
        """
        managers: set[int] = set()
        try:
            managers = await self.vk.group_managers()
        except Exception as e:
            log.warning("group_managers failed: %s (остаёмся на старом списке)", e)
            return [f"админы: ошибка API ({e})"]
        new_set = managers | set(self.cfg.admin_vk_ids)
        old = self.admins_vk
        added = sorted(new_set - old)
        removed = sorted(old - new_set)
        self.admins_vk = new_set
        lines = []
        if added:
            lines.append(f"админы +{len(added)}: {', '.join(map(str, added))}")
        if removed:
            lines.append(f"админы −{len(removed)}: {', '.join(map(str, removed))}")
        log.info("админы обновлены: %d", len(self.admins_vk))
        return lines

    async def shutdown(self) -> None:
        """Корректная остановка: checkpoint WAL, закрытие клиентов и движка."""
        log.info("остановка: checkpoint WAL…")
        try:
            from sqlalchemy import text

            with self.db.engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                conn.commit()
        except Exception:
            log.exception("wal_checkpoint failed")
        await self.vk.close()
        await self.tg.close()
        self.db.engine.dispose()
        log.info("остановлен")

    async def run(self) -> None:
        self.bootstrap()
        await self.refresh_admins()
        for w in self.cfg.warnings:
            log.warning("конфиг: %s", w)
        if self.cfg.tech_admin_vk_id:
            try:
                await self.vk.send_message(
                    self.cfg.tech_admin_vk_id,
                    f"✅ Бот клуба запущен (v5). Время: {dt.datetime.now(self.cfg.tz):%d.%m %H:%M}.",
                )
            except Exception as e:
                log.warning("tech-admin notice failed: %s", e)
        log.info(
            "Запуск: VK group=%s",
            self.cfg.vk_group_id,
        )
        tasks = [
            asyncio.create_task(self.vk.poll_forever(vk_handlers.handle_vk_update_closure(self)),
                                name="vk-poll"),
            asyncio.create_task(self.tg.poll_forever(tg_handlers.handle_tg_update_closure(self)),
                                name="tg-poll"),
            asyncio.create_task(run_outbox(self), name="outbox"),
            asyncio.create_task(scheduler_loop(self), name="scheduler"),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            await self.vk.close()
            await self.tg.close()
