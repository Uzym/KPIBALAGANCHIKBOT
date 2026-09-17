"""BLL: межслойные контракты (DTO входа и ViewModel выхода).

API-слой приводит апдейты платформ к IncomingMessage/ButtonPress и передаёт в BLL.
BLL возвращает OutMessageVM — платформонезависимое сообщение; рендер в текст
ВК/TG делают рендереры API-слоя.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatRef:
    platform: str  # vk | tg
    chat_id: int
    thread_id: int | None = None


@dataclass
class AccountRef:
    platform: str
    user_id: int


@dataclass
class MediaRef:
    kind: str  # photo | doc | voice | video_link
    url: str | None = None
    tg_file_id: str | None = None
    vk_attachment: str | None = None  # готовая строка attachment ("photo1_2")
    filename: str | None = None
    caption: str | None = None


@dataclass
class IncomingMessage:
    platform: str
    chat: ChatRef
    account: AccountRef
    text: str
    message_id: int | None = None
    sender_name: str = ""
    media: list[MediaRef] = field(default_factory=list)
    reply_to_message_id: int | None = None
    reply_snippet: str | None = None  # короткий текст сообщения, на которое ответили
    fwd_lines: list[str] = field(default_factory=list)  # развёрнутые пересылки
    is_admin: bool = False
    is_bot_own: bool = False


@dataclass
class ButtonPress:
    platform: str
    chat: ChatRef
    account: AccountRef
    message_id: int
    callback_id: str  # VK event_id / TG callback_query.id — для тоста
    action: str
    value: str | None = None
    event_id: int | None = None


# --- ViewModel -----------------------------------------------------------------


@dataclass
class ButtonVM:
    action: str  # vote | remove_vote | publish | cancel_draft | close | cancel_event | menu
    label: str
    value: str | None = None
    event_id: int | None = None


@dataclass
class EntryVM:
    name: str
    tag: str | None = None        # [VK]/[TG] для неслинкованных
    struck_at: str | None = None  # время смены выбора, если запись зачёркнута


@dataclass
class ListVM:
    answer: str   # yes | maybe | no
    title: str    # «✅ Придут»
    entries: list[EntryVM] = field(default_factory=list)


@dataclass
class EventVM:
    event_id: int
    title: str
    when_line: str
    place: str | None = None
    note: str | None = None
    status_line: str | None = None
    lists: list[ListVM] = field(default_factory=list)


@dataclass
class PollOptionVM:
    idx: int
    text: str
    entries: list[EntryVM] = field(default_factory=list)


@dataclass
class PollVM:
    poll_id: int
    title: str
    multichoice: bool
    closes_line: str | None = None
    status_line: str | None = None
    options: list[PollOptionVM] = field(default_factory=list)


@dataclass
class OutMessageVM:
    kind: str  # dm_card|preview|notice|announcement|menu
    text: str | None = None
    event: EventVM | None = None
    poll: PollVM | None = None
    buttons: list[list[ButtonVM]] = field(default_factory=list)
    reply_to: int | None = None  # message_id в целевом чате (для реплаев)
    media: list[MediaRef] = field(default_factory=list)

    # --- сериализация для outbox -------------------------------------------
    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "OutMessageVM":
        media = [MediaRef(**m) for m in d.get("media") or []]
        buttons = [[ButtonVM(**b) for b in row] for row in d.get("buttons") or []]
        ev = d.get("event")
        if ev:
            lists = [ListVM(**{**l, "entries": [EntryVM(**e) for e in l["entries"]]}) for l in ev.get("lists") or []]
            ev = EventVM(**{**ev, "lists": lists})
        pv = d.get("poll")
        if pv:
            opts = [
                PollOptionVM(**{**o, "entries": [EntryVM(**e) for e in o["entries"]]})
                for o in pv.get("options") or []
            ]
            pv = PollVM(**{**pv, "options": opts})
        return OutMessageVM(
            kind=d["kind"], text=d.get("text"), event=ev, poll=pv,
            buttons=buttons, reply_to=d.get("reply_to"), media=media,
        )


def vm_hash(vm: OutMessageVM) -> str:
    import hashlib

    payload = json.dumps(vm.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
