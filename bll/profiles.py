"""BLL: подписки, членство (академ), профили, синхронизация людей."""
from __future__ import annotations

from sqlalchemy import select, update

from dal import repositories as repo
from dal.models import Post, Subscription

from config import Config
from . import linking as linking_bll
from .publication import drop_dm_cards, ensure_dm_card


def activate_subscription(s, cfg: Config, acc, vk_user_id: int) -> int:
    """Член клуба написал боту: активируем и досылаем все активные карточки.

    Возвращает количество карточек, которые были выданы.
    """
    repo.upsert_subscription(s, acc.id, "active")
    given = 0
    for ev in repo.open_events(s):
        ensure_dm_card(s, cfg, ev, acc.id, vk_user_id)
        given += 1
    from . import polls as polls_bll
    for p in repo.open_polls(s):
        polls_bll.ensure_poll_card(s, cfg, p.id, acc.id, "vk", str(vk_user_id))
        given += 1
    return given


def on_member_message(s, cfg: Config, acc, vk_user_id: int) -> str | None:
    """Что сделать при сообщении члена клуба. Возвращает приветствие или None.

    active — ничего; paused (академ закончился) — активируем + карточки;
    stopped (сам отписался) — оставляем, подсказка /start;
    нет подписки — активируем + карточки.
    """
    sub = repo.get_subscription(s, acc.id)
    if sub is None:
        given = activate_subscription(s, cfg, acc, vk_user_id)
        return f"✅ Доступ открыт. Актуальных событий и опросов: {given}." if given else \
            "✅ Доступ открыт. Активных событий и опросов пока нет."
    if sub.status == "paused":
        given = activate_subscription(s, cfg, acc, vk_user_id)
        return f"👋 С возвращением! Карточек доставлено: {given}."
    if sub.status == "stopped":
        return "События отключены (/стоп ранее). Напиши /start, чтобы вернуть."
    return None


def ensure_votable_dm(s, account_id: int) -> bool:
    """Голос из ЛС — только активные подписчики (карточки приходят только им)."""
    sub = repo.get_subscription(s, account_id)
    return sub is not None and sub.status == "active"


def unsubscribe(s, account_id: int) -> str:
    drop_dm_cards(s, account_id)
    repo.set_subscription_status(s, account_id, "stopped")
    sub = repo.get_subscription(s, account_id)
    if sub and sub.status == "stopped":
        return "Хорошо, больше не буду присылать события. Вернуться — /start."
    return "Подписки и так не было."


def toggle_announcements(s, account_id: int) -> str:
    sub = repo.get_subscription(s, account_id)
    if sub is None:
        return "Сначала напиши /start."
    new_value = not sub.send_announcements
    repo.set_send_announcements(s, account_id, new_value)
    state = "вкл ✅" if new_value else "выкл ❌"
    return f"Объявления в личку: {state}."


def set_tg_nick(s, cfg: Config, account_id: int, nick: str) -> str:
    acc = repo.get_account(s, account_id)
    if acc is None:
        return "Сначала /start."
    nick = nick.strip().lstrip("@")
    if not nick or " " in nick:
        return "Ник выглядит странно — пришли ник без «@» и пробелов (например: anny)."
    acc.tg_nick = nick
    s.flush()
    result = linking_bll.try_link(s, cfg, acc)
    if result == "linked":
        return "✅ Ник сохранён, аккаунты связаны — голоса VK и TG объединены."
    if result == "conflict":
        return "Ник сохранён, но он заявлен несколькими людьми — попроси админа связать вручную."
    return (
        "Ник сохранён. Как только ты проголосуешь в TG тем же аккаунтом — "
        "объединю голоса автоматически."
    )


async def revalidate_membership(app, s, cfg: Config) -> list[str]:
    """Сверка членства (академ): вышел из сообщества — paused + уведомление,
    вернулся — active + карточки."""
    lines: list[str] = []
    for sub, acc in repo.active_subscriptions(s):
        try:
            is_member = await app.vk.is_member(acc.platform_user_id)
        except Exception as e:
            app.log.warning("revalidate: isMember(%s) failed: %s", acc.platform_user_id, e)
            return lines
        if not is_member:
            repo.set_subscription_status(s, acc.id, "paused")
            drop_dm_cards(s, acc.id)
            lines.append(f"{acc.display_name}: active→paused (академ)")
            from .publication import OutMessageVM
            vm = OutMessageVM(kind="notice", text=(
                "📴 Ты в академе: тебя нет в сообществе клуба, поэтому события, "
                "опросы и объявления больше не приходят. Вернёшься в сообщество — "
                "всё снова заработает."
            ))
            repo.enqueue_job(
                s, op="send", platform="vk", chat_id=acc.platform_user_id,
                account_id=acc.id, view_model=vm.to_dict(),
                idempotency_key=f"academ:{acc.id}",
            )
    paused = list(s.scalars(select(Subscription).where(Subscription.status == "paused")))
    for sub in paused:
        acc = repo.get_account(s, sub.account_id)
        if acc is None:
            continue
        try:
            is_member = await app.vk.is_member(acc.platform_user_id)
        except Exception:
            continue
        if is_member:
            repo.set_subscription_status(s, acc.id, "active")
            given = 0
            for ev in repo.open_events(s):
                ensure_dm_card(s, cfg, ev, acc.id, acc.platform_user_id)
                given += 1
            from . import polls as polls_bll
            for p in repo.open_polls(s):
                polls_bll.ensure_poll_card(s, cfg, p.id, acc.id, "vk",
                                           str(acc.platform_user_id))
                given += 1
            lines.append(f"{acc.display_name}: paused→active (+{given} карточек)")
            from .publication import OutMessageVM
            vm = OutMessageVM(kind="notice", text="👋 С возвращением! События и опросы снова приходят.")
            repo.enqueue_job(
                s, op="send", platform="vk", chat_id=acc.platform_user_id,
                account_id=acc.id, view_model=vm.to_dict(),
                idempotency_key=f"welcome:{acc.id}",
            )
    return lines


async def sync_people(app) -> list[str]:
    """Полный синк людей: руководители + членство. Возвращает строки изменений."""
    cfg: Config = app.cfg
    admin_lines = await app.refresh_admins()
    with app.db.session() as s:
        member_lines = await revalidate_membership(app, s, cfg)
        s.commit()
    return admin_lines + member_lines
