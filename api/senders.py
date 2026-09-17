"""API: исполнение outbox — отправка/редактирование с рейт-лимитами и ретраями."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from bll.contracts import OutMessageVM, vm_hash
from dal import repositories as repo
from dal.models import Post

from .renderers import render_tg, render_vk

log = logging.getLogger("senders")

VK_PACER = None
TG_PACER = None


class Pacer:
    """Минимальные интервалы: глобально по платформе и на один чат/пир."""

    def __init__(self, min_global: float, min_per_key: float):
        self.min_global = min_global
        self.min_per_key = min_per_key
        self._last_global = 0.0
        self._last_by_key: dict[tuple, float] = {}

    async def wait(self, key: tuple) -> None:
        while True:
            now = time.monotonic()
            since_global = now - self._last_global
            last_key = self._last_by_key.get(key)
            # нет истории по ключу — можно сразу (не полагаемся на эпоху monotonic)
            since_key = now - last_key if last_key is not None else float("inf")
            if since_global >= self.min_global and since_key >= self.min_per_key:
                self._last_global = now
                self._last_by_key[key] = now
                return
            wait_needed = max(
                (self.min_global - since_global) if since_global < self.min_global else 0.0,
                (self.min_per_key - since_key) if since_key < self.min_per_key else 0.0,
            )
            await asyncio.sleep(max(0.02, wait_needed))


async def _vk_attachments(app, media, peer_id: int) -> str | None:
    atts: list[str] = []
    for m in media:
        try:
            if m.vk_attachment:
                atts.append(m.vk_attachment)
            elif m.tg_file_id and m.kind == "photo":
                url = await app.tg.file_url(m.tg_file_id)
                if url:
                    data = await app.tg.download(url)
                    atts.append(await app.vk.upload_photo(peer_id, data))
            elif m.tg_file_id and m.kind == "voice":
                url = await app.tg.file_url(m.tg_file_id)
                if url:
                    data = await app.tg.download(url)
                    atts.append(
                        await app.vk.upload_doc(peer_id, data, "voice.ogg", kind="audio_message")
                    )
            elif m.tg_file_id and m.kind == "doc":
                url = await app.tg.file_url(m.tg_file_id)
                if url:
                    data = await app.tg.download(url)
                    atts.append(
                        await app.vk.upload_doc(peer_id, data, m.filename or "file.bin")
                    )
            elif m.url and m.kind == "photo":
                data = await app.vk.download(m.url)
                atts.append(await app.vk.upload_photo(peer_id, data))
            elif m.url and m.kind == "voice":
                data = await app.vk.download(m.url)
                atts.append(
                    await app.vk.upload_doc(peer_id, data, "voice.ogg", kind="audio_message")
                )
            elif m.url and m.kind == "doc":
                data = await app.vk.download(m.url)
                atts.append(await app.vk.upload_doc(peer_id, data, m.filename or "file.bin"))
            elif m.url and m.kind == "video_link":
                atts.append(m.url)
        except Exception as e:
            log.warning("медиа не перенесено в VK (%s): %s", m.kind, e)
    return ",".join(atts) or None


async def run_outbox(app) -> None:
    global VK_PACER, TG_PACER
    VK_PACER = Pacer(min_global=0.35, min_per_key=1.0)
    TG_PACER = Pacer(min_global=0.05, min_per_key=1.0)
    log.info("outbox-сендеры запущены")
    while True:
        try:
            with app.db.session() as s:
                jobs = repo.fetch_pending_jobs(s, limit=25)
                s.commit()
            if not jobs:
                await asyncio.sleep(0.7)
                continue
            log.info("outbox: %d заданий в работе", len(jobs))
            for job in jobs:
                await _exec(app, job)
        except Exception:
            log.exception("цикл outbox")
            await asyncio.sleep(2)


async def _exec(app, job) -> None:
    post = None
    if job.post_id:
        with app.db.session() as s:
            post = s.get(Post, job.post_id)

    try:
        if job.op == "delete":
            if post is None or not post.message_id:
                raise RuntimeError("нет сообщения для delete")
            if job.platform == "vk":
                await VK_PACER.wait(("vk", job.chat_id))
                await app.vk.delete_message(int(job.chat_id), post.message_id)
            else:
                await TG_PACER.wait(("tg", job.chat_id))
                await app.tg.delete_message(job.chat_id, post.message_id)
            _on_delete_success(app, job)
            return
        if job.op == "send" and job.platform == "vk_bulk":
            await _exec_bulk(app, job)
            return
        vm = OutMessageVM.from_dict(json.loads(job.view_model))
        if job.op == "edit":
            if post is None or not post.message_id:
                raise RuntimeError("нет сообщения для edit")
            if job.platform == "vk":
                await VK_PACER.wait(("vk", job.chat_id))
                text, kb = render_vk(vm, app.cfg.vk_strike_fallback)
                await app.vk.edit_message(int(job.chat_id), post.message_id, text, kb)
                mid = post.message_id
            else:
                await TG_PACER.wait(("tg", job.chat_id))
                text, markup = render_tg(vm)
                await app.tg.edit_message_text(job.chat_id, post.message_id, text, markup)
                mid = post.message_id
        else:
            if job.platform == "vk_wall":
                await VK_PACER.wait(("vk_wall", job.chat_id))
                text, _kb = render_vk(vm, app.cfg.vk_strike_fallback)
                mid = await app.vk.wall_post(text)
            elif job.platform == "vk":
                log.debug("exec %s: pacer…", job.id)
                await VK_PACER.wait(("vk", job.chat_id))
                log.debug("exec %s: render…", job.id)
                text, kb = render_vk(vm, app.cfg.vk_strike_fallback)
                log.debug("exec %s: media…", job.id)
                attachment = await _vk_attachments(app, vm.media, int(job.chat_id))
                log.debug("exec %s: send…", job.id)
                mid = await app.vk.send_message(
                    int(job.chat_id), text, kb, attachment=attachment, reply_to=vm.reply_to
                )
                log.debug("exec %s: sent=%s", job.id, mid)
            else:
                await TG_PACER.wait(("tg", job.chat_id))
                text, markup = render_tg(vm)
                if vm.media:
                    media = []
                    for m in vm.media:
                        if m.kind == "video_link":
                            continue
                        item = {"kind": m.kind, "caption": text if not media else None}
                        if m.url:
                            item["url"] = m.url
                        elif m.tg_file_id:
                            item["file_id"] = m.tg_file_id
                        media.append(item)
                    await app.tg.send_media(
                        job.chat_id, media, thread_id=job.thread_id, reply_to=vm.reply_to
                    )
                    mid = None
                else:
                    mid = await app.tg.send_message(
                        job.chat_id, text, markup, thread_id=job.thread_id, reply_to=vm.reply_to
                    )
        _on_success(app, job, vm, mid)
    except Exception as e:
        await _on_error(app, job, vm, e)


async def _exec_bulk(app, job) -> None:
    """Батч-отправка VK user_ids: одна рассылка до 100 адресатов."""
    payload = json.loads(job.view_model)
    users = payload.get("users") or []
    if not users:
        with app.db.session() as s:
            repo.finish_job(s, job.id)
            s.commit()
        return
    vm = OutMessageVM(kind=payload.get("kind", "notice"), text=payload.get("text"))
    await VK_PACER.wait(("vk", "bulk"))
    text, _kb = render_vk(vm, app.cfg.vk_strike_fallback)
    try:
        # при ретрае не дублируем: уже доставленные (post.ok + message_id) пропускаем
        targets: list[list] = []
        with app.db.session() as s:
            for acc_id, uid, post_id in users:
                p = s.get(Post, post_id)
                if p is None or (p.status == "ok" and p.message_id):
                    continue
                targets.append([acc_id, uid, post_id])
            s.commit()
        if not targets:
            with app.db.session() as s:
                repo.finish_job(s, job.id)
                s.commit()
            return
        results = await app.vk.send_bulk([u[1] for u in targets], text)
        by_peer = {int(r.get("peer_id", 0)): r for r in results}
        with app.db.session() as s:
            for acc_id, uid, post_id in targets:
                r = by_peer.get(int(uid), {})
                err = r.get("error")
                if err:
                    code = err.get("code") if isinstance(err, dict) else None
                    log.warning("bulk send to %s failed: %s", uid, err)
                    if code in (900, 901, 902, 903) and acc_id:
                        sub = repo.get_subscription(s, acc_id)
                        if sub:
                            repo.set_subscription_status(s, acc_id, "blocked")
                        repo.update_post(s, post_id, status="blocked")
                    else:
                        repo.update_post(s, post_id, status="pending")
                else:
                    mid = r.get("conversation_message_id") or r.get("message_id")
                    repo.update_post(s, post_id, message_id=mid, status="ok")
            repo.finish_job(s, job.id)
            s.commit()
    except Exception as e:
        await _on_error(app, job, vm, e)


def _on_delete_success(app, job) -> None:
    with app.db.session() as s:
        repo.finish_job(s, job.id)
        if job.post_id:
            repo.update_post(s, job.post_id, status="deleted", message_id=None)
        s.commit()


def _on_success(app, job, vm, mid: int | None) -> None:
    with app.db.session() as s:
        repo.finish_job(s, job.id, sent_message_id=mid)
        if job.post_id and mid is not None:
            values: dict = {"message_id": mid, "status": "ok"}
            if job.op != "edit":
                # у edit'ов vm_hash не трогаем: в БД лежит хеш целевого состояния
                # (перезапись устаревшей копией сломает сверку)
                values["vm_hash"] = vm_hash(vm)
            repo.update_post(s, job.post_id, **values)
        s.commit()


async def _on_error(app, job, vm, exc: Exception) -> None:
    desc = str(exc)
    code = getattr(exc, "code", None)
    log.warning("outbox %s %s->%s упал: %s", job.op, job.platform, job.chat_id, desc)

    blocked = (job.platform == "vk" and code in (900, 901, 902, 903)) or (
        job.platform == "tg" and "blocked" in desc.lower()
    )
    edit_broken = job.op == "edit" and (
        (job.platform == "vk" and code in (15, 10))
        or (job.platform == "tg" and "message to edit not found" in desc.lower())
    )
    not_modified = job.platform == "tg" and "message is not modified" in desc.lower()

    with app.db.session() as s:
        if blocked and job.account_id:
            if job.platform == "tg":
                # юзер заблокировал TG-бота — выключаем уведомления, чтобы не ретраить
                acc = repo.get_account(s, job.account_id)
                if acc is not None:
                    acc.tg_dm_notifications = False
                repo.finish_job(s, job.id, error=desc, fail=True)
                s.commit()
                return
            sub = repo.get_subscription(s, job.account_id)
            if sub:
                repo.set_subscription_status(s, job.account_id, "blocked")
            if job.post_id:
                repo.update_post(s, job.post_id, status="blocked")
            repo.finish_job(s, job.id, error=desc, fail=True)
            s.commit()
            return

        if not_modified:
            repo.finish_job(s, job.id, sent_message_id=None)
            if job.post_id:
                repo.update_post(s, job.post_id, status="ok", vm_hash=vm_hash(vm))
            s.commit()
            return

        if edit_broken and job.post_id:
            # сообщение потеряно — следующим шагом отправим новое с тем же контентом
            repo.finish_job(s, job.id, sent_message_id=None)
            repo.update_post(s, job.post_id, status="deleted", message_id=None)
            h = vm_hash(vm)
            repo.enqueue_job(
                s, op="send", platform=job.platform, chat_id=job.chat_id,
                thread_id=job.thread_id, account_id=job.account_id,
                post_id=job.post_id, view_model=vm.to_dict(),
                idempotency_key=f"send:{job.post_id}:{h}",
            )
            repo.update_post(s, job.post_id, vm_hash=h, status="pending")
            s.commit()
            return

        result = repo.finish_job(s, job.id, retry_in=1, error=desc)
        if result == "failed":
            log.error("outbox job %s окончательно провалился: %s", job.id, desc)
        s.commit()
