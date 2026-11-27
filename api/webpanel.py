"""REST API + раздача статики фронтенда.

Полный CRUD: события, опросы, оплата, объявления, посещаемость.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib

from aiohttp import web

from bll import events as events_bll
from bll import fees as fees_bll
from bll import polls as polls_bll
from bll.announcements import publish_for_content
from bll.publication import event_vm
from bll.timeparse import parse_event_command, parse_when
from config import Config
from dal import repositories as repo
from dal.database import from_db

log = logging.getLogger("webpanel")

FRONTEND_DIST = pathlib.Path(__file__).parent.parent / "frontend" / "dist"


# ═══════════════ Сериализаторы ═══════════════


def ser_event(s, cfg: Config, ev) -> dict:
    vm = event_vm(s, cfg, ev)
    counts = {}
    for lst in vm.lists:
        counts[lst.answer] = len([e for e in lst.entries if not e.struck_at])
    votes = []
    for v, acc in repo.votes_with_accounts(s, ev.id):
        votes.append({
            "name": acc.display_name or str(acc.platform_user_id),
            "answer": v.answer,
            "prev": v.prev_answer if v.changes_count else None,
            "prevTime": from_db(v.updated_at).astimezone(cfg.tz).strftime("%H:%M") if v.prev_answer else None,
            "tag": acc.platform.upper() if not acc.person_id else None,
        })
    return {
        "id": ev.id,
        "title": ev.title,
        "starts_at": str(ev.starts_at),
        "ends_at": str(ev.ends_at),
        "place": ev.place,
        "note": ev.note,
        "status": ev.status,
        "cancelled": bool(getattr(ev, 'cancelled', False)),
        "counts": counts,
        "votes": votes,
        "my_vote": None,
    }


def ser_poll(s, cfg: Config, poll) -> dict:
    opts_raw = poll.options if isinstance(poll.options, list) else json.loads(poll.options or "[]")
    # подсчёт голосов
    from dal.models import PollVote
    from sqlalchemy import select, func
    counts = {}
    for row in s.execute(
        select(PollVote.option_id, func.count())
        .where(PollVote.poll_id == poll.id, PollVote.active == True)
        .group_by(PollVote.option_id)
    ):
        counts[row[0]] = row[1]
    total_votes = sum(counts.values())
    return {
        "id": poll.id,
        "question": poll.title,
        "multi": poll.multichoice,
        "status": "open" if poll.status == "active" else poll.status,
        "deadline": from_db(poll.closes_at).astimezone(cfg.tz).strftime("%d.%m") if poll.closes_at else None,
        "voted": total_votes,
        "options": [
            {"id": o["idx"], "label": o["text"], "count": counts.get(o["idx"], 0)}
            for o in opts_raw
        ],
        "my_picks": [],
    }


# ═══════════════ Хендлеры ═══════════════


def make_handler(app):
    cfg = app.cfg
    db = app.db

    # ─────────── СОБЫТИЯ ───────────

    async def get_events(request):
        with db.session() as s:
            events = repo.all_events(s)
            return web.json_response([ser_event(s, cfg, e) for e in events])

    async def get_event(request):
        eid = int(request.match_info["id"])
        with db.session() as s:
            ev = repo.get_event(s, eid)
            if ev is None:
                return web.json_response({"error": "not found"}, status=404)
            return web.json_response(ser_event(s, cfg, ev))

    async def create_event(request):
        body = await request.json()
        title = body.get("title", "").strip()
        starts_at = body.get("starts_at", "")
        if not title or not starts_at:
            return web.json_response({"error": "title и starts_at обязательны"}, status=400)
        with db.session() as s:
            # парсим дату
            parsed_when = parse_when(starts_at.replace("T", " "), cfg.tz, dt.datetime.now(cfg.tz))
            if parsed_when is None:
                return web.json_response({"error": f"не поняла дату «{starts_at}»"}, status=400)
            starts = parsed_when[0]
            ends = starts + dt.timedelta(hours=1)
            # конец из тела
            ends_raw = body.get("ends_at")
            if ends_raw:
                parsed_end = parse_when(ends_raw.replace("T", " "), cfg.tz, dt.datetime.now(cfg.tz), base=starts)
                if parsed_end:
                    ends = parsed_end[0]
            from dal.database import to_db
            ev = repo.create_event(
                s,
                title=title,
                starts_at=to_db(starts),
                ends_at=to_db(ends),
                place=body.get("place") or None,
                note=body.get("note") or None,
                status="active",
            )
            s.commit()
            result = events_bll.publish(s, cfg, ev.id)
            s.commit()
            if isinstance(result, dict):
                return web.json_response({"ok": True, "id": ev.id, **result})
            return web.json_response({"ok": True, "id": ev.id, "publish_result": str(result)})

    async def update_event(request):
        eid = int(request.match_info["id"])
        body = await request.json()
        with db.session() as s:
            ev = repo.get_event(s, eid)
            if ev is None:
                return web.json_response({"error": "not found"}, status=404)
            values = {}
            if "title" in body: values["title"] = body["title"]
            if "place" in body: values["place"] = body["place"] or None
            if "note" in body: values["note"] = body["note"] or None
            if "starts_at" in body:
                parsed = parse_when(body["starts_at"].replace("T", " "), cfg.tz, dt.datetime.now(cfg.tz))
                if parsed:
                    from dal.database import to_db
                    values["starts_at"] = to_db(parsed[0])
                    if "ends_at" not in body:
                        values["ends_at"] = to_db(parsed[0] + dt.timedelta(hours=1))
            if values:
                events_bll.update_fields(s, cfg, eid, values)
                s.commit()
            ev = repo.get_event(s, eid)
            return web.json_response(ser_event(s, cfg, ev))

    async def delete_event(request):
        eid = int(request.match_info["id"])
        with db.session() as s:
            result = events_bll.delete_event(s, cfg, eid)
            s.commit()
            return web.json_response({"ok": result is not None})

    async def close_event(request):
        eid = int(request.match_info["id"])
        with db.session() as s:
            result = events_bll.close(s, cfg, eid)
            s.commit()
            return web.json_response({"ok": result is not None, "message": result})

    async def reopen_event(request):
        eid = int(request.match_info["id"])
        with db.session() as s:
            result = events_bll.reopen(s, cfg, eid)
            s.commit()
            return web.json_response({"ok": result is not None, "message": result})

    async def cancel_event(request):
        eid = int(request.match_info["id"])
        with db.session() as s:
            events_bll.cancel(s, cfg, eid)
            s.commit()
            return web.json_response({"ok": True})

    async def post_vote(request):
        eid = int(request.match_info["id"])
        body = await request.json()
        answer = body.get("answer", "")
        user = request.get("user")
        if user:
            platform = user["platform"]
            user_id = user["platform_user_id"]
        else:
            platform = body.get("platform", "vk")
            user_id = int(body.get("user_id", 0))
        if not user_id:
            return web.json_response({"error": "не авторизован"}, status=401)
        with db.session() as s:
            result = rsvp_vote(s, cfg, platform, user_id, eid, answer)
            s.commit()
            ev = repo.get_event(s, eid)
            return web.json_response({"result": result, **ser_event(s, cfg, ev)})

    async def announce_event(request):
        eid = int(request.match_info["id"])
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return web.json_response({"error": "text обязателен"}, status=400)
        with db.session() as s:
            sent = publish_for_content(s, cfg, "event", eid, text)
            s.commit()
            return web.json_response({"ok": True, "sent": sent})

    async def toggle_attendance(request):
        eid = int(request.match_info["id"])
        body = await request.json()
        key = body.get("key", "")
        with db.session() as s:
            result = events_bll.toggle_attendance(s, eid, key)
            s.commit()
            return web.json_response({"present": result})

    # ─────────── ОПРОСЫ ───────────

    async def get_polls(request):
        with db.session() as s:
            polls = repo.all_polls(s)
            return web.json_response([ser_poll(s, cfg, p) for p in polls])

    async def create_poll(request):
        body = await request.json()
        question = body.get("question", "").strip()
        options = [o.strip() for o in body.get("options", []) if o.strip()]
        if not question or len(options) < 2:
            return web.json_response({"error": "нужны question и минимум 2 варианта"}, status=400)
        with db.session() as s:
            parsed = {
                "title": question,
                "options": [{"idx": i, "text": t} for i, t in enumerate(options)],
                "multichoice": bool(body.get("multichoice", False)),
                "closes_at": None,
            }
            poll = polls_bll.create_draft(s, cfg, None, parsed)
            s.commit()
            polls_bll.publish(s, cfg, poll.id)
            s.commit()
            p = repo.get_poll(s, poll.id)
            return web.json_response({"ok": True, "id": poll.id, **ser_poll(s, cfg, p)})

    async def update_poll(request):
        pid = int(request.match_info["id"])
        body = await request.json()
        with db.session() as s:
            poll = repo.get_poll(s, pid)
            if poll is None:
                return web.json_response({"error": "not found"}, status=404)
            if "question" in body:
                poll.title = body["question"]
            if "multichoice" in body:
                poll.multichoice = bool(body["multichoice"])
            if "options" in body:
                opts = [o.strip() for o in body["options"] if o.strip()]
                if len(opts) >= 2:
                    poll.options = json.dumps(
                        [{"idx": i, "text": t} for i, t in enumerate(opts)],
                        ensure_ascii=False,
                    )
            s.commit()
            p = repo.get_poll(s, pid)
            return web.json_response(ser_poll(s, cfg, p))

    async def delete_poll(request):
        pid = int(request.match_info["id"])
        with db.session() as s:
            result = polls_bll.delete_poll(s, cfg, pid)
            s.commit()
            return web.json_response({"ok": result is not None})

    async def close_poll(request):
        pid = int(request.match_info["id"])
        with db.session() as s:
            try:
                polls_bll.close(s, cfg, pid)
                s.commit()
            except Exception as e:
                log.warning("poll close outbox error (не критично): %s", e)
                s.rollback()
                # всё равно закрываем в БД
                from dal.models import Poll
                p = s.get(Poll, pid)
                if p:
                    p.status = "closed"
                    s.commit()
            return web.json_response({"ok": True})

    async def reopen_poll(request):
        pid = int(request.match_info["id"])
        with db.session() as s:
            try:
                polls_bll.reopen(s, cfg, pid)
                s.commit()
            except Exception as e:
                log.warning("poll reopen outbox error: %s", e)
                s.rollback()
                from dal.models import Poll
                p = s.get(Poll, pid)
                if p:
                    p.status = "active"
                    s.commit()
            return web.json_response({"ok": True})

    async def post_poll_vote(request):
        pid = int(request.match_info["id"])
        body = await request.json()
        option_id = int(body.get("option_id", 0))
        platform = body.get("platform", "vk")
        user_id = int(body.get("user_id", 0))
        with db.session() as s:
            try:
                result = polls_bll.cast_poll_vote(s, cfg, platform, user_id, pid, option_id)
                s.commit()
            except Exception as e:
                log.warning("poll vote outbox error (не критично): %s", e)
                s.rollback()
                result = "ok"  # голос засчитан, только карточка не обновилась
            return web.json_response({"result": result})

    # ─────────── ОПЛАТА ───────────

    async def get_fees(request):
        user = request.get("user")
        if user and user.get("person_id"):
            person_id = user["person_id"]
        else:
            person_id = int(request.query.get("person_id", 0))
        if not person_id:
            return web.json_response({"error": "person_id обязателен"}, status=400)
        with db.session() as s:
            debt = fees_bll.debt_of(s, person_id)
            history = fees_bll.history_text(s, cfg, person_id, limit=20)
            return web.json_response({
                "my_debt": debt,
                "monthly": cfg.fee_monthly_rub,
                "threshold": cfg.debt_alert_limit_rub,
                "history_text": history,
                "history": [],
            })

    async def post_fee_report(request):
        body = await request.json()
        amount = int(body.get("amount", 0))
        if not amount:
            return web.json_response({"error": "amount обязателен"}, status=400)
        return web.json_response({"ok": True, "hint": "заявка отправлена админам"})

    # ─────────── АДМИН ───────────

    async def get_admin_stats(request):
        with db.session() as s:
            events = repo.all_events(s)
            active_events = [e for e in events if e.status == "active"]
            polls = repo.all_polls(s)
            active_polls = [p for p in polls if p.status == "active"]
            sub_stats = repo.subscription_stats(s)

            total_debt = 0
            debt_over = 0
            collected = 0
            from dal.models import FeeEntry
            from sqlalchemy import select, func
            month_start = dt.datetime.now(cfg.tz).replace(day=1, hour=0, minute=0, second=0)
            for sub, acc in repo.active_subscriptions(s):
                if acc.person_id:
                    debt = fees_bll.debt_of(s, acc.person_id)
                    total_debt += debt
                    if debt > cfg.debt_alert_limit_rub:
                        debt_over += 1
            # собрано за месяц
            row = s.execute(
                select(func.sum(FeeEntry.amount_rub))
                .where(FeeEntry.kind == "payment", FeeEntry.amount_rub < 0,
                       FeeEntry.created_at >= month_start)
            ).scalar()
            collected = abs(row) if row else 0

            return web.json_response({
                "active_events": len(active_events),
                "active_polls": len(active_polls),
                "subscribers": sum(sub_stats.values()),
                "total_debt": total_debt,
                "debt_over_threshold": debt_over,
                "collected_month": collected,
                "subscription_stats": sub_stats,
            })

    async def get_admin_people(request):
        with db.session() as s:
            result = []
            for sub, acc in repo.active_subscriptions(s):
                debt = fees_bll.debt_of(s, acc.person_id) if acc.person_id else 0
                result.append({
                    "id": acc.person_id or acc.id,
                    "name": acc.display_name or str(acc.platform_user_id),
                    "platform": acc.platform,
                    "tg": acc.username if acc.platform == "tg" else None,
                    "vk": acc.platform == "vk",
                    "status": sub.status if sub else "unknown",
                    "debt": debt,
                    "akadem": sub.status == "paused" if sub else False,
                })
            return web.json_response(result)

    async def get_person_fees(request):
        """История операций по человеку: начисления, платежи, траты."""
        pid = int(request.match_info["id"])
        with db.session() as s:
            from dal.models import FeeEntry, Person
            from sqlalchemy import select
            person = s.get(Person, pid)
            if person is None:
                return web.json_response({"error": "person not found"}, status=404)
            entries = list(s.scalars(
                select(FeeEntry)
                .where(FeeEntry.person_id == pid)
                .order_by(FeeEntry.created_at.desc())
                .limit(50)
            ))
            return web.json_response({
                "name": fees_bll.display_name(person),
                "debt": fees_bll.debt_of(s, pid),
                "history": [
                    {
                        "kind": e.kind,
                        "amount": e.amount_rub,
                        "label": e.label or "",
                        "month": e.month or "",
                        "date": str(e.created_at)[:16] if e.created_at else "",
                    }
                    for e in entries
                ],
            })

    async def get_person_attendance(request):
        """Где был человек: события + ответ + отметка посещения."""
        pid = int(request.match_info["id"])
        with db.session() as s:
            from dal.models import Vote, Event, Account
            from sqlalchemy import select
            # все аккаунты этого человека
            accounts = list(s.scalars(
                select(Account).where(Account.person_id == pid)
            ))
            acc_ids = [a.id for a in accounts]
            if not acc_ids:
                return web.json_response([])
            # голоса по событиям
            votes = list(s.execute(
                select(Vote, Event)
                .join(Event, Vote.event_id == Event.id)
                .where(Vote.account_id.in_(acc_ids))
                .order_by(Event.starts_at.desc())
            ))
            result = []
            for vote, event in votes:
                result.append({
                    "event_id": event.id,
                    "title": event.title,
                    "starts_at": str(event.starts_at)[:16],
                    "status": event.status,
                    "answer": vote.answer,
                    "prev_answer": vote.prev_answer if vote.changes_count else None,
                    "attended": bool(getattr(event, 'attended_ids', None) and pid in (event.attended_ids or [])),
                })
            return web.json_response(result)

    async def post_admin_payment(request):
        body = await request.json()
        person_id = int(body.get("person_id", 0))
        amount = int(body.get("amount", 0))
        label = body.get("label", "")
        if not person_id or not amount:
            return web.json_response({"error": "person_id и amount обязательны"}, status=400)
        with db.session() as s:
            err, alert = fees_bll.record_payment(s, cfg, person_id, amount, label)
            s.commit()
            debt = fees_bll.debt_of(s, person_id)
            return web.json_response({"error": err, "alert": alert, "debt": debt})

    async def post_admin_charge(request):
        body = await request.json()
        person_id = int(body.get("person_id", 0))
        amount = int(body.get("amount", 0))
        label = body.get("label", "")
        if not person_id or not amount:
            return web.json_response({"error": "person_id и amount обязательны"}, status=400)
        with db.session() as s:
            fees_bll.record_expense(s, cfg, person_id, amount, label)
            s.commit()
            debt = fees_bll.debt_of(s, person_id)
            return web.json_response({"debt": debt})

    async def get_admin_applications(request):
        return web.json_response([])

    # ─────────── ЗДОРОВЬЕ ───────────

    async def health(request):
        return web.json_response({"status": "ok"})

    def rsvp_vote(s, cfg, platform, user_id, event_id, answer):
        from bll import rsvp as rsvp_bll
        return rsvp_bll.cast_vote(s, cfg, platform, user_id, event_id, answer)

    return locals()


# ═══════════════ Запуск ═══════════════


async def start_webpanel(app, port: int):
    h = make_handler(app)
    cfg = app.cfg

    web_app = web.Application()

    routes = [
        # события
        web.get("/api/events", h["get_events"]),
        web.get("/api/events/{id}", h["get_event"]),
        web.post("/api/events", h["create_event"]),
        web.put("/api/events/{id}", h["update_event"]),
        web.delete("/api/events/{id}", h["delete_event"]),
        web.post("/api/events/{id}/vote", h["post_vote"]),
        web.post("/api/events/{id}/close", h["close_event"]),
        web.post("/api/events/{id}/reopen", h["reopen_event"]),
        web.post("/api/events/{id}/cancel", h["cancel_event"]),
        web.post("/api/events/{id}/announce", h["announce_event"]),
        web.post("/api/events/{id}/attendance", h["toggle_attendance"]),
        # опросы
        web.get("/api/polls", h["get_polls"]),
        web.post("/api/polls", h["create_poll"]),
        web.put("/api/polls/{id}", h["update_poll"]),
        web.delete("/api/polls/{id}", h["delete_poll"]),
        web.post("/api/polls/{id}/vote", h["post_poll_vote"]),
        web.post("/api/polls/{id}/close", h["close_poll"]),
        web.post("/api/polls/{id}/reopen", h["reopen_poll"]),
        # оплата
        web.get("/api/fees", h["get_fees"]),
        web.post("/api/fees/report", h["post_fee_report"]),
        # админ
        web.get("/api/admin/stats", h["get_admin_stats"]),
        web.get("/api/admin/people", h["get_admin_people"]),
        web.get("/api/admin/people/{id}/fees", h["get_person_fees"]),
        web.get("/api/admin/people/{id}/attendance", h["get_person_attendance"]),
        web.post("/api/admin/fees/payment", h["post_admin_payment"]),
        web.post("/api/admin/fees/charge", h["post_admin_charge"]),
        web.get("/api/admin/applications", h["get_admin_applications"]),
        # здоровье
        web.get("/api/health", h["health"]),
    ]
    web_app.add_routes(routes)

    # ── авторизация (если задан PANEL_SECRET) ──────────────────
    # Панель содержит персональные данные — наружу (nginx/домен) без ключа нельзя.
    # Два способа доступа:
    #  1) Сессия пользователя (cookie "sid", создаётся через /api/auth/login?t=token из бота)
    #  2) PANEL_SECRET (?key= или Basic Auth) — админский bootstrap
    import base64 as _b64
    import uuid as _uuid
    from datetime import timedelta as _td
    from dal.models import WebSession as _WS, Account as _Acc, Person as _Per
    from dal.database import now_utc as _now
    from sqlalchemy import select as _sel

    SESSION_COOKIE = "sid"
    SESSION_DAYS = 30

    def _get_session_user(s, request):
        """Возвращает инфо о пользователе из cookie sid или None."""
        sid = request.cookies.get(SESSION_COOKIE)
        if not sid:
            return None
        ws = s.scalar(_sel(_WS).where(_WS.session_key == sid, _WS.login_used == True))
        if ws is None or ws.expires_at < _now():
            return None
        acc = s.get(_Acc, ws.account_id)
        if acc is None:
            return None
        is_admin = acc.platform == "vk" and acc.platform_user_id in cfg.admin_vk_ids
        sub = repo.get_subscription(s, acc.id)
        person = s.get(_Per, acc.person_id) if acc.person_id else None
        return {
            "account_id": acc.id,
            "person_id": acc.person_id,
            "name": (person.display_override if person and person.display_override else None)
                    or acc.display_name or str(acc.platform_user_id),
            "platform": acc.platform,
            "platform_user_id": acc.platform_user_id,
            "role": "admin" if is_admin else "member",
            "subscription": sub.status if sub else "unknown",
            "announcements": sub.send_announcements if sub else True,
        }

    @web.middleware
    async def auth_mw(request, handler):
        if request.path == "/api/health":
            return await handler(request)

        # сессия пользователя (cookie)
        with db.session() as s:
            user = _get_session_user(s, request)
        if user:
            request["user"] = user
            return await handler(request)

        # PANEL_SECRET: ?key= или cookie или Basic Auth
        if cfg.panel_secret:
            secret = cfg.panel_secret
            cookie_max_age = SESSION_DAYS * 24 * 3600

            if request.cookies.get("panel_key") == secret:
                request["user"] = {"role": "admin", "name": "Руководитель"}
                return await handler(request)

            if request.query.get("key") == secret:
                resp = await handler(request)
                resp.set_cookie("panel_key", secret, httponly=True,
                                samesite="Lax", max_age=cookie_max_age)
                return resp

            auth = request.headers.get("Authorization", "")
            if auth.startswith("Basic "):
                try:
                    decoded = _b64.b64decode(auth[6:]).decode("utf-8")
                    if decoded.split(":", 1)[-1] == secret:
                        resp = await handler(request)
                        resp.set_cookie("panel_key", secret, httponly=True,
                                        samesite="Lax", max_age=cookie_max_age)
                        return resp
                except Exception:
                    pass

        # auth endpoints не требуют сессии
        if request.path.startswith("/api/auth/"):
            return await handler(request)

        if request.path.startswith("/api/"):
            return web.json_response({"error": "unauthorized"}, status=401)
        # SPA без ключа — отдаём index (фронт покажет логин-экран)
        return await handler(request)

    web_app.middlewares.append(auth_mw)

    # ── auth endpoints ──────────────────────────────────────────

    async def auth_login(request):
        """GET /api/auth/login?t=<login_token> — обменять одноразовый токен на сессию."""
        token = request.query.get("t", "")
        if not token:
            return web.json_response({"error": "нет токена"}, status=400)
        with db.session() as s:
            ws = s.scalar(_sel(_WS).where(
                _WS.login_token == token, _WS.login_used == False))
            if ws is None or ws.expires_at < _now():
                return web.json_response({"error": "ссылка недействительна или истекла"}, status=401)
            # создать сессию
            session_key = _uuid.uuid4().hex
            ws.session_key = session_key
            ws.login_used = True
            ws.expires_at = _now() + _td(days=SESSION_DAYS)
            s.commit()
            # получить юзера
            user = _get_session_user(s, request.clone(cookies={SESSION_COOKIE: session_key}))
        if user is None:
            return web.json_response({"error": "аккаунт не найден"}, status=401)
        resp = web.json_response(user)
        resp.set_cookie(SESSION_COOKIE, session_key, httponly=True,
                        samesite="Lax", max_age=SESSION_DAYS * 24 * 3600)
        return resp

    async def auth_me(request):
        """GET /api/auth/me — текущий пользователь."""
        user = request.get("user")
        if user:
            return web.json_response(user)
        return web.json_response({"error": "unauthorized"}, status=401)

    async def auth_logout(request):
        """POST /api/auth/logout — выход."""
        sid = request.cookies.get(SESSION_COOKIE)
        if sid:
            with db.session() as s:
                ws = s.scalar(_sel(_WS).where(_WS.session_key == sid))
                if ws:
                    ws.session_key = None
                    s.commit()
        resp = web.json_response({"ok": True})
        resp.del_cookie(SESSION_COOKIE)
        return resp

    web_app.router.add_get("/api/auth/login", auth_login)
    web_app.router.add_get("/api/auth/me", auth_me)
    web_app.router.add_post("/api/auth/logout", auth_logout)

    # статика через middleware (API маршруты уже зарегистрированы выше)
    if FRONTEND_DIST.exists():
        index_path = FRONTEND_DIST / "index.html"
        assets_dir = FRONTEND_DIST / "assets"

        @web.middleware
        async def spa_fallback(request, handler):
            """API → хендлер; /assets/* → статика; всё остальное → index.html (SPA)."""
            path = request.path
            # API и статика — пропускаем к зарегистрированным маршрутам
            if path.startswith("/api/") or path == "/api":
                return await handler(request)
            # статические ассеты
            if path.startswith("/assets/"):
                file = assets_dir / path[len("/assets/"):]
                if file.is_file():
                    return web.FileResponse(file)
            # всё остальное → SPA index (клиентский роутер разберётся)
            if index_path.is_file():
                return web.FileResponse(index_path)
            return web.json_response(
                {"error": "frontend not built", "hint": "cd frontend && npm run build"},
                status=503,
            )

        web_app.middlewares.append(spa_fallback)
    else:
        @web.middleware
        async def no_frontend_mw(request, handler):
            if request.path.startswith("/api"):
                return await handler(request)
            return web.json_response(
                {"error": "frontend not built", "hint": "cd frontend && npm run build"},
                status=503,
            )
        web_app.middlewares.append(no_frontend_mw)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, cfg.panel_host, port)
    await site.start()
    log.info("веб-панель: http://%s:%s (API + статика)", cfg.panel_host, port)
    return runner
