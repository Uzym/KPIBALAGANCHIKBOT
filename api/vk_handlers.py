"""API: обработчики апдейтов ВК (ЛС + кнопки). Беседы игнорируются.

Доступ: только члены сообщества клуба и админы; не-членам — «нет доступа»,
академ (вышел из сообщества) — отдельное сообщение.
"""
from __future__ import annotations

import json
import logging
import re
import time

from bll import announcements as ann_bll
from bll import events as events_bll
from bll import linking as linking_bll
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
    "➕ Опрос — /создать опрос Вопрос; вариант1; вариант2; …; [несколько]; [до 20.09 19:00]\n"
    "✏️ /edit <id> <поля как при создании> — правит событие/опрос из чата\n"
    "📢 Объявление — глобальное; по событию — из панели [⚙️ #id]\n"
    "📋 События / 📋 Опросы — списки с кнопками [⚙️ #id]\n"
    "🔒/🔓 — закрыть/снова открыть запись (или опрос); ❌/📊 — отменить/итоги (панель [⚙️ #id])\n"
    "🔄 Синхронизация — вручную сверить админов и членство (академ)\n"
    "🔗 /связать <vk_id> <tg_id> — ручная линковка аккаунтов\n"
    "👥 /подписчики — статистика подписок\n"
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
                ["🔁 Режим участника", "❓ Помощь"],
            ],
        )
        return

    rows = [["📅 События", "🗳 Голосования"], ["⚙️ Настройки", "📩 Написать админам"]]
    if is_admin:
        rows.append(["🔁 Режим админа"])
    if sub is not None and sub.status == "stopped":
        text = "События отключены (ты нажимал /стоп). Напиши /start, чтобы вернуть."
    else:
        text = "Меню участника. События и опросы — карточками в этом чате."
    await send_reply_kb(app, uid, text, rows)


# --- вход ------------------------------------------------------------------------


async def handle_vk_update(app, update: dict) -> None:
    utype = update.get("type")
    if utype == "message_new":
        await _on_message(app, update.get("object", {}).get("message", {}))
    elif utype == "message_event":
        await _on_button(app, update.get("object", {}))


async def _on_message(app, m: dict) -> None:
    from_id = m.get("from_id")
    peer_id = m.get("peer_id")
    if from_id is None or peer_id is None or from_id == -app.cfg.vk_group_id:
        return
    if peer_id >= CHAT_PEER_BASE:
        log.debug("сообщение из беседы %s — игнорируем (v5: только ЛС)", peer_id)
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
            if low.startswith("/стоп") or text == "⏹ Закончить":
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

    # команды
    if text.startswith("/"):
        if await _admin_commands(app, msg):
            return
        if low.startswith("/start") or low.startswith("/начать"):
            with app.db.session() as s:
                acc = repo.ensure_account(s, "vk", uid)
                sub = repo.get_subscription(s, acc.id)
                if sub is not None and sub.status == "stopped":
                    given = profiles_bll.activate_subscription(s, app.cfg, acc, uid)
                    reply = f"С возвращением! Карточек доставлено: {given}."
                else:
                    reply = None
                s.commit()
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
        await app.vk.send_message(uid, "Пиши сообщение — перешлю админам клуба. "
                                        "/стоп — выйти из режима.")
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
            uid, "Формат: /создать опрос Вопрос; вариант1; вариант2; …; [несколько]; "
                 "[до 20.09 19:00]\n(минимум 2 варианта; «несколько» — мультивыбор)")
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
                uid, f"Не получилось: {err}.\nФормат: /создать опрос Вопрос; вариант1; "
                     "вариант2; …; [несколько]; [до 20.09 19:00]"
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
            if not profiles_bll.ensure_votable_dm(s, acc.id):
                s.commit()
                await toast("Сначала /start")
                return
            if action == "vote":
                key = rsvp_bll.cast_vote(s, app.cfg, "vk", user_id, content_id, value)
            else:
                key = rsvp_bll.remove_vote(s, app.cfg, "vk", user_id, content_id)
            s.commit()
        await toast(rsvp_bll.TOASTS.get(key, "?"))
        return

    if action == "poll":
        with app.db.session() as s:
            acc = repo.ensure_account(s, "vk", user_id)
            if not profiles_bll.ensure_votable_dm(s, acc.id):
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
            if not profiles_bll.ensure_votable_dm(s, acc.id):
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
            await app.vk.send_message(
                user_id,
                f"Опубликовано: ЛС {result['dm']}. Доставка — в прогрессе."
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
