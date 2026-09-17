"""Интеграционная проверка живых API (v5: только ЛС + членство/руководители).

Read-only вызовы + опциональный самоликвидирующийся round-trip
(тест-сообщение админу, удаляется сразу).

Запуск:
  .venv\\Scripts\\python integration_check.py               — только read-only
  .venv\\Scripts\\python integration_check.py --messaging   — + тест-сообщение
"""
import asyncio
import sys

from api.sslctx import build_ssl_context
from api.tg_client import TGClient
from api.vk_client import VKClient
from config import Config


async def check_vk(vk: VKClient, cfg: Config, messaging: bool) -> list[str]:
    out: list[str] = []

    def add(name: str, status: str, extra: str = "") -> None:
        out.append(f"[{'OK' if 'FAIL' not in status else '!!'}] {name}: {status}"
                   + (f" — {extra}" if extra else ""))

    # 1. сообщество
    try:
        g = await vk.call("groups.getById", group_id=cfg.vk_group_id,
                          fields="members_count,is_closed,type")
        grp = g["groups"][0]
        closed = {0: "открытое", 1: "закрытое", 2: "частное"}.get(grp.get("is_closed"), "?")
        add("groups.getById", f"«{grp.get('name')}» ({closed}, участников: {grp.get('members_count')})")
    except Exception as e:
        add("groups.getById", f"FAIL {e}")
        return out

    # 2. long poll
    try:
        await vk.call("groups.getLongPollServer", group_id=cfg.vk_group_id)
        add("groups.getLongPollServer", "доступен (Bots Long Poll включён)")
    except Exception as e:
        add("groups.getLongPollServer", f"FAIL {e}")

    # 3. руководители (админы бота)
    try:
        managers = await vk.group_managers()
        add("groups.getMembers(managers)", f"{len(managers)}: {sorted(managers)}")
    except Exception as e:
        add("groups.getMembers(managers)", f"FAIL {e}")

    # 4. админы из конфига: членство и имена
    for uid in cfg.admin_vk_ids:
        try:
            member = await vk.is_member(uid)
            info = await vk.users_info([uid])
            u = info.get(uid, {})
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            add(f"isMember({uid})", "в сообществе" if member else "НЕ в сообществе", name)
        except Exception as e:
            add(f"isMember({uid})", f"FAIL {e}")

    # 5. медиа-права (объявления с вложениями)
    peer = cfg.admin_vk_ids[0] if cfg.admin_vk_ids else cfg.vk_group_id
    try:
        await vk.call("photos.getMessagesUploadServer", peer_id=peer)
        add("photos.getMessagesUploadServer", "доступен")
    except Exception as e:
        add("photos.getMessagesUploadServer", f"FAIL {e}")
    try:
        await vk.call("docs.getMessagesUploadServer", type="doc", peer_id=peer)
        add("docs.getMessagesUploadServer", "доступен")
    except Exception as e:
        add("docs.getMessagesUploadServer", f"FAIL {e}")

    # 6. round-trip ЛС (самоочистка): send → edit(+клавиатура) → delete
    if messaging and cfg.admin_vk_ids:
        import json as _json
        admin = cfg.admin_vk_ids[0]
        try:
            kb = {"inline": True, "buttons": [[{"action": {
                "type": "callback", "label": "Test", "payload": _json.dumps({"a": "test"})},
                "color": "primary"}]]}
            mid = await vk.send_message(admin, "🧪 Интеграционный тест (v1, удалится)", keyboard=kb)
            edited = await vk.edit_message(admin, mid, "🧪 Интеграционный тест (v2 — отредактировано)")
            info = await vk.call("messages.getById", message_ids=str(mid), extended=0)
            item = (info.get("items") or [{}])[0]
            ok = bool(edited) and "v2" in (item.get("text") or "")
            await vk.delete_message(admin, mid)
            add("messages.send+edit+delete (DM админу)",
                f"OK (message_id={mid}, edit подтверждён getById, удалено)"
                if ok else f"FAIL: edit не подтверждён getById ({item})")
        except Exception as e:
            add("messages.send+edit+delete", f"FAIL {e}")

        # bulk-рассылка (vk_bulk): один вызов user_ids → удалить сообщение
        try:
            results = await vk.send_bulk([admin], "Bulk test (self-deleting)")
            r0 = (results or [{}])[0]
            if "error" not in r0:
                mid = r0.get("conversation_message_id") or r0.get("message_id")
                await vk.delete_message(admin, int(mid))
                add("messages.send user_ids (bulk)", f"OK (message_id={mid}, удалено)")
            else:
                add("messages.send user_ids (bulk)", f"FAIL: {r0}")
        except Exception as e:
            add("messages.send user_ids (bulk)", f"FAIL {e}")

        # загрузка документа (путь /экспорт): upload_doc → attach → удалить
        try:
            att = await vk.upload_doc(admin, b"kpibalaganchikbot integration test", "itest.txt")
            mid = await vk.send_message(admin, "Doc test (self-deleting)", attachment=att)
            await vk.delete_message(admin, mid)
            add("docs upload+send+delete", f"OK (attachment={att}, message_id={mid}, удалено)")
        except Exception as e:
            add("docs upload+send+delete", f"FAIL {e}")

    return out


async def check_tg(tg: TGClient) -> list[str]:
    out: list[str] = []
    try:
        me = await tg.call("getMe")
        out.append(f"[OK] getMe: @{me.get('username')}")
    except Exception as e:
        out.append(f"[!!] TG недоступен: {e}")
        out.append("[..] Проверь сеть/прокси: TCP 443 к api.telegram.org закрыт? "
                   "TG-часть проверится на машине с доступом.")
    return out


async def main() -> None:
    cfg = Config.load(".env")
    messaging = "--messaging" in sys.argv
    vk = VKClient(cfg.vk_token, cfg.vk_group_id, cfg.vk_api_version,
                  ssl_ctx=build_ssl_context(cfg.ssl_ca_bundle, cfg.ssl_verify))
    tg = TGClient(cfg.tg_token, ssl_ctx=build_ssl_context(cfg.ssl_ca_bundle, cfg.ssl_verify))
    print("=== VK ===")
    for line in await check_vk(vk, cfg, messaging):
        print(line)
    print("=== TG ===")
    for line in await check_tg(tg):
        print(line)
    missing = cfg.validate_runtime()
    if missing:
        print("=== Ошибки конфига ===")
        for e in missing:
            print(" -", e)
    await vk.close()
    await tg.close()


if __name__ == "__main__":
    asyncio.run(main())
