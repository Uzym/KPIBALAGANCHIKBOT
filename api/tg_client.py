"""API: клиент Telegram Bot API (long polling, без внешних фреймворков)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import aiohttp

log = logging.getLogger("tg")


class TGApiError(Exception):
    def __init__(self, description: str, code: int | None = None, parameters: dict | None = None):
        super().__init__(f"TG error: {description}")
        self.description = description
        self.code = code
        self.parameters = parameters or {}


class TGClient:
    def __init__(self, token: str, ssl_ctx=None):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        self._ssl = ssl_ctx
        self._session: aiohttp.ClientSession | None = None
        self._file_session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=35),
                connector=aiohttp.TCPConnector(ssl=self._ssl),
                trust_env=True,  # HTTPS_PROXY/HTTP_PROXY (VPS, где Telegram заблокирован)
            )
        return self._session

    async def close(self) -> None:
        for s in (self._session, self._file_session):
            if s and not s.closed:
                await s.close()

    async def call(self, method: str, data: dict | None = None) -> Any:
        session = await self._ensure_session()
        async with session.post(f"{self.base}/{method}", json=data or {}) as resp:
            payload = await resp.json(content_type=None)
        if not payload.get("ok"):
            raise TGApiError(
                payload.get("description", "unknown"),
                payload.get("error_code"),
                payload.get("parameters"),
            )
        return payload.get("result")

    # --- long poll ---------------------------------------------------------------

    async def poll_forever(self, handler: Callable[[dict], Any]) -> None:
        session = await self._ensure_session()
        offset = 0
        started = False
        while True:
            try:
                if not started:
                    await self.call("deleteWebhook", {"drop_pending_updates": False})
                    me = await self.call("getMe")
                    log.info("TG long poll запущен (@%s)", me.get("username"))
                    started = True
                async with session.get(
                    f"{self.base}/getUpdates",
                    params={
                        "offset": offset,
                        "timeout": 30,
                        "allowed_updates": json_dumps(["message", "callback_query"]),
                    },
                    timeout=aiohttp.ClientTimeout(total=40),
                ) as resp:
                    payload = await resp.json(content_type=None)
                if not payload.get("ok"):
                    raise TGApiError(payload.get("description", "getUpdates failed"))
                for update in payload.get("result", []):
                    offset = max(offset, update["update_id"] + 1)
                    try:
                        await handler(update)
                    except Exception:
                        log.exception("обработка апдейта TG: %s", update)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if "CERTIFICATE_VERIFY_FAILED" in str(e):
                    log.error(
                        "SSL: сертификат api.telegram.org не доверенный (антивирус/прокси?). "
                        "Варианты: SSL_CA_BUNDLE=<путь к PEM>, либо временно SSL_VERIFY=false"
                    )
                log.warning("TG long poll: сеть/ошибка (%s), повтор через 5 с", e)
                await asyncio.sleep(5)
            except TGApiError as e:
                log.error("TG long poll: ошибка API (%s), повтор через 10 с", e)
                await asyncio.sleep(10)
            except Exception:
                log.exception("TG long poll: неожиданная ошибка, пауза 5 с")
                await asyncio.sleep(5)

    # --- сообщения -----------------------------------------------------------------

    async def send_message(
        self, chat_id: int, text: str, reply_markup: dict | None = None,
        thread_id: int | None = None, reply_to: int | None = None,
        disable_web_page_preview: bool = True,
    ) -> int:
        data: dict[str, Any] = {
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": disable_web_page_preview},
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        if thread_id:
            data["message_thread_id"] = thread_id
        if reply_to:
            data["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        msg = await self.call("sendMessage", data)
        return msg["message_id"]

    async def edit_message_text(
        self, chat_id: int, message_id: int, text: str, reply_markup: dict | None = None,
    ) -> None:
        data: dict[str, Any] = {
            "chat_id": chat_id, "message_id": message_id, "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        await self.call("editMessageText", data)

    async def answer_callback(self, callback_query_id: str, text: str | None = None) -> None:
        try:
            await self.call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})
        except TGApiError as e:
            log.debug("callback answer не доставлен: %s", e)

    async def delete_message(self, chat_id: str, message_id: int) -> None:
        await self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    # --- медиа ----------------------------------------------------------------------

    async def send_media(
        self, chat_id: int, media: list[dict], thread_id: int | None = None,
        reply_to: int | None = None,
    ) -> None:
        """media: [{kind, url|file_id, caption}] через sendPhoto/sendDocument/sendVoice."""
        for i, item in enumerate(media):
            method = {"photo": "sendPhoto", "doc": "sendDocument", "voice": "sendVoice"}.get(
                item["kind"], "sendDocument"
            )
            data: dict[str, Any] = {
                "chat_id": chat_id,
                item["kind"] if item["kind"] != "doc" else "document": item.get("url") or item.get("file_id"),
            }
            if i == 0 and item.get("caption"):
                data["caption"] = item["caption"]
                data["parse_mode"] = "HTML"
            if thread_id:
                data["message_thread_id"] = thread_id
            if reply_to and i == 0:
                data["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
            await self.call(method, data)

    async def get_file(self, file_id: str) -> dict:
        return await self.call("getFile", {"file_id": file_id})

    async def file_url(self, file_id: str) -> str | None:
        try:
            info = await self.get_file(file_id)
            path = info.get("file_path")
            return f"https://api.telegram.org/file/bot{self.token}/{path}" if path else None
        except TGApiError as e:
            log.warning("getFile(%s…) failed: %s", str(file_id)[:24], e)
            return None

    async def download(self, url: str) -> bytes:
        if self._file_session is None or self._file_session.closed:
            self._file_session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=self._ssl),
                trust_env=True,
            )
        async with self._file_session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value)
