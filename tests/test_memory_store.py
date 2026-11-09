"""The layered memory's storage (spec Part 12, section 8, ticket 80): long-term facts in sections, a
journal of dated events (append only), and a flag on each saved message marking turns that used web
content. Both stores must behave identically."""
import sqlite3
from contextlib import closing

import pytest

from companion.history import InMemoryHistory, SqliteHistory

SECTIONS = ("使用者", "共同經歷", "角色自己的事", "待跟進", "更早的摘要")


@pytest.fixture(params=["memory", "sqlite"])
def kind(request):
    return request.param


@pytest.fixture
def open_store(kind, tmp_path):
    """A factory: calling it again models a restart (SQLite reopens the same file)."""
    shared = InMemoryHistory()
    db = tmp_path / "history.db"

    def factory():
        return shared if kind == "memory" else SqliteHistory(db)

    return factory


def test_a_fresh_store_has_no_facts_no_events_and_no_polluted_turns(open_store):
    store = open_store()
    assert store.load_facts() == {}
    assert store.load_events(["2026-10-24"]) == []
    assert store.load_polluted() == []


def test_facts_are_saved_as_whole_sections_and_a_new_set_replaces_the_old(open_store):
    open_store().save_facts({"使用者": "- 喜歡黑咖啡", "共同經歷": "- 一起看過海"})
    assert open_store().load_facts() == {"使用者": "- 喜歡黑咖啡", "共同經歷": "- 一起看過海"}
    open_store().save_facts({"待跟進": "- 2026-10-28 面試"})
    assert open_store().load_facts() == {"待跟進": "- 2026-10-28 面試"}


def test_events_come_back_by_date_in_the_order_they_were_written(open_store):
    store = open_store()
    store.append_events([{"date": "2026-10-24", "time": "09:00", "kind": "事件", "text": "早餐"},
                         {"date": "2026-10-23", "time": None, "kind": "事件", "text": "昨天的事"}])
    store.append_events([{"date": "2026-10-24", "time": "21:30", "kind": "狀態", "text": "地點→咖啡廳"}])
    today = open_store().load_events(["2026-10-24"])
    assert [(e["time"], e["text"]) for e in today] == [("09:00", "早餐"), ("21:30", "地點→咖啡廳")]
    assert [e["text"] for e in open_store().load_events(["2026-10-23"])] == ["昨天的事"]
    assert {e["text"] for e in open_store().load_events(["2026-10-23", "2026-10-24"])} == {"昨天的事", "早餐", "地點→咖啡廳"}
    assert open_store().load_events(["2026-10-22"]) == []


def test_each_saved_turn_says_whether_it_used_web_content(open_store):
    store = open_store()
    store.append_turn("你好", "嗨")
    store.append_turn("查一下", "查到了", polluted=True)
    store.append_turn("謝謝", "不客氣")
    assert open_store().load_polluted() == [False, False, True, True, False, False]


def test_a_new_store_has_made_no_fold_progress(open_store):
    assert open_store().load_fold_progress() == 0


def test_the_fold_progress_is_what_the_last_fold_saved(open_store):
    store = open_store()
    store.apply_fold([], None, 4)
    store.apply_fold([], None, 6)
    assert store.load_fold_progress() == 6


def test_a_fold_that_cannot_be_saved_in_full_leaves_nothing_behind(tmp_path):
    """Events, facts and progress go in as one transaction: no events without the progress that goes with
    them (that would write the same events again next time)."""
    store = SqliteHistory(tmp_path / "history.db")
    store.save_facts({"使用者": "- 舊事實"})
    events = [{"date": "2026-10-01", "time": None, "kind": "事件", "text": "聊了貓"}]
    with pytest.raises(sqlite3.Error):
        store.apply_fold(events, {"使用者": "- 新事實"}, None)    # the last step, saving the progress, fails
    assert store.load_events(["2026-10-01"]) == []
    assert store.load_facts() == {"使用者": "- 舊事實"}
    assert store.load_fold_progress() == 0


def test_applying_a_fold_replaces_the_facts_moves_the_progress_and_adds_the_events(open_store):
    store = open_store()
    store.save_facts({"使用者": "- 舊事實", "待跟進": "- 舊待辦"})
    store.apply_fold([{"date": "2026-10-01", "time": None, "kind": "事件", "text": "聊了貓"}], {"使用者": "- 新事實"}, 4)
    again = open_store()
    assert again.load_facts() == {"使用者": "- 新事實"}
    assert again.load_fold_progress() == 4
    assert [e["text"] for e in again.load_events(["2026-10-01"])] == ["聊了貓"]
    again.apply_fold([], None, 6)                         # None = keep the facts, only move the progress
    assert open_store().load_facts() == {"使用者": "- 新事實"} and open_store().load_fold_progress() == 6


# ---- the database file is made new: one clean layout, nothing kept for older files ----

def test_a_new_database_has_exactly_these_columns(tmp_path):
    db = tmp_path / "new.db"
    SqliteHistory(db)
    with closing(sqlite3.connect(db)) as conn:
        columns = {table: [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
                   for table in ("messages", "relationship", "memory", "memory_facts", "memory_events")}
    assert columns == {
        "messages": ["id", "role", "content", "created_at", "polluted"],
        "relationship": ["id", "affection", "last_interaction"],
        "memory": ["id", "summarized_messages"],
        "memory_facts": ["section", "text"],
        "memory_events": ["id", "date", "time", "kind", "text"],
    }
