"""API: обработчики апдейтов ВК (ЛС + кнопки). Беседы игнорируются.

Доступ: только члены сообщества клуба и админы; не-членам — «нет доступа»,
академ (вышел из сообщества) — отдельное сообщение.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import time

from bll import announcements as ann_bll
from bll import events as events_bll
from bll import fees as fees_bll
from bll import linking as linking_bll
from bll import panel as panel_bll
from bll import polls as polls_bll
from bll import profiles as profiles_bll
from bll import rsvp as rsvp_bll
from bll.contracts import (
    AccountRef,
    ButtonVM,
    ChatRef,
    IncomingMessage,
    MediaRef,
    OutMessageVM,
)
from bll.timeparse import parse_event_command
from bll.publication import ensure_dm_cards_for_tg, notice_admins, person_name
from dal import repositories as repo

from .renderers import render_vk

log = logging.getLogger("vk.handlers")

CHAT_PEER_BASE = 2_000_000_000
MEMBERSHIP_CACHE_SECONDS = 600.0

# дедуп двойных нажатий callback-кнопок (VK не гарантирует однократность event'а)
_last_press: dict[tuple, float] = {}
DEDUP_SECONDS = 2.0


def _dedup_ok(key: tuple) -> bool:
    now = time.monotonic()
    prev = _last_press.get(key)
    if prev is not None and now - prev < DEDUP_SECONDS:
        return False
    _last_press[key] = now
    if len(_last_press) > 500:
        for k in [k for k, v in _last_press.items() if now - v > DEDUP_SECONDS]:
            _last_press.pop(k, None)
    return True


HELP_TEXT = (
    "❓ Как голосовать\n"
    "• Кнопками на карточке события/опроса в этом чате.\n"
    "• Или текстом: ответь (reply) на карточку и напиши «пойду» / «возможно» / "
    "«не пойду» / «снять»; для опроса — номер варианта (например «2» или «1,3»)."
)

ADMIN_HELP_TEXT = (
    "❓ Справка админа\n"
    "➕ Событие — /событие Название - 15.09 19:00 - 15.09 21:00 - описание\n"
    "➕ Опрос — /опрос Вопрос, дальше варианты построчно; [несколько]; [до 20.09 19:00]\n"
    "✏️ /edit <id> <поля как при создании> — правит событие/опрос из чата\n"
    "📢 Объявление — глобальное; по событию — из панели [⚙️ #id]\n"
    "📋 События / 📋 Опросы — списки с кнопками [⚙️ #id]\n"
    "🔒/🔓 — закрыть/снова открыть запись (или опрос); ❌/📊 — отменить/итоги (панель [⚙️ #id])\n"
    "🔄 Синхронизация — вручную сверить админов и членство (академ)\n"
    "🔗 /связать <vk_id> <tg_id> — ручная линковка аккаунтов\n"
    "👥 /подписчики — статистика подписок\n"
    "💰 /оплата — свой долг; /оплата <кто> <сумма> <за что> — фиксация платежа\n"
    "💰 /долги — список должников; /история <кто> — операции человека\n"
    "🚫 /бан <кто> — запретить доступ (TG); /разбан <кто> — снять бан\n"
    "✏️ /имя <id> <имя> — переименовать человека (видно во всех списках)\n"
    "🔐 /панель — токены админ-панели; /панель отозвать <id>\n"
    "🔁 Режим участника / админа — переключение клавиатуры\n"
    "Академ: исключи человека из сообщества — бот сам поставит паузу и уведомит."
)


def handle_vk_update_closure(app):
    async def handler(update: dict) -> None:
        await handle_vk_update(app, update)

    return handler


# --- VK-вложения -> MediaRef ---------------------------------------------------


def vk_attachments_to_media(attachments: list[dict]) -> list[MediaRef]:
    media: list[MediaRef] = []
    for a in attachments or []:
        t = a.get("type")
        obj = a.get(t) or {}
        if t == "photo":
            sizes = obj.get("sizes") or []
            best = max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0), default={})
            if best.get("url"):
                media.append(MediaRef(kind="photo", url=best["url"]))
        elif t == "doc":
            if obj.get("url"):
                media.append(MediaRef(kind="doc", url=obj["url"], filename=obj.get("title")))
        elif t == "audio_message":
            link = obj.get("link_ogg") or obj.get("link_mp3")
            if link:
                media.append(MediaRef(kind="voice", url=link))
        elif t == "video":
            media.append(
                MediaRef(kind="video_link", url=f"https://vk.com/video{obj.get('owner_id')}_{obj.get('id')}")
            )
        # стикеры и прочее — игнорируем
    return media


# --- прямые ответы и клавиатуры --------------------------------------------------


async def send_dm_vm(app, peer_id: int, vm: OutMessageVM) -> None:
    text, kb = render_vk(vm, app.cfg.vk_strike_fallback)
    await app.vk.send_message(peer_id, text, keyboard=kb)


def _reply_kb(rows: list[list[str]]) -> dict:
    return {
        "one_time": False,  # постоянное меню: не исчезает после нажатия
        "buttons": [
            [
                {"action": {"type": "text", "label": label, "payload": "{}"}, "color": "primary"}
                for label in row
            ]
            for row in rows
        ],
    }


async def send_reply_kb(app, peer_id: int, text: str, rows: list[list[str]]) -> None:
    await app.vk.send_message(peer_id, text, keyboard=_reply_kb(rows))


def settings_vm(sub, acc) -> OutMessageVM:
    if sub is None:
        return OutMessageVM(kind="menu", text="Сначала /start.")
    sub_state = {"active": "вкл ✅", "paused": "пауза (академ — тебя нет в сообществе)",
                 "blocked": "недоступно (заблокирован бот)", "stopped": "выкл"}[sub.status]
    ann = "вкл ✅" if sub.send_announcements else "выкл ❌"
    nick = acc.tg_nick or "не указан"
    return OutMessageVM(
        kind="menu",
        text=f"⚙️ Настройки\n• События: {sub_state}\n• Объявления в личку: {ann}\n• Мой ник в TG: {nick}",
        buttons=[
            [ButtonVM(action="menu", label=f"Объявления: {'выкл' if sub.send_announcements else 'вкл'}", value="ann_toggle")],
            [ButtonVM(action="menu", label="✏️ Указать ник в TG", value="nick_tg")],
            [ButtonVM(action="menu", label="❓ Как голосовать", value="help")],
            [ButtonVM(action="menu", label="⬅️ Назад", value="back")],
        ],
    )


# --- членство ---------------------------------------------------------------------


async def is_member_cached(app, uid: int) -> bool:
    now = time.monotonic()
    hit = app.membership_cache.get(uid)
    if hit and now - hit[0] < MEMBERSHIP_CACHE_SECONDS:
        return hit[1]
    try:
        member = await app.vk.is_member(uid)
    except Exception:
        member = True  # при сбое API не блокируем доступ
    app.membership_cache[uid] = (now, member)
    return member


# --- меню (reply-клавиатура) --------------------------------------------------------


async def send_menu(app, uid: int) -> None:
    """Приветствие + reply-клавиатура (член клуба; режим админа — по accounts.mode)."""
    with app.db.session() as s:
        acc = repo.ensure_account(s, "vk", uid)
        sub = repo.get_subscription(s, acc.id)
        mode = acc.mode
        s.commit()

    is_admin = uid in app.admins_vk

    if is_admin and mode == "admin":
        await send_reply_kb(
            app, uid,
            "Режим админа. Создание, управление и справка — кнопками ниже "
            "(или командами: /событие, /создать опрос, /edit <id> …).",
            [
                ["➕ Событие", "➕ Опрос", "📢 Объявление"],
                ["📋 События", "📋 Опросы", "👥 Подписчики"],
                ["🔗 Связать аккаунты", "🔄 Синхронизация"],
                ["🔁 Режим участника", "❓ Помощь", "💰 Долги"],
            ],
        )
        return

    rows = [["📅 События", "🗳 Голосования"], ["⚙️ Настройки", "📩 Написать админам"],
            ["💰 Оплата"]]
    if is_admin:
        rows.append(["🔁 Режим админа"])
    if sub is not None and sub.status == "stopped":
        text = "События отключены (ты нажимал /стоп). Напиши /start, чтобы вернуть."
    else:
        text = "Меню участника. События и опросы — карточками в этом чате."
    await send_reply_kb(app, uid, text, rows)


async def _on_start(app, uid: int) -> str | None:
    """Обработка /start и «Начать»: реактивация при stopped. Возвращает ответ, если был."""
    reply = None
    with app.db.session() as s:
        acc = repo.ensure_account(s, "vk", uid)
        sub = repo.get_subscription(s, acc.id)
        if sub is not None and sub.status == "stopped":
            given = profiles_bll.activate_subscription(s, app.cfg, acc, uid)
            reply = f"С возвращением! Карточек доставлено: {given}."
        s.commit()
    return reply


# --- вход ------------------------------------------------------------------------


async def handle_vk_update(app, update: dict) -> None:
    utype = update.get("type")
    if utype == "message_new":
        await _on_message(app, update.get("object", {}).get("message", {}))
    elif utype == "message_event":
        await _on_button(app, update.get("object", {}))


async def _readonly_chat(app, peer_id: int, from_id: int, m: dict) -> None:
    """Чат только для чтения: удаляем сообщение человека, ему в ЛС — кнопка «Я понял»."""
    cmid = m.get("conversation_message_id") or m.get("id")
    if cmid:
        try:
            await app.vk.delete_message(peer_id, int(cmid), in_chat=True)
        except Exception as e:
            log.warning("readonly delete в %s не прошёл: %s", peer_id, e)
    kb = {
        "inline": True,
        "buttons": [[{
            "action": {"type": "callback", "label": "Я понял",
                       "payload": json.dumps({"a": "readonly_ack"})},
        }]],
    }
    try:
        await app.vk.send_message(
            from_id, "Здесь писать нельзя — этот чат только для чтения.",
            keyboard=kb,
        )
    except Exception as e:
        log.warning("readonly notice to %s failed: %s", from_id, e)


async def _on_message(app, m: dict) -> None:
    from_id = m.get("from_id")
    peer_id = m.get("peer_id")
    if from_id is None or peer_id is None or from_id == -app.cfg.vk_group_id:
        return
    if peer_id >= CHAT_PEER_BASE:
        if peer_id in app.cfg.readonly_chat_peers:
            await _readonly_chat(app, peer_id, from_id, m)
        else:
            log.debug("сообщение из беседы %s — игнорируем", peer_id)
        return

    text = (m.get("text") or "").strip()
    is_admin = from_id in app.admins_vk
    name = await app.vk.display_name(from_id)

    reply_cmid = None
    reply_snippet = None
    rm = m.get("reply_message") or {}
    if rm:
        reply_cmid = rm.get("conversation_message_id") or rm.get("id")
        reply_snippet = (rm.get("text") or "")[:200] or None

    msg = IncomingMessage(
        platform="vk",
        chat=ChatRef(platform="vk", chat_id=peer_id),
        account=AccountRef(platform="vk", user_id=from_id),
        text=text,
        message_id=m.get("id"),
        sender_name=name,
        media=vk_attachments_to_media(m.get("attachments") or []),
        reply_to_message_id=reply_cmid,
        reply_snippet=reply_snippet,
        is_admin=is_admin,
    )

    with app.db.session() as s:
        acc = repo.ensure_account(s, "vk", from_id, display_name=name)
        if acc.tg_nick:
            linking_bll.try_link(s, app.cfg, acc)
        sub = repo.get_subscription(s, acc.id)
        s.commit()

    member = True
    if not is_admin:
        member = await is_member_cached(app, from_id)
    if not member:
        if sub is not None and sub.status == "paused":
            await app.vk.send_message(
                from_id, "📴 Ты в академе: тебя нет в сообществе клуба, поэтому "
                         "события, опросы и объявления не приходят. Вернёшься "
                         "в сообщество — всё снова заработает."
            )
        else:
            await app.vk.send_message(
                from_id, "🔒 Нет доступа: бот работает только для участников "
                         "сообщества клуба. Вступи в сообщество и напиши мне снова."
            )
        return
    # авто-подписка для всех членов (включая админов — руководители тоже члены)
    with app.db.session() as s:
        acc2 = repo.ensure_account(s, "vk", from_id)
        reply = profiles_bll.on_member_message(s, app.cfg, acc2, from_id)
        s.commit()
    if reply:
        await app.vk.send_message(from_id, reply)

    await _on_dm_message(app, msg)


# --- личные сообщения ---------------------------------------------------------------


async def _on_dm_message(app, msg: IncomingMessage) -> None:
    uid = msg.account.user_id
    text = msg.text
    state_key = ("vk", uid)
    low = text.lower() if text else ""

    # переписка в панели: фиксируем каждое входящее ЛС
    try:
        with app.db.session() as s:
            media_json = None
            if msg.media:
                media_json = json.dumps(
                    [dataclasses.asdict(m) for m in msg.media], ensure_ascii=False)
            repo.add_dm_message(s, "vk", uid, "in", text or "", media_json)
            s.commit()
    except Exception as e:
        log.warning("dm record vk %s: %s", uid, e)

    # ответ админа на обращение (reply на пересланное сообщение) — персист в БД
    if msg.is_admin and msg.reply_to_message_id:
        with app.db.session() as s:
            am = repo.appeal_message_by_cmid(s, msg.reply_to_message_id)
            appeal = repo.get_appeal(s, am.appeal_id) if am is not None else None
            first_answer = am is not None and not am.answered
            others = repo.appeal_messages(s, am.appeal_id) if am is not None else []
            if am is not None and first_answer:
                repo.mark_appeal_answered(s, am.id)
            s.commit()
        if appeal is not None:
            body = f"👤 Админ: {text}" if text else "👤 Админ: (вложение)"
            if appeal.platform == "tg":
                await app.tg.send_message(appeal.member_id, body)
            else:
                await app.vk.send_message(appeal.member_id, body)
            await app.vk.send_message(uid, "✅ Ответ отправлен участнику.")
            if first_answer:
                admin_name = await app.vk.display_name(uid)
                for o in others:
                    if o.message_id == msg.reply_to_message_id:
                        continue
                    try:
                        await app.vk.send_message(
                            o.admin_id,
                            f"↩️ {admin_name} уже ответил на обращение "
                            f"от {appeal.member_name or 'участника'}."
                        )
                    except Exception as e:
                        log.warning("answered notice to %s failed: %s", o.admin_id, e)
            return

    # многошаговые диалоги
    state = app.dialog_states.get(state_key)
    if state:
        if state == "set_tg_nick" and text and not text.startswith("/"):
            app.dialog_states.pop(state_key, None)
            with app.db.session() as s:
                acc = repo.ensure_account(s, "vk", uid)
                reply = profiles_bll.set_tg_nick(s, app.cfg, acc.id, text)
                s.commit()
            await app.vk.send_message(uid, reply)
            return
        if state == "announce_global":
            app.dialog_states.pop(state_key, None)
            if low.startswith("/стоп"):
                await app.vk.send_message(uid, "Отменено.")
                await send_menu(app, uid)
                return
            with app.db.session() as s:
                acc = repo.ensure_account(s, "vk", uid)
                counts = ann_bll.publish_global(s, app.cfg, text, media=msg.media,
                                                admin_account_id=acc.id)
                s.commit()
            await app.vk.send_message(
                uid, f"📢 Объявление разослано: ЛС {counts['dm']}."
            )
            await send_menu(app, uid)
            return
        if state and state.startswith("announce:"):
            app.dialog_states.pop(state_key, None)
            cid = int(state.split(":", 1)[1])
            if low.startswith("/стоп"):
                await app.vk.send_message(uid, "Отменено.")
                await send_menu(app, uid)
                return
            with app.db.session() as s:
                c = repo.get_content(s, cid)
                if c is None:
                    s.commit()
                    await app.vk.send_message(uid, "Контент не найден.")
                    return
                acc = repo.ensure_account(s, "vk", uid)
                sent = ann_bll.publish_for_content(s, app.cfg, c.kind, cid, text,
                                                   media=msg.media, admin_account_id=acc.id)
                s.commit()
            await app.vk.send_message(
                uid, f"📢 Объявление для #{cid} разослано (ЛС {sent}), секция в карточке обновлена."
            )
            return
        if state == "appeal":
            if low.startswith("/start") or low.startswith("/начать") or low == "начать":
                app.dialog_states.pop(state_key, None)
                await app.vk.send_message(uid, "Вышел из режима обращения.")
                reply = await _on_start(app, uid)
                if reply:
                    await app.vk.send_message(uid, reply)
                await send_menu(app, uid)
                return
            if (low.startswith("/стоп") or low.startswith("/stop")
                    or text == "⏹ Закончить"):
                app.dialog_states.pop(state_key, None)
                await app.vk.send_message(uid, "Вышел из режима обращения.")
                await send_menu(app, uid)
                return
            await _forward_appeal(app, msg)
            return

    # текстовый fallback голосования: reply на карточку
    if msg.reply_to_message_id and text and not text.startswith("/"):
        if await _text_vote(app, msg):
            return

    # кнопки reply-клавиатуры
    if await _menu_route(app, msg):
        return

    # оплата: свой долг — доступно всем (без аргументов)
    if low in ("/оплата", "/платёж", "/платеж"):
        await _member_fees(app, uid)
        return

    # команды
    if text.startswith("/"):
        if low.startswith("/веб") or low.startswith("/web") or low.startswith("/panel"):
            await _web_login(app, uid)
            return
        if await _admin_commands(app, msg):
            return
        if low.startswith("/start") or low.startswith("/начать"):
            reply = await _on_start(app, uid)
            if reply:
                await app.vk.send_message(uid, reply)
            await send_menu(app, uid)
            return
        if low.startswith("/стоп") or low.startswith("/stop"):
            with app.db.session() as s:
                acc = repo.ensure_account(s, "vk", uid)
                reply = profiles_bll.unsubscribe(s, acc.id)
                s.commit()
            await app.vk.send_message(uid, reply)
            await send_menu(app, uid)
            return
        await app.vk.send_message(uid, "Не понял команду. /start — меню.")
        return

    if not text and msg.media:
        await app.vk.send_message(uid, "Медиа вижу, но события и опросы — в карточках "
                                        "этого чата 🙂")
        return
    await send_menu(app, uid)


# --- маршруты reply-клавиатуры --------------------------------------------------------


async def _menu_route(app, msg: IncomingMessage) -> bool:
    """Кнопки reply-клавиатуры приходят как обычный текст. Возвращает True, если обработано."""
    t = msg.text
    uid = msg.account.user_id
    handled = True

    if t == "⚙️ Настройки":
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", uid)
            sub = repo.get_subscription(s, acc.id)
            vm = settings_vm(sub, acc)
            s.commit()
        await send_dm_vm(app, uid, vm)
    elif t == "❓ Как голосовать":
        await app.vk.send_message(uid, HELP_TEXT)
    elif t == "📅 События" or t == "📋 События":
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", uid)
            is_admin_mode = uid in app.admins_vk and acc.mode == "admin"
            if is_admin_mode:
                vm = events_bll.admin_listing_vm(s, app.cfg)
                await send_dm_vm(app, uid, vm)
            else:
                await app.vk.send_message(uid, events_bll.listing_text(s, app.cfg))
    elif t == "🗳 Голосования" or t == "📋 Опросы":
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", uid)
            is_admin_mode = uid in app.admins_vk and acc.mode == "admin"
            if is_admin_mode:
                vm = polls_bll.admin_listing_vm(s, app.cfg)
                await send_dm_vm(app, uid, vm)
            else:
                await app.vk.send_message(uid, polls_bll.listing_text(s, app.cfg))
    elif t == "📩 Написать админам":
        app.dialog_states[("vk", uid)] = "appeal"
        await send_reply_kb(
            app, uid,
            "Пиши сообщение — перешлю админам клуба.\n"
            "⏹ Закончить, «Начать» или /start — выйти из режима.",
            [["⏹ Закончить"]],
        )
    elif t == "💰 Оплата":
        await _member_fees(app, uid)
    elif t == "💰 Долги" and uid in app.admins_vk:
        with app.db.session() as s:
            text = fees_bll.debtors_text(s, app.cfg)
            s.commit()
        await app.vk.send_message(uid, text)
    elif t == "🔄 Синхронизация" and uid in app.admins_vk:
        lines = await profiles_bll.sync_people(app)
        app.membership_cache.clear()
        report = "\n".join(f"• {l}" for l in lines) if lines else "• Без изменений"
        await app.vk.send_message(uid, f"🔄 Синхронизация завершена:\n{report}")
    elif t == "🔁 Режим админа" and uid in app.admins_vk:
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", uid)
            repo.set_account_mode(s, acc.id, "admin")
            s.commit()
        await send_menu(app, uid)
    elif t == "🔁 Режим участника":
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", uid)
            repo.set_account_mode(s, acc.id, "member")
            s.commit()
        await send_menu(app, uid)
    elif t == "➕ Событие":
        await app.vk.send_message(
            uid, "Формат: /событие Название - 15.09 19:00 - 15.09 21:00 - описание\n"
                 "(конец и описание можно опустить; «завтра 19:00», «вт 19:00» — тоже можно)")
    elif t == "➕ Опрос":
        await app.vk.send_message(
            uid, "Формат:\n/опрос Вопрос\nвариант 1\nвариант 2\n[несколько]\n[до 20.09 19:00]\n"
                 "(минимум 2 варианта; «несколько» — мультивыбор; старый формат "
                 "через «;» тоже работает)")
    elif t == "📢 Объявление":
        app.dialog_states[("vk", uid)] = "announce_global"
        await app.vk.send_message(uid, "Пришли текст объявления (можно с фото/документом) — "
                                        "разошлю всем. /стоп — отмена.")
    elif t == "👥 Подписчики":
        with app.db.session() as s:
            stats = repo.subscription_stats(s)
        pretty = ", ".join(f"{k}: {v}" for k, v in sorted(stats.items())) or "подписок нет"
        await app.vk.send_message(uid, f"Подписки: {pretty}")
    elif t == "🔗 Связать аккаунты":
        await app.vk.send_message(uid, "Формат: /связать <vk_user_id> <tg_user_id>")
    elif t == "❓ Помощь":
        await app.vk.send_message(uid, ADMIN_HELP_TEXT)
    else:
        handled = False
    return handled


async def _forward_appeal(app, msg: IncomingMessage) -> None:
    uid = msg.account.user_id
    name = msg.sender_name or str(uid)
    body = msg.text or ""
    if msg.media:
        body += "\n📎 вложения: " + ", ".join(m.kind for m in msg.media)
    with app.db.session() as s:
        acc = repo.ensure_account(s, "vk", uid)
        if acc.person_id:
            pn = person_name(s, acc.person_id)
            if pn:
                name = pn  # переопределённое имя — во всех текстовках
        appeal = repo.create_appeal(s, "vk", uid, name)
        appeal_id = appeal.id
        s.commit()
    for admin_id in app.admins_vk:
        try:
            mid = await app.vk.send_message(admin_id, f"📩 [VK] {name} (id{uid}):\n{body}")
            with app.db.session() as s:
                repo.create_appeal_message(s, appeal_id, admin_id, mid)
                s.commit()
        except Exception as e:
            log.warning("appeal forward to %s failed: %s", admin_id, e)


# --- текстовое голосование (reply на карточку) -----------------------------------------


RSVP_WORDS = {
    "yes": ("пойду", "приду", "иду", "да", "+", "буду"),
    "no": ("не пойду", "не приду", "нет", "не смогу", "не буду", "-"),
    "maybe": ("возможно", "может быть", "может", "50/50", "не знаю"),
    "remove": ("снять", "убрать", "снять ответ", "убрать ответ"),
}


async def _text_vote(app, msg: IncomingMessage) -> bool:
    uid = msg.account.user_id
    text = msg.text
    with app.db.session() as s:
        post = repo.find_post_by_message(s, "vk", str(uid), msg.reply_to_message_id)
        if post is None or post.content_type not in ("event", "poll"):
            s.commit()
            return False
        acc = repo.ensure_account(s, "vk", uid)
        if not profiles_bll.ensure_votable_dm(s, acc.id):
            s.commit()
            await app.vk.send_message(uid, "Сначала /start.")
            return True
        if post.content_type == "event":
            key = _event_text_vote(s, app.cfg, uid, post.content_id, text)
        else:
            key = _poll_text_vote(s, app.cfg, uid, post.content_id, text)
        s.commit()
    if key == "unknown":
        await app.vk.send_message(
            uid, "Не понял. Для события: «пойду», «возможно», «не пойду», «снять»; "
                 "для опроса: номер варианта («2» или «1,3») или «снять»."
        )
        return True
    await app.vk.send_message(uid, rsvp_bll.TOASTS.get(key, polls_bll.TOASTS.get(key, "?")))
    return True


def _event_text_vote(s, cfg, uid: int, event_id: int, text: str) -> str:
    low = text.lower().strip()
    for ans, words in RSVP_WORDS.items():
        if low in words:
            if ans == "remove":
                return rsvp_bll.remove_vote(s, cfg, "vk", uid, event_id)
            return rsvp_bll.cast_vote(s, cfg, "vk", uid, event_id, ans)
    return "unknown"


def _poll_text_vote(s, cfg, uid: int, poll_id: int, text: str) -> str:
    low = text.lower().strip()
    if low in ("снять", "убрать", "снять все", "снять выборы", "убрать все"):
        return polls_bll.clear_poll_votes(s, cfg, "vk", uid, poll_id)
    if re.fullmatch(r"[\d,.\s]+", text):
        digits = [int(d) - 1 for d in re.findall(r"\d+", text)]
        return polls_bll.set_poll_choices(s, cfg, "vk", uid, poll_id, set(digits))
    return "unknown"


# --- команды главы -------------------------------------------------------------------


async def _web_login(app, uid: int) -> None:
    """Команда /веб: одноразовая ссылка для входа в веб-панель."""
    import uuid as _uuid
    from datetime import timedelta

    if not app.cfg.panel_url:
        await app.vk.send_message(uid, "Веб-панель не настроена. Попроси руководителя.")
        return

    token = _uuid.uuid4().hex
    from dal.database import now_utc
    from dal.models import WebSession as WS

    with app.db.session() as s:
        acc = repo.ensure_account(s, "vk", uid)
        s.add(WS(login_token=token, account_id=acc.id,
                  expires_at=now_utc() + timedelta(hours=24)))
        s.commit()

    url = f"{app.cfg.panel_url}/auth?t={token}"
    await app.vk.send_message(
        uid,
        f"🔗 Вход в панель клуба (ссылка действует 24 часа):\n{url}\n\n"
        f"После входа увидишь свои события, взносы и запись.",
    )


async def _member_fees(app, uid: int) -> None:
    """Просмотр своего долга (доступно участникам)."""
    with app.db.session() as s:
        acc = repo.ensure_account(s, "vk", uid)
        if acc.person_id is None:
            s.commit()
            await app.vk.send_message(uid, "Сначала /start.")
            return
        text = fees_bll.debt_overview(s, app.cfg, acc.person_id)
        s.commit()
    await app.vk.send_message(uid, text)


async def _admin_payment(app, uid: int, raw: str) -> None:
    """/оплата <кто> <сумма> <за что> — фиксация платежа; минус — отмена (долг растёт)."""
    m = re.match(r"^/(?:оплата|платёж|платеж)\s+(.+?)\s+(-?\d+)\s*(.*)$", raw,
                 flags=re.IGNORECASE)
    if not m:
        await app.vk.send_message(
            uid, "Формат: /оплата <кто> <сумма> <за что>\n"
                 "Пример: /оплата 253519572 200 взнос за сентябрь\n"
                 "(«кто» — имя, логин TG (@ник) или id; отрицательная сумма — отмена)")
        return
    ref = m.group(1).strip()
    amount = int(m.group(2))
    label = m.group(3).strip()
    await _resolve_ref(app, uid, ref, "pay", {"amount": amount, "label": label})


def _person_label(s, person) -> str:
    name = person_name(s, person.id) or f"#{person.id}"
    tags = []
    if repo.vk_account_for_person(s, person.id):
        tags.append("VK")
    if repo.tg_account_for_person(s, person.id):
        tags.append("TG")
    return f"{name} ({', '.join(tags)})" if tags else name


async def _pick_person(app, uid: int, ref: str, persons: list, cmd: str,
                       args: dict | None = None) -> None:
    """Несколько кандидатов по «кто» — inline-кнопки выбора."""
    with app.db.session() as s:
        labels = [_person_label(s, p) for p in persons[:10]]
        s.commit()
    kb = {
        "inline": True,
        "buttons": [[{
            "action": {"type": "callback", "label": label,
                       "payload": json.dumps({"a": "person_pick", "c": cmd,
                                              "e": p.id, "v": json.dumps(args or {})})},
        }] for p, label in zip(persons[:10], labels)],
    }
    await app.vk.send_message(
        uid, f"По «{ref}» несколько совпадений — выбери, кого ты имел в виду:",
        keyboard=kb,
    )


async def _apply_person_action(app, uid: int, cmd: str, person, args: dict) -> str:
    """Действие по выбранной персоне (pay|history|name|ban|unban). Текст результата."""
    if cmd == "pay":
        amount = int(args.get("amount", 0))
        label = str(args.get("label") or "")
        with app.db.session() as s:
            admin_acc = repo.ensure_account(s, "vk", uid)
            err, alert = fees_bll.record_payment(s, app.cfg, person.id, amount,
                                                 label, created_by=admin_acc.id)
            if err:
                s.commit()
                return f"Не получилось: {err}"
            debt = fees_bll.debt_of(s, person.id)
            name = fees_bll.display_name(person)
            s.commit()
            if alert:
                notice_admins(s, app.cfg, alert, unique=f"debt{person.id}",
                              admins=app.admins_vk)
                s.commit()
        return f"✅ {name}: {amount} ₽ ({label or 'платёж'}). Теперь долг: {debt} ₽."
    if cmd == "history":
        with app.db.session() as s:
            text = fees_bll.history_text(s, app.cfg, person.id)
            s.commit()
        return text
    if cmd == "name":
        new_name = str(args.get("name") or "")
        with app.db.session() as s:
            p = repo.get_person(s, person.id)
            old = person_name(s, p.id) or f"#{p.id}"
            p.display_override = new_name or None
            s.commit()
        return (f"✏️ Имя изменено: {old} → {new_name}." if new_name
                else f"↩️ Имя сброшено: {old} (теперь из ВК).")
    if cmd in ("ban", "unban"):
        with app.db.session() as s:
            tg_acc = repo.tg_account_for_person(s, person.id)
            if tg_acc is None:
                s.commit()
                return f"У «{person_name(s, person.id) or person.id}» нет TG-аккаунта."
            sub = repo.get_subscription(s, tg_acc.id)
            if sub is None:
                sub = repo.upsert_subscription(s, tg_acc.id, "blocked")
            if cmd == "ban":
                sub.banned = True
                sub.status = "blocked"
                notice = "⛔ Ты заблокирован. Если это ошибка — свяжись с руководителем клуба."
            else:
                sub.banned = False
                notice = "🔓 Бан снят. Напиши /start, чтобы вернуться."
            name = tg_acc.display_name or str(tg_acc.platform_user_id)
            s.commit()
            try:
                await app.tg.send_message(tg_acc.platform_user_id, notice)
            except Exception as e:
                log.warning("ban/unban notice failed: %s", e)
        return (f"🚫 Забанен: {name} (TG)." if cmd == "ban"
                else f"🔓 Бан снят: {name}.")
    return "Неизвестное действие."


async def _resolve_ref(app, uid: int, ref: str, cmd: str,
                       args: dict | None = None) -> None:
    """0 кандидатов → «никого не нашли»; 1 → применить; >1 → кнопки выбора."""
    with app.db.session() as s:
        persons = repo.find_persons_by_ref(s, ref)
        s.commit()
    if not persons:
        await app.vk.send_message(
            uid, f"Никого не нашёл по «{ref}». Уточни: имя, логин TG (@ник), id ВК или TG.")
        return
    if len(persons) > 1:
        await _pick_person(app, uid, ref, persons, cmd, args)
        return
    text = await _apply_person_action(app, uid, cmd, persons[0], args or {})
    await app.vk.send_message(uid, text)


async def _admin_commands(app, msg: IncomingMessage) -> bool:
    """Возвращает True, если команда обработана как админская."""
    if not msg.is_admin:
        return False
    uid = msg.account.user_id
    low = msg.text.lower()

    if low in ("/admin", "/админ"):
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", uid)
            repo.set_account_mode(s, acc.id, "admin")
            s.commit()
        await send_menu(app, uid)
        return True

    if low.startswith("/help") or low.startswith("/помощь"):
        await app.vk.send_message(uid, ADMIN_HELP_TEXT)
        return True

    if low.startswith("/оплата") or low.startswith("/платёж") or low.startswith("/платеж"):
        await _admin_payment(app, uid, msg.text)
        return True

    if low.startswith("/долги") or low.startswith("/debts"):
        with app.db.session() as s:
            text = fees_bll.debtors_text(s, app.cfg)
            s.commit()
        await app.vk.send_message(uid, text)
        return True

    if low.startswith("/история") or low.startswith("/history"):
        m = re.match(r"^/(?:история|history)\s+(.+)$", msg.text, flags=re.IGNORECASE)
        if not m:
            await app.vk.send_message(uid, "Формат: /история <кто> (имя, логин TG или id)")
            return True
        await _resolve_ref(app, uid, m.group(1).strip(), "history")
        return True

    if low.startswith("/имя") or low.startswith("/name"):
        m = re.match(r"^/(?:имя|name)\s+(.+?)\s*$", msg.text, flags=re.IGNORECASE)
        if not m:
            await app.vk.send_message(
                uid, "Формат: /имя <кто> <новое имя>\n"
                     "Пример: /имя 253519572 Александр\n"
                     "/имя <кто> — сброс (вернётся имя из ВК).")
            return True
        parts = m.group(1).split(None, 1)
        ref = parts[0].strip()
        new_name = parts[1].strip() if len(parts) > 1 else ""
        await _resolve_ref(app, uid, ref, "name", {"name": new_name})
        return True

    if low.startswith("/бан") or low.startswith("/ban"):
        m = re.match(r"^/(?:бан|ban)\s+(.+)$", msg.text, flags=re.IGNORECASE)
        if not m:
            await app.vk.send_message(uid, "Формат: /бан <кто> (имя, логин TG или id) — "
                                             "запретить доступ к боту.")
            return True
        await _resolve_ref(app, uid, m.group(1).strip(), "ban")
        return True

    if low.startswith("/разбан") or low.startswith("/unban"):
        m = re.match(r"^/(?:разбан|unban)\s+(.+)$", msg.text, flags=re.IGNORECASE)
        if not m:
            await app.vk.send_message(uid, "Формат: /разбан <кто> (имя, логин TG или id).")
            return True
        await _resolve_ref(app, uid, m.group(1).strip(), "unban")
        return True

    if low.startswith("/панель"):
        m = re.match(r"^/панель(?:\s+отозвать\s+(\d+))?$", msg.text, flags=re.IGNORECASE)
        if not m:
            await app.vk.send_message(uid, "Формат: /панель — активные токены панели; "
                                             "/панель отозвать <id> — отозвать токен.")
            return True
        revoke_id = int(m.group(1)) if m.group(1) else 0
        with app.db.session() as s:
            if revoke_id:
                ok = panel_bll.revoke_login(s, revoke_id)
                s.commit()
                await app.vk.send_message(
                    uid, f"🔐 Токен #{revoke_id} отозван." if ok
                    else f"Сессия #{revoke_id} не найдена или не активна.")
            else:
                lines = panel_bll.session_lines(s, "approved")
                s.commit()
                await app.vk.send_message(
                    uid, "🔐 Активные токены панели:\n"
                         + ("\n".join(lines) if lines else "— нет активных"))
        return True

    if low.startswith("/удалить") or low.startswith("/delete"):
        m = re.match(r"^/(?:удалить|delete)\s+(\d+)", msg.text, flags=re.IGNORECASE)
        if not m:
            await app.vk.send_message(uid, "Формат: /удалить <id> (id — в списках 📋). "
                                             "Карточки удалятся у всех.")
            return True
        cid = int(m.group(1))
        with app.db.session() as s:
            c = repo.get_content(s, cid)
            if c is None:
                s.commit()
                await app.vk.send_message(uid, f"Контент #{cid} не найден.")
                return True
            if c.kind == "poll":
                err = polls_bll.delete_poll(s, app.cfg, cid)
            else:
                err = events_bll.delete_event(s, app.cfg, cid)
            s.commit()
        await app.vk.send_message(
            uid, err or f"🗑 #{cid} удалён; карточки у всех исчезают (рассылаю удаление)."
        )
        return True

    if low.startswith("/посещаемость") or low.startswith("/кто пришёл"):
        m = re.match(r"^/(?:посещаемость|кто пришёл)\s+(\d+)", msg.text, flags=re.IGNORECASE)
        if not m:
            await app.vk.send_message(uid, "Формат: /посещаемость <id> (событие).")
            return True
        cid = int(m.group(1))
        with app.db.session() as s:
            vm = events_bll.attendance_vm(s, app.cfg, cid)
            if vm is None:
                s.commit()
                await app.vk.send_message(uid, "Событие не найдено.")
                return True
            s.commit()
        text, kb = render_vk(vm, app.cfg.vk_strike_fallback)
        mid = await app.vk.send_message(uid, text, keyboard=kb)
        app.attendance_msgs[(uid, cid)] = mid
        return True

    if low.startswith("/экспорт") or low.startswith("/export"):
        import datetime as dt
        from bll import export as export_bll

        with app.db.session() as s:
            data = export_bll.build_export_xlsx(s, app.cfg)
            s.commit()
        fname = f"итоги_{dt.datetime.now(app.cfg.tz).strftime('%Y%m%d')}.xlsx"
        try:
            att = await app.vk.upload_doc(uid, data, fname)
            await app.vk.send_message(uid, "📊 Экспорт итогов:", attachment=att)
        except Exception as e:
            log.warning("export send failed: %s", e)
            await app.vk.send_message(uid, f"Не получилось отправить файл: {e}")
        return True

    if low in ("/member", "/участник"):
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", uid)
            repo.set_account_mode(s, acc.id, "member")
            s.commit()
        await send_menu(app, uid)
        return True

    if low.startswith("/edit") or low.startswith("/изменить"):
        m = re.match(r"^/(edit|изменить)\s+(\d+)\s*(.*)$", msg.text, flags=re.IGNORECASE)
        if not m:
            await app.vk.send_message(
                uid, "Формат: /edit <id> <поля как при создании>\n"
                     "Пример: /edit 12 Тренировка - 15.09 19:00 - 15.09 21:00 - описание\n"
                     "id — в списках (📋) или первой строкой карточки."
            )
            return True
        content_id = int(m.group(2))
        body = m.group(3).strip()
        if not body:
            await app.vk.send_message(uid, "После id нужны поля. Формат: /edit <id> Название - даты - описание")
            return True
        with app.db.session() as s:
            c = repo.get_content(s, content_id)
            if c is None:
                s.commit()
                await app.vk.send_message(uid, f"Контент #{content_id} не найден.")
                return True
            if c.kind == "poll":
                human, err = polls_bll.apply_poll_edit(s, app.cfg, content_id, body)
            else:
                result = events_bll.apply_full_edit(s, app.cfg, content_id, body)
                human = result if isinstance(result, list) else None
                err = result if isinstance(result, str) else None
            s.commit()
        if err:
            await app.vk.send_message(uid, f"Не получилось: {err}")
        else:
            await app.vk.send_message(
                uid, f"Обновил #{content_id}: " + "; ".join(human or []) +
                     " — карточки подписчиков обновлены."
            )
        return True

    if low.startswith("/создать опрос") or low.startswith("/опрос") or low.startswith("/poll"):
        import datetime as dt

        parsed, err = polls_bll.parse_poll_command(msg.text, app.cfg, dt.datetime.now(app.cfg.tz))
        if parsed is None:
            await app.vk.send_message(
                uid, f"Не получилось: {err}.\nФормат:\n/опрос Вопрос\nвариант 1\n"
                     "вариант 2\n[несколько]\n[до 20.09 19:00]"
            )
            return True
        with app.db.session() as s:
            admin_acc = repo.ensure_account(s, "vk", uid)
            poll = polls_bll.create_draft(s, app.cfg, admin_acc.id, parsed)
            s.commit()
            await send_dm_vm(app, uid, polls_bll.preview_vm(s, app.cfg, poll))
            s.close()
        return True

    if low.startswith("/событие") or low.startswith("/event"):
        if not (low.startswith("/события") or low.startswith("/events")):
            import datetime as dt

            parsed = parse_event_command(msg.text, app.cfg.tz, dt.datetime.now(app.cfg.tz))
            if parsed.missing or not parsed.title or not parsed.starts_at:
                missing = ", ".join(parsed.missing) if parsed.missing else "не понял"
                await app.vk.send_message(
                    uid,
                    f"Не получилось: {missing}.\nФормат: /событие Название - 15.09 19:00 - "
                    f"15.09 21:00 - описание\n(конец и описание можно опустить)",
                )
                return True
            with app.db.session() as s:
                admin_acc = repo.ensure_account(s, "vk", uid)
                ev = events_bll.create_draft(s, app.cfg, admin_acc.id, parsed)
                s.commit()
                await send_dm_vm(app, uid, events_bll.preview_vm(s, app.cfg, ev))
                s.close()
            return True

    if low.startswith("/события") or low.startswith("/events"):
        with app.db.session() as s:
            await app.vk.send_message(uid, events_bll.listing_text(s, app.cfg))
        return True

    if low.startswith("/подписчики"):
        with app.db.session() as s:
            stats = repo.subscription_stats(s)
        pretty = ", ".join(f"{k}: {v}" for k, v in sorted(stats.items())) or "подписок нет"
        await app.vk.send_message(uid, f"Подписки: {pretty}")
        return True

    if low.startswith("/связать"):
        parts = msg.text.split()
        try:
            vk_id, tg_id = int(parts[1]), int(parts[2])
        except (IndexError, ValueError):
            await app.vk.send_message(uid, "Формат: /связать <vk_user_id> <tg_user_id>")
            return True
        with app.db.session() as s:
            reply = linking_bll.admin_force_link(s, app.cfg, vk_id, tg_id)
            s.commit()
        await app.vk.send_message(uid, reply)
        return True

    return False


# --- кнопки (message_event) ---------------------------------------------------------


async def _on_button(app, obj: dict) -> None:
    """Всегда отвечаем на message_event — иначе кнопка крутит спиннер бесконечно."""
    user_id = obj.get("user_id")
    peer_id = obj.get("peer_id")
    event_id_vk = obj.get("event_id") or ""
    if user_id is None:
        return
    try:
        await _on_button_impl(app, obj)
    finally:
        try:
            await app.vk.answer_event(event_id_vk, user_id, peer_id or user_id, "")
        except Exception:
            log.debug("финальный answer_event не прошёл: %s", event_id_vk)


async def _on_button_impl(app, obj: dict) -> None:
    user_id = obj.get("user_id")
    peer_id = obj.get("peer_id")
    event_id_vk = obj.get("event_id") or ""
    payload = obj.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    payload = payload or {}
    if user_id is None:
        return

    action = payload.get("a")
    value = payload.get("v")
    content_id = payload.get("e")

    async def toast(text: str) -> None:
        await app.vk.answer_event(event_id_vk, user_id, peer_id or user_id, text)

    def require_admin() -> bool:
        return user_id in app.admins_vk

    def content_kind(s) -> str | None:
        c = repo.get_content(s, content_id)
        return c.kind if c else None

    # нажата ли кнопка на общей карточке беседы (тогда нет персональных клавиатур)
    cmid_obj = obj.get("conversation_message_id")
    chat_card = False
    if cmid_obj:
        with app.db.session() as s:
            post = repo.find_post_by_message(s, "vk_chat", str(peer_id or user_id),
                                             int(cmid_obj))
            chat_card = post is not None and post.kind == "chat_card"
            s.commit()

    if action in ("vote", "remove_vote", "poll", "poll_clear") and chat_card:
        if user_id not in app.admins_vk and not await is_member_cached(app, user_id):
            await toast("Кнопки — только для членов клуба")
            return

    if action == "readonly_ack":
        # «Я понял»: удаляем ЛС-оповещение о read-only чате
        cmid = obj.get("conversation_message_id")
        if cmid:
            try:
                await app.vk.delete_message(user_id, int(cmid), in_chat=False)
            except Exception as e:
                log.debug("readonly ack delete failed: %s", e)
        return

    if action == "person_pick":
        # выбор кандидата из кнопок (неоднозначный «кто»)
        if not require_admin():
            await toast("Нет прав")
            return
        cmd = payload.get("c")
        pid = int(content_id or 0) if content_id else 0
        args: dict = {}
        if isinstance(value, str):
            try:
                args = json.loads(value)
            except ValueError:
                args = {}
        elif isinstance(value, dict):
            args = value
        with app.db.session() as s:
            person = repo.get_person(s, pid)
            s.commit()
        if person is None:
            await toast("Человек не найден")
            return
        text = await _apply_person_action(app, user_id, cmd, person, args)
        if cmd == "history":
            await app.vk.send_message(user_id, text)
        else:
            await toast(text[:90])
        return

    if action == "panel_req":
        # одобрение/отказ входа в админ-панель (payload: a=panel_req, e=session_id, v=yes|no)
        if not require_admin():
            await toast("Нет прав")
            return
        sid = int(content_id or 0) if content_id else 0
        with app.db.session() as s:
            if value == "yes":
                err = panel_bll.approve_login(s, sid, user_id)
                if not err:
                    sess = repo.get_panel_session(s, sid)
                    panel_bll.log_to_tech(
                        s, app.cfg,
                        f"🔑 Панель: вход одобрен (заявка #{sid}, "
                        f"{sess.label or 'без подписи'} · IP {sess.ip})")
            else:
                err = panel_bll.deny_login(s, sid, user_id)
                if not err:
                    panel_bll.log_to_tech(
                        s, app.cfg, f"🚫 Панель: вход отклонён (заявка #{sid})")
            s.commit()
        if not err:
            await toast("Одобрил ✅" if value == "yes" else "Отказал")
        else:
            await toast(err)
        return

    if action == "tgreq":
        # одобрение/отказ TG-заявки (payload: a=tgreq, e=tg_user_id, v=yes|no)
        if not require_admin():
            await toast("Нет прав")
            return
        tguid = int(content_id or 0) if content_id else 0
        if tguid <= 0:
            await toast("Заявка не найдена")
            return
        with app.db.session() as s:
            tacc = repo.get_account_by_platform_id(s, "tg", tguid)
            if tacc is None:
                s.commit()
                await toast("Аккаунт не найден")
                return
            if value == "yes":
                if tacc.person_id is None:
                    person = repo.get_or_create_person(
                        s, display_name=tacc.display_name or "TG"
                    )
                    tacc.person_id = person.id
                repo.upsert_subscription(s, tacc.id, "active")
                s.commit()
                try:
                    await app.tg.send_message(
                        tguid, "✅ Добро пожаловать в клуб! События, опросы и "
                               "объявления — карточками в этом чате."
                    )
                except Exception as e:
                    log.warning("tg approve notice failed: %s", e)
                with app.db.session() as s2:
                    tacc2 = repo.get_account_by_platform_id(s2, "tg", tguid)
                    ensure_dm_cards_for_tg(s2, app.cfg, tacc2)
                    s2.commit()
                await toast("Пустил")
            else:
                repo.upsert_subscription(s, tacc.id, "blocked")
                s.commit()
                try:
                    await app.tg.send_message(tguid, "Твоя заявка отклонена.")
                except Exception as e:
                    log.warning("tg reject notice failed: %s", e)
                await toast("Отказал")
        return

    if action in ("vote", "remove_vote", "poll", "poll_clear"):
        # защита от повтора ОДНОГО И ТОГО ЖЕ event'а (VK иногда дублирует доставку);
        # разные нажатия имеют разные event_id и не блокируются
        dedup_key = ("ev", event_id_vk) if event_id_vk else (user_id, action, content_id, value)
        if not _dedup_ok(dedup_key):
            await toast("Уже обрабатываю…")
            return

    if action in ("vote", "remove_vote"):
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", user_id)
            # в общей карточке беседы членство уже проверено выше — подписка не нужна
            if not chat_card and not profiles_bll.ensure_votable_dm(s, acc.id):
                s.commit()
                await toast("Сначала /start")
                return
            if action == "vote":
                if chat_card:
                    # на общей карточке повторное нажатие на свой выбор = снять
                    v = repo.get_vote(s, content_id, acc.id)
                    if v is not None and v.answer == value:
                        key = rsvp_bll.remove_vote(s, app.cfg, "vk", user_id, content_id)
                    else:
                        key = rsvp_bll.cast_vote(s, app.cfg, "vk", user_id,
                                                 content_id, value)
                else:
                    key = rsvp_bll.cast_vote(s, app.cfg, "vk", user_id,
                                             content_id, value)
            else:
                key = rsvp_bll.remove_vote(s, app.cfg, "vk", user_id, content_id)
            s.commit()
        await toast(rsvp_bll.TOASTS.get(key, "?"))
        return

    if action == "poll":
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", user_id)
            if not chat_card and not profiles_bll.ensure_votable_dm(s, acc.id):
                s.commit()
                await toast("Сначала /start")
                return
            try:
                opt = int(value)
            except (TypeError, ValueError):
                opt = -1
            key = polls_bll.cast_poll_vote(s, app.cfg, "vk", user_id, content_id, opt)
            s.commit()
        await toast(polls_bll.TOASTS.get(key, "?"))
        return

    if action == "poll_clear":
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", user_id)
            if not chat_card and not profiles_bll.ensure_votable_dm(s, acc.id):
                s.commit()
                await toast("Сначала /start")
                return
            key = polls_bll.clear_poll_votes(s, app.cfg, "vk", user_id, content_id)
            s.commit()
        await toast(polls_bll.TOASTS.get(key, "?"))
        return

    if action == "publish":
        if not require_admin():
            await toast("Нет прав")
            return
        with app.db.session() as s:
            kind = content_kind(s)
            if kind == "poll":
                result = polls_bll.publish(s, app.cfg, content_id)
            else:
                result = events_bll.publish(s, app.cfg, content_id)
            s.commit()
        if isinstance(result, dict):
            where = (f"беседа: {result.get('chat', 0)} карточек"
                     if app.cfg.card_chat_peer else f"ЛС {result['dm']}")
            await app.vk.send_message(
                user_id,
                f"Опубликовано: {where}. Доставка — в прогрессе."
            )
        else:
            await app.vk.send_message(user_id, str(result))
        return

    if action == "cancel_draft":
        if not require_admin():
            await toast("Нет прав")
            return
        with app.db.session() as s:
            kind = content_kind(s)
            if kind == "poll":
                polls_bll.delete_draft(s, content_id)
            else:
                events_bll.delete_draft(s, content_id)
            s.commit()
        await app.vk.send_message(user_id, "Черновик удалён.")
        return

    if action == "close":
        if not require_admin():
            await toast("Нет прав")
            return
        with app.db.session() as s:
            kind = content_kind(s)
            if kind == "poll":
                result = polls_bll.close(s, app.cfg, content_id, admins=app.admins_vk)
            else:
                result = events_bll.close(s, app.cfg, content_id)
            s.commit()
        await app.vk.send_message(user_id, result or "Не могу закрыть (не активен или уже закрыт).")
        return

    if action == "reopen":
        if not require_admin():
            await toast("Нет прав")
            return
        with app.db.session() as s:
            kind = content_kind(s)
            if kind == "poll":
                result = polls_bll.reopen(s, app.cfg, content_id)
            else:
                result = events_bll.reopen(s, app.cfg, content_id)
            s.commit()
        await app.vk.send_message(user_id, result or "Не могу открыть (не закрыт или уже начался).")
        return

    if action == "cancel_event":
        if not require_admin():
            await toast("Нет прав")
            return
        with app.db.session() as s:
            kind = content_kind(s)
            if kind == "poll":
                polls_bll.cancel(s, app.cfg, content_id, admins=app.admins_vk)
            else:
                events_bll.cancel(s, app.cfg, content_id)
            s.commit()
        await app.vk.send_message(user_id, "Отменено, все уведомлены.")
        return

    if action == "panel":
        if not require_admin():
            await toast("Нет прав")
            return
        await _send_panel(app, user_id, content_id)
        return

    if action == "ann_content":
        if not require_admin():
            await toast("Нет прав")
            return
        app.dialog_states[("vk", user_id)] = f"announce:{content_id}"
        await app.vk.send_message(
            user_id, f"Пришли текст объявления для #{content_id} (можно с фото/документом). "
                     "/стоп — отмена."
        )
        return

    if action == "edit_hint":
        if not require_admin():
            await toast("Нет прав")
            return
        await app.vk.send_message(
            user_id,
            f"Формат: /edit {content_id} <поля как при создании>\n"
            "Событие: /edit 12 Тренировка - 15.09 19:00 - 15.09 21:00 - описание\n"
            "Опрос: /edit 13 Вопрос; [несколько|один]; [до 20.09 19:00]"
        )
        return

    if action == "results":
        if not require_admin():
            await toast("Нет прав")
            return
        with app.db.session() as s:
            c = repo.get_content(s, content_id)
            if c is None:
                s.commit()
                await app.vk.send_message(user_id, "Контент не найден.")
                return
            if c.kind == "poll":
                poll = repo.get_poll(s, content_id)
                text = polls_bll.poll_summary_line(s, app.cfg, poll) or "Голосов нет."
                text = f"📊 #{content_id} «{poll.title}»\n" + text
            else:
                from bll.publication import event_vm
                from bll.summary import final_summary_text

                text = final_summary_text(event_vm(s, app.cfg, repo.get_event(s, content_id)))
            s.commit()
        await app.vk.send_message(user_id, text)
        return

    if action == "delete_content":
        if not require_admin():
            await toast("Нет прав")
            return
        with app.db.session() as s:
            c = repo.get_content(s, content_id)
            if c is None:
                s.commit()
                await app.vk.send_message(user_id, "Контент не найден.")
                return
            if c.kind == "poll":
                err = polls_bll.delete_poll(s, app.cfg, content_id)
            else:
                err = events_bll.delete_event(s, app.cfg, content_id)
            s.commit()
        await app.vk.send_message(
            user_id, err or f"🗑 #{content_id} удалён; карточки у всех исчезают."
        )
        return

    if action == "attend_open":
        if not require_admin():
            await toast("Нет прав")
            return
        with app.db.session() as s:
            vm = events_bll.attendance_vm(s, app.cfg, content_id)
            if vm is None:
                s.commit()
                await app.vk.send_message(user_id, "Событие не найдено.")
                return
            s.commit()
        text, kb = render_vk(vm, app.cfg.vk_strike_fallback)
        mid = await app.vk.send_message(user_id, text, keyboard=kb)
        app.attendance_msgs[(user_id, content_id)] = mid
        return

    if action == "attend":
        if not require_admin():
            await toast("Нет прав")
            return
        if not value:
            await toast("?")
            return
        added = False
        with app.db.session() as s:
            added = events_bll.toggle_attendance(s, content_id, value or "")
            vm = events_bll.attendance_vm(s, app.cfg, content_id)
            s.commit()
        if vm is None:
            await toast("Событие не найдено")
            return
        text, kb = render_vk(vm, app.cfg.vk_strike_fallback)
        mid_prev = app.attendance_msgs.get((user_id, content_id))
        try:
            if mid_prev:
                await app.vk.edit_message(user_id, mid_prev, text, kb)
                mid = mid_prev
            else:
                mid = await app.vk.send_message(user_id, text, keyboard=kb)
                app.attendance_msgs[(user_id, content_id)] = mid
        except Exception:
            mid = await app.vk.send_message(user_id, text, keyboard=kb)
            app.attendance_msgs[(user_id, content_id)] = mid
        await toast("✅ Отмечен" if added else "Отметка снята")
        return

    if action == "menu":
        await _menu_button(app, user_id, value)


async def _send_panel(app, user_id: int, content_id: int) -> None:
    """Панель управления контентом: [📢] [✏️] [🔒] [❌] [📊] + [✅ Кто пришёл] [🗑]."""
    with app.db.session() as s:
        c = repo.get_content(s, content_id)
        if c is None:
            s.commit()
            await app.vk.send_message(user_id, "Контент не найден.")
            return
        if c.kind == "poll":
            poll = repo.get_poll(s, content_id)
            title = poll.title if poll else "?"
            if poll is not None and poll.status == "closed":
                close_label = "🔓 Открыть опрос"
                close_action = "reopen"
            else:
                close_label = "🔒 Закрыть опрос"
                close_action = "close"
            ev_status = None
        else:
            ev = repo.get_event(s, content_id)
            title = ev.title if ev else "?"
            if ev is not None and ev.status == "closed":
                close_label = "🔓 Открыть запись"
                close_action = "reopen"
            else:
                close_label = "🔒 Закрыть запись"
                close_action = "close"
            ev_status = ev.status if ev else None
        s.commit()
    extra: list[ButtonVM] = []
    if c.kind != "poll" and ev_status in ("closed", "finished"):
        extra.append(ButtonVM(action="attend_open", label="✅ Кто пришёл", event_id=content_id))
    extra.append(ButtonVM(action="delete_content", label="🗑 Удалить", event_id=content_id))
    vm = OutMessageVM(
        kind="menu",
        text=f"#{content_id} «{title}»",
        buttons=[
            [ButtonVM(action="ann_content", label="📢 Объявление", event_id=content_id),
             ButtonVM(action="edit_hint", label="✏️ Изменить", event_id=content_id)],
            [ButtonVM(action=close_action, label=close_label, event_id=content_id),
             ButtonVM(action="cancel_event", label="❌ Отменить", event_id=content_id),
             ButtonVM(action="results", label="📊 Итоги", event_id=content_id)],
            extra,
        ],
    )
    await send_dm_vm(app, user_id, vm)


async def _menu_button(app, user_id: int, value: str | None) -> None:
    if value == "settings":
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", user_id)
            sub = repo.get_subscription(s, acc.id)
            vm = settings_vm(sub, acc)
            s.commit()
        await send_dm_vm(app, user_id, vm)
        return

    if value == "ann_toggle":
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", user_id)
            profiles_bll.toggle_announcements(s, acc.id)
            sub = repo.get_subscription(s, acc.id)
            vm = settings_vm(sub, acc)
            s.commit()
        await send_dm_vm(app, user_id, vm)
        return

    if value == "nick_tg":
        app.dialog_states[("vk", user_id)] = "set_tg_nick"
        await app.vk.send_message(
            user_id, "Пришли свой ник в TG без «@» (например: anny). "
                     "Нужен для объединения голосов."
        )
        return

    if value == "help":
        await app.vk.send_message(user_id, HELP_TEXT)
        return

    if value == "back":
        await send_menu(app, user_id)
        return
