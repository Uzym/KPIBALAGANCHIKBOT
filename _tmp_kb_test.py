import asyncio
import json

from api.sslctx import build_ssl_context
from api.vk_client import VKClient
from config import Config


async def main():
    cfg = Config.load(".env")
    vk = VKClient(cfg.vk_token, cfg.vk_group_id, ssl_ctx=build_ssl_context())
    admin = cfg.admin_vk_ids[0]

    kb1 = {"inline": True, "buttons": [[{"action": {
        "type": "callback", "label": "Btn v1", "payload": json.dumps({"a": "poll", "e": 1, "v": "0"})},
        "color": "primary"}]]}
    kb2 = {"inline": True, "buttons": [[{"action": {
        "type": "callback", "label": "Btn v2 CHANGED", "payload": json.dumps({"a": "poll", "e": 1, "v": "1"})},
        "color": "positive"}]]}

    mid = await vk.send_message(admin, "kb edit test v1", keyboard=kb1)
    print("sent", mid)
    await asyncio.sleep(1.5)
    r = await vk.edit_message(admin, mid, "kb edit test v2", keyboard=kb2)
    print("edited:", r)
    await asyncio.sleep(1.5)
    g = await vk.call("messages.getById", message_ids=str(mid), extended=0)
    item = (g.get("items") or [{}])[0]
    kb_now = item.get("keyboard")
    print("keyboard after edit:", json.dumps(kb_now, ensure_ascii=False))
    label = ""
    try:
        label = kb_now["buttons"][0][0]["action"]["label"]
    except Exception:
        pass
    print("LABEL:", label, "| CHANGED:", "CHANGED" in label)
    await vk.delete_message(admin, mid)
    print("cleaned")
    await vk.close()


asyncio.run(main())
