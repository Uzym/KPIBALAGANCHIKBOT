"""Тесты сводок: списки, зачёркивания, дедуп после линковки, рендер."""
import datetime as dt
from zoneinfo import ZoneInfo

from api.renderers import render_tg, render_vk, vk_strike
from bll.contracts import ButtonVM, OutMessageVM
from bll.summary import VoteRow, build_event_vm

TZ = ZoneInfo("Europe/Moscow")

VOTE_BUTTONS = [[ButtonVM(action="vote", label="✅ Приду", value="yes", event_id=1)]]


def vm_(votes, status="active", cancelled=False):
    return build_event_vm(
        event_id=1, title="Тренировка",
        starts_at=dt.datetime(2026, 9, 15, 19, 0, tzinfo=TZ),
        ends_at=dt.datetime(2026, 9, 15, 21, 0, tzinfo=TZ),
        status=status, cancelled=cancelled, place="Зал №2", note="спарринг",
        votes=votes, tz=TZ,
    )


def vote(name, platform="vk", answer="yes", prev=None, person=None, count=1,
         updated=None):
    return VoteRow(
        answer=answer, prev_answer=prev, changes_count=1 if prev else 0,
        updated_at=updated or dt.datetime(2026, 9, 13, 19, 40, tzinfo=TZ),
        display_name=name, platform=platform, person_id=person,
        person_accounts_count=count,
    )


def test_lists_and_counts():
    vm = vm_([vote("Аня"), vote("Боба", "tg"), vote("Вика", answer="no")])
    assert len(vm.lists[0].entries) == 2  # yes
    assert len(vm.lists[2].entries) == 1  # no
    assert vm.lists[0].entries[0].tag == "VK"  # нелинкованный — с меткой


def test_changed_vote_shows_only_current_list():
    # смена выбора: человек только в новом списке, без зачёркивания в старом
    vm = vm_([vote("Боба", answer="no", prev="yes")])
    yes_list = vm.lists[0]
    assert yes_list.entries == []
    no_list = vm.lists[2]
    assert len(no_list.entries) == 1 and no_list.entries[0].struck_at is None
    assert no_list.entries[0].name == "Боба"


def test_linked_person_dedup():
    # один человек: VK «Аня К» и TG «anny» слинкованы (person=7, count=2)
    vm = vm_([
        vote("Аня К.", "vk", "yes", person=7, count=2, updated=dt.datetime(2026, 9, 13, 10, 0, tzinfo=TZ)),
        vote("anny", "tg", "no", person=7, count=2, updated=dt.datetime(2026, 9, 13, 11, 0, tzinfo=TZ)),
    ])
    # актуальный — последний по времени (no), метки платформы нет
    assert len(vm.lists[2].entries) == 1
    assert vm.lists[2].entries[0].tag is None
    assert vm.lists[0].entries == []


def test_vk_render_no_strike():
    text, kb = render_vk(OutMessageVM(kind="dm_card", event=vm_([vote("Боба", answer="no", prev="yes")]), buttons=VOTE_BUTTONS))
    assert "📋 Тренировка" in text
    assert "Зал №2" in text
    assert "Боба [VK]" in text            # человек виден в актуальном списке
    assert vk_strike("Боба") not in text  # зачёркивания отключены
    assert "изм." not in text
    assert kb is not None and kb["inline"]


def test_tg_render_strike_and_buttons():
    text, kb = render_tg(OutMessageVM(kind="topic_record", event=vm_([vote("Аня")]), buttons=VOTE_BUTTONS))
    assert "<b>📋 Тренировка</b>" in text
    assert "<i>[VK]</i>" in text
    assert "inline_keyboard" in kb
    cb = kb["inline_keyboard"][0][0]["callback_data"]
    assert cb.startswith("vote:1:")


def test_closed_status_line():
    vm = vm_([vote("Аня")], status="closed")
    assert vm.status_line == "🔒 Запись закрыта"
    text, kb = render_vk(OutMessageVM(kind="feed_record", event=vm))
    assert "🔒" in text
    assert kb is None  # кнопки сняты
