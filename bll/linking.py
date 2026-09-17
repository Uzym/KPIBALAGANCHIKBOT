"""BLL: линковка аккаунтов VK ↔ TG по заявленным никам + ручная связка."""
from __future__ import annotations

from sqlalchemy import select

from dal import repositories as repo
from dal.models import Account

from config import Config
from .publication import ensure_dm_cards_for_tg, refresh_content


def _merge_persons(s, a: Account, b: Account) -> None:
    if a.person_id and b.person_id and a.person_id != b.person_id:
        # конфликт двух персон — перепривязываем все аккаунты персоны b к персоне a
        for acc in s.scalars(select(Account).where(Account.person_id == b.person_id)):
            acc.person_id = a.person_id
    if a.person_id and not b.person_id:
        b.person_id = a.person_id
    elif b.person_id and not a.person_id:
        a.person_id = b.person_id
    elif not a.person_id and not b.person_id:
        p = repo.get_or_create_person(s, a.display_name or b.display_name)
        a.person_id = p.id
        b.person_id = p.id
    s.flush()


def _refresh_affected(s, cfg: Config, account_ids: list[int]) -> None:
    if not account_ids:
        return
    from dal.models import Vote

    event_ids = set(
        s.scalars(select(Vote.event_id).where(Vote.account_id.in_(account_ids)))
    )
    for eid in event_ids:
        refresh_content(s, cfg, "event", eid)


def link_accounts(s, cfg: Config, a: Account, b: Account) -> None:
    _merge_persons(s, a, b)
    _refresh_affected(s, cfg, [a.id, b.id])
    # слинкованному TG-аккаунту — сразу карточки всех активных событий/опросов
    for acc in (a, b):
        if acc.platform == "tg":
            ensure_dm_cards_for_tg(s, cfg, acc)


def try_link(s, cfg: Config, account: Account) -> str:
    """Попытка слинковать аккаунт по его заявленным никам.

    Возвращает: linked | none | conflict.
    """
    if account.platform == "vk" and account.tg_nick:
        cands = repo.find_tg_accounts_by_username(s, account.tg_nick)
        if len(cands) == 1:
            link_accounts(s, cfg, account, cands[0])
            return "linked"
        if len(cands) > 1:
            return "conflict"
    # обратный матчинг: vk-аккаунт заявил ник этого tg-аккаунта
    if account.platform == "tg" and account.username:
        claimed = list(
            s.scalars(
                select(Account).where(
                    Account.platform == "vk", Account.tg_nick.is_not(None)
                )
            )
        )
        for vk_acc in claimed:
            if (vk_acc.tg_nick or "").strip().lstrip("@").lower() == (
                account.username or ""
            ).strip().lstrip("@").lower():
                link_accounts(s, cfg, vk_acc, account)
                return "linked"
    return "none"


def admin_force_link(s, cfg: Config, vk_user_id: int, tg_user_id: int) -> str:
    a = repo.get_account_by_platform_id(s, "vk", vk_user_id)
    b = repo.get_account_by_platform_id(s, "tg", tg_user_id)
    if a is None or b is None:
        return "Не найдены оба аккаунта (они должны были хотя бы раз написать боту)."
    link_accounts(s, cfg, a, b)
    return f"Связал: {a.display_name} (VK) ↔ {b.display_name} (TG)."


def vk_name_for_person(s, account: Account) -> str | None:
    """ВК-имя персоны для статуса привязки в TG (имена в списках — из ВК)."""
    if account.person_id is None:
        return None
    accs = s.scalars(
        select(Account).where(Account.person_id == account.person_id, Account.platform == "vk")
    ).all()
    if not accs:
        return None
    return (accs[0].display_name or str(accs[0].platform_user_id)) if accs else None
