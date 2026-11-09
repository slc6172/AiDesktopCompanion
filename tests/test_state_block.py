"""What she is told about herself right now — where she is, how her body feels, what she wears and
carries, how close she is to the person — in ONE block (spec Part 12, ticket 77). Observed in the
system prompt the engine sends, with a fake LLM that records it."""
import pytest

from companion.engine import PROACTIVE_TRIGGER, TurnEngine
from companion.history import InMemoryHistory
from companion.outfits import Wardrobe
from companion.state import InMemoryState

HOUR = 3600.0
NOW = 1_800_000_000.0

SETTINGS = {"enabled": True, "default_location": "家裡",
            "status_ttl_hours": {"微醺": 3, "酒醉": 8, "疲倦": 10, "感冒": 72},
            "default_status_ttl_hours": 12.0, "max_items": 20}


class SpyLLM:
    def __init__(self, reply="好。"):
        self.systems = []
        self.reply = reply

    def stream(self, system, messages):
        self.systems.append(system)
        yield self.reply


@pytest.fixture
def build(tmp_path):
    clips = tmp_path / "clips"
    for name in ("日常", "睡衣"):
        (clips / name).mkdir(parents=True)
        (clips / name / "idle.webm").write_bytes(b"v")
    (clips / "睡衣" / "outfit.txt").write_text("a soft pajama set\n", encoding="utf-8")

    def make(state=None, settings=None, with_state=True, with_wardrobe=True, reply="好。", **kwargs):
        state = state if state is not None else InMemoryState()
        llm = SpyLLM(reply)
        engine = TurnEngine(
            llm, persona="p", history_store=InMemoryHistory(), wall_clock=lambda: NOW,
            wardrobe=Wardrobe(clips, state, settings=lambda: {"default": "日常", "aliases": {}}) if with_wardrobe else None,
            character_state=state if with_state else None,
            state_settings=dict(SETTINGS, **(settings or {})), **kwargs)
        return engine, llm, state

    return make


def system_of(engine, llm, text="嗨"):
    list(engine.send(text))
    return llm.systems[-1]


def block(system):
    """Just the 【你現在的狀態】 block of the prompt."""
    assert "【你現在的狀態】" in system
    return system.split("【你現在的狀態】")[1].split("\n\n【")[0]


# ---- one block with everything in it -------------------------------------------------------------

def test_where_she_is_how_she_feels_what_she_wears_and_carries_are_all_in_one_block(build):
    engine, llm, state = build()
    state.set_location("咖啡廳")
    state.set_status("微醺", at=NOW - HOUR)
    state.set_items(["紅洋裝", "筆記本"])
    system = system_of(engine, llm)
    assert system.count("【你現在的狀態】") == 1
    text = block(system)
    for expected in ("地點:咖啡廳", "身體狀態:微醺", "你目前穿著:日常", "紅洋裝", "筆記本", "好感度:", "你可以換的服裝只有:日常、睡衣"):
        assert expected in text, expected
    assert "【你和使用者的關係】" not in system and "【服裝】" not in system   # folded into the one block


def test_her_mood_joins_the_block_once_she_has_one(build):
    engine, llm, _ = build(reply="[心情:雀躍]好。")
    assert "你目前的心情" not in system_of(engine, llm)          # none yet
    assert "你目前的心情:雀躍" in block(system_of(engine, llm))   # she said she was cheerful


def test_the_outfit_description_and_a_fresh_start_read_sensibly(build):
    engine, llm, state = build()
    state.set_outfit("睡衣")
    text = block(system_of(engine, llm))
    assert "你目前穿著:睡衣(a soft pajama set)" in text
    assert "地點:家裡" in text and "身體狀態:正常" in text and "持有物品:沒有" in text


def test_the_configured_default_place_is_used_when_she_has_not_moved(build):
    engine, llm, state = build(state=InMemoryState(default_location="海邊小屋"))
    assert "地點:海邊小屋" in block(system_of(engine, llm))


def test_it_survives_a_restart(build):
    engine, llm, state = build()
    state.set_location("公園")
    state.set_items(["紅洋裝"])
    again, llm2, _ = build(state=state)
    assert "地點:公園" in block(system_of(again, llm2)) and "紅洋裝" in block(system_of(again, llm2))


def test_a_proactive_turn_gets_the_block_too(build):
    engine, llm, state = build()
    state.set_location("咖啡廳")
    list(engine.send(PROACTIVE_TRIGGER))
    assert "地點:咖啡廳" in block(llm.systems[-1])


# ---- body status wears off ------------------------------------------------------------------------------

@pytest.mark.parametrize("status, hours_ago, still_there", [
    ("酒醉", 9, False), ("酒醉", 7.9, True), ("微醺", 3.1, False), ("微醺", 2.9, True),
    ("感冒", 71, True), ("感冒", 73, False),
    ("發呆", 13, False), ("發呆", 11, True),          # a word nobody listed uses the default of 12 hours
])
def test_a_body_status_lasts_its_own_time_and_then_counts_as_normal(build, status, hours_ago, still_there):
    engine, llm, state = build()
    state.set_status(status, at=NOW - hours_ago * HOUR)
    text = block(system_of(engine, llm))
    assert (f"身體狀態:{status}" in text) is still_there
    if not still_there:
        assert "身體狀態:正常" in text


def test_the_lifetimes_come_from_the_settings(build):
    engine, llm, state = build(settings={"status_ttl_hours": {"酒醉": 1}})
    state.set_status("酒醉", at=NOW - 2 * HOUR)
    assert "身體狀態:正常" in block(system_of(engine, llm))


def test_a_status_without_a_time_is_treated_as_worn_off(build):
    engine, llm, state = build()
    state.set_status("酒醉")   # no time recorded: nothing can say when it began
    assert "身體狀態:正常" in block(system_of(engine, llm))


# ---- switched off ---------------------------------------------------------------------------------------------

def test_with_the_feature_off_the_prompt_is_exactly_what_it_was_without_the_feature(build):
    off, off_llm, off_state = build(settings={"enabled": False})
    off_state.set_location("咖啡廳")
    off_state.set_items(["紅洋裝"])
    baseline, base_llm, _ = build(with_state=False)
    assert system_of(off, off_llm) == system_of(baseline, base_llm)
    assert "【你現在的狀態】" not in off_llm.systems[-1] and "咖啡廳" not in off_llm.systems[-1]


def test_with_the_feature_off_and_no_outfits_it_is_still_the_old_prompt(build):
    off, off_llm, _ = build(settings={"enabled": False}, with_wardrobe=False)
    baseline, base_llm, _ = build(with_state=False, with_wardrobe=False)
    assert system_of(off, off_llm) == system_of(baseline, base_llm)


# ---- the real wiring: config.json -> app -> prompt -----------------------------------------------------------

@pytest.fixture
def app_prompt(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from companion.server import create_app

    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.delenv("COMPANION_FAKE", raising=False)
    (tmp_path / "clips" / "日常").mkdir(parents=True)
    (tmp_path / "clips" / "日常" / "idle.webm").write_bytes(b"v")

    class Tts:
        mime_type = "audio/fake"

        def synthesize(self, text):
            return b"x"

    def ask(config, seed):
        (tmp_path / "config.json").write_text(json.dumps(dict({"stt": {"enabled": False}}, **config)), encoding="utf-8")
        state = InMemoryState()
        seed(state)
        llm = SpyLLM()
        client = TestClient(create_app(llm=llm, persona="p", tts=Tts(), store=InMemoryHistory(), state_store=state))
        client.post("/chat", json={"message": "嗨"})
        return llm.systems[-1]

    return ask


def test_the_app_tells_her_where_she_is(app_prompt):
    system = app_prompt({}, lambda s: s.set_location("咖啡廳"))
    assert "地點:咖啡廳" in block(system)


def test_switched_off_in_config_json_the_app_says_nothing_about_her_state(app_prompt):
    system = app_prompt({"companion_state": {"enabled": False}}, lambda s: s.set_location("咖啡廳"))
    assert "【你現在的狀態】" not in system and "咖啡廳" not in system


def test_the_status_lifetimes_in_config_json_are_honoured(app_prompt):
    import time

    seed = lambda s: s.set_status("酒醉", at=time.time() - 2 * HOUR)
    assert "身體狀態:酒醉" in block(app_prompt({}, seed))
    assert "身體狀態:正常" in block(app_prompt({"companion_state": {"status_ttl_hours": {"酒醉": 1}}}, seed))


def test_the_database_backed_store_starts_at_the_configured_place(tmp_path, monkeypatch):
    import json

    from companion.server import build_state_store

    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.delenv("COMPANION_FAKE", raising=False)
    monkeypatch.delenv("COMPANION_DB", raising=False)
    (tmp_path / "config.json").write_text(json.dumps({"companion_state": {"default_location": "海邊小屋"}}), encoding="utf-8")
    assert build_state_store().load()["location"] == "海邊小屋"


def test_with_the_feature_off_she_still_gets_the_old_relationship_and_outfit_blocks(build):
    off, off_llm, _ = build(settings={"enabled": False})
    system = system_of(off, off_llm)
    assert "【你和使用者的關係】\n好感度:" in system
    assert "【服裝】\n你目前穿著:日常" in system
