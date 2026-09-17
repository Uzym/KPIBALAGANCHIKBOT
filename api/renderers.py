"""API: рендеринг ViewModel в платформенные тексты и клавиатуры.

VK — простой текст (markdown нет; зачёркивание юникодом), TG — HTML (нативный <s>).
"""
from __future__ import annotations

import html
import json

from bll.contracts import ButtonVM, OutMessageVM

MAX_LEN = 3900  # запас до лимитов платформ (4096)

VK_COLORS = {
    ("vote", "yes"): "positive",
    ("vote", "no"): "negative",
    ("vote", "maybe"): "secondary",
    ("remove_vote", None): "secondary",
    ("publish", None): "primary",
}


# --- VK -------------------------------------------------------------------------


def vk_strike(text: str, fallback: bool = False) -> str:
    if fallback:
        return f"({text})"
    combining = "\u0336"
    return "".join(ch + combining if ch != " " else ch for ch in text)


def _vk_entry(name: str, tag: str | None, struck_at: str | None, fallback: bool) -> str:
    base = name + (f" [{tag}]" if tag else "")
    if struck_at:
        return f"{vk_strike(base, fallback)} ({struck_at})"
    return base


def _event_lines_vk(vm: OutMessageVM, fallback: bool) -> list[str]:
    ev = vm.event
    lines: list[str] = []
    if ev.status_line:
        lines.append(ev.status_line)
    lines.append(f"📋 {ev.title}")
    place = f" · 📍 {ev.place}" if ev.place else ""
    lines.append(f"📅 {ev.when_line}{place}")
    if ev.note:
        lines.append(ev.note)
    lines.append("")
    for lst in ev.lists:
        # зачёркивания убраны: показываем только актуальных (struck-записи фильтруем
        # на случай устаревших VM в outbox)
        current = [e for e in lst.entries if not e.struck_at]
        parts = [_vk_entry(e.name, e.tag, None, fallback) for e in current]
        lines.append(f"{lst.title} ({len(current)}): {', '.join(parts) if parts else '—'}")
    return lines


def _vk_payload(b: ButtonVM) -> str:
    payload: dict = {"a": b.action}
    if b.event_id is not None:
        payload["e"] = b.event_id
    if b.value is not None:
        payload["v"] = b.value
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _poll_lines_vk(vm: OutMessageVM, fallback: bool) -> list[str]:
    p = vm.poll
    lines: list[str] = []
    if p.status_line:
        lines.append(p.status_line)
    lines.append(f"🗳 {p.title}")
    mode = "Можно выбрать несколько" if p.multichoice else "Один вариант"
    if p.closes_line:
        mode += " · " + p.closes_line
    lines.append(mode)
    lines.append("")
    for o in p.options:
        current = [e for e in o.entries if not e.struck_at]
        parts = [_vk_entry(e.name, e.tag, None, fallback) for e in current]
        lines.append(f"{o.idx + 1}️⃣ {o.text} — {len(current)}: {', '.join(parts) if parts else '—'}")
    return lines


def _poll_html(vm: OutMessageVM) -> str:
    p = vm.poll
    lines: list[str] = []
    if p.status_line:
        lines.append(f"<b>{esc(p.status_line)}</b>")
    lines.append(f"<b>🗳 {esc(p.title)}</b>")
    mode = "Можно выбрать несколько" if p.multichoice else "Один вариант"
    if p.closes_line:
        mode += " · " + esc(p.closes_line)
    lines.append(mode)
    lines.append("")
    for o in p.options:
        current = [e for e in o.entries if not e.struck_at]
        parts = [_tg_entry(e) for e in current]
        lines.append(f"{o.idx + 1}️⃣ {esc(o.text)} — {len(current)}: "
                     f"{', '.join(parts) if parts else '—'}")
    return "\n".join(lines)


def render_vk(vm: OutMessageVM, strike_fallback: bool = False) -> tuple[str, dict | None]:
    if vm.event:
        lines = [f"#{vm.event.event_id}"] + _event_lines_vk(vm, strike_fallback)
        if vm.text:
            lines += ["", vm.text]
        text = "\n".join(lines)
    elif vm.poll:
        lines = [f"#{vm.poll.poll_id}"] + _poll_lines_vk(vm, strike_fallback)
        if vm.text:
            lines += ["", vm.text]
        text = "\n".join(lines)
    elif vm.text is not None:
        text = vm.text
    else:
        text = ""
    for m in vm.media:
        if m.kind == "video_link" and m.url:
            text += f"\n🎬 {m.url}"
    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 30] + "\n… (список сокращён, полнее — у бота: /события)"

    keyboard = None
    if vm.buttons:
        rows = []
        for row in vm.buttons:
            buttons = []
            for b in row:
                color = VK_COLORS.get((b.action, b.value), "secondary")
                buttons.append(
                    {
                        "action": {"type": "callback", "label": b.label[:40], "payload": _vk_payload(b)},
                        "color": color,
                    }
                )
            rows.append(buttons)
        keyboard = {"inline": True, "buttons": rows}
    return text, keyboard


# --- TG -------------------------------------------------------------------------


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def _tg_entry(e) -> str:
    base = esc(e.name) + (f" <i>[{esc(e.tag)}]</i>" if e.tag else "")
    if e.struck_at:
        return f"<s>{base}</s> <i>({esc(e.struck_at)})</i>"
    return base


def _event_html(vm: OutMessageVM) -> str:
    ev = vm.event
    lines: list[str] = []
    if ev.status_line:
        lines.append(f"<b>{esc(ev.status_line)}</b>")
    lines.append(f"<b>📋 {esc(ev.title)}</b>")
    place = f" · 📍 {esc(ev.place)}" if ev.place else ""
    lines.append(f"📅 {esc(ev.when_line)}{place}")
    if ev.note:
        lines.append(esc(ev.note))
    lines.append("")
    for lst in ev.lists:
        current = [e for e in lst.entries if not e.struck_at]
        parts = [_tg_entry(e) for e in current]
        lines.append(f"<b>{lst.title} ({len(current)}):</b> {', '.join(parts) if parts else '—'}")
    return "\n".join(lines)


def render_tg(vm: OutMessageVM) -> tuple[str, dict | None]:
    if vm.event:
        text = f"#{vm.event.event_id}\n" + _event_html(vm)
        if vm.text:
            text += "\n\n" + esc(vm.text)
    elif vm.poll:
        text = f"#{vm.poll.poll_id}\n" + _poll_html(vm)
        if vm.text:
            text += "\n\n" + esc(vm.text)
    elif vm.text is not None:
        text = esc(vm.text)
    else:
        text = ""
    for m in vm.media:
        if m.kind == "video_link" and m.url:
            text += f"\n🎬 {m.url}"
    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 30] + "\n… (список сокращён) — /events у бота"

    keyboard = None
    if vm.buttons:
        rows = []
        for row in vm.buttons:
            rows.append([{"text": b.label[:60], "callback_data": _tg_cb(b)} for b in row])
        keyboard = {"inline_keyboard": rows}
    return text, keyboard


def _tg_cb(b: ButtonVM) -> str:
    if b.action == "menu":
        return f"m:{b.value}"[:64]
    parts = [b.action[:20]]
    if b.event_id is not None:
        parts.append(str(b.event_id))
    if b.value is not None:
        parts.append(b.value[:20])
    return ":".join(parts)[:64]
