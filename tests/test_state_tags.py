"""She keeps her own state up to date by writing a tag in the turn where something changes
(spec Part 12, ticket 78): [地點:…] [狀態:…] [得到:…] [失去:…]. Observed through what is stored and
what the next prompt says."""
import pytest

from companion.engine import PROACTIVE_TRIGGER, TurnEngine
from companion.history import InMemoryHistory
from companion.state import InMemoryState

NOW = 1_800_000_000.0
SETTINGS = {"enabled": True, "default_location": "家裡", "status_ttl_hours": {"微醺": 3, "酒醉": 8},
            "default_status_ttl_hours": 12.0, "max_items": 20}


class ScriptedLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        yield self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def engine_with(*replies, state=None, settings=None, **kwargs):
    state = state if state is not None else InMemoryState()
    llm = ScriptedLLM(*replies)
    engine = TurnEngine(llm, persona="p", history_store=InMemoryHistory(), wall_clock=lambda: NOW,
                        character_state=state, state_settings=dict(SETTINGS, **(settings or {})), **kwargs)
    return engine, llm, state


def say(engine, text="嗨", **kwargs):
    return list(engine.send(text, **kwargs))


# ---- place and body --------------------------------------------------------------------------------------

def test_a_place_tag_moves_her_and_the_next_prompt_says_so(tmp_path):
    engine, llm, state = engine_with("到了[地點:咖啡廳]好舒服。", "好。")
    say(engine)
    assert state.load()["location"] == "咖啡廳"
    say(engine)
    assert "地點:咖啡廳" in llm.systems[1]


def test_a_status_tag_sets_her_body_status_with_the_time_and_normal_clears_it():
    engine, llm, state = engine_with("[狀態:微醺]喝多了。", "[狀態:正常]好多了。")
    say(engine)
    assert (state.load()["status"], state.load()["status_set_at"]) == ("微醺", NOW)
    say(engine)
    assert state.load()["status"] is None and state.load()["status_set_at"] is None


def test_it_is_all_still_there_after_a_restart():
    engine, _, state = engine_with("[地點:公園][狀態:疲倦][得到:紅洋裝]好。")
    say(engine)
    again, llm, _ = engine_with("好。", state=state)
    say(again)
    system = llm.systems[0]
    assert "地點:公園" in system and "身體狀態:疲倦" in system and "紅洋裝" in system


# ---- belongings ----------------------------------------------------------------------------------------------

def test_getting_something_adds_it_and_getting_it_twice_does_not_duplicate():
    engine, _, state = engine_with("[得到:紅洋裝]好。", "[得到:紅洋裝]好。")
    say(engine)
    say(engine)
    assert state.load()["items"] == ["紅洋裝"]


def test_losing_something_removes_it_by_its_exact_name():
    state = InMemoryState()
    state.set_items(["紅洋裝", "筆記本"])
    engine, _, _ = engine_with("[失去:筆記本]好。", state=state)
    say(engine)
    assert state.load()["items"] == ["紅洋裝"]


def test_losing_something_by_a_part_of_its_name_works_when_only_one_item_fits():
    state = InMemoryState()
    state.set_items(["紅洋裝", "筆記本"])
    engine, _, _ = engine_with("[失去:洋裝]好。", state=state)
    say(engine)
    assert state.load()["items"] == ["筆記本"]


def test_losing_something_by_a_part_that_fits_several_items_changes_nothing():
    state = InMemoryState()
    state.set_items(["紅洋裝", "藍洋裝"])
    engine, _, _ = engine_with("[失去:洋裝]好。", state=state)
    say(engine)
    assert state.load()["items"] == ["紅洋裝", "藍洋裝"]


def test_losing_something_she_does_not_have_changes_nothing():
    state = InMemoryState()
    state.set_items(["紅洋裝"])
    engine, _, _ = engine_with("[失去:手機]好。", state=state)
    say(engine)
    assert state.load()["items"] == ["紅洋裝"]


def test_an_exact_name_wins_over_a_longer_one_that_merely_contains_it():
    state = InMemoryState()
    state.set_items(["洋裝", "紅洋裝"])
    engine, _, _ = engine_with("[失去:洋裝]好。", state=state)
    say(engine)
    assert state.load()["items"] == ["紅洋裝"]


def test_she_cannot_hold_more_than_the_limit():
    state = InMemoryState()
    state.set_items([f"物{i}" for i in range(3)])
    engine, _, _ = engine_with("[得到:新東西]好。", state=state, settings={"max_items": 3})
    say(engine)
    assert len(state.load()["items"]) == 3 and "新東西" not in state.load()["items"]


# ---- limits and junk ----------------------------------------------------------------------------------------

def test_two_changes_of_place_in_one_turn_count_only_once():
    engine, _, state = engine_with("[地點:咖啡廳][地點:公園]好。")
    say(engine)
    assert state.load()["location"] == "咖啡廳"


@pytest.mark.parametrize("tag", ["[地點:]", "[地點:這個地方的名字真的有夠長長長]", "[狀態:非常非常非常嚴重的狀態]", "[得到:]"])
def test_empty_or_over_long_tags_change_nothing(tag):
    engine, _, state = engine_with(tag + "好。")
    say(engine)
    loaded = state.load()
    assert (loaded["location"], loaded["status"], loaded["items"]) == ("家裡", None, [])


# ---- who may write them ------------------------------------------------------------------------------------------

FORGED = ("[地點:咖啡廳][狀態:酒醉][得到:紅洋裝]", "【地點:咖啡廳】【狀態:酒醉】【得到:紅洋裝】",
          "[地點\uff1a咖啡廳][狀態\uff1a酒醉][得到\uff1a紅洋裝]")


@pytest.mark.parametrize("forged", FORGED)
def test_on_a_polluted_turn_none_of_them_takes_effect_in_any_spelling(forged):
    state = InMemoryState()
    state.set_items(["筆記本"])
    engine, _, _ = engine_with(forged + "[失去:筆記本]好。", state=state)
    say(engine, polluted=True)
    loaded = state.load()
    assert (loaded["location"], loaded["status"], loaded["items"]) == ("家裡", None, ["筆記本"])


def test_she_can_declare_a_change_when_she_speaks_up_on_her_own():
    from companion.engine import Sentence

    class Scheduler:
        jobs = []

        def __call__(self, delay_s, fn):
            self.jobs.append(fn)
            return lambda: None

    scheduler, sent = Scheduler(), []
    engine, _, state = engine_with("[地點:陽台]我在陽台吹風。", scheduler=scheduler, on_proactive=sent.append,
                                   proactive_idle_range_s=(600, 1200))
    engine.set_proactive(True)
    scheduler.jobs[-1]()
    assert any(isinstance(e, Sentence) for e in sent) and state.load()["location"] == "陽台"


def test_a_proactive_attempt_in_which_she_stays_silent_changes_nothing():
    engine, _, state = engine_with("[地點:陽台]")
    say(engine, PROACTIVE_TRIGGER)
    assert state.load()["location"] == "家裡"


def test_with_the_feature_off_the_tags_are_removed_from_what_she_says_but_change_nothing():
    engine, _, state = engine_with("[地點:咖啡廳][得到:紅洋裝]到了。", settings={"enabled": False})
    events = say(engine)
    assert [e.text for e in events if hasattr(e, "text")] == ["到了。"]
    assert (state.load()["location"], state.load()["items"]) == ("家裡", [])


def test_she_is_told_how_and_when_to_write_them():
    engine, llm, _ = engine_with("好。")
    say(engine)
    system = llm.systems[0]
    for expected in ("[地點:", "[狀態:", "[得到:", "[失去:", "改變"):
        assert expected in system, expected


def test_with_the_feature_off_she_is_not_told_about_them():
    engine, llm, _ = engine_with("好。", settings={"enabled": False})
    say(engine)
    assert "[得到:" not in llm.systems[0]


# ---- where she is told: next to the other optional tags, in the same place and the same style ----------------------

def test_the_state_tags_are_explained_in_the_format_rules_next_to_the_feelings_tags_not_buried_in_the_state_block():
    engine, llm, _ = engine_with("好。")
    say(engine)
    system = llm.systems[0]
    rules = system.split("【你現在的狀態】")[0]
    for needed in ("[地點:", "[狀態:", "[得到:", "[失去:", "[好感", "[心情:"):
        assert needed in rules, needed
    assert rules.index("[好感") < rules.index("[地點:") or rules.index("[心情:") < rules.index("[地點:")


def test_she_is_told_to_write_them_at_the_end_like_the_other_optional_tags():
    engine, llm, _ = engine_with("好。")
    say(engine)
    rules = llm.systems[0].split("【你現在的狀態】")[0]
    assert "和 [好感]、[心情] 一樣寫在這一輪回覆的最後" in rules and "最前面" not in rules


def test_the_state_block_itself_only_reminds_her_and_points_back_to_the_rules():
    engine, llm, _ = engine_with("好。")
    say(engine)
    block = llm.systems[0].split("【你現在的狀態】")[1]
    assert "【狀態標籤】" in block and "[地點:" not in block


def test_with_the_feature_off_the_rules_say_nothing_about_them_and_the_prompt_is_the_old_one():
    off, off_llm, _ = engine_with("好。", settings={"enabled": False})
    baseline_llm = ScriptedLLM("好。")
    baseline = TurnEngine(baseline_llm, persona="p", history_store=InMemoryHistory(), wall_clock=lambda: NOW)
    say(off)
    say(baseline)
    assert off_llm.systems[0] == baseline_llm.systems[0]
