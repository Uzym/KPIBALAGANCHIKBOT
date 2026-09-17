"""Тесты гигиены хранения (retention)."""
import datetime as dt

from bll import maintenance as m_bll
from config import Config
from dal import repositories as repo
from dal.database import Database, now_utc
from dal.models import Appeal, AppealMessage, OutboxJob

from sqlalchemy import select


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def _old(days: int):
    return now_utc() - dt.timedelta(days=days)


def test_cleanup_old_records(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1)
        ev = repo.create_event(
            s, title="Т", starts_at=_old(-10), ends_at=_old(-9), status="active",
            created_by=admin.id,
        )
        # старый done-джоб — удалится
        s.add(OutboxJob(op="send", platform="vk", chat_id="1",
                        view_model="{}", idempotency_key="old1", status="done",
                        created_at=_old(40)))
        # свежий done-джоб — останется
        s.add(OutboxJob(op="send", platform="vk", chat_id="1",
                        view_model="{}", idempotency_key="new1", status="done"))
        # старый удалённый пост без заданий — удалится
        p_old = repo.create_post(s, "event", ev.id, "dm_card", "vk", "100",
                                 account_id=admin.id)
        p_old.status = "deleted"
        p_old.created_at = _old(10)
        # старый удалённый пост, на который ссылается задание — останется
        acc2 = repo.ensure_account(s, "vk", 2)
        p_keep = repo.create_post(s, "event", ev.id, "dm_card", "vk", "101",
                                  account_id=acc2.id)
        p_keep.status = "deleted"
        p_keep.created_at = _old(10)
        s.add(OutboxJob(op="delete", platform="vk", chat_id="101", post_id=p_keep.id,
                        view_model="{}", idempotency_key="del1", status="done",
                        created_at=_old(10)))
        # старое обращение — удалится вместе с пересылками
        a = Appeal(platform="vk", member_id=100, member_name="Аня", created_at=_old(120))
        s.add(a)
        s.flush()
        s.add(AppealMessage(appeal_id=a.id, admin_id=1, message_id=555,
                            created_at=_old(120)))
        s.commit()

    with db.session() as s:
        lines = m_bll.cleanup_old_records(s, cfg)
        s.commit()
    assert any("outbox" in l for l in lines)

    with db.session() as s:
        keys = {j.idempotency_key for j in s.scalars(select(OutboxJob)).all()}
        assert "old1" not in keys and "new1" in keys
        # p_old удалён, p_keep жив (на него ссылается задание)
        from dal.models import Post
        ids = {p.id for p in s.scalars(select(Post)).all()}
        assert p_old.id not in ids and p_keep.id in ids
        from dal.models import Appeal as A, AppealMessage as AM
        assert s.scalars(select(A)).all() == []
        assert s.scalars(select(AM)).all() == []
