"""Time awareness through the engine (spec Part 11). Everything here goes through TurnEngine with a
recording LLM, a fake wall clock and a fixed time zone — no new test seam."""
from calendar import timegm

import pytest

from companion.engine import TurnEngine
from companion.errors import LLMError
from companion.history import InMemoryHistory


def utc(year, month, day, hour=0, minute=0, second=0):
    return float(timegm((year, month, day, hour, minute, second)))


class WallClock:
    """Test double for the wall clock (epoch seconds) the engine reads."""

    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class RecordingLLM:
    """Streams a fixed reply and remembers exactly what it was sent."""

    def __init__(self, reply="[happy]好的。"):
        self.reply = reply
        self.calls = []

    def stream(self, system, messages):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        yield self.reply


class FailsOnce:
    """Raises an LLMError on the first call, then behaves like RecordingLLM."""

    def __init__(self, reply="[happy]好的。"):
        self.reply, self.calls, self._failed = reply, [], False

    def stream(self, system, messages):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        if not self._failed:
            self._failed = True
            raise LLMError("unavailable")
        yield self.reply


# ---- ticket 46: the engine stamps every saved turn with its own clock ----

def test_a_saved_turn_is_stamped_with_the_engines_clock():
    store, clock = InMemoryHistory(), WallClock(1_000_000.0)
    engine = TurnEngine(RecordingLLM(), persona="p", history_store=store, wall_clock=clock)
    list(engine.send("嗨"))
    clock.now += 500
    list(engine.send("再來"))
    assert store.load_times() == [1_000_000.0] * 2 + [1_000_500.0] * 2


def test_a_proactive_turn_is_stamped_too():
    store, clock = InMemoryHistory(), WallClock(2_000_000.0)
    engine = TurnEngine(RecordingLLM("[happy]在嗎?"), persona="p", history_store=store, wall_clock=clock)
    list(engine._attempt_proactive_stream())
    assert store.load_times() == [2_000_000.0] * 2


def test_a_failed_turn_leaves_nothing_behind_not_even_a_time():
    store, clock = InMemoryHistory(), WallClock(3_000_000.0)
    engine = TurnEngine(FailsOnce(), persona="p", history_store=store, wall_clock=clock)
    list(engine.send("嗨"))
    assert store.load() == [] and store.load_times() == []


# ---- ticket 47: the time block in the system prompt ----

from zoneinfo import ZoneInfo  # noqa: E402

TAIPEI = ZoneInfo("Asia/Taipei")  # UTC+8, no daylight saving: easy to reason about by hand
DAY = 86400.0


def time_cfg(**overrides):
    """A resolved time config as companion.config.resolve_time_config() would produce it."""
    cfg = {"enabled": True, "timezone": TAIPEI, "gap_marker_minutes": 30, "routine": [],
           "quiet_hours": {"enabled": False, "start": 0, "end": 7 * 60}}
    cfg.update(overrides)
    return cfg


def make_engine(now, history=(), llm=None, **engine_kwargs):
    """An engine whose clock reads `now`, with earlier turns [(user, assistant, at), ...] already stored."""
    store = InMemoryHistory()
    for user, assistant, at in history:
        store.append_turn(user, assistant, at=at)
    llm = llm or RecordingLLM()
    clock = WallClock(now)
    engine = TurnEngine(llm, persona="你是小晴", history_store=store, wall_clock=clock, **engine_kwargs)
    return engine, llm, store, clock


def system_of(engine_and_friends, message="嗨"):
    engine, llm, *_ = engine_and_friends
    list(engine.send(message))
    return llm.calls[-1]["system"]


def test_without_any_time_settings_the_system_prompt_is_exactly_what_it_always_was():
    baseline = system_of(make_engine(utc(2026, 10, 7, 13, 40)))
    assert "2026" not in baseline and "週" not in baseline


def test_with_the_master_switch_off_the_system_prompt_is_identical_to_having_no_settings():
    now = utc(2026, 10, 7, 13, 40)
    history = [("你好", "[happy]哈囉。", now - 3 * DAY)]
    without = system_of(make_engine(now, history))
    switched_off = system_of(make_engine(now, history, time_config=time_cfg(enabled=False)))
    assert switched_off == without


def test_when_on_the_prompt_says_the_local_date_weekday_and_time():
    # 13:40 UTC on Wednesday 2026-10-07 is 21:40 in Taipei
    system = system_of(make_engine(utc(2026, 10, 7, 13, 40), time_config=time_cfg()))
    assert "2026-10-07(週三) 21:40" in system


def test_the_displayed_time_follows_the_configured_time_zone():
    now = utc(2026, 10, 7, 13, 40)
    assert "2026-10-07(週三) 13:40" in system_of(make_engine(now, time_config=time_cfg(timezone=ZoneInfo("UTC"))))
    # Taipei is already into Thursday when it is 17:00 UTC on Wednesday
    assert "2026-10-08(週四) 01:00" in system_of(make_engine(utc(2026, 10, 7, 17, 0), time_config=time_cfg()))


def test_the_time_block_comes_after_the_memory_and_relationship_blocks():
    system = system_of(make_engine(utc(2026, 10, 7, 13, 40), time_config=time_cfg()))
    assert system.index("好感度") < system.index("2026-10-07")


def test_the_time_block_is_rebuilt_every_turn_not_remembered():
    engine, llm, store, clock = make_engine(utc(2026, 10, 7, 13, 40), time_config=time_cfg())
    list(engine.send("嗨"))
    clock.now += 3600
    list(engine.send("再來"))
    assert "21:40" in llm.calls[0]["system"] and "22:40" in llm.calls[1]["system"]
    assert all("2026" not in m["content"] for m in store.load())  # nothing about time leaks into the saved chat


@pytest.mark.parametrize("hour, minute, part", [
    (0, 0, "凌晨"), (4, 59, "凌晨"),
    (5, 0, "早上"), (10, 59, "早上"),
    (11, 0, "中午"), (12, 59, "中午"),
    (13, 0, "下午"), (17, 59, "下午"),
    (18, 0, "晚上"), (22, 59, "晚上"),
    (23, 0, "深夜"), (23, 59, "深夜"),
])
def test_the_part_of_the_day_is_named_with_exact_boundaries(hour, minute, part):
    # Build the instant from a Taipei wall-clock reading (UTC+8) so the expectation is by hand
    now = utc(2026, 10, 7, hour, minute) - 8 * 3600
    system = system_of(make_engine(now, time_config=time_cfg()))
    others = {"凌晨", "早上", "中午", "下午", "晚上", "深夜"} - {part}
    block = system[system.index("【時間資訊"):]
    assert f"{hour:02d}:{minute:02d}" in block and part in block
    assert not any(other in block for other in others)


TIERS = ["接續", "隔了一陣子", "過了半天以上", "隔了好幾天", "很久沒聊"]


def tier_in(system):
    block = system[system.index("【時間資訊"):]
    found = [t for t in TIERS if t in block]
    assert len(found) == 1, f"expected exactly one tier label, got {found}"
    return found[0]


def system_after(gap_seconds, **kw):
    """The prompt for a message sent `gap_seconds` after the last stored one."""
    last = utc(2026, 10, 4, 13, 12)  # Sunday evening in Taipei
    return system_of(make_engine(last + gap_seconds, [("嗨", "[happy]嗨。", last)], time_config=time_cfg(), **kw))


@pytest.mark.parametrize("gap, tier", [
    (0, "接續"), (29 * 60 + 59, "接續"),
    (30 * 60, "隔了一陣子"), (5 * 3600 + 59 * 60 + 59, "隔了一陣子"),
    (6 * 3600, "過了半天以上"), (23 * 3600 + 59 * 60 + 59, "過了半天以上"),
    (24 * 3600, "隔了好幾天"), (6 * DAY + 23 * 3600, "隔了好幾天"),
    (7 * DAY, "很久沒聊"), (90 * DAY, "很久沒聊"),
])
def test_the_gap_since_the_last_message_is_graded_in_five_levels_with_exact_boundaries(gap, tier):
    assert tier_in(system_after(gap)) == tier


def test_the_block_says_roughly_how_long_it_has_been():
    assert "40 分鐘" in system_after(40 * 60)
    assert "5 小時" in system_after(5 * 3600 + 20 * 60)
    assert "3 天" in system_after(3 * DAY + 5 * 3600)


def test_the_time_of_the_previous_message_is_shown_in_the_same_format():
    assert "上一則訊息的時間:2026-10-04(週日) 21:12" in system_after(3 * DAY)


def test_a_very_first_chat_has_no_gap_and_no_previous_message_time():
    system = system_of(make_engine(utc(2026, 10, 7, 13, 40), time_config=time_cfg()))
    block = system[system.index("【時間資訊"):]
    assert "2026-10-07(週三) 21:40" in block
    assert not any(t in block for t in TIERS) and "上一則訊息" not in block


def test_when_the_previous_time_is_unknown_the_gap_is_left_out_but_the_current_time_stays():
    now = utc(2026, 10, 7, 13, 40)
    system = system_of(make_engine(now, [("嗨", "[happy]嗨。", None)], time_config=time_cfg()))
    block = system[system.index("【時間資訊"):]
    assert "2026-10-07(週三) 21:40" in block
    assert not any(t in block for t in TIERS) and "上一則訊息" not in block


def test_a_clock_that_went_backwards_is_treated_as_no_time_passed():
    last = utc(2026, 10, 4, 13, 12)
    system = system_of(make_engine(last - 3600, [("嗨", "[happy]嗨。", last)], time_config=time_cfg()))
    assert tier_in(system) == "接續"
    assert "-" not in system[system.index("距離上一則訊息"):].split("\n")[0]


def test_the_block_tells_the_model_how_to_use_the_time_and_not_to_recite_it():
    block = system_after(2 * DAY)
    block = block[block.index("【時間資訊"):]
    assert "不要在回覆中複述" in block       # annotations are the system's, not something to say aloud
    assert "不要逐項報時" in block           # react naturally; only state the time if asked
    assert "久遠" in block                   # don't treat an old conversation as if it just happened


def test_a_proactive_turn_also_gets_the_time_block():
    now = utc(2026, 10, 7, 13, 40)
    engine, llm, *_ = make_engine(now, [("嗨", "[happy]嗨。", now - 3600)], llm=RecordingLLM("[happy]在嗎?"), time_config=time_cfg())
    list(engine._attempt_proactive_stream())
    system = llm.calls[-1]["system"]
    assert "2026-10-07(週三) 21:40" in system and "隔了一陣子" in system


def test_retrying_a_failed_turn_gives_the_model_exactly_the_same_time_information():
    now = utc(2026, 10, 7, 13, 40)
    llm = FailsOnce()
    engine, _, store, _ = make_engine(now, [("嗨", "[happy]嗨。", now - 2 * DAY)], llm=llm, time_config=time_cfg())
    list(engine.send("早"))      # fails
    list(engine.send("早"))      # the retry
    assert len(llm.calls) == 2 and llm.calls[0]["system"] == llm.calls[1]["system"]
    assert len(store.load()) == 4  # the original turn plus exactly one saved turn: the failure left no trace


def test_a_gap_under_a_minute_is_not_described_as_about_zero_minutes():
    system = system_after(20)
    assert "不到 1 分鐘" in system and "0 分鐘" not in system


# ---- ticket 48: gap annotations on the messages sent to the model ----

MINUTE, HOUR = 60.0, 3600.0
LAST = utc(2026, 10, 4, 13, 12)  # when the previous exchange happened


def sent_after(gap_seconds, message="早", cfg=None, history=None, **kw):
    """The messages the model received when `message` arrives `gap_seconds` after the last turn."""
    history = history if history is not None else [("嗨", "[happy]嗨。", LAST)]
    engine, llm, *_ = make_engine(LAST + gap_seconds, history, time_config=cfg or time_cfg(), **kw)
    list(engine.send(message))
    return llm.calls[-1]["messages"]


@pytest.mark.parametrize("gap, text", [
    (30 * MINUTE, "30 分鐘"),
    (59 * MINUTE + 59, "59 分鐘"),
    (60 * MINUTE, "1 小時"),
    (23 * HOUR + 59 * MINUTE, "23 小時"),
    (24 * HOUR, "1 天"),
    (13 * DAY, "13 天"),
    (14 * DAY, "2 週"),
    (55 * DAY, "7 週"),
    (56 * DAY, "1 個月"),
    (90 * DAY, "3 個月"),
])
def test_the_gap_before_a_new_message_is_written_in_the_largest_fitting_unit_rounded_down(gap, text):
    assert sent_after(gap)[-1]["content"] == f"(距上一句約 {text})\n早"


def test_the_threshold_is_inclusive_and_one_second_short_gets_no_note():
    assert sent_after(30 * MINUTE)[-1]["content"].startswith("(距上一句")
    assert sent_after(30 * MINUTE - 1)[-1]["content"] == "早"


def test_the_threshold_comes_from_the_settings():
    cfg = time_cfg(gap_marker_minutes=60)
    assert sent_after(45 * MINUTE, cfg=cfg)[-1]["content"] == "早"
    assert sent_after(60 * MINUTE, cfg=cfg)[-1]["content"] == "(距上一句約 1 小時)\n早"
    short = time_cfg(gap_marker_minutes=5)
    assert sent_after(6 * MINUTE, cfg=short)[-1]["content"] == "(距上一句約 6 分鐘)\n早"


def test_earlier_messages_in_the_history_are_annotated_too_but_only_the_users_never_the_characters():
    history = [
        ("第一天", "[happy]第一天的回覆。", utc(2026, 10, 1, 13, 0)),
        ("三天後", "[happy]三天後的回覆。", utc(2026, 10, 4, 13, 0)),
    ]
    now = utc(2026, 10, 4, 13, 10)  # ten minutes after the second stored turn
    engine, llm, *_ = make_engine(now, history, time_config=time_cfg())
    list(engine.send("十分鐘後"))
    sent = llm.calls[-1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user", "assistant", "user"]
    assert sent[0]["content"] == "第一天"                        # nothing before it: no note
    assert sent[1]["content"] == "[happy]第一天的回覆。"          # the character's lines are never touched
    assert sent[2]["content"] == "(距上一句約 3 天)\n三天後"
    assert sent[3]["content"] == "[happy]三天後的回覆。"
    assert sent[4]["content"] == "十分鐘後"                       # only 10 minutes: below the threshold


def test_the_first_message_in_the_window_is_measured_against_the_one_before_it_even_if_that_was_cut_off():
    history = [
        ("很久以前", "[happy]嗯。", utc(2026, 9, 1, 8, 0)),
        ("一個月後", "[happy]好。", utc(2026, 10, 3, 8, 0)),
    ]
    now = utc(2026, 10, 3, 8, 5)
    engine, llm, *_ = make_engine(now, history, time_config=time_cfg(), max_turns=1)  # window = the last exchange only
    list(engine.send("五分鐘後"))
    sent = llm.calls[-1]["messages"]
    assert [m["content"] for m in sent] == ["(距上一句約 4 週)\n一個月後", "[happy]好。", "五分鐘後"]


def test_messages_already_folded_into_the_long_term_summary_still_count_as_the_one_before():
    store = InMemoryHistory()
    store.append_turn("舊的", "[happy]舊答。", at=utc(2026, 9, 18, 8, 0))
    store.append_turn("新的", "[happy]新答。", at=utc(2026, 10, 3, 8, 0))
    store.apply_fold([], None, 2)  # the first exchange has been folded away
    llm = RecordingLLM()
    engine = TurnEngine(llm, persona="p", history_store=store, wall_clock=WallClock(utc(2026, 10, 3, 8, 1)),
                        summarize=True, background=lambda fn: None, time_config=time_cfg())
    list(engine.send("嗨"))
    assert llm.calls[-1]["messages"][0]["content"] == "(距上一句約 2 週)\n新的"


def test_no_note_when_either_time_is_unknown():
    history = [("沒時間", "[happy]嗯。", None), ("有時間", "[happy]好。", utc(2026, 10, 3, 8, 0))]
    engine, llm, *_ = make_engine(utc(2026, 10, 9, 8, 0), history, time_config=time_cfg())
    list(engine.send("六天後"))
    contents = [m["content"] for m in llm.calls[-1]["messages"]]
    assert contents[0] == "沒時間"                       # nothing before it
    assert contents[2] == "有時間"                       # its previous message has no time
    assert contents[4] == "(距上一句約 6 天)\n六天後"     # but this one is fully known


def test_a_very_first_message_has_no_note():
    engine, llm, *_ = make_engine(utc(2026, 10, 7, 13, 40), [], time_config=time_cfg())
    list(engine.send("嗨"))
    assert llm.calls[-1]["messages"] == [{"role": "user", "content": "嗨"}]


def test_the_characters_own_made_up_prompt_is_never_annotated_in_history_or_as_the_current_message():
    from companion.engine import PROACTIVE_PROMPT
    history = [("嗨", "[happy]嗨。", utc(2026, 10, 1, 8, 0)),
               (PROACTIVE_PROMPT, "[happy]在嗎?", utc(2026, 10, 4, 8, 0))]
    engine, llm, _store, clock = make_engine(utc(2026, 10, 7, 8, 0), history, llm=RecordingLLM("[happy]嗨!"), time_config=time_cfg())
    list(engine._attempt_proactive_stream())               # as the current message
    assert llm.calls[-1]["messages"][2]["content"] == PROACTIVE_PROMPT  # in history: no note either
    assert llm.calls[-1]["messages"][-1]["content"] == PROACTIVE_PROMPT
    clock.now += 2 * DAY
    list(engine.send("我回來了"))                           # a real message afterwards is annotated normally
    assert llm.calls[-1]["messages"][-1]["content"] == "(距上一句約 2 天)\n我回來了"


def test_an_image_message_gets_the_note_in_front_of_the_image_marker_in_history_and_for_the_current_one():
    from companion.engine import IMAGE_MARKER
    from companion.engine import UserImage
    history = [("嗨", "[happy]嗨。", utc(2026, 10, 1, 8, 0)),
               (IMAGE_MARKER + "看這張", "[happy]好看。", utc(2026, 10, 4, 8, 0))]
    engine, llm, *_ = make_engine(utc(2026, 10, 7, 8, 0), history, time_config=time_cfg())
    list(engine.send("這張呢", image=UserImage(b"\x89PNG", "image/png")))
    sent = llm.calls[-1]["messages"]
    assert sent[2]["content"] == "(距上一句約 3 天)\n" + IMAGE_MARKER + "看這張"
    assert sent[-1]["content"] == "(距上一句約 3 天)\n這張呢" and sent[-1]["image"].mime_type == "image/png"


def test_what_gets_saved_is_always_exactly_what_the_user_wrote_even_when_the_model_was_sent_a_note():
    now = utc(2026, 10, 7, 8, 0)
    engine, llm, store, _ = make_engine(now, [("嗨", "[happy]嗨。", now - 3 * DAY)], time_config=time_cfg())
    list(engine.send("我回來了"))
    assert llm.calls[-1]["messages"][-1]["content"].startswith("(距上一句約 3 天)")   # the model did see it
    assert [m["content"] for m in store.load()] == ["嗨", "[happy]嗨。", "我回來了", "[happy]好的。"]
    assert not any("距上一句" in m["content"] for m in store.load())


def test_annotating_never_alters_the_messages_the_store_hands_out():
    now = utc(2026, 10, 7, 8, 0)
    engine, llm, store, _ = make_engine(now, [("一", "[happy]答一。", now - 9 * DAY), ("二", "[happy]答二。", now - 3 * DAY)],
                                        time_config=time_cfg())
    before = store.load()
    list(engine.send("三"))
    assert store.load()[: len(before)] == before


def test_after_a_restart_the_database_still_holds_only_the_users_own_words_and_notes_are_recomputed(tmp_path):
    from companion.history import SqliteHistory
    db = tmp_path / "history.db"
    t0 = utc(2026, 10, 1, 8, 0)
    first = TurnEngine(RecordingLLM(), persona="p", history_store=SqliteHistory(db), wall_clock=WallClock(t0), time_config=time_cfg())
    list(first.send("週四早安"))
    # the app is closed; three days later it is started again on the same database
    llm = RecordingLLM()
    second = TurnEngine(llm, persona="p", history_store=SqliteHistory(db), wall_clock=WallClock(t0 + 3 * DAY), time_config=time_cfg())
    list(second.send("週日早安"))
    sent = llm.calls[-1]["messages"]
    assert sent[-1]["content"] == "(距上一句約 3 天)\n週日早安"
    assert [m["content"] for m in SqliteHistory(db).load() if m["role"] == "user"] == ["週四早安", "週日早安"]


def test_changing_the_threshold_changes_how_the_same_old_history_is_annotated():
    now = utc(2026, 10, 7, 8, 0)
    history = [("甲", "[happy]答。", now - 4 * HOUR), ("乙", "[happy]答。", now - 3 * HOUR)]
    loose = [m["content"] for m in make_sent(now, history, time_cfg(gap_marker_minutes=30)) if m["role"] == "user"]
    strict = [m["content"] for m in make_sent(now, history, time_cfg(gap_marker_minutes=600)) if m["role"] == "user"]
    assert loose[-1].startswith("(距上一句約 3 小時)") and strict[-1] == "嗨"


def make_sent(now, history, cfg):
    engine, llm, *_ = make_engine(now, history, time_config=cfg)
    list(engine.send("嗨"))
    return llm.calls[-1]["messages"]


def test_with_the_master_switch_off_the_messages_are_exactly_what_they_always_were():
    now = utc(2026, 10, 7, 8, 0)
    history = [("甲", "[happy]答。", now - 9 * DAY), ("乙", "[happy]答。", now - 3 * DAY)]
    assert make_sent(now, history, time_cfg(enabled=False)) == make_sent(now, history, None)
    assert not any("距上一句" in m["content"] for m in make_sent(now, history, time_cfg(enabled=False)))


def test_notes_do_not_use_up_the_history_windows_turn_allowance():
    now = utc(2026, 10, 7, 8, 0)
    history = [(f"問{i}", f"[happy]答{i}。", now - (10 - i) * DAY) for i in range(5)]
    engine, llm, *_ = make_engine(now, history, time_config=time_cfg(), max_turns=2)
    list(engine.send("新的"))
    assert len(llm.calls[-1]["messages"]) == 2 * 2 + 1   # the last 2 exchanges + the new message, as ever


def test_the_characters_lines_are_never_annotated_even_when_a_long_gap_precedes_one(tmp_path):
    import sqlite3
    from contextlib import closing
    from companion.history import SqliteHistory
    db = tmp_path / "history.db"
    store = SqliteHistory(db)
    with closing(sqlite3.connect(db)) as conn, conn:  # a user line, and the character's reply two days LATER
        conn.executemany("INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)", [
            ("user", "晚安", "2026-10-01 14:00:00"),
            ("assistant", "[happy]晚安。(兩天後才補的回覆)", "2026-10-03 14:00:00"),
        ])
    llm = RecordingLLM()
    engine = TurnEngine(llm, persona="p", history_store=store, wall_clock=WallClock(utc(2026, 10, 3, 14, 5)), time_config=time_cfg())
    list(engine.send("嗨"))
    assert llm.calls[-1]["messages"][1] == {"role": "assistant", "content": "[happy]晚安。(兩天後才補的回覆)"}


# ---- ticket 49: the daily routine ----

def at_taipei(day, hour, minute=0):
    """The epoch time of a Taipei (UTC+8) wall-clock reading in October 2026, worked out by hand."""
    return utc(2026, 10, day, hour, minute) - 8 * HOUR


def entry(name, start, end):
    h1, m1 = divmod(start, 100)
    h2, m2 = divmod(end, 100)
    return {"name": name, "hint": f"HINT-{name}", "start": h1 * 60 + m1, "end": h2 * 60 + m2}


ROUTINE = [entry("早餐", 700, 900), entry("午餐", 1200, 1330), entry("深夜", 2300, 700)]


def hints_in(system):
    return sorted({f"HINT-{e['name']}" for e in ROUTINE + [entry("B", 1000, 1200), entry("A", 800, 1100)] if f"HINT-{e['name']}" in system})


def first_chat_system(now, routine=ROUTINE, **cfg):
    return system_of(make_engine(now, [], time_config=time_cfg(routine=routine, **cfg)))


@pytest.mark.parametrize("hour, minute, expected", [
    (6, 59, ["HINT-深夜"]), (7, 0, ["HINT-早餐"]), (8, 59, ["HINT-早餐"]), (9, 0, []),
    (11, 59, []), (12, 0, ["HINT-午餐"]), (13, 29, ["HINT-午餐"]), (13, 30, []),
    (22, 59, []), (23, 0, ["HINT-深夜"]), (23, 59, ["HINT-深夜"]), (0, 0, ["HINT-深夜"]), (3, 30, ["HINT-深夜"]),
])
def test_a_time_falls_in_a_period_from_its_start_up_to_but_not_including_its_end(hour, minute, expected):
    assert hints_in(first_chat_system(at_taipei(7, hour, minute))) == expected


def test_when_periods_overlap_the_one_listed_first_wins():
    routine = [entry("B", 1000, 1200), entry("A", 800, 1100)]
    assert hints_in(first_chat_system(at_taipei(7, 10, 30), routine)) == ["HINT-B"]
    assert hints_in(first_chat_system(at_taipei(7, 8, 30), routine)) == ["HINT-A"]


def test_an_empty_routine_or_a_switched_off_feature_gives_no_hints_at_all():
    assert hints_in(first_chat_system(at_taipei(7, 12, 10), routine=[])) == []
    assert hints_in(system_of(make_engine(at_taipei(7, 12, 10), [], time_config=time_cfg(enabled=False, routine=ROUTINE)))) == []


def test_the_hint_is_the_periods_own_text_placed_with_the_other_time_information():
    system = first_chat_system(at_taipei(7, 12, 10))
    assert "HINT-午餐" in system[system.index("【時間資訊"):]
    assert "午餐" in system


def lunch_hint_on_each_turn(times_in_taipei, routine=ROUTINE, history=None, **kw):
    """Whether HINT-午餐 (or whichever hint) shows up on each of a series of consecutive turns."""
    engine, llm, _store, clock = make_engine(times_in_taipei[0], history or [], time_config=time_cfg(routine=routine), **kw)
    shown = []
    for t in times_in_taipei:
        clock.now = t
        list(engine.send("嗯"))
        shown.append(hints_in(llm.calls[-1]["system"]))
    return shown


def test_the_hint_appears_only_on_the_first_turn_after_entering_a_period():
    shown = lunch_hint_on_each_turn([at_taipei(7, 12, 5), at_taipei(7, 12, 20), at_taipei(7, 13, 10)])
    assert shown == [["HINT-午餐"], [], []]


def test_the_next_day_the_same_period_counts_as_new_again():
    shown = lunch_hint_on_each_turn([at_taipei(7, 12, 5), at_taipei(7, 12, 30), at_taipei(8, 12, 5)])
    assert shown == [["HINT-午餐"], [], ["HINT-午餐"]]


def test_coming_from_outside_any_period_or_from_another_period_counts_as_entering():
    shown = lunch_hint_on_each_turn([at_taipei(7, 8, 50), at_taipei(7, 10, 0), at_taipei(7, 12, 0)])
    assert shown == [["HINT-早餐"], [], ["HINT-午餐"]]                  # 早餐 -> (none) -> 午餐
    # straight from one period into the next, with no gap between them
    back_to_back = [entry("早餐", 700, 900), entry("午餐", 900, 1330)]
    shown = lunch_hint_on_each_turn([at_taipei(7, 8, 30), at_taipei(7, 9, 30)], routine=back_to_back)
    assert shown == [["HINT-早餐"], ["HINT-午餐"]]


def test_a_period_that_crosses_midnight_is_one_period_for_the_whole_night():
    night = [at_taipei(7, 23, 30), at_taipei(8, 1, 0), at_taipei(8, 6, 59)]
    assert lunch_hint_on_each_turn(night) == [["HINT-深夜"], [], []]       # 23:30, then 01:00 and 06:59 next day: same night


def test_the_same_clock_time_on_two_different_nights_is_two_separate_periods():
    nights = [at_taipei(7, 23, 30), at_taipei(8, 23, 30)]
    assert lunch_hint_on_each_turn(nights) == [["HINT-深夜"], ["HINT-深夜"]]


def test_the_very_first_chat_and_an_unknown_previous_time_both_count_as_entering():
    assert lunch_hint_on_each_turn([at_taipei(7, 12, 5)]) == [["HINT-午餐"]]
    unknown = [("嗨", "[happy]嗨。", None)]
    assert lunch_hint_on_each_turn([at_taipei(7, 12, 5)], history=unknown) == [["HINT-午餐"]]


def test_a_failed_turn_leaves_no_trace_so_the_retry_gets_the_same_hint():
    llm = FailsOnce()
    engine, *_ = make_engine(at_taipei(7, 12, 5), [], llm=llm, time_config=time_cfg(routine=ROUTINE))
    list(engine.send("嗨"))   # fails
    list(engine.send("嗨"))   # retry
    assert "HINT-午餐" in llm.calls[0]["system"] and "HINT-午餐" in llm.calls[1]["system"]
    assert llm.calls[0]["system"] == llm.calls[1]["system"]


def test_a_proactive_turn_always_gets_the_current_periods_hint_even_mid_period():
    history = [("嗨", "[happy]嗨。", at_taipei(7, 12, 5))]               # we already talked in this very lunch period
    engine, llm, *_ = make_engine(at_taipei(7, 12, 40), history, llm=RecordingLLM("[happy]吃飯了嗎?"), time_config=time_cfg(routine=ROUTINE))
    list(engine._attempt_proactive_stream())
    assert "HINT-午餐" in llm.calls[-1]["system"]
    engine2, llm2, *_ = make_engine(at_taipei(7, 12, 40), history, time_config=time_cfg(routine=ROUTINE))
    list(engine2.send("嗨"))                                              # a normal turn there stays quiet
    assert "HINT-午餐" not in llm2.calls[-1]["system"]


def test_hints_are_never_saved_into_the_conversation():
    engine, llm, store, _ = make_engine(at_taipei(7, 12, 5), [], time_config=time_cfg(routine=ROUTINE))
    list(engine.send("嗨"))
    assert "HINT" not in " ".join(m["content"] for m in store.load())


# ---- ticket 50: quiet hours stop unprompted speech ----

class FakeScheduler:
    """Test double for the delayed-call boundary: records what was scheduled; the test fires a job
    by calling its captured function, so nothing ever runs on its own."""

    def __init__(self):
        self.scheduled = []

    def __call__(self, delay_s, fn):
        self.scheduled.append((delay_s, fn))
        return lambda: None

    def fire_latest(self):
        self.scheduled[-1][1]()


DEFAULT_QUIET = {"enabled": True, "start": 0, "end": 7 * 60}


def proactive_setup(now, quiet=DEFAULT_QUIET, **cfg):
    scheduler, sent, store, clock, llm = FakeScheduler(), [], InMemoryHistory(), WallClock(now), RecordingLLM("[happy]在嗎?")
    store.save_affection(70, at=now)
    engine = TurnEngine(llm, persona="p", history_store=store, wall_clock=clock, scheduler=scheduler,
                        on_proactive=sent.append, proactive_idle_range_s=(600, 1200),
                        time_config=time_cfg(quiet_hours=quiet, **cfg))
    engine.set_proactive(True)
    return engine, scheduler, sent, store, llm


def fires_at_taipei(hour, minute=0, quiet=DEFAULT_QUIET, **cfg):
    """Fire the pending proactive attempt at a Taipei wall-clock time; returns (spoke, scheduler, store, llm)."""
    engine, scheduler, sent, store, llm = proactive_setup(at_taipei(7, hour, minute), quiet, **cfg)
    scheduler.fire_latest()
    return bool(sent), scheduler, store, llm


@pytest.mark.parametrize("hour, minute, silent", [
    (23, 59, False), (0, 0, True), (3, 0, True), (6, 59, True), (7, 0, False), (12, 0, False),
])
def test_the_default_quiet_hours_midnight_to_seven_keep_the_character_from_speaking_up(hour, minute, silent):
    spoke, *_ = fires_at_taipei(hour, minute)
    assert spoke is (not silent)


@pytest.mark.parametrize("hour, minute, silent", [
    (22, 59, False), (23, 0, True), (2, 0, True), (6, 59, True), (7, 0, False),
])
def test_quiet_hours_can_cross_midnight(hour, minute, silent):
    spoke, *_ = fires_at_taipei(hour, minute, quiet={"enabled": True, "start": 23 * 60, "end": 7 * 60})
    assert spoke is (not silent)


def test_a_skipped_attempt_touches_nothing_and_just_schedules_the_next_one():
    spoke, scheduler, store, llm = fires_at_taipei(3, 0)
    assert spoke is False
    assert llm.calls == []                              # the model is never even asked
    assert store.load() == [] and store.load_times() == []
    assert store.load_affection() == 70                 # nothing moved
    assert len(scheduler.scheduled) == 2                # the original attempt + exactly one new one
    assert 600 <= scheduler.scheduled[-1][0] <= 1200    # the usual random idle wait


def test_after_a_skipped_attempt_the_next_one_outside_quiet_hours_works_normally():
    engine, scheduler, sent, store, llm = proactive_setup(at_taipei(7, 3, 0))
    scheduler.fire_latest()
    assert sent == []
    engine._wall_clock.now = at_taipei(7, 8, 0)
    scheduler.fire_latest()
    assert sent and len(llm.calls) == 1


def test_quiet_hours_are_judged_in_the_configured_time_zone():
    now = utc(2026, 10, 7, 20, 0)  # 04:00 in Taipei (quiet), 20:00 in UTC (not quiet)
    for tz, silent in ((TAIPEI, True), (ZoneInfo("UTC"), False)):
        engine, scheduler, sent, *_ = proactive_setup(now, timezone=tz)
        scheduler.fire_latest()
        assert (sent == []) is silent


def test_switching_quiet_hours_off_or_the_whole_feature_off_means_she_may_speak_at_any_hour():
    assert fires_at_taipei(3, 0, quiet={"enabled": False, "start": 0, "end": 420})[0] is True
    assert fires_at_taipei(3, 0, enabled=False)[0] is True


def test_the_user_can_still_chat_during_quiet_hours():
    engine, scheduler, sent, store, llm = proactive_setup(at_taipei(7, 3, 0))
    list(engine.send("睡不著"))
    assert len(store.load()) == 2 and len(llm.calls) == 1


# ---- ticket 51: dates in the long-term memory summary ----

VALID_SUMMARY = {"events": [{"date": "2026-10-01", "text": "聊過貓"}],
                 "facts": {"user": ["使用者喜歡貓"], "shared": ["聊過貓和咖啡"], "self": [], "followups": []}}


class SummarizingLLM(RecordingLLM):
    """Chats like RecordingLLM, and also answers the memory summary's structured call."""

    def __init__(self, reply="[happy]好。"):
        super().__init__(reply)
        self.summary_requests = []

    def generate_structured(self, system, messages, schema):
        self.summary_requests.append({"system": system, "request": messages[0]["content"]})
        return VALID_SUMMARY


def summarizing_engine(cfg, history=(), llm=None):
    store = InMemoryHistory()
    for user, assistant, at in history:
        store.append_turn(user, assistant, at=at)
    llm, clock = llm or SummarizingLLM(), WallClock(0.0)
    engine = TurnEngine(llm, persona="p", history_store=store, wall_clock=clock, summarize=True, max_turns=3,
                        summary_batch=2, background=lambda fn: fn(), time_config=cfg)
    return engine, llm, store, clock


def chat_on_days(engine, clock, days):
    """One turn per entry of `days` (each a Taipei date-time); returns nothing, the LLM records it all."""
    for n, when in enumerate(days):
        clock.now = when
        list(engine.send(f"話{n + 1}"))


def new_conversation_lines(llm, call=0):
    text = llm.summary_requests[call]["request"]
    return text.split("【要併入的新對話】\n")[1].split("\n")


def test_every_message_sent_for_summarising_carries_the_date_it_was_written():
    engine, llm, _, clock = summarizing_engine(time_cfg())
    chat_on_days(engine, clock, [at_taipei(1, 9), at_taipei(1, 21), at_taipei(3, 8), at_taipei(4, 8)])
    assert new_conversation_lines(llm) == [
        "[2026-10-01 週四] 使用者:話1", "[2026-10-01 週四] 角色:好。",
        "[2026-10-01 週四] 使用者:話2", "[2026-10-01 週四] 角色:好。",
    ]


def test_dates_follow_the_configured_time_zone_not_utc():
    # 20:30 UTC on 1 Oct is already the early hours of 2 Oct (Friday) in Taipei
    engine, llm, _, clock = summarizing_engine(time_cfg())
    chat_on_days(engine, clock, [utc(2026, 10, 1, 20, 30)] * 4)
    assert new_conversation_lines(llm)[0] == "[2026-10-02 週五] 使用者:話1"
    engine, llm, _, clock = summarizing_engine(time_cfg(timezone=ZoneInfo("UTC")))
    chat_on_days(engine, clock, [utc(2026, 10, 1, 20, 30)] * 4)
    assert new_conversation_lines(llm)[0] == "[2026-10-01 週四] 使用者:話1"


def test_each_batch_is_dated_with_its_own_messages_not_with_someone_elses():
    engine, llm, _, clock = summarizing_engine(time_cfg())
    days = [at_taipei(d, 9) for d in (1, 2, 3, 4, 5, 6)]  # six turns, one per day
    chat_on_days(engine, clock, days)
    assert len(llm.summary_requests) == 2
    assert new_conversation_lines(llm, 0)[0::2] == ["[2026-10-01 週四] 使用者:話1", "[2026-10-02 週五] 使用者:話2"]
    assert new_conversation_lines(llm, 1)[0::2] == ["[2026-10-03 週六] 使用者:話3", "[2026-10-04 週日] 使用者:話4"]


def test_a_message_with_an_unknown_time_is_sent_as_it_always_was_next_to_dated_ones():
    history = [("舊一", "[happy]舊答。", None), ("舊二", "[happy]舊答。", at_taipei(1, 9))]
    engine, llm, _, clock = summarizing_engine(time_cfg(), history)
    chat_on_days(engine, clock, [at_taipei(2, 9), at_taipei(3, 9)])
    lines = new_conversation_lines(llm)
    assert lines[0] == "使用者:舊一" and lines[1] == "角色:舊答。"
    assert lines[2] == "[2026-10-01 週四] 使用者:舊二"


def test_the_summariser_is_told_to_record_events_with_absolute_dates():
    engine, llm, _, clock = summarizing_engine(time_cfg())
    chat_on_days(engine, clock, [at_taipei(d, 9) for d in (1, 2, 3, 4)])
    system = llm.summary_requests[0]["system"]
    assert "絕對日期" in system and "下週" in system        # and what to do with relative wording
    assert "SUMMARY" not in system and "你是記憶整理助手" in system  # the original instructions are all still there


def test_with_the_master_switch_off_the_summary_request_is_exactly_what_it_always_was():
    days = [at_taipei(d, 9) for d in (1, 2, 3, 4)]
    off_engine, off_llm, _, off_clock = summarizing_engine(time_cfg(enabled=False))
    chat_on_days(off_engine, off_clock, days)
    plain_engine, plain_llm, _, plain_clock = summarizing_engine(None)
    chat_on_days(plain_engine, plain_clock, days)
    assert off_llm.summary_requests == plain_llm.summary_requests
    assert "絕對日期" not in off_llm.summary_requests[0]["system"]
    assert "[2026" not in off_llm.summary_requests[0]["request"]


def test_the_existing_long_term_memory_is_handed_over_unchanged_to_be_folded_into():
    engine, llm, store, clock = summarizing_engine(time_cfg())
    store.save_facts({"使用者": "- 使用者住在台北", "更早的摘要": "早先聊過旅行"})
    chat_on_days(engine, clock, [at_taipei(d, 9) for d in (1, 2, 3, 4)])
    request = llm.summary_requests[0]["request"]
    assert "〔更早的摘要〕\n早先聊過旅行" in request and "〔使用者〕\n- 使用者住在台北" in request


def test_the_fold_is_saved_in_the_layered_memory_and_the_chat_history_has_no_dates_in_it():
    engine, llm, store, clock = summarizing_engine(time_cfg())
    chat_on_days(engine, clock, [at_taipei(d, 9) for d in (1, 2, 3, 4)])
    assert store.load_facts() == {"使用者": "- 使用者喜歡貓", "共同經歷": "- 聊過貓和咖啡"}
    assert store.load_fold_progress() == 4
    assert not any("[2026" in m["content"] for m in store.load())


def test_a_skipped_attempt_also_leaves_the_last_interaction_time_alone():
    engine, scheduler, sent, store, llm = proactive_setup(at_taipei(7, 3, 0))
    last_seen = store.load_last_interaction()
    scheduler.fire_latest()
    assert store.load_last_interaction() == last_seen and sent == []


def test_with_proactive_speech_switched_off_quiet_hours_change_nothing():
    scheduler = FakeScheduler()
    store = InMemoryHistory()
    engine = TurnEngine(RecordingLLM(), persona="p", history_store=store, wall_clock=WallClock(at_taipei(7, 3, 0)),
                        scheduler=scheduler, time_config=time_cfg(quiet_hours=DEFAULT_QUIET))
    assert scheduler.scheduled == []            # never turned on: nothing is ever scheduled
    engine.set_proactive(True)
    engine.set_proactive(False)
    assert len(scheduler.scheduled) == 1        # exactly what turning it on once did, as before
