"""Remembering something that is not in front of her (spec Part 12, section 8, ticket 82): each turn the user's
message is matched, locally and without another model call, against the older conversation, the journal and any
facts that did not fit into the always-present memory; the few best matches are shown to her."""
import re
from datetime import timedelta

import pytest

from companion import timesense
from companion.engine import PROACTIVE_TRIGGER, TurnEngine
from companion.history import InMemoryHistory

NOW = 1_800_000_000.0
DAY = 86400.0
LIMITS = {"long_term_max_chars": 2000, "recent_notes_max_chars": 600, "retrieval_k": 3, "retrieval_snippet_chars": 200,
          "retrieval_min_message_chars": 3, "archive_scan_limit": 20000, "retrieval_min_score": 0.6}


class SpyLLM:
    def __init__(self):
        self.systems, self.calls = [], 0

    def stream(self, system, messages):
        self.calls += 1
        self.systems.append(system)
        yield "好。"

    def generate_structured(self, *args):
        self.calls += 1
        raise AssertionError("retrieval must never make another model call")


def day(offset, epoch=NOW):
    return f"{timesense.local_datetime(epoch, None) + timedelta(days=offset):%Y-%m-%d}"


def ask(store, message, memory=True, limits=None, max_turns=3, **kwargs):
    llm = SpyLLM()
    engine = TurnEngine(llm, persona="p", history_store=store, summarize=memory, max_turns=max_turns, wall_clock=lambda: NOW,
                        memory_settings=dict(LIMITS, **(limits or {})), **kwargs)
    list(engine.send(message))
    return llm.systems[-1], llm


def old_store(*turns, days_ago=90):
    """A history in which `turns` happened long ago, followed by a few unrelated recent chats."""
    store = InMemoryHistory()
    for i, (user, assistant) in enumerate(turns):
        store.append_turn(user, assistant, at=NOW - (days_ago - i) * DAY)
    for n in range(3):
        store.append_turn(f"最近的閒聊{n}", "[neutral]嗯嗯。", at=NOW - 3600 + n)
    return store


def block(system):
    assert "【可能相關的記憶】" in system
    return system.split("【可能相關的記憶】")[1].split("\n\n【")[0]


# ---- finding it ---------------------------------------------------------------------------------------

def test_something_said_long_ago_comes_back_with_its_date_when_it_comes_up_again():
    store = old_store(("我下週三要去面試,好緊張", "[neutral]加油喔。"))
    system, _ = ask(store, "上次說的面試怎麼樣了")
    found = block(system)
    assert "面試" in found and day(-90) in found


def test_a_two_character_word_is_enough_to_find_it():
    store = old_store(("我養了一隻叫小橘的貓", "[neutral]好可愛。"))
    system, _ = ask(store, "小橘啦")
    assert "小橘" in block(system)


def test_what_she_herself_said_can_be_found_too_and_is_marked_as_hers():
    store = old_store(("你今天想做什麼", "[neutral]我想去爬山看日出。"))
    system, _ = ask(store, "你上次說想爬山")
    assert "你說" in block(system) and "爬山看日出" in block(system)


def test_the_journal_is_searched_beyond_today_and_yesterday_but_not_in_them():
    def journal_store():
        store = old_store()
        store.append_events([{"date": day(-30), "time": None, "kind": "事件", "text": "角色買了一件紅洋裝"},
                             {"date": day(0), "time": None, "kind": "事件", "text": "角色今天去了咖啡廳"}])
        return store

    system, _ = ask(journal_store(), "那件紅洋裝呢")
    assert "紅洋裝" in block(system) and day(-30) in block(system)
    system, _ = ask(journal_store(), "那間咖啡廳呢")        # today's journal is already in the prompt for good
    assert "【可能相關的記憶】" not in system and "角色今天去了咖啡廳" in system


def facts_store():
    store = old_store()
    store.save_facts({"使用者": "- 住在台北\n- 養了一隻貓叫小橘\n- 喜歡爬山"})
    return store


def test_facts_that_did_not_fit_into_the_always_present_memory_can_still_be_found():
    system, _ = ask(facts_store(), "小橘還好嗎", limits={"long_term_max_chars": 12})
    assert "小橘" in block(system) and "- 住在台北" in system


def test_facts_that_are_already_in_the_always_present_memory_are_not_looked_up_again():
    system, _ = ask(facts_store(), "小橘還好嗎")
    assert "【可能相關的記憶】" not in system and "- 養了一隻貓叫小橘" in system


# ---- what is not looked at ----------------------------------------------------------------------------

def test_what_is_still_in_the_recent_conversation_is_not_dug_up_again():
    store = InMemoryHistory()
    store.append_turn("我下週三要去面試", "[neutral]加油喔。", at=NOW - 600)
    system, _ = ask(store, "面試的事你覺得呢")
    assert "【可能相關的記憶】" not in system


def test_nothing_unrelated_is_brought_up():
    store = old_store(("我下週三要去面試", "[neutral]加油喔。"))
    system, _ = ask(store, "今天天氣真好呢")
    assert "【可能相關的記憶】" not in system


def test_everyday_words_alone_do_not_count_as_a_match():
    store = old_store(("我們一起去海邊玩吧,我們好久沒去了", "[neutral]好啊我們去。"))
    system, _ = ask(store, "我們去吃飯吧")
    assert "【可能相關的記憶】" not in system


def test_a_very_short_message_is_not_searched():
    store = old_store(("我下週三要去面試", "[neutral]加油喔。"))
    system, _ = ask(store, "面試")                         # 2 characters: under the 3-character minimum
    assert "【可能相關的記憶】" not in system


def test_a_proactive_turn_is_not_searched_even_when_her_own_prompt_happens_to_match_something():
    store = old_store(("你自己選擇在這個時間點開口", "[neutral]好。"))   # words the made-up prompt also contains
    system, _ = ask(store, PROACTIVE_TRIGGER)
    assert "【可能相關的記憶】" not in system


def test_only_the_most_recent_messages_up_to_the_scan_limit_are_searched():
    # 2 old messages + 6 recent ones (the recent window) + the one being sent now
    system, _ = ask(old_store(("我下週三要去面試", "[neutral]加油喔。")), "上次說的面試呢", limits={"archive_scan_limit": 6})
    assert "【可能相關的記憶】" not in system
    system, _ = ask(old_store(("我下週三要去面試", "[neutral]加油喔。")), "上次說的面試呢", limits={"archive_scan_limit": 8})
    assert "面試" in block(system)


# ---- how much, and the cost ---------------------------------------------------------------------------------

def test_at_most_k_matches_are_shown_best_first_and_each_cut_to_the_snippet_length():
    store = old_store(*[(f"第{i}次聊到小橘貓咪," + "很長的一段話" * 30, "[neutral]嗯。") for i in range(6)])
    system, _ = ask(store, "小橘貓咪最近怎麼了", limits={"retrieval_k": 2, "retrieval_snippet_chars": 40})
    lines = [line for line in block(system).splitlines() if line.startswith("- ")]
    snippets = [re.split("[:\uff1a]", line, maxsplit=1)[1] for line in lines]
    assert len(lines) == 2 and all(0 < len(snippet) <= 40 for snippet in snippets)


def test_one_rare_word_outranks_two_common_ones():
    # six conversations about coffee beans (both pairs "咖啡" and "啡豆" are everywhere) and one about diving
    store = old_store(*[(f"第{i}次聊到咖啡豆", "[neutral]好。") for i in range(6)], ("聊到潛水", "[neutral]好。"))
    system, _ = ask(store, "咖啡豆潛水", limits={"retrieval_k": 1})
    assert "潛水" in block(system)


def test_of_two_equally_good_matches_the_more_recent_one_wins():
    store = old_store(("第一次聊到小橘", "[neutral]好。"), ("第二次聊到小橘", "[neutral]好。"), days_ago=90)
    system, _ = ask(store, "小橘啦", limits={"retrieval_k": 1})
    assert "第二次" in block(system) and "第一次" not in block(system)


def test_a_topic_mentioned_only_a_few_times_among_many_messages_is_still_found():
    store = old_store(*[(f"今天吃了第{i}碗的拉麵", "[neutral]好。") for i in range(40)],
                      ("我在學潛水", "[neutral]好。"), ("潛水課好玩嗎", "[neutral]好。"))
    system, _ = ask(store, "潛水學得怎麼樣了")
    assert "潛水" in block(system)


def test_it_costs_no_extra_model_call():
    store = old_store(("我下週三要去面試", "[neutral]加油喔。"))
    _, llm = ask(store, "上次說的面試怎麼樣了", max_turns=20)    # (nothing to fold: only the chat call is made)
    assert llm.calls == 1


def test_a_better_threshold_can_be_set():
    store = old_store(("我下週三要去面試", "[neutral]加油喔。"))
    system, _ = ask(store, "上次說的面試怎麼樣了", limits={"retrieval_min_score": 3.0})
    assert "【可能相關的記憶】" not in system


# ---- switched off ------------------------------------------------------------------------------------------------

def test_with_memory_switched_off_nothing_is_searched_and_the_prompt_is_what_it_always_was():
    store = old_store(("我下週三要去面試", "[neutral]加油喔。"))
    with_history, _ = ask(store, "上次說的面試怎麼樣了", memory=False)
    baseline, _ = ask(old_store(), "上次說的面試怎麼樣了", memory=False)
    assert "【可能相關的記憶】" not in with_history
    assert with_history == baseline


def test_the_block_says_it_may_not_be_exact():
    store = old_store(("我下週三要去面試", "[neutral]加油喔。"))
    system, _ = ask(store, "上次說的面試怎麼樣了")
    assert "不一定完全準確" in system and "自然" in system
