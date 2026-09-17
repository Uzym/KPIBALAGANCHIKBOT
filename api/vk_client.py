"""API: клиент ВК — Bots Long Poll + вызовы методов + загрузка медиа."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from typing import Any, Callable

import aiohttp

log = logging.getLogger("vk")

API_BASE = "https://api.vk.com/method/"


class VKApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"VK error {code}: {message}")
        self.code = code
        self.message = message


class VKClient:
    def __init__(self, token: str, group_id: int, api_version: str = "5.199",
                 ssl_ctx=None):
        self.token = token
        self.group_id = group_id
        self.v = api_version
        self._ssl = ssl_ctx
        self._session: aiohttp.ClientSession | None = None
        self._poll_session: aiohttp.ClientSession | None = None
        self._user_names: dict[int, dict] = {}

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=35),
                connector=aiohttp.TCPConnector(ssl=self._ssl),
                trust_env=True,  # HTTPS_PROXY/HTTP_PROXY (VPS, где Telegram/VK за прокси)
            )
        return self._session

    async def close(self) -> None:
        for s in (self._session, self._poll_session):
            if s and not s.closed:
                await s.close()

    # --- вызовы методов ------------------------------------------------------

    async def call(self, method: str, **params: Any) -> Any:
        session = await self._ensure_session()
        payload = {k: v for k, v in params.items() if v is not None}
        payload.update({"access_token": self.token, "v": self.v})
        async with session.post(API_BASE + method, data=payload) as resp:
            data = await resp.json(content_type=None)
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            raise VKApiError(err.get("error_code", -1), err.get("error_msg", "unknown"))
        return data.get("response") if isinstance(data, dict) else data

    # --- long poll -------------------------------------------------------------

    async def poll_forever(self, handler: Callable[[dict], Any]) -> None:
        if self._poll_session is None or self._poll_session.closed:
            self._poll_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=40),
                connector=aiohttp.TCPConnector(ssl=self._ssl),
                trust_env=True,
            )
        server = key = ts = None
        while True:
            try:
                if server is None:
                    server_data = await self.call("groups.getLongPollServer", group_id=self.group_id)
                    server, key, ts = server_data["server"], server_data["key"], server_data["ts"]
                    log.info("VK long poll запущен (group_id=%s)", self.group_id)
                url = f"{server}?act=a_check&key={key}&ts={ts}&wait=25"
                async with self._poll_session.get(url) as resp:
                    data = await resp.json(content_type=None)
                if "failed" in data:
                    code = data["failed"]
                    if code == 1:
                        ts = data["ts"]
                    else:
                        server_data = await self.call(
                            "groups.getLongPollServer", group_id=self.group_id
                        )
                        server, key = server_data["server"], server_data["key"]
                        ts = server_data.get("ts", data.get("ts", ts))
                    continue
                ts = data.get("ts", ts)
                for update in data.get("updates", []):
                    try:
                        await handler(update)
                    except Exception:
                        log.exception("обработка апдейта VK: %s", update)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if "CERTIFICATE_VERIFY_FAILED" in str(e):
                    log.error(
                        "SSL: сертификат api.vk.com не доверенный (антивирус/прокси?). "
                        "Варианты: SSL_CA_BUNDLE=<путь к PEM>, либо временно SSL_VERIFY=false"
                    )
                log.warning("VK long poll: сеть/ошибка (%s), повтор через 5 с", e)
                await asyncio.sleep(5)
            except VKApiError as e:
                if e.code == 100 and "longpoll" in e.message.lower():
                    log.error(
                        "ВК: Bots Long Poll API не включён. Включите: сообщество → "
                        "Управление → Работа с API → Bots Long Poll API → «Включить». "
                        "Затем перезапустите бота."
                    )
                log.error("VK long poll: ошибка API (%s), повтор через 10 с", e)
                server = None
                await asyncio.sleep(10)
            except Exception:
                log.exception("VK long poll: неожиданная ошибка, пауза 5 с")
                await asyncio.sleep(5)

    # --- сообщения -------------------------------------------------------------

    async def send_message(
        self, peer_id: int, text: str | None = None, keyboard: dict | None = None,
        attachment: str | None = None, reply_to: int | None = None,
    ) -> int:
        resp = await self.call(
            "messages.send",
            peer_id=peer_id,
            message=text,
            keyboard=json.dumps(keyboard, ensure_ascii=False) if keyboard else None,
            attachment=attachment,
            reply_to=reply_to,
            random_id=random.randint(0, 2**31 - 1),  # int32, как требует API
        )
        return int(resp)

    async def edit_message(
        self, peer_id: int, conversation_message_id: int, text: str,
        keyboard: dict | None = None,
    ) -> int:
        resp = await self.call(
            "messages.edit",
            peer_id=peer_id,
            conversation_message_id=conversation_message_id,
            message=text,
            keyboard=json.dumps(keyboard, ensure_ascii=False) if keyboard else None,
            keep_snippets=1,
        )
        return int(resp)

    async def answer_event(self, event_id: str, user_id: int, peer_id: int, text: str) -> None:
        try:
            params: dict[str, Any] = {
                "event_id": event_id, "user_id": user_id, "peer_id": peer_id,
            }
            if text:
                # пустой текст = просто ack (снять спиннер с кнопки)
                params["event_data"] = json.dumps(
                    {"type": "show_snackbar", "text": text}, ensure_ascii=False
                )
            await self.call("messages.sendMessageEventAnswer", **params)
        except VKApiError as e:
            log.debug("toast не доставлен: %s", e)

    async def delete_message(self, peer_id: int, conversation_message_id: int) -> None:
        await self.call(
            "messages.delete", message_ids=str(conversation_message_id), delete_for_all=1
        )

    async def send_bulk(self, user_ids: list[int], text: str | None = None,
                        attachment: str | None = None) -> list[dict]:
        """Одна рассылка до 100 адресатов (peer_ids; user_ids устарел с 5.138)."""
        resp = await self.call(
            "messages.send",
            peer_ids=",".join(str(u) for u in user_ids),
            message=text,
            attachment=attachment,
            random_id=random.randint(0, 2**31 - 1),
        )
        if isinstance(resp, list):
            return resp
        return [{"peer_id": uid, "error": str(resp)} for uid in user_ids]

    # --- стена сообщества (только создание — лог завершённых событий/опросов) ----------

    async def wall_post(self, message: str) -> int:
        """Пост от имени сообщества (создание доступно с ключом сообщества)."""
        resp = await self.call("wall.post", owner_id=-self.group_id, from_group=1, message=message)
        return int(resp.get("post_id", 0))

    # --- участники/имена ---------------------------------------------------------

    async def conversation_member_ids(self, peer_id: int) -> set[int]:
        ids: set[int] = set()
        offset = 0
        while True:
            resp = await self.call(
                "messages.getConversationMembers",
                peer_id=peer_id, offset=offset, count=200, fields="",
            )
            for item in resp.get("items", []):
                mid = item.get("member_id")
                if mid and mid > 0:
                    ids.add(mid)
            offset += 200
            if offset >= int(resp.get("count", 0)):
                break
        return ids

    async def users_info(self, user_ids: list[int]) -> dict[int, dict]:
        if not user_ids:
            return {}
        resp = await self.call(
            "users.get", user_ids=",".join(map(str, user_ids[:200])), fields="domain"
        )
        return {int(u["id"]): u for u in resp or []}

    async def display_name(self, user_id: int) -> str:
        cached = self._user_names.get(user_id)
        if cached:
            return cached["name"]
        try:
            info = await self.users_info([user_id])
            u = info.get(user_id, {})
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or str(user_id)
            self._user_names[user_id] = {"name": name, "domain": u.get("domain")}
            return name
        except VKApiError:
            return str(user_id)

    async def resolve_user(self, screen_name: str) -> int | None:
        """Ник/ссылка ВК -> user_id (для линковки)."""
        resp = await self.call("users.get", user_ids=screen_name)
        if resp and isinstance(resp, list) and resp[0].get("id"):
            return int(resp[0]["id"])
        return None

    async def is_member(self, user_id: int) -> bool:
        """Членство пользователя в сообществе (валидация подписки)."""
        resp = await self.call("groups.isMember", group_id=self.group_id, user_id=user_id)
        return bool(resp)

    async def group_managers(self) -> set[int]:
        """Руководители сообщества (владелец + админы + редакторы) — источники прав."""
        resp = await self.call("groups.getMembers", group_id=self.group_id, filter="managers")
        ids: set[int] = set()
        for item in resp.get("items") or []:
            mid = item.get("id") or item.get("member_id")  # API отдаёт поле id
            if mid and int(mid) > 0:
                ids.add(int(mid))
        return ids

    # --- загрузка медиа ------------------------------------------------------------

    async def upload_photo(self, peer_id: int, data: bytes, filename: str = "photo.jpg") -> str:
        server = await self.call(
            "photos.getMessagesUploadServer", peer_id=peer_id
        )
        upload_url = server["upload_url"]
        session = await self._ensure_session()
        form = aiohttp.FormData()
        form.add_field("photo", data, filename=filename, content_type="image/jpeg")
        async with session.post(upload_url, data=form) as resp:
            uploaded = await resp.json(content_type=None)
        saved = await self.call(
            "photos.saveMessagesPhoto",
            photo=uploaded.get("photo"), server=uploaded.get("server"),
            hash=uploaded.get("hash"),
        )
        p = saved[0]
        return f"photo{p['owner_id']}_{p['id']}"

    async def upload_doc(
        self, peer_id: int, data: bytes, filename: str, kind: str = "doc",
    ) -> str:
        """kind: doc | audio_message (голосовое)."""
        server = await self.call(
            "docs.getMessagesUploadServer", type=kind, peer_id=peer_id
        )
        session = await self._ensure_session()
        form = aiohttp.FormData()
        form.add_field(
            "file", data, filename=filename,
            content_type="audio/ogg" if kind == "audio_message" else "application/octet-stream",
        )
        async with session.post(server["upload_url"], data=form) as resp:
            uploaded = await resp.json(content_type=None)
        file_meta = uploaded.get("file", uploaded)
        if isinstance(file_meta, dict):
            file_meta = json.dumps(file_meta)
        # docs.save ждёт строку «file» как есть (из ответа upload-сервера)
        saved = await self.call("docs.save", file=file_meta, title=filename)
        item = saved[0] if isinstance(saved, list) else saved
        doc = item.get("doc", item)
        return f"doc{doc['owner_id']}_{doc['id']}"

    async def download(self, url: str) -> bytes:
        session = await self._ensure_session()
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()
