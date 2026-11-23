"""Тесты мемоизации (app_meta) и восстановления списка админов."""
from app import _load_stored_admins
from dal import repositories as repo
from dal.database import Database


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def test_meta_get_set(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        assert repo.get_meta(s, "admins_vk") is None
        repo.set_meta(s, "admins_vk", "111,222")
        s.commit()
    with db.session() as s:
        assert repo.get_meta(s, "admins_vk") == "111,222"
        repo.set_meta(s, "admins_vk", "333")
        s.commit()
    with db.session() as s:
        assert repo.get_meta(s, "admins_vk") == "333"
        s.commit()


def test_load_stored_admins(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        assert _load_stored_admins(s) == set()
        repo.set_meta(s, "admins_vk", "111,222,м,0")
        s.commit()
    with db.session() as s:
        # мусорные токены игнорируются
        assert _load_stored_admins(s) == {111, 222, 0}
        s.commit()
