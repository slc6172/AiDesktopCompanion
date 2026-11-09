"""History stores can say WHEN each message was written (spec Part 11, ticket 46).

These tests sit directly on the storage boundary (like the adapter tests): until the engine reads
the times (tickets 47/48) there is nothing observable one level up."""
import sqlite3
from calendar import timegm
from contextlib import closing

import pytest

from companion.history import InMemoryHistory, SqliteHistory


def utc(year, month, day, hour=0, minute=0, second=0):
    """Epoch seconds of a UTC instant, written out by hand so the tests never lean on the code
    under test to compute their expectations."""
    return float(timegm((year, month, day, hour, minute, second)))


def insert_rows(path, rows):
    """Arrange a database the way an OLDER version of the app would have left it: rows whose
    created_at is whatever SQLite's CURRENT_TIMESTAMP wrote (UTC, "YYYY-MM-DD HH:MM:SS")."""
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executemany("INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)", rows)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "history.db"


def test_times_line_up_one_to_one_with_the_messages_and_are_epoch_seconds(db):
    store = SqliteHistory(db)
    insert_rows(db, [
        ("user", "嗨", "2026-10-02 13:12:00"),            # a Friday evening in Taipei (UTC+8)
        ("assistant", "[happy]嗨!", "2026-10-02 13:12:09"),
        ("user", "早", "2026-10-05 00:30:45"),
    ])
    assert [m["content"] for m in store.load()] == ["嗨", "[happy]嗨!", "早"]
    assert store.load_times() == [
        utc(2026, 10, 2, 13, 12, 0),
        utc(2026, 10, 2, 13, 12, 9),
        utc(2026, 10, 5, 0, 30, 45),
    ]


def test_an_empty_history_has_no_times(db):
    assert SqliteHistory(db).load_times() == []


@pytest.mark.parametrize("junk", [None, "", "yesterday", "2026-13-45 99:99:99", "2026-10-02"])
def test_a_missing_or_unreadable_time_is_unknown_and_never_an_error(db, junk):
    store = SqliteHistory(db)
    insert_rows(db, [("user", "a", "2026-10-02 13:12:00"), ("assistant", "b", junk), ("user", "c", "2026-10-02 13:13:00")])
    times = store.load_times()
    assert len(times) == len(store.load()) == 3
    assert times[0] == utc(2026, 10, 2, 13, 12, 0)
    assert times[1] is None
    assert times[2] == utc(2026, 10, 2, 13, 13, 0)


def raw_created_at(path):
    with closing(sqlite3.connect(path)) as conn:
        return [row[0] for row in conn.execute("SELECT created_at FROM messages ORDER BY id")]


def test_a_turn_saved_with_a_time_stores_that_time_for_both_rows(db):
    store = SqliteHistory(db)
    at = utc(2026, 10, 7, 13, 40, 5)
    store.append_turn("嗨", "[happy]嗨!", at=at)
    assert store.load_times() == [at, at]


def test_the_stored_format_is_the_same_utc_text_older_versions_wrote(db):
    store = SqliteHistory(db)
    store.append_turn("嗨", "[happy]嗨!", at=utc(2026, 10, 7, 13, 40, 5))
    assert raw_created_at(db) == ["2026-10-07 13:40:05", "2026-10-07 13:40:05"]


def test_rows_from_an_older_version_and_rows_with_an_explicit_time_read_side_by_side(db):
    store = SqliteHistory(db)
    insert_rows(db, [("user", "舊", "2026-10-01 08:00:00"), ("assistant", "舊答", "2026-10-01 08:00:02")])
    store.append_turn("新", "新答", at=utc(2026, 10, 7, 13, 40, 5))
    assert store.load_times() == [
        utc(2026, 10, 1, 8, 0, 0), utc(2026, 10, 1, 8, 0, 2),
        utc(2026, 10, 7, 13, 40, 5), utc(2026, 10, 7, 13, 40, 5),
    ]


def test_without_a_time_the_turn_is_stamped_by_the_database_exactly_as_before(db):
    store = SqliteHistory(db)
    store.append_turn("嗨", "[happy]嗨!")
    assert [m["content"] for m in store.load()] == ["嗨", "[happy]嗨!"]
    times = store.load_times()
    assert len(times) == 2 and all(t is not None for t in times)
    import time
    assert all(abs(t - time.time()) < 5 for t in times)


def test_times_survive_closing_and_reopening_the_database(db):
    SqliteHistory(db).append_turn("嗨", "答", at=utc(2026, 10, 7, 13, 40, 5))
    assert SqliteHistory(db).load_times() == [utc(2026, 10, 7, 13, 40, 5)] * 2


def test_the_existing_message_listing_still_has_only_role_and_content(db):
    store = SqliteHistory(db)
    store.append_turn("嗨", "答", at=utc(2026, 10, 7, 13, 40, 5))
    assert store.load() == [{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "答"}]


def test_the_in_memory_store_remembers_the_time_it_was_given():
    store = InMemoryHistory()
    store.append_turn("嗨", "答", at=1000.0)
    store.append_turn("再", "答二", at=2000.5)
    assert store.load_times() == [1000.0, 1000.0, 2000.5, 2000.5]
    assert len(store.load()) == 4


def test_a_turn_saved_without_a_time_in_memory_is_unknown():
    store = InMemoryHistory()
    store.append_turn("嗨", "答")
    store.append_turn("再", "答二", at=5.0)
    assert store.load_times() == [None, None, 5.0, 5.0]


def test_the_in_memory_message_listing_is_unchanged_and_still_a_copy():
    store = InMemoryHistory()
    store.append_turn("嗨", "答", at=1.0)
    listing = store.load()
    assert listing == [{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "答"}]
    listing[0]["content"] = "tampered"
    assert store.load()[0]["content"] == "嗨"
