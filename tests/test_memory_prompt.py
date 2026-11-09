"""What she remembers, as the system prompt shows it (spec Part 12, section 8, ticket 80): the long-term
facts and today's and yesterday's journal are always there, each within its size limit; with memory
switched off the prompt is exactly what it is today."""
from datetime import timedelta

import pytest

from companion import timesense
from companion.engine import PROACTIVE_TRIGGER, TurnEngine
from companion.history import InMemoryHistory, SqliteHistory

NOW = 1_800_000_000.0
LIMITS = {"long_term_max_chars": 2000, "recent_notes_max_chars": 600}


def day(offset=0, epoch=NOW, tz=None):
    return f"{timesense.local_datetime(epoch, tz) + timedelta(days=offset):%Y-%m-%d}"


class SpyLLM:
    def __init__(self):
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        yield "好。"


def engine_for(store, memory=True, limits=None, **kwargs):
    llm = SpyLLM()
    engine = TurnEngine(llm, persona="p", history_store=store, summarize=memory, wall_clock=lambda: NOW,
                        memory_settings=dict(LIMITS, **(limits or {})), **kwargs)
    return engine, llm


def prompt(store, text="嗨", **kwargs):
    engine, llm = engine_for(store, **kwargs)
    list(engine.send(text))
    return llm.systems[-1]


def event(date, text, time="12:00", kind="事件"):
    return {"date": date, "time": time, "kind": kind, "text": text}


# ---- long-term facts ----------------------------------------------------------------------------------

def test_the_long_term_facts_are_always_in_the_prompt_section_by_section_in_a_fixed_order():
    store = InMemoryHistory()
    store.save_facts({"待跟進": "- 2026-10-28 面試", "使用者": "- 喜歡黑咖啡", "角色自己的事": "- 怕打雷"})
    system = prompt(store)
    assert "【長期記憶" in system
    positions = [system.index(h) for h in ("〔使用者〕", "〔角色自己的事〕", "〔待跟進〕")]
    assert positions == sorted(positions)
    assert "- 喜歡黑咖啡" in system and "- 2026-10-28 面試" in system


def test_long_term_memory_over_its_limit_keeps_the_earlier_lines_and_never_exceeds_the_limit():
    store = InMemoryHistory()
    store.save_facts({"使用者": "\n".join(f"- 事實{i:03d}" for i in range(100)), "待跟進": "- 重要的待辦"})
    text = prompt(store, limits={"long_term_max_chars": 200}).split("【長期記憶")[1].split("\n\n【")[0]
    body = "\n".join(line for line in text.splitlines() if line.startswith("- "))
    assert len(body) <= 200
    assert "- 事實000" in text and "- 事實099" not in text


# ---- the journal ---------------------------------------------------------------------------------------------

def test_today_and_yesterday_are_in_the_prompt_and_older_days_are_not():
    store = InMemoryHistory()
    store.append_events([event(day(0), "今天去了咖啡廳"), event(day(-1), "昨天面試"), event(day(-2), "前天的事"),
                         event(day(1), "明天的事")])
    system = prompt(store)
    assert "今天去了咖啡廳" in system and "昨天面試" in system
    assert "前天的事" not in system and "明天的事" not in system
    assert system.index("昨天面試") < system.index("今天去了咖啡廳")      # in the order they happened
    assert f"今天 {day(0)}" in system and f"昨天 {day(-1)}" in system


def test_an_event_line_shows_its_time_when_it_has_one():
    store = InMemoryHistory()
    store.append_events([event(day(0), "地點→咖啡廳", time="09:30"), event(day(0), "沒有時間的事", time=None)])
    system = prompt(store)
    assert "- 09:30 地點→咖啡廳" in system and "- 沒有時間的事" in system


def test_each_days_journal_keeps_its_latest_lines_within_the_limit():
    store = InMemoryHistory()
    store.append_events([event(day(0), f"第{i:02d}件事", time=None) for i in range(50)])
    system = prompt(store, limits={"recent_notes_max_chars": 60})
    today = system.split(f"今天 {day(0)}:")[1].split("\n\n【")[0].strip().splitlines()
    assert sum(len(line) + 1 for line in today) <= 60
    assert "第49件事" in system and "第00件事" not in system


def test_the_days_follow_the_configured_time_zone(tmp_path, monkeypatch):
    import json
    from zoneinfo import ZoneInfo

    from companion.config import resolve_time_config

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"time": {"timezone": "Asia/Taipei"}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    late_utc = 1_800_000_000.0 + 12 * 3600          # still "today" in UTC, already tomorrow in Taipei
    taipei_today = day(0, late_utc, ZoneInfo("Asia/Taipei"))
    store = InMemoryHistory()
    store.append_events([event(taipei_today, "台北的今天")])
    engine = TurnEngine(SpyLLM(), persona="p", history_store=store, summarize=True, wall_clock=lambda: late_utc,
                        memory_settings=LIMITS, time_config=resolve_time_config())
    llm = engine._llm
    list(engine.send("嗨"))
    assert f"今天 {taipei_today}" in llm.systems[-1] and "台北的今天" in llm.systems[-1]


def test_a_proactive_turn_remembers_too():
    store = InMemoryHistory()
    store.save_facts({"使用者": "- 喜歡黑咖啡"})
    assert "喜歡黑咖啡" in prompt(store, PROACTIVE_TRIGGER)


# ---- nothing stored, or switched off ------------------------------------------------------------------------

def test_with_nothing_remembered_the_prompt_has_no_empty_memory_headings():
    system = prompt(InMemoryHistory())
    assert "【長期記憶" not in system and "【最近的日誌" not in system


@pytest.mark.parametrize("with_content", [False, True])
def test_with_memory_switched_off_the_prompt_is_exactly_what_it_is_without_the_feature(with_content):
    full = InMemoryHistory()
    if with_content:
        full.save_facts({"使用者": "- 喜歡黑咖啡"})
        full.append_events([event(day(0), "今天的事")])
    off = prompt(full, memory=False)
    baseline = prompt(InMemoryHistory(), memory=False)
    assert off == baseline
    assert "喜歡黑咖啡" not in off and "今天的事" not in off


def test_the_environment_switch_does_the_same_as_the_setting(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from companion.server import create_app
    from companion.state import InMemoryState

    class Tts:
        mime_type = "audio/fake"

        def synthesize(self, text):
            return b"x"

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"stt": {"enabled": False}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    (tmp_path / "clips" / "日常").mkdir(parents=True)
    (tmp_path / "clips" / "日常" / "idle.webm").write_bytes(b"v")
    monkeypatch.delenv("COMPANION_FAKE", raising=False)

    def ask(env):
        if env:
            monkeypatch.setenv("COMPANION_MEMORY", "off")
        else:
            monkeypatch.delenv("COMPANION_MEMORY", raising=False)
        store = InMemoryHistory()
        store.save_facts({"使用者": "- 喜歡黑咖啡"})
        llm = SpyLLM()
        TestClient(create_app(llm=llm, persona="p", tts=Tts(), store=store, state_store=InMemoryState())).post("/chat", json={"message": "嗨"})
        return llm.systems[-1]

    assert "喜歡黑咖啡" in ask(env=False)
    assert "喜歡黑咖啡" not in ask(env=True)


def test_the_limits_in_config_json_reach_the_prompt(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from companion.server import create_app
    from companion.state import InMemoryState

    class Tts:
        mime_type = "audio/fake"

        def synthesize(self, text):
            return b"x"

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"stt": {"enabled": False}, "memory": {"long_term_max_chars": 200}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.setattr("companion.server.user_dir", lambda: tmp_path)
    (tmp_path / "clips" / "日常").mkdir(parents=True)
    (tmp_path / "clips" / "日常" / "idle.webm").write_bytes(b"v")
    monkeypatch.delenv("COMPANION_FAKE", raising=False)
    monkeypatch.delenv("COMPANION_MEMORY", raising=False)
    store = InMemoryHistory()
    store.save_facts({"使用者": "\n".join(f"- 事實{i:03d}" for i in range(100))})
    llm = SpyLLM()
    TestClient(create_app(llm=llm, persona="p", tts=Tts(), store=store, state_store=InMemoryState())).post("/chat", json={"message": "嗨"})
    assert "- 事實000" in llm.systems[-1] and "- 事實099" not in llm.systems[-1]
