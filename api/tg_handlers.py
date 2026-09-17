"""API: обработчики апдейтов Telegram (ЛС профиля; канал — только исходящий)."""
from __future__ import annotations

import logging

from bll import events as events_bll
from bll import linking as linking_bll
from bll import polls as polls_bll
from bll import rsvp as rsvp_bll
from bll.contracts import ButtonVM, OutMessageVM
from dal import repositories as repo

from .renderers import render_tg

log = logging.getLogger("tg.handlers")

LINK_ALERT = (
    "⚠️ Голос не засчитан. 1) Напиши боту клуба в ВК — он проверит, что ты "
    "в сообществе. 2) В настройках укажи свой ник в TG. Имена — из ВК."
)


def handle_tg_update_closure(app):
    async def handler(update: dict) -> None:
        await handle_tg_update(app, update)

    return handler


async def send_dm_vm_tg(app, chat_id: int, vm: OutMessageVM) -> None:
    text, markup = render_tg(vm)
    await app.tg.send_message(chat_id, text, reply_markup=markup)


def welcome_tg_vm(linked: bool, vk_name: str | None = None) -> OutMessageVM:
    if linked:
        text = (
            f"✅ Ты привязан к ВК: {vk_name or '—'}.\n\n"
            "События, опросы и объявления — постами в нашем канале, "
            "уведомления и кнопки голосования приходят сюда."
        )
    else:
        text = (
            "Привет! События, опросы и объявления — постами в нашем канале.\n\n"
            "Чтобы голосовать: 1) напиши боту клуба в ВК — он проверит, что ты "
            "в сообществе; 2) в его настройках укажи свой ник в TG. "
            "Имена в списках берутся из ВК."
        )
    return OutMessageVM(kind="menu", text=text)


def _reply_kb(rows: list[list[str]]) -> dict:
    return {
        "keyboard": [[{"text": label} for label in row] for row in rows],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


async def send_menu_tg(app, uid: int, linked: bool, vk_name: str | None = None) -> None:
    rows = [["📅 События", "🗳 Голосования"], ["⚙️ Настройки", "📩 Написать админам"]] if linked \
        else [["📩 Написать админам"]]
    text = (welcome_tg_vm(linked, vk_name).text or "")
    await app.tg.send_message(uid, text, reply_markup=_reply_kb(rows))


async def handle_tg_update(app, update: dict) -> None:
    if "message" in update:
        await _on_message(app, update["message"])
    elif "callback_query" in update:
        await _on_callback(app, update["callback_query"])


async def _on_message(app, m: dict) -> None:
    chat = m.get("chat") or {}
    sender = m.get("from") or {}
    if sender.get("is_bot"):
        return
    if chat.get("type") != "private":
        # канал и группа комментариев — только исходящие посты бота
        log.debug("сообщение из %s %s — игнорируем", chat.get("type"), chat.get("id"))
        return
    await _on_private(app, sender, chat, m)


def tg_state(app, sender: dict, chat: dict, m: dict) -> tuple[int, bool, str | None]:
    """(uid, linked, vk_name) с обновлением аккаунта и попыткой линковки."""
    uid = sender.get("id")
    name = " ".join(x for x in [sender.get("first_name"), sender.get("last_name")] if x) or "?"
    with app.db.session() as s:
        acc = repo.ensure_account(s, "tg", uid, display_name=name, username=sender.get("username"))
        linking_bll.try_link(s, app.cfg, acc)
        linked = acc.person_id is not None
        vk_name = linking_bll.vk_name_for_person(s, acc) if linked else None
        s.commit()
    return uid, linked, vk_name


async def _on_private(app, sender: dict, chat: dict, m: dict) -> None:
    uid, linked, vk_name = tg_state(app, sender, chat, m)
    text = (m.get("text") or "").strip()
    state_key = ("tg", uid)

    state = app.dialog_states.get(state_key)
    if state == "appeal":
        if text.startswith("/стоп"):
            app.dialog_states.pop(state_key, None)
            await app.tg.send_message(chat["id"], "Вышел из режима обращения.")
            await send_menu_tg(app, uid, linked, vk_name)
            return
        if text:
            await _forward_appeal(app, uid, sender, m)
            await app.tg.send_message(chat["id"], "Переслал админам. Пиши ещё или /стоп.")
            return

    low = text.lower()
    if text in ("📅 События",):
        with app.db.session() as s:
            await app.tg.send_message(chat["id"], events_bll.listing_text(s, app.cfg))
        return
    if text == "🗳 Голосования":
        with app.db.session() as s:
            await app.tg.send_message(chat["id"], polls_bll.listing_text(s, app.cfg))
        return
    if text == "⚙️ Настройки":
        await _settings(app, uid, chat["id"])
        return
    if text == "📩 Написать админам":
        app.dialog_states[state_key] = "appeal"
        await app.tg.send_message(chat["id"], "Пиши сообщение — перешлю админам клуба. /стоп — отмена.")
        return

    if low.startswith("/start"):
        await send_menu_tg(app, uid, linked, vk_name)
        return
    await send_menu_tg(app, uid, linked, vk_name)


async def _settings(app, uid: int, chat_id: int) -> None:
    with app.db.session() as s:
        acc = repo.get_account_by_platform_id(s, "tg", uid)
        notify = acc.tg_dm_notifications if acc else True
        s.commit()
    vm = OutMessageVM(
        kind="menu",
        text=f"⚙️ Настройки\n• Уведомления в личку: {'вкл ✅' if notify else 'выкл ❌'}",
        buttons=[[ButtonVM(action="menu", label=f"🔕 Уведомления: {'выкл' if notify else 'вкл'}",
                           value="tg_notify")]],
    )
    await send_dm_vm_tg(app, chat_id, vm)


async def _forward_appeal(app, uid: int, sender: dict, m: dict) -> None:
    name = " ".join(x for x in [sender.get("first_name"), sender.get("last_name")] if x) or "?"
    body = (m.get("text") or "").strip() or "📎 (медиа)"
    with app.db.session() as s:
        appeal = repo.create_appeal(s, "tg", uid, name)
        appeal_id = appeal.id
        s.commit()
    for admin_id in app.admins_vk:
        try:
            mid = await app.vk.send_message(admin_id, f"📩 [TG] {name} (id{uid}):\n{body}")
            with app.db.session() as s:
                repo.create_appeal_message(s, appeal_id, admin_id, mid)
                s.commit()
        except Exception as e:
            log.warning("appeal forward to %s failed: %s", admin_id, e)


async def _on_callback(app, cb: dict) -> None:
    sender = cb.get("from") or {}
    uid = sender.get("id")
    data = cb.get("data") or ""

    async def toast(text: str) -> None:
        await app.tg.answer_callback(cb["id"], text)

    if data.startswith("m:"):
        value = data[2:]
        if value == "tg_notify":
            with app.db.session() as s:
                acc = repo.get_account_by_platform_id(s, "tg", uid)
                if acc is not None:
                    acc.tg_dm_notifications = not acc.tg_dm_notifications
                    notify = acc.tg_dm_notifications
                else:
                    notify = True
                s.commit()
            await toast(f"Уведомления: {'вкл ✅' if notify else 'выкл ❌'}")
        elif value == "appeal":
            app.dialog_states[("tg", uid)] = "appeal"
            await app.tg.send_message(uid, "Пиши сообщение — перешлю админам клуба. /стоп — отмена.")
        return

    parts = data.split(":")
    if len(parts) < 2:
        return
    action, content_id = parts[0], int(parts[1])
    value = parts[2] if len(parts) > 2 else None

    name = " ".join(x for x in [sender.get("first_name"), sender.get("last_name")] if x) or "?"

    if action in ("vote", "remove_vote", "poll", "poll_clear"):
        with app.db.session() as s:
            acc = repo.ensure_account(s, "tg", uid, display_name=name, username=sender.get("username"))
            linking_bll.try_link(s, app.cfg, acc)
            if acc.person_id is None:
                s.commit()
                await toast(LINK_ALERT)
                return
            if action == "vote":
                key = rsvp_bll.cast_vote(s, app.cfg, "tg", uid, content_id, value)
            elif action == "remove_vote":
                key = rsvp_bll.remove_vote(s, app.cfg, "tg", uid, content_id)
            elif action == "poll":
                try:
                    opt = int(value or -1)
                except (TypeError, ValueError):
                    opt = -1
                key = polls_bll.cast_poll_vote(s, app.cfg, "tg", uid, content_id, opt)
            else:
                key = polls_bll.clear_poll_votes(s, app.cfg, "tg", uid, content_id)
            s.commit()
        await toast(rsvp_bll.TOASTS.get(key, polls_bll.TOASTS.get(key, "?")))
        return
