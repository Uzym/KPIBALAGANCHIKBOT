"""BLL: голосование (RSVP)."""
from __future__ import annotations

from dal import repositories as repo

from config import Config
from .publication import refresh_content

VALID = {"yes", "maybe", "no"}

TOASTS = {
    "ok": "Записал ✅",
    "ok_maybe": "Отметил «возможно» 🤔",
    "ok_no": "Понял, не придёшь ❌",
    "removed": "Ответ снят",
    "same": "Уже так и отмечено",
    "closed": "🔒 Запись уже закрыта",
    "not_active": "Событие уже не активно",
    "no_event": "Событие не найдено",
}


def cast_vote(s, cfg: Config, platform: str, user_id: int, event_id: int, answer: str) -> str:
    """Ключ тоста. Вызывающий уже проверил подписку/линковку."""
    if answer not in VALID:
        return "no_event"
    event = repo.get_event(s, event_id)
    if event is None:
        return "no_event"
    if event.cancelled or event.status in ("cancelled", "finished"):
        return "not_active"
    if event.status != "active":
        return "closed"

    acc = repo.ensure_account(s, platform, user_id)
    vote, changed = repo.upsert_vote(s, event_id, acc.id, answer)
    if changed:
        refresh_content(s, cfg, "event", event_id)
        if answer == "yes":
            return "ok"
        if answer == "maybe":
            return "ok_maybe"
        return "ok_no"
    return "same"


def remove_vote(s, cfg: Config, platform: str, user_id: int, event_id: int) -> str:
    event = repo.get_event(s, event_id)
    if event is None:
        return "no_event"
    if event.status != "active":
        return "closed"
    acc = repo.ensure_account(s, platform, user_id)
    removed = False
    if acc.person_id:
        # слинкованная персона: снимаем голоса всех её аккаунтов (VK и TG)
        for v, a in repo.votes_with_accounts(s, event_id):
            if a.person_id == acc.person_id:
                repo.delete_vote(s, event_id, a.id)
                removed = True
    else:
        removed = repo.delete_vote(s, event_id, acc.id)
    if removed:
        refresh_content(s, cfg, "event", event_id)
        return "removed"
    return "same"
