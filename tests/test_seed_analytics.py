"""Тест: посев синтетики + аналитика + сверка на посеянных данных."""
import pathlib

from bll import polls as polls_bll
from bll.publication import event_vm, refresh_content
from config import Config
from dal import repositories as repo
from dal.database import Database

from seed_demo import analytics, seed


def test_seed_and_analytics(tmp_path):
    db_path = str(tmp_path / "demo.db")
    db = Database(db_path)
    db.create_all()
    cfg = Config(db_path=db_path, vk_group_id=123, admin_vk_ids=[1])

    summary = seed(db, cfg)
    assert summary == {"members": 12, "events": 5, "polls": 3, "appeals": 2}

    with db.session() as s:
        stats = repo.subscription_stats(s)
        assert stats["active"] == 10
        assert stats["paused"] == 1
        assert stats["stopped"] == 1

        # смены выбора: зачёркивания убраны, человек виден только в актуальном списке
        vm = event_vm(s, cfg, repo.get_event(s, 1))
        struck = [e for lst in vm.lists for e in lst.entries if e.struck_at]
        assert struck == [], "зачёркивания не должны отображаться"

        # закрытый опрос: голоса собраны ДО закрытия
        pvm = polls_bll.poll_vm(s, cfg, repo.get_poll(s, 7))
        total = sum(len([e for e in o.entries if not e.struck_at]) for o in pvm.options)
        assert total == 4

        # завершённое событие: посещаемость отмечена
        assert len(repo.attendance_for_event(s, 4)) == 3

        # обращения персистятся
        assert repo.appeal_message_by_cmid(s, 900001) is not None
        assert repo.appeal_message_by_cmid(s, 900002) is not None

        # сверка карточек не падает на посеянных данных
        for ev in repo.open_events(s):
            refresh_content(s, cfg, "event", ev.id)
        for p in repo.open_polls(s):
            refresh_content(s, cfg, "poll", p.id)
        s.commit()

    report = analytics(db, cfg)
    assert "active: 10" in report
    xlsx = pathlib.Path(tmp_path) / "demo_export.xlsx"
    assert xlsx.exists() and xlsx.stat().st_size > 500
