"""Her own changes of state leave a line in the journal (spec Part 12, section 8, ticket 83) — written by the
program when something REALLY changed, never by the model, so the memory of "she bought a dress" does not
depend on her remembering to say so."""
import pytest

from companion import timesense
from companion.engine import TurnEngine
from companion.history import InMemoryHistory
from companion.outfits import Wardrobe
from companion.state import InMemoryState

NOW = 1_800_000_000.0
SETTINGS = {"enabled": True, "default_location": "家裡", "status_ttl_hours": {"微醺": 3},
            "default_status_ttl_hours": 12.0, "max_items": 20}
TODAY = f"{timesense.local_datetime(NOW, None):%Y-%m-%d}"
CLOCK = f"{timesense.local_datetime(NOW, None):%H:%M}"


class ScriptedLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        yield self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


@pytest.fixture
def build(tmp_path):
    clips = tmp_path / "clips"
    for name in ("日常", "睡衣"):
        (clips / name).mkdir(parents=True, exist_ok=True)
        (clips / name / "idle.webm").write_bytes(b"v")

    def make(*replies, memory=True, state=None):
        state = state if state is not None else InMemoryState()
        store = InMemoryHistory()
        llm = ScriptedLLM(*replies)
        engine = TurnEngine(llm, persona="p", history_store=store, summarize=memory, wall_clock=lambda: NOW,
                            character_state=state, state_settings=SETTINGS,
                            wardrobe=Wardrobe(clips, state, settings=lambda: {"default": "日常", "aliases": {}}))
        return engine, llm, store, state

    return make


def journal(store):
    return [e["text"] for e in store.load_all_events()]


def say(engine, text="嗨", **kwargs):
    return list(engine.send(text, **kwargs))


# ---- each kind of change ----------------------------------------------------------------------------------

@pytest.mark.parametrize("reply, line", [
    ("[地點:咖啡廳]到了。", "地點→咖啡廳"),
    ("[狀態:微醺]喝多了。", "狀態→微醺"),
    ("[得到:紅洋裝]收下了。", "得到:紅洋裝"),
    ("[換裝:睡衣]我去換。", "換裝→睡衣"),
])
def test_a_real_change_writes_one_line_with_todays_date_and_the_time(build, reply, line):
    engine, _, store, _ = build(reply)
    say(engine)
    [event] = store.load_all_events()
    assert (event["date"], event["time"], event["text"], event["kind"]) == (TODAY, CLOCK, line, "狀態")


def test_losing_something_and_recovering_are_recorded_too(build):
    state = InMemoryState()
    state.set_items(["紅洋裝"])
    state.set_status("微醺", at=NOW - 60)
    engine, _, store, _ = build("[失去:紅洋裝][狀態:正常]好。", state=state)
    say(engine)
    assert sorted(journal(store)) == sorted(["失去:紅洋裝", "狀態→正常"])


def test_asking_for_a_change_of_clothes_in_words_is_recorded_as_well(build):
    engine, _, store, _ = build("好。")
    say(engine, "換成睡衣")
    assert journal(store) == ["換裝→睡衣"]


def test_what_was_written_shows_in_the_next_prompt_as_todays_journal(build):
    engine, llm, _, _ = build("[地點:咖啡廳]到了。", "好。")
    say(engine)
    say(engine)
    assert f"- {CLOCK} 地點→咖啡廳" in llm.systems[1]


# ---- nothing changed, nothing written ----------------------------------------------------------------------

def test_saying_the_same_thing_again_changes_nothing_and_writes_nothing(build):
    state = InMemoryState()
    state.set_location("咖啡廳")
    state.set_items(["紅洋裝"])
    state.set_status("微醺", at=NOW - 60)
    engine, _, store, _ = build("[地點:咖啡廳][狀態:微醺][得到:紅洋裝]好。", state=state)
    say(engine)
    assert journal(store) == []


def test_recovering_when_nothing_was_wrong_and_losing_what_she_does_not_have_write_nothing(build):
    engine, _, store, _ = build("[狀態:正常][失去:手機]好。")
    say(engine)
    assert journal(store) == []


def test_a_status_that_had_already_worn_off_counts_as_a_new_one_when_declared_again(build):
    state = InMemoryState()
    state.set_status("微醺", at=NOW - 10 * 3600)         # stored, but past its 3 hours
    engine, _, store, _ = build("[狀態:微醺]又喝了。", state=state)
    say(engine)
    assert journal(store) == ["狀態→微醺"]


def test_wearing_what_she_already_wears_writes_nothing(build):
    engine, _, store, _ = build("[換裝:日常]好。")
    say(engine)
    assert journal(store) == []


def test_tags_that_were_thrown_away_write_nothing(build):
    engine, _, store, _ = build("[地點:這個地方的名字真的有夠長長長][得到:]好。")
    say(engine)
    assert journal(store) == []


def test_a_polluted_turn_changes_nothing_so_writes_nothing(build):
    engine, _, store, _ = build("[地點:咖啡廳][換裝:睡衣]好。")
    say(engine, polluted=True)
    assert journal(store) == []


# ---- switched off ---------------------------------------------------------------------------------------------

def test_with_memory_switched_off_the_state_still_changes_but_no_journal_is_kept(build):
    engine, _, store, state = build("[地點:咖啡廳]到了。", memory=False)
    say(engine)
    assert state.load()["location"] == "咖啡廳" and journal(store) == []
