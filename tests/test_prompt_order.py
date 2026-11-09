"""The order of everything she is told, fixed once (spec Part 12, section 8): who she is and the rules, what she
remembers for good, the journal of the last two days, who she is right now, what time it is, what comes to mind
because of what was just said, and anything particular to this kind of turn."""
import json

import pytest

from companion.config import resolve_time_config
from companion.engine import PROACTIVE_SYSTEM_ADDENDUM, PROACTIVE_TRIGGER, TurnEngine
from companion.history import InMemoryHistory
from companion.outfits import Wardrobe
from companion.state import InMemoryState

NOW = 1_800_000_000.0
DAY = 86400.0
STATE = {"enabled": True, "default_location": "家裡", "status_ttl_hours": {}, "default_status_ttl_hours": 12.0, "max_items": 20}


class SpyLLM:
    def __init__(self):
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        yield "好。"

    def generate_structured(self, system, messages, schema):
        return None  # these tests are about the prompt; folding is not what is being looked at


@pytest.fixture
def prompt(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"time": {"timezone": "Asia/Taipei"}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    clips = tmp_path / "clips"
    for name in ("日常", "睡衣"):
        (clips / name).mkdir(parents=True)
        (clips / name / "idle.webm").write_bytes(b"v")

    def build(message="上次說的面試怎麼樣了", state_on=True):
        store = InMemoryHistory()
        store.append_turn("我下週三要去面試", "[neutral]加油喔。", at=NOW - 90 * DAY)
        for n in range(3):
            store.append_turn(f"閒聊{n}", "[neutral]嗯。", at=NOW - 3600 + n)
        store.save_facts({"使用者": "- 喜歡黑咖啡"})
        from companion import timesense

        today = f"{timesense.local_datetime(NOW, resolve_time_config()['timezone']):%Y-%m-%d}"
        store.append_events([{"date": today, "time": "09:00", "kind": "事件", "text": "今天的事"}])
        llm, state = SpyLLM(), InMemoryState()
        engine = TurnEngine(llm, persona="我是小桃。", history_store=store, summarize=True, max_turns=3, wall_clock=lambda: NOW,
                            time_config=resolve_time_config(), character_state=state,
                            state_settings=dict(STATE, enabled=state_on),
                            wardrobe=Wardrobe(clips, state, settings=lambda: {"default": "日常", "aliases": {}}))
        list(engine.send(message))
        return llm.systems[-1]

    return build


def in_order(system, *markers):
    positions = [system.index(m) for m in markers]
    assert positions == sorted(positions) and len(set(positions)) == len(positions), list(zip(markers, positions))


def test_everything_comes_in_the_fixed_order(prompt):
    system = prompt()
    assert system.startswith("我是小桃。")
    in_order(system, "我是小桃。", "【回覆格式】", "【長期記憶", "【最近的日誌】", "【你現在的狀態】",
             "【時間資訊(系統提供)】", "【可能相關的記憶】")


def test_the_relationship_and_the_clothes_are_part_of_the_state_block_when_it_is_on(prompt):
    system = prompt()
    in_order(system, "【你現在的狀態】", "你目前穿著:", "好感度:", "【時間資訊(系統提供)】")
    assert "【你和使用者的關係】" not in system and "【服裝】" not in system


def test_with_the_state_block_off_the_relationship_and_clothes_blocks_take_its_place_in_the_same_order(prompt):
    system = prompt(state_on=False)
    in_order(system, "【長期記憶", "【最近的日誌】", "【你和使用者的關係】", "【服裝】", "【時間資訊(系統提供)】", "【可能相關的記憶】")
    assert "【你現在的狀態】" not in system


def test_what_belongs_only_to_a_proactive_turn_comes_last(prompt):
    system = prompt(message=PROACTIVE_TRIGGER)
    in_order(system, "【長期記憶", "【最近的日誌】", "【你現在的狀態】", "【時間資訊(系統提供)】", PROACTIVE_SYSTEM_ADDENDUM.strip()[:12])
    assert "【可能相關的記憶】" not in system
