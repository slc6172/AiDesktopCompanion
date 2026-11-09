"""The character's own state: where she is, how she feels physically, what she holds, what she
wears, and how many photos she has taken today (spec Part 12, ticket 69).

These tests sit directly on the storage boundary, like test_history_times.py: until the engine
reads and writes the store (tickets 74+) there is nothing observable one level up. Both
implementations must pass the SAME tests."""
import pytest

from companion.state import InMemoryState, SqliteState


@pytest.fixture(params=["memory", "sqlite"])
def make_state(request, tmp_path):
    """A factory returning a store. Calling it again models a restart: SQLite reopens the same
    file; the in-memory store (which has nothing to reopen) is simply returned again."""
    db = tmp_path / "history.db"
    shared = InMemoryState(default_location="家裡")

    def factory(default_location="家裡"):
        if request.param == "memory":
            shared.default_location = default_location
            return shared
        return SqliteState(db, default_location=default_location)

    factory.kind = request.param
    factory.db = db
    return factory


def test_a_brand_new_store_has_sensible_defaults(make_state):
    state = make_state().load()
    assert state["outfit"] is None            # nothing chosen yet: the outfit module falls back
    assert state["location"] == "家裡"
    assert state["status"] is None            # no body status = normal
    assert state["items"] == []
    assert state["photo_count"] == 0
    assert state["photo_exhausted_until"] is None


def test_what_was_written_is_still_there_after_a_restart(make_state):
    state = make_state()
    state.set_outfit("睡衣")
    state.set_location("咖啡廳")
    state.set_status("微醺", at=1_700_000_000.0)
    state.set_items(["紅洋裝", "筆記本"])

    after_restart = make_state().load()
    assert after_restart["outfit"] == "睡衣"
    assert after_restart["location"] == "咖啡廳"
    assert after_restart["status"] == "微醺"
    assert after_restart["status_set_at"] == 1_700_000_000.0
    assert after_restart["items"] == ["紅洋裝", "筆記本"]


def test_a_cleared_body_status_goes_back_to_normal(make_state):
    state = make_state()
    state.set_status("酒醉", at=100.0)
    state.set_status(None)

    loaded = make_state().load()
    assert loaded["status"] is None
    assert loaded["status_set_at"] is None


def test_photos_are_counted_per_utc_day_and_the_count_restarts_on_a_new_day(make_state):
    state = make_state()
    state.record_photo("2026-10-24")
    state.record_photo("2026-10-24")
    loaded = make_state().load()
    assert (loaded["photo_day"], loaded["photo_count"]) == ("2026-10-24", 2)

    make_state().record_photo("2026-10-25")  # the next UTC day starts from one again
    loaded = make_state().load()
    assert (loaded["photo_day"], loaded["photo_count"]) == ("2026-10-25", 1)


def test_the_out_of_quota_marker_survives_a_restart_and_can_be_cleared(make_state):
    make_state().set_photo_exhausted_until(1_761_264_000.0)
    assert make_state().load()["photo_exhausted_until"] == 1_761_264_000.0

    make_state().set_photo_exhausted_until(None)
    assert make_state().load()["photo_exhausted_until"] is None


def test_reset_clears_only_outfit_place_body_and_belongings_never_the_photo_quota(make_state):
    state = make_state()
    state.set_outfit("睡衣")
    state.set_location("咖啡廳")
    state.set_status("感冒", at=5.0)
    state.set_items(["紅洋裝"])
    state.record_photo("2026-10-24")
    state.record_photo("2026-10-24")
    state.set_photo_exhausted_until(1_761_264_000.0)

    make_state().reset()

    loaded = make_state().load()
    assert (loaded["outfit"], loaded["location"], loaded["status"], loaded["items"]) == (None, "家裡", None, [])
    assert loaded["status_set_at"] is None
    # the quota record stays accurate: a reset must not hand out free photos
    assert (loaded["photo_day"], loaded["photo_count"]) == ("2026-10-24", 2)
    assert loaded["photo_exhausted_until"] == 1_761_264_000.0


def test_reset_puts_the_place_back_to_the_configured_default(make_state):
    make_state(default_location="咖啡廳").set_location("公園")
    make_state(default_location="咖啡廳").reset()
    assert make_state(default_location="咖啡廳").load()["location"] == "咖啡廳"


def test_reset_leaves_history_memory_and_affection_in_the_same_database_untouched(tmp_path):
    from companion.history import SqliteHistory

    db = tmp_path / "history.db"
    history = SqliteHistory(db)
    history.append_turn("嗨", "[happy]嗨!", at=1_700_000_000.0)
    history.apply_fold([], {"使用者": "- 喜歡咖啡"}, 2)
    history.save_affection(72.0, at=1_700_000_000.0)
    state = SqliteState(db)
    state.set_location("公園")

    SqliteState(db).reset()

    assert history.load() == [{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "[happy]嗨!"}]
    assert history.load_facts() == {"使用者": "- 喜歡咖啡"} and history.load_fold_progress() == 2
    assert history.load_affection() == 72.0
    assert history.load_last_interaction() == 1_700_000_000.0


def test_resetting_a_store_that_never_wrote_anything_is_harmless(make_state):
    make_state().reset()
    assert make_state().load()["location"] == "家裡"


# ---- the `--reset-state` command -------------------------------------------------------------

@pytest.fixture
def cli(tmp_path, monkeypatch):
    """Runs the real command-line entry point against a throw-away database; anything that would
    start the actual app fails the test instead."""
    from companion import launcher

    db = tmp_path / "data" / "history.db"
    monkeypatch.setenv("COMPANION_DB", str(db))
    monkeypatch.setattr(launcher, "user_dir", lambda: tmp_path)

    def never(*args, **kwargs):
        raise AssertionError("--reset-state must not start the app")

    monkeypatch.setattr(launcher, "start_server", never)
    monkeypatch.setattr(launcher, "open_electron_window", never)
    return launcher.main, db


def test_the_reset_command_clears_the_state_but_not_the_history_or_the_photo_quota(cli, capsys):
    from companion.history import SqliteHistory

    main, db = cli
    db.parent.mkdir(parents=True)
    history = SqliteHistory(db)
    history.append_turn("嗨", "[happy]嗨!", at=1_700_000_000.0)
    history.save_affection(80.0, at=1_700_000_000.0)
    state = SqliteState(db)
    state.set_location("公園")
    state.set_outfit("睡衣")
    state.set_items(["紅洋裝"])
    state.record_photo("2026-10-24")
    state.set_photo_exhausted_until(1_761_264_000.0)

    main(["--reset-state"])

    loaded = SqliteState(db).load()
    assert (loaded["outfit"], loaded["location"], loaded["items"]) == (None, "家裡", [])
    assert (loaded["photo_count"], loaded["photo_exhausted_until"]) == (1, 1_761_264_000.0)
    assert len(history.load()) == 2 and history.load_affection() == 80.0
    assert "角色狀態" in capsys.readouterr().out   # it tells the person what it did


def test_the_reset_command_is_fine_on_a_first_run_with_no_database_yet(cli, capsys):
    main, db = cli
    main(["--reset-state"])
    assert "角色狀態" in capsys.readouterr().out
