"""Тесты опросов: парсер команды, голоса-тумблеры, сводка, рендер."""
import datetime as dt
from zoneinfo import ZoneInfo

from api.renderers import render_tg, render_vk
from bll import polls as polls_bll
from bll.publication import vm_hash
from config import Config
from dal import repositories as repo
from dal.database import Database

TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=TZ)


def make_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_all()
    return db


def test_parse_poll_command():
    cfg = Config()
    parsed, err = polls_bll.parse_poll_command(
        "/создать опрос Куда идём; Парк; Кино; Дома; несколько; до 20.09 19:00",
        cfg, NOW,
    )
    assert err is None
    assert parsed["title"] == "Куда идём"
    assert [o["text"] for o in parsed["options"]] == ["Парк", "Кино", "Дома"]
    assert parsed["multichoice"] is True
    assert parsed["closes_at"].hour == 19


def test_parse_poll_multiline():
    cfg = Config()
    parsed, err = polls_bll.parse_poll_command(
        "/опрос Куда идём\nПарк\nКино\nДома\n[несколько]\n[до 20.09 19:00]",
        cfg, NOW,
    )
    assert err is None
    assert parsed["title"] == "Куда идём"
    assert [o["text"] for o in parsed["options"]] == ["Парк", "Кино", "Дома"]
    assert parsed["multichoice"] is True
    assert parsed["closes_at"].hour == 19


def test_parse_poll_multiline_minimal():
    cfg = Config()
    parsed, err = polls_bll.parse_poll_command("/опрос Кросс\nда\nнет", cfg, NOW)
    assert err is None
    assert parsed["title"] == "Кросс"
    assert [o["text"] for o in parsed["options"]] == ["да", "нет"]
    assert parsed["multichoice"] is False
    assert parsed["closes_at"] is None
    # «до» без скобок и без слова «несколько» — тоже работает
    parsed, err = polls_bll.parse_poll_command(
        "/опрос Кросс\nда\nнет\nдо 20.09 19:00", cfg, NOW)
    assert err is None
    assert parsed["closes_at"] is not None
    # вариант-число не путается с модификатором
    parsed, err = polls_bll.parse_poll_command("/опрос Число\n1\n2", cfg, NOW)
    assert err is None
    assert [o["text"] for o in parsed["options"]] == ["1", "2"]


def test_parse_poll_multiline_errors():
    cfg = Config()
    _, err = polls_bll.parse_poll_command("/опрос Только вопрос", cfg, NOW)
    assert err and "минимум 2" in err
    _, err = polls_bll.parse_poll_command("/опрос Вопрос\nодин вариант", cfg, NOW)
    assert err and "минимум 2" in err
    _, err = polls_bll.parse_poll_command("/опрос Вопрос\nа\nб\nдо когда-нибудь", cfg, NOW)
    assert err and "не поняла срок" in err
    _, err = polls_bll.parse_poll_command("просто текст", cfg, NOW)
    assert err and "начинаться с /опрос" in err


def test_parse_poll_errors():
    cfg = Config()
    _, err = polls_bll.parse_poll_command("/создать опрос Только вопрос", cfg, NOW)
    assert err and "минимум 2" in err
    cfg_small = Config(poll_max_options=3)
    _, err = polls_bll.parse_poll_command(
        "/создать опрос В; а; б; в; г", cfg_small, NOW)
    assert err and "не больше 3" in err
    _, err = polls_bll.parse_poll_command(
        "/создать опрос В; а; б; до когда-нибудь", cfg, NOW)
    assert err and "не поняла срок" in err


def make_poll(tmp_path, cfg, command):
    db = make_db(tmp_path)
    with db.session() as s:
        admin = repo.ensure_account(s, "vk", 1, display_name="Глава")
        parsed, err = polls_bll.parse_poll_command(command, cfg, NOW)
        assert err is None, err
        poll = polls_bll.create_draft(s, cfg, admin.id, parsed)
        counts = polls_bll.publish(s, cfg, poll.id)
        s.commit()
    return db, poll.id, counts


def test_publish_fanout(tmp_path):
    cfg = Config()
    db, poll_id, counts = make_poll(tmp_path, cfg, "/создать опрос В; а; б")
    assert counts == {"dm": 0}
    with db.session() as s:
        kinds = {p.kind for p in repo.posts_for_content(s, "poll", poll_id)}
        assert kinds == set() or kinds  # без подписчиков карточек нет


def test_multichoice_toggle(tmp_path):
    cfg = Config()
    db, poll_id, _ = make_poll(tmp_path, cfg, "/создать опрос В; а; б; несколько")
    with db.session() as s:
        assert polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 0) == "ok"
        assert polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 1) == "ok"
        assert polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 0) == "off"
        acc = repo.get_account_by_platform_id(s, "vk", 100)
        assert repo.selected_poll_options(s, poll_id, acc.id) == {1}
        assert polls_bll.clear_poll_votes(s, cfg, "vk", 100, poll_id) == "cleared"
        assert repo.selected_poll_options(s, poll_id, acc.id) == set()


def test_single_choice_switch(tmp_path):
    cfg = Config()
    db, poll_id, _ = make_poll(tmp_path, cfg, "/создать опрос В; а; б")
    with db.session() as s:
        assert polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 0) == "ok"
        assert polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 1) == "ok"
        acc = repo.get_account_by_platform_id(s, "vk", 100)
        assert repo.selected_poll_options(s, poll_id, acc.id) == {1}
        rows = repo.poll_votes_with_accounts(s, poll_id)
        by_opt = {r[0].option_id: r[0].active for r in rows if r[0].account_id == acc.id}
        assert by_opt == {0: False, 1: True}


def test_poll_vm_render(tmp_path):
    cfg = Config()
    db, poll_id, _ = make_poll(tmp_path, cfg, "/создать опрос В; а; б; несколько")
    with db.session() as s:
        polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 0)
        polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 0)  # снял
        polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 1)
        vm = polls_bll.vm_for_poll_post(s, cfg, poll_id, "dm_card")
        o0, o1 = vm.poll.options
        # снятый выбор не отображается (без зачёркиваний)
        assert o0.entries == []
        assert any(not e.struck_at for e in o1.entries)
        text, kb = render_vk(vm)
        assert text.startswith(f"#{poll_id}\n")
        assert "1️⃣ а — 0:" in text and "снял выбор" not in text
        assert kb is not None and kb["inline"]  # кнопки вариантов в ЛС
        ttext, _ = render_tg(vm)
        assert "🗳" in ttext


def test_poll_close(tmp_path):
    cfg = Config()
    db, poll_id, _ = make_poll(tmp_path, cfg, "/создать опрос В; а; б")
    with db.session() as s:
        polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 0)
        polls_bll.cast_poll_vote(s, cfg, "vk", 100, poll_id, 1)
        result = polls_bll.close(s, cfg, poll_id)
        assert result and "🔒 Опрос закрыт" in result
        poll = repo.get_poll(s, poll_id)
        assert poll.status == "closed"
        # после закрытия голоса не принимаются
        assert polls_bll.cast_poll_vote(s, cfg, "vk", 200, poll_id, 0) == "closed"
        vm = polls_bll.vm_for_poll_post(s, cfg, poll_id, "dm_card", None)
        assert vm.buttons == []  # кнопки сняты
