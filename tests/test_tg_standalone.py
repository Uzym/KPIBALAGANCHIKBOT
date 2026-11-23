"""Тесты TG-отдельного: заявка → одобрение → бан (уровень репозитория)."""
from dal import repositories as repo
from dal.database import Database


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def test_tg_standalone_lifecycle(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        # 1. чистый TG: заявка pending
        acc = repo.ensure_account(s, "tg", 999, display_name="Вася", username="vasya")
        sub = repo.upsert_subscription(s, acc.id, "pending")
        assert sub.status == "pending"
        s.commit()

        # 2. одобрение: персона + active
        person = repo.get_or_create_person(s, display_name="Вася")
        acc.person_id = person.id
        repo.upsert_subscription(s, acc.id, "active")
        s.commit()
        assert repo.get_subscription(s, acc.id).status == "active"
        assert repo.tg_account_for_person(s, person.id).platform_user_id == 999
        assert repo.tg_linked_accounts(s)[0].id == acc.id  # получает карточки
        s.commit()

        # 3. бан: blocked + banned
        sub = repo.get_subscription(s, acc.id)
        sub.banned = True
        sub.status = "blocked"
        s.commit()
        sub = repo.get_subscription(s, acc.id)
        assert sub.banned and sub.status == "blocked"
        s.commit()

        # 4. разбан: флаг снят (статус остаётся — человек подаст /start)
        sub = repo.get_subscription(s, acc.id)
        sub.banned = False
        s.commit()
        assert repo.get_subscription(s, acc.id).banned is False


def test_tg_rejected_can_reapply(tmp_path):
    db = make_db(tmp_path)
    with db.session() as s:
        acc = repo.ensure_account(s, "tg", 777, display_name="Петя")
        repo.upsert_subscription(s, acc.id, "pending")
        s.commit()
        # отказ
        repo.set_subscription_status(s, acc.id, "blocked")
        s.commit()
        assert repo.get_subscription(s, acc.id).status == "blocked"
        # новая заявка по /start
        repo.set_subscription_status(s, acc.id, "pending")
        s.commit()
        assert repo.get_subscription(s, acc.id).status == "pending"
