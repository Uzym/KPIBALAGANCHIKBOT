"""Тесты входа в админ-панель: заявка, одобрение, токены, rate-limit, отзыв."""
from bll import panel as panel_bll
from config import Config
from dal import repositories as repo
from dal.database import Database


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def test_login_flow(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        sid, token, err = panel_bll.request_login(s, cfg, "1.2.3.4", "UA", "Илья",
                                                  admins={1, 2})
        assert err is None and token
        jobs = repo.fetch_pending_jobs(s, limit=10)
        assert len([j for j in jobs if j.idempotency_key.startswith("panelreq:")]) == 2
        assert panel_bll.poll_status(s, sid) == "pending"
        # до одобрения токен не действует
        assert panel_bll.check_token(s, token) is False
        s.commit()

    # повторная заявка с того же IP — rate-limit
    with db.session() as s:
        sid2, _tok2, err2 = panel_bll.request_login(s, cfg, "1.2.3.4", "UA", "x", admins={1})
        assert sid2 is None and "часто" in (err2 or "")
        s.commit()

    # одобрение
    with db.session() as s:
        assert panel_bll.approve_login(s, sid, approver_id=1) is None
        assert panel_bll.check_token(s, token) is True
        assert panel_bll.check_token(s, "левак") is False
        assert panel_bll.approve_login(s, sid, approver_id=2) == "Уже обработана"
        sess = repo.get_panel_session(s, sid)
        assert sess.status == "approved" and sess.token_hash != token
        s.commit()

    # отзыв
    with db.session() as s:
        assert panel_bll.revoke_login(s, sid) is True
        assert panel_bll.check_token(s, token) is False
        s.commit()


def test_deny_login(tmp_path):
    db = make_db(tmp_path)
    cfg = Config()
    with db.session() as s:
        sid, token, _ = panel_bll.request_login(s, cfg, "9.9.9.9", "UA", "", admins={1})
        assert panel_bll.deny_login(s, sid, 1) is None
        assert panel_bll.poll_status(s, sid) == "denied"
        assert panel_bll.deny_login(s, sid, 2) == "Уже обработана"
        assert panel_bll.check_token(s, token) is False  # отклонённый токен не действует
        s.commit()


def test_log_to_tech(tmp_path):
    db = make_db(tmp_path)
    cfg = Config(tech_admin_vk_peer=2000000007)
    with db.session() as s:
        panel_bll.log_to_tech(s, cfg, "🔑 Панель: вход одобрен (заявка #1)")
        jobs = repo.fetch_pending_jobs(s, limit=10)
        assert any(j.platform == "vk" and str(j.chat_id) == "2000000007" for j in jobs)
        s.commit()
