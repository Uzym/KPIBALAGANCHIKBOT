"""BLL: объявления — глобальные и по контенту (v5: только ЛС)."""
from __future__ import annotations

import dataclasses
import json

from dal import repositories as repo
from dal.database import from_db
from dal.models import Event, Poll

from config import Config
from .contracts import MediaRef
from .publication import notice_dm_tracked, refresh_content, wall_log
from .summary import fmt_when


def _media_json(media: list[MediaRef] | None) -> str | None:
    if not media:
        return None
    return json.dumps([dataclasses.asdict(m) for m in media], ensure_ascii=False)


def _content_header(s, cfg: Config, content_type: str, content_id: int) -> str:
    if content_type == "event":
        ev: Event | None = repo.get_event(s, content_id)
        if ev is None:
            return "[событие]"
        return f"[{ev.title}, {fmt_when(from_db(ev.starts_at), from_db(ev.ends_at), cfg.tz)}]"
    p: Poll | None = repo.get_poll(s, content_id)
    if p is None:
        return "[опрос]"
    return f"[опрос «{p.title}»]"


def publish_for_content(
    s, cfg: Config, content_type: str, content_id: int, text: str,
    media: list[MediaRef] | None = None, admin_account_id: int | None = None,
) -> int:
    """Объявление по событию/опросу: секция в карточке + TTL-уведомления."""
    a = repo.create_announcement(s, content_type, content_id, admin_account_id, text,
                                 media=_media_json(media))

    # секция «📢 Объявления» обновится при перерисовке карточек контента
    refresh_content(s, cfg, content_type, content_id)

    header = f"📢 {_content_header(s, cfg, content_type, content_id)}\n{text}"
    sent = notice_dm_tracked(
        s, cfg, header, announcements_only=True,
        content_type="announcement", content_id=a.id, media=media,
    )
    # архив: объявление дублируется постом в сообщество ВК
    wall_log(s, cfg, header, unique=f"ann{a.id}")
    return sent


def publish_global(
    s, cfg: Config, text: str, media: list[MediaRef] | None = None,
    admin_account_id: int | None = None,
) -> dict[str, int]:
    """Глобальное объявление: TTL-уведомления всем подписчикам (v5: только ЛС)."""
    a = repo.create_announcement(s, "global", None, admin_account_id, text,
                                 media=_media_json(media))
    header = f"📢 [Клуб]\n{text}"
    dm = notice_dm_tracked(
        s, cfg, header, announcements_only=True,
        content_type="announcement", content_id=a.id, media=media,
    )
    # архив: объявление дублируется постом в сообщество ВК
    wall_log(s, cfg, header, unique=f"ann{a.id}")
    return {"dm": dm}
