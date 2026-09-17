"""Наполнение БД синтетическими данными + аналитика (демо/тест).

Запуск:
  .venv\\Scripts\\python seed_demo.py [--db data/demo.db]

Создаёт демо-БД: участники (VK + слинкованные TG), подписки (включая академ и
стопнутых), события всех статусов с голосами и сменой выбора, опросы
(активный/закрытый/отменённый), объявления, обращения, посещаемость. Затем
печатает аналитику и сохраняет экспорт xlsx рядом с БД.

Продакшн-БД (data/kpibalaganchikbot.db) не трогается.
"""
import argparse
import datetime as dt
import pathlib
import sys
from zoneinfo import ZoneInfo

from bll import announcements as ann_bll
from bll import events as events_bll
from bll import linking as linking_bll
from bll import polls as polls_bll
from bll import rsvp as rsvp_bll
from bll import export as export_bll
from bll.timeparse import parse_event_command
from config import Config
from dal import repositories as repo
from dal.database import Database

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ)

NAMES = ["Аня К.", "Вика Л.", "Гоша М.", "Дима С.", "Ева Т.", "Женя П.",
         "Боба Н.", "Ира В.", "Коля Д.", "Лена Р.", "Макс Ф.", "Оля Г."]
TG_LOGINS = ["anny", "vika", "gosha_m"]


def seed(db: Database, cfg: Config) -> dict:
    """Наполнить БД синтетикой. Возвращает сводные ключи для аналитики."""
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава клуба")
        members = []
        for i, name in enumerate(NAMES):
            acc = repo.ensure_account(s, "vk", 1000 + i, display_name=name)
            repo.upsert_subscription(s, acc.id, "active")
            members.append(acc)
        repo.set_subscription_status(s, members[-1].id, "paused")   # академ
        repo.set_subscription_status(s, members[-2].id, "stopped")  # сам отписался
        for i, login in enumerate(TG_LOGINS):
            tg = repo.ensure_account(s, "tg", 2000 + i, display_name=login, username=login)
            vk = members[i]
            vk.tg_nick = login
            linking_bll.try_link(s, cfg, vk)
        s.commit()

    def make_event(command: str) -> int:
        with db.session() as s:
            parsed = parse_event_command(command, cfg.tz, NOW)
            ev = events_bll.create_draft(s, cfg, admin.id, parsed)
            events_bll.publish(s, cfg, ev.id)
            s.commit()
            return ev.id

    ev_active = make_event("/событие Тренировка - 15.09 19:00 - 15.09 21:00 - спарринг, перчатки")
    ev_active2 = make_event("/событие Плавание - 18.09 08:00 - 18.09 10:00 - бассейн")
    ev_closed = make_event("/событие Йога - 12.09 10:00 - 12.09 11:00 - коврики")
    ev_finished = make_event("/событие Сборы - 08.09 10:00 - 08.09 18:00 - выезд")
    ev_cancelled = make_event("/событие Кино - 20.09 20:00 - 20.09 23:00 - кинотеатр")

    with db.session() as s:
        # голоса (часть — со сменой выбора)
        plan = {
            ev_active: [(1000, "yes"), (1001, "yes"), (1002, "maybe"), (1003, "no"),
                        (1004, "yes"), (1005, "no"), (1006, "maybe")],
            ev_active2: [(1000, "yes"), (1001, "maybe"), (1002, "yes")],
            ev_closed: [(1000, "yes"), (1001, "yes"), (1002, "no"), (1003, "maybe")],
            ev_finished: [(1000, "yes"), (1001, "yes"), (1002, "yes"), (1003, "no"),
                          (1004, "no"), (1005, "maybe")],
            ev_cancelled: [(1000, "yes"), (1001, "maybe")],
        }
        for eid, votes in plan.items():
            for uid, ans in votes:
                rsvp_bll.cast_vote(s, cfg, "vk", uid, eid, ans)
        # смены выбора (зачёркивания)
        rsvp_bll.cast_vote(s, cfg, "vk", 1003, ev_active, "yes")   # no→yes
        rsvp_bll.cast_vote(s, cfg, "vk", 1006, ev_active, "no")    # maybe→no
        # закрытие/завершение/отмена
        events_bll.close(s, cfg, ev_closed)
        events_bll.close(s, cfg, ev_finished)
        events_bll.finish(s, cfg, ev_finished, admins={1})
        events_bll.cancel(s, cfg, ev_cancelled)
        s.commit()

    with db.session() as s:
        # опросы
        p1, _ = polls_bll.parse_poll_command(
            "/создать опрос Куда идём в субботу; Парк; Кино; Дома; несколько; до 19.09 19:00",
            cfg, NOW)
        poll1 = polls_bll.create_draft(s, cfg, admin.id, p1)
        polls_bll.publish(s, cfg, poll1.id)
        p2, _ = polls_bll.parse_poll_command("/создать опрос Форма на тренировку; Кимоно; Шорты", cfg, NOW)
        poll2 = polls_bll.create_draft(s, cfg, admin.id, p2)
        polls_bll.publish(s, cfg, poll2.id)
        p3, _ = polls_bll.parse_poll_command("/создать опрос Время старта; 10:00; 11:00", cfg, NOW)
        poll3 = polls_bll.create_draft(s, cfg, admin.id, p3)
        polls_bll.publish(s, cfg, poll3.id)
        polls_bll.cancel(s, cfg, poll3.id, admins={1})
        # голоса ПО закрытого опроса
        for uid, opt in [(1000, 0), (1001, 0), (1002, 1), (1005, 0)]:
            polls_bll.cast_poll_vote(s, cfg, "vk", uid, poll2.id, opt)
        polls_bll.close(s, cfg, poll2.id, admins={1})
        for uid, opts in [(1000, {0}), (1001, {0, 1}), (1002, {1}), (1003, {2}), (1004, {0, 2})]:
            for opt in opts:
                polls_bll.cast_poll_vote(s, cfg, "vk", uid, poll1.id, opt)
        # тумблер: снял выбор
        polls_bll.cast_poll_vote(s, cfg, "vk", 1004, poll1.id, 2)
        s.commit()

    with db.session() as s:
        # объявления
        ev = repo.get_event(s, ev_active)
        ann_bll.publish_for_content(s, cfg, "event", ev_active,
                                    "Берите перчатки и воду", admin_account_id=admin.id)
        ann_bll.publish_global(s, cfg, "В субботу зал закрыт", admin_account_id=admin.id)
        # обращения
        a = repo.create_appeal(s, "vk", 1003, "Дима С.")
        repo.create_appeal_message(s, a.id, 1, 900001)
        a2 = repo.create_appeal(s, "tg", 2002, "gosha_m")
        repo.create_appeal_message(s, a2.id, 1, 900002)
        # посещаемость (только реально пришедшие из «приду»)
        for uid in (1000, 1001, 1002):
            acc = repo.get_account_by_platform_id(s, "vk", uid)
            if acc.person_id:
                events_bll.toggle_attendance(s, ev_finished, f"p:{acc.person_id}")
            else:
                events_bll.toggle_attendance(s, ev_finished, f"a:{acc.id}")
        s.commit()

    return {
        "members": len(NAMES),
        "events": 5,
        "polls": 3,
        "appeals": 2,
    }


def analytics(db: Database, cfg: Config) -> str:
    """Сводная аналитика по посеянной БД (текст) + путь к xlsx."""
    lines: list[str] = []
    with db.session() as s:
        stats = repo.subscription_stats(s)
        lines.append("Подписки: " + (", ".join(f"{k}: {v}" for k, v in sorted(stats.items())) or "—"))
        lines.append("")
        lines.append("— События участнику —")
        lines.append(events_bll.listing_text(s, cfg) or "нет")
        lines.append("")
        lines.append("— Опросы участнику —")
        lines.append(polls_bll.listing_text(s, cfg) or "нет")
        lines.append("")
        lines.append("— События админу —")
        vm = events_bll.admin_listing_vm(s, cfg)
        lines.append(vm.text)
        lines.append("")
        lines.append("— Опросы админу —")
        lines.append(polls_bll.admin_listing_vm(s, cfg).text)
        lines.append("")
        for ev in repo.all_events(s):
            if ev.status in ("closed", "finished"):
                att = repo.attendance_for_event(s, ev.id)
                if att:
                    lines.append(f"Посещаемость #{ev.id} «{ev.title}»: отмечено {len(att)}")
        data = export_bll.build_export_xlsx(s, cfg)
        s.commit()
    out = pathlib.Path(cfg.db_path).parent / "demo_export.xlsx"
    out.write_bytes(data)
    lines.append(f"Экспорт: {out} ({len(data)} байт)")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/demo.db")
    args = ap.parse_args()
    cfg = Config(db_path=args.db, admin_vk_ids=[1], vk_group_id=241483738)
    # демо-БД пересоздаём начисто (повторные запуски не должны дублировать контент)
    p = pathlib.Path(cfg.db_path)
    for suffix in ("", "-shm", "-wal"):
        pathlib.Path(str(p) + suffix).unlink(missing_ok=True)
    db = Database(cfg.db_path)
    db.create_all()
    summary = seed(db, cfg)
    print("=== Посеяно:", ", ".join(f"{k}={v}" for k, v in summary.items()), "===")
    print(analytics(db, cfg))


if __name__ == "__main__":
    main()
