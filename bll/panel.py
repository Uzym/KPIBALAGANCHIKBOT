"""BLL: админ-панель — вход по одобрению, токены доступа, уведомления.

Все функции синхронные (ставят задачи в outbox) — панель работает из
своего потока, не трогая event loop бота.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from dal import repositories as repo
from dal.database import from_db, now_utc

from config import Config
from .contracts import ButtonVM, OutMessageVM

LOGIN_COOLDOWN_SECONDS = 60


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_token(token: str) -> str:
    """Публичный хеш токена (для секретного входа владельца)."""
    return _hash(token)


def request_login(s, cfg: Config, ip: str, ua: str, label: str,
                  admins: set[int]) -> tuple[int | None, str | None, str | None]:
    """Заявка на вход в панель. Возвращает (session_id, token, ошибка).

    Токен генерируется здесь и отдаётся клиенту один раз; в БД — только хеш.
    Действовать токен начинает после одобрения админом.
    """
    ip = (ip or "?")[:64]
    since = now_utc() - dt.timedelta(seconds=LOGIN_COOLDOWN_SECONDS)
    if repo.recent_panel_sessions_from_ip(s, ip, since):
        return None, None, "Слишком часто — подожди минуту."
    token = secrets.token_urlsafe(32)
    sess = repo.create_panel_session(s, ip=ip, ua=ua, label=label)
    sess.token_hash = _hash(token)
    _notify_admins_request(s, cfg, sess, admins)
    return sess.id, token, None


def poll_status(s, session_id: int) -> str:
    sess = repo.get_panel_session(s, session_id)
    return sess.status if sess else "missing"


def approve_login(s, session_id: int, approver_id: int) -> str | None:
    """Одобрение заявки: токен клиента становится действительным."""
    sess = repo.get_panel_session(s, session_id)
    if sess is None:
        return "Заявка не найдена"
    if sess.status != "pending":
        return "Уже обработана"
    sess.status = "approved"
    sess.approved_by = approver_id
    sess.approved_at = now_utc()
    return None


def deny_login(s, session_id: int, approver_id: int) -> str | None:
    sess = repo.get_panel_session(s, session_id)
    if sess is None:
        return "Заявка не найдена"
    if sess.status != "pending":
        return "Уже обработана"
    sess.status = "denied"
    sess.approved_by = approver_id
    return None


def check_token(s, token: str) -> bool:
    sess = repo.panel_session_by_token_hash(s, _hash(token))
    return sess is not None and sess.status == "approved"


def revoke_login(s, session_id: int) -> bool:
    sess = repo.get_panel_session(s, session_id)
    if sess is None or sess.status not in ("approved", "pending"):
        return False
    sess.status = "revoked"
    sess.token_hash = None
    return True


def session_lines(s, status: str = "approved") -> list[str]:
    out = []
    for sess in repo.panel_sessions_by_status(s, status):
        when = from_db(sess.created_at).strftime("%d.%m %H:%M")
        out.append(f"#{sess.id} · {sess.label or 'без подписи'} · IP {sess.ip} · {when}")
    return out


def _notify_admins_request(s, cfg: Config, sess, admins: set[int]) -> None:
    """Заявка на вход — всем админам с кнопками ✅/❌ (через outbox)."""
    text = (f"🔐 Попытка входа в панель: {sess.label or 'без подписи'}\n"
            f"IP {sess.ip} · {from_db(sess.created_at).strftime('%d.%m %H:%M')}")
    for uid in admins:
        vm = OutMessageVM(kind="notice", text=text, buttons=[
            [ButtonVM(action="panel_req", label="✅ Одобрить", value="yes", event_id=sess.id)],
            [ButtonVM(action="panel_req", label="❌ Отклонить", value="no", event_id=sess.id)],
        ])
        repo.enqueue_job(
            s, op="send", platform="vk", chat_id=uid,
            view_model=vm.to_dict(), idempotency_key=f"panelreq:{sess.id}:{uid}",
        )


def log_to_tech(s, cfg: Config, text: str) -> None:
    """Строка журнала панели в чат «Логи»."""
    if not cfg.tech_admin_vk_peer:
        return
    vm = OutMessageVM(kind="notice", text=text)
    repo.enqueue_job(
        s, op="send", platform="vk", chat_id=cfg.tech_admin_vk_peer,
        view_model=vm.to_dict(), idempotency_key=f"panellog:{text}",
    )
