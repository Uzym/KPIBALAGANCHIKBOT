"""Тесты схемы v2: contents (сквозной id), poll_votes (тумблеры), posts (дедуп)."""
import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from dal import repositories as repo
from dal.database import Database


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def _event_kw(admin_id):
    return dict(
        title="Тренировка",
        starts_at=dt.datetime(2026, 9, 15, 19, 0),
        ends_at=dt.datetime(2026, 9, 15, 21, 0),
        status="active",
        created_by=admin_id,
    )


def test_contents_shared_id_space(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        ev = repo.create_event(s, **_event_kw(admin.id))
        p = repo.create_poll(
            s, title="Куда идём", options=[{"idx": 0, "text": "Парк"}],
            multichoice=False, closes_at=None, created_by=admin.id,
        )
        assert ev.id != p.id
        assert repo.get_content(s, ev.id).kind == "event"
        assert repo.get_content(s, p.id).kind == "poll"


def test_poll_vote_toggle(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        p = repo.create_poll(
            s, title="Куда идём",
            options=[{"idx": 0, "text": "Парк"}, {"idx": 1, "text": "Кино"}],
            multichoice=True, closes_at=None, created_by=admin.id,
        )
        acc = repo.ensure_account(s, "vk", 2)
        v, changed, active = repo.toggle_poll_vote(s, p.id, acc.id, 0)
        assert changed and active and v.changes_count == 0
        v2, changed2, active2 = repo.toggle_poll_vote(s, p.id, acc.id, 0)
        assert changed2 and not active2
        rows = repo.poll_votes_with_accounts(s, p.id)
        assert len(rows) == 1 and not rows[0][0].active
        # повторное включение — тумблер обратно
        _, _, active3 = repo.toggle_poll_vote(s, p.id, acc.id, 0)
        assert active3


def test_posts_dm_dedup(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        ev = repo.create_event(s, **_event_kw(admin.id))
        repo.create_post(s, "event", ev.id, "dm_card", "vk", "100", account_id=admin.id)
        s.commit()
    with db.session() as s:
        with pytest.raises(IntegrityError):
            repo.create_post(s, "event", ev.id, "dm_card", "vk", "100", account_id=admin.id)
            s.flush()
    # та же пара (content, kind), но другой подписчик — можно
    with db.session() as s:
        acc2 = repo.ensure_account(s, "vk", 3)
        p = repo.create_post(s, "event", ev.id, "dm_card", "vk", "100", account_id=acc2.id)
        s.flush()
        assert p.id
