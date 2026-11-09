"""Folding old conversation into memory (spec Part 12, section 8, ticket 81): one structured call turns the
oldest turns into dated journal events AND a complete new version of the long-term facts. Observed through
the turn engine, with a fake model that answers the chat and the folding call, and the stores."""
import pytest

from companion.engine import Done, TurnEngine
from companion.errors import LLMError
from companion.history import InMemoryHistory

NOW = 1_790_000_000.0   # an arbitrary fixed "today"
LIMITS = {"long_term_max_chars": 2000, "recent_notes_max_chars": 600}


def fold_answer(events=None, user=("使用者喜歡貓",), shared=("聊過貓和咖啡",), own=(), followups=(), earlier=None):
    facts = {"user": list(user), "shared": list(shared), "self": list(own), "followups": list(followups)}
    if earlier is not None:
        facts["earlier_summary"] = earlier
    return {"events": [{"date": "2026-10-01", "text": "聊了貓"}] if events is None else events, "facts": facts}


class FoldLLM:
    """Chats with "好。" and answers each folding call with the next scripted result (or exception)."""

    def __init__(self, *folds):
        self.folds = list(folds)
        self.fold_requests = []
        self.chats = 0

    def stream(self, system, messages):
        self.chats += 1
        yield "[neutral]好。"

    def generate_structured(self, system, messages, schema):
        self.fold_requests.append({"system": system, "request": messages[0]["content"], "schema": schema})
        result = self.folds.pop(0) if len(self.folds) > 1 else self.folds[0]
        if isinstance(result, BaseException):
            raise result
        return result


def engine_for(llm, store=None, limits=None, **kwargs):
    store = store if store is not None else InMemoryHistory()
    engine = TurnEngine(llm, persona="p", history_store=store, summarize=True, max_turns=3, summary_batch=2,
                        background=lambda fn: fn(), wall_clock=lambda: NOW,
                        memory_settings=dict(LIMITS, **(limits or {})), **kwargs)
    return engine, store


def chat(engine, count):
    for n in range(count):
        list(engine.send(f"話{n + 1}"))


# ---- when it happens ------------------------------------------------------------------------------------

def test_folding_starts_only_when_the_unfolded_tail_is_longer_than_the_window_and_takes_one_batch():
    llm = FoldLLM(fold_answer())
    engine, store = engine_for(llm)
    chat(engine, 3)
    assert llm.fold_requests == []                       # still within the window
    chat(engine, 1)
    assert len(llm.fold_requests) == 1                   # the fourth turn pushed it over
    assert store.load_fold_progress() == 4   # one batch = 2 turns = 4 messages
    assert "話1" in llm.fold_requests[0]["request"] and "話2" in llm.fold_requests[0]["request"]
    assert "話3" not in llm.fold_requests[0]["request"]


def test_folding_never_holds_up_the_conversation():
    pending = []
    llm = FoldLLM(fold_answer())
    engine = TurnEngine(llm, persona="p", history_store=InMemoryHistory(), summarize=True, max_turns=3, summary_batch=2,
                        background=pending.append, wall_clock=lambda: NOW, memory_settings=LIMITS)
    for n in range(4):
        events = list(engine.send(f"話{n + 1}"))
        assert events[-1] == Done()
    assert llm.fold_requests == [] and pending            # queued for the background, not run inside any turn
    for job in pending:
        job()
    assert len(llm.fold_requests) == 1                    # and however many were queued, the turns fold once


def test_only_one_fold_runs_at_a_time():
    class Reentrant(FoldLLM):
        engine = None

        def generate_structured(self, system, messages, schema):
            if len(self.fold_requests) == 0:
                self.engine._maybe_summarize()      # a second fold starts while the first is still working
            return super().generate_structured(system, messages, schema)

    llm = Reentrant(fold_answer())
    engine, _ = engine_for(llm)
    llm.engine = engine
    chat(engine, 4)
    assert len(llm.fold_requests) == 1


# ---- what is asked and how it is asked -------------------------------------------------------------------

def test_it_is_one_structured_call_whose_shape_is_enforced_by_a_schema():
    llm = FoldLLM(fold_answer())
    engine, _ = engine_for(llm)
    chat(engine, 4)
    schema = llm.fold_requests[0]["schema"]
    assert set(schema["properties"]) == {"events", "facts"} and set(schema["required"]) == {"events", "facts"}
    assert set(schema["properties"]["facts"]["properties"]) == {"user", "shared", "self", "followups", "earlier_summary"}
    assert "JSON" not in llm.fold_requests[0]["system"]


def test_the_request_shows_the_current_long_term_memory_with_its_size_and_the_limit():
    llm = FoldLLM(fold_answer())
    store = InMemoryHistory()
    store.save_facts({"使用者": "- 住在台北", "更早的摘要": "早先聊過旅行"})
    engine, _ = engine_for(llm, store=store, limits={"long_term_max_chars": 500})
    chat(engine, 4)
    request = llm.fold_requests[0]["request"]
    assert "〔使用者〕\n- 住在台北" in request and "〔更早的摘要〕\n早先聊過旅行" in request
    assert "上限 500" in request and f"共 {len('- 住在台北') + len('早先聊過旅行')} 字" in request


def test_the_instructions_ask_for_absolute_dates_and_keep_her_present_state_out_of_the_facts():
    llm = FoldLLM(fold_answer())
    engine, _ = engine_for(llm)
    chat(engine, 4)
    system = llm.fold_requests[0]["system"]
    assert "你是記憶整理助手" in system
    assert "地點" in system and "身體狀態" in system and "持有" in system and "事實" in system
    assert "過時" in system


# ---- what is written ---------------------------------------------------------------------------------------------

def test_events_are_appended_to_the_journal_and_the_facts_replace_the_old_ones_as_a_whole():
    llm = FoldLLM(fold_answer(events=[{"date": "2026-10-01", "text": "聊了貓"}, {"date": "2026-10-02", "text": "說了面試"}],
                              user=["喜歡貓", "住台北"], followups=["2026-10-08 面試"]))
    store = InMemoryHistory()
    store.save_facts({"使用者": "- 舊事實", "共同經歷": "- 舊的共同經歷", "角色自己的事": "- 舊的角色的事"})
    engine, _ = engine_for(llm, store=store)
    chat(engine, 4)
    # a section the new version leaves empty is gone, not left behind from the old one
    assert store.load_facts() == {"使用者": "- 喜歡貓\n- 住台北", "共同經歷": "- 聊過貓和咖啡", "待跟進": "- 2026-10-08 面試"}
    assert [(e["date"], e["text"]) for e in store.load_events(["2026-10-01", "2026-10-02"])] == [
        ("2026-10-01", "聊了貓"), ("2026-10-02", "說了面試")]


def test_the_older_summary_is_kept_unless_the_model_rewrites_it():
    store = InMemoryHistory()
    store.save_facts({"更早的摘要": "早先聊過旅行"})
    engine, _ = engine_for(FoldLLM(fold_answer()), store=store)
    chat(engine, 4)
    assert store.load_facts()["更早的摘要"] == "早先聊過旅行"
    store2 = InMemoryHistory()
    store2.save_facts({"更早的摘要": "早先聊過旅行"})
    engine2, _ = engine_for(FoldLLM(fold_answer(earlier="旅行與工作")), store=store2)
    chat(engine2, 4)
    assert store2.load_facts()["更早的摘要"] == "旅行與工作"


def test_what_she_remembers_shows_up_in_the_next_prompt():
    llm = FoldLLM(fold_answer(user=["使用者喜歡貓"]))
    engine, _ = engine_for(llm)
    chat(engine, 4)
    seen = []
    original = llm.stream
    llm.stream = lambda system, messages: (seen.append(system), original(system, messages))[1]
    list(engine.send("再來"))
    assert "使用者喜歡貓" in seen[0]


def test_at_most_ten_events_each_cut_to_eighty_characters_and_bad_ones_dropped():
    events = [{"date": "2026-10-01", "text": f"事件{i}"} for i in range(15)]
    events[0] = {"date": "2026-10-01", "text": "長" * 100}
    events.insert(1, {"date": "2026-10-01", "text": "   "})      # empty: dropped, does not use up a place
    events.insert(2, {"date": "2026-10-01", "text": 7})          # not text: dropped
    llm = FoldLLM(fold_answer(events=events))
    engine, store = engine_for(llm)
    chat(engine, 4)
    saved = store.load_events(["2026-10-01"])
    assert len(saved) == 10 and len(saved[0]["text"]) == 80


def test_an_event_with_a_missing_or_malformed_date_is_dated_with_the_day_it_was_folded():
    from datetime import datetime

    today = f"{datetime.fromtimestamp(NOW).astimezone():%Y-%m-%d}"
    llm = FoldLLM(fold_answer(events=[{"date": "下週三", "text": "面試"}, {"text": "沒有日期"}]))
    engine, store = engine_for(llm)
    chat(engine, 4)
    assert [e["date"] for e in store.load_events([today])] == [today, today]


def test_facts_are_trimmed_and_empty_or_non_text_entries_dropped():
    llm = FoldLLM(fold_answer(user=["  喜歡貓 ", "", 3, None, "住台北"]))
    engine, store = engine_for(llm)
    chat(engine, 4)
    assert store.load_facts()["使用者"] == "- 喜歡貓\n- 住台北"


# ---- too big -----------------------------------------------------------------------------------------------------

def test_facts_over_the_limit_are_not_written_nor_cut_but_the_events_and_progress_are(caplog):
    llm = FoldLLM(fold_answer(user=["很長的事實" * 20]))
    store = InMemoryHistory()
    store.save_facts({"使用者": "- 舊事實"})
    engine, _ = engine_for(llm, store=store, limits={"long_term_max_chars": 50})
    chat(engine, 4)
    assert store.load_facts() == {"使用者": "- 舊事實"}                       # the old version stands, uncut
    assert [e["text"] for e in store.load_events(["2026-10-01"])] == ["聊了貓"]
    assert store.load_fold_progress() == 4                      # and the batch is not folded again
    assert any("limit" in m for m in caplog.messages)


def test_a_result_exactly_at_the_limit_is_accepted():
    llm = FoldLLM(fold_answer(user=["一二三"], shared=[]))
    engine, store = engine_for(llm, limits={"long_term_max_chars": len("- 一二三")})
    chat(engine, 4)
    assert store.load_facts() == {"使用者": "- 一二三"}


# ---- things going wrong --------------------------------------------------------------------------------------------

UNUSABLE = [
    None, ["not", "an", "object"], {}, {"events": [], "facts": "x"}, {"events": "x", "facts": fold_answer()["facts"]},
    {"events": [], "facts": {"user": "使用者喜歡貓", "shared": [], "self": [], "followups": []}},   # a section is not a list
    {"events": [], "facts": {"user": []}},                                                         # sections missing
    LLMError("timeout"), ValueError("the model returned no structured output"),
]


@pytest.mark.parametrize("unusable", UNUSABLE, ids=lambda u: type(u).__name__ + ":" + str(u)[:30])
def test_an_unusable_answer_writes_nothing_moves_nothing_and_is_retried_on_a_later_turn(unusable):
    llm = FoldLLM(unusable, fold_answer())
    engine, store = engine_for(llm)
    chat(engine, 4)
    assert store.load_facts() == {} and store.load_events(["2026-10-01"]) == []
    assert store.load_fold_progress() == 0
    list(engine.send("話5"))
    assert len(llm.fold_requests) == 2 and store.load_fold_progress() == 4


def test_an_answer_that_would_wipe_a_memory_that_has_content_is_not_trusted():
    llm = FoldLLM(fold_answer(user=[], shared=[]), fold_answer())
    store = InMemoryHistory()
    store.save_facts({"使用者": "- 舊事實"})
    engine, _ = engine_for(llm, store=store)
    chat(engine, 4)
    assert store.load_facts() == {"使用者": "- 舊事實"} and store.load_fold_progress() == 0


def test_a_first_fold_with_nothing_worth_keeping_is_fine_when_there_was_nothing_before():
    llm = FoldLLM(fold_answer(user=[], shared=[], events=[]))
    engine, store = engine_for(llm)
    chat(engine, 4)
    assert store.load_fold_progress() == 4 and store.load_facts() == {}


# ---- what is left alone -------------------------------------------------------------------------------------------------

def test_with_memory_switched_off_there_is_no_folding_at_all():
    llm = FoldLLM(fold_answer())
    engine = TurnEngine(llm, persona="p", history_store=InMemoryHistory(), summarize=False, max_turns=3, summary_batch=2,
                        background=lambda fn: fn(), wall_clock=lambda: NOW)
    chat(engine, 6)
    assert llm.fold_requests == []


def test_the_fold_survives_a_restart(tmp_path):
    from companion.history import SqliteHistory

    db = tmp_path / "chat.db"
    engine, _ = engine_for(FoldLLM(fold_answer(user=["使用者喜歡貓"])), store=SqliteHistory(db))
    chat(engine, 4)
    reopened = SqliteHistory(db)
    assert reopened.load_facts()["使用者"] == "- 使用者喜歡貓"
    assert reopened.load_fold_progress() == 4
    assert [e["text"] for e in reopened.load_events(["2026-10-01"])] == ["聊了貓"]
