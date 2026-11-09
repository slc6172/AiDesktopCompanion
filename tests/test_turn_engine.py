import pytest

from companion.engine import TurnEngine, Sentence, Audio, Done, Failure, Notice
from companion.errors import LLMError, TTSUnavailable
from companion.history import InMemoryHistory, SqliteHistory


class FakeLLM:
    """Test double for the LLM boundary: streams the given chunks."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.consumed = 0
        self.calls = []

    def stream(self, system, messages):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk


def test_reply_yields_its_sentences_with_their_emotion_then_done():
    engine = TurnEngine(FakeLLM(["[happy]你好呀!"]), persona="你是小晴")
    events = list(engine.send("嗨"))
    assert events == [Sentence("你好呀!", "happy"), Done()]


def test_sentences_are_emitted_as_soon_as_complete_even_if_chunks_split_them():
    llm = FakeLLM(["[happy]你好", "呀!今天過", "得好嗎?", "我很想你"])
    stream = TurnEngine(llm, persona="p").send("嗨")
    assert next(stream) == Sentence("你好呀!", "happy")
    assert llm.consumed < 4  # first sentence arrived before the LLM finished
    assert list(stream) == [Sentence("今天過得好嗎?", "happy"), Sentence("我很想你", "happy"), Done()]


def test_persona_and_allowed_emotions_are_sent_to_llm_as_system_prompt():
    llm = FakeLLM(["[neutral]嗯"])
    list(TurnEngine(llm, persona="你是活潑的小晴").send("嗨"))
    system = llm.calls[0]["system"]
    assert "你是活潑的小晴" in system
    for name in ["neutral", "happy", "angry", "sad", "surprised"]:
        assert name in system


def test_second_turn_includes_first_exchange():
    llm = FakeLLM(["[happy]你好呀!"])
    engine = TurnEngine(llm, persona="p")
    list(engine.send("嗨"))
    list(engine.send("你是誰"))
    assert llm.calls[1]["messages"] == [
        {"role": "user", "content": "嗨"},
        {"role": "assistant", "content": "[happy]你好呀!"},
        {"role": "user", "content": "你是誰"},
    ]


def test_a_tag_outside_the_allowed_set_counts_as_happy_when_speech_follows():
    events = list(TurnEngine(FakeLLM(["[furious]走開!"]), persona="p").send("嗨"))
    assert events == [Sentence("走開!", "happy"), Done()]


def test_a_reply_without_any_tag_is_neutral_and_keeps_its_text():
    events = list(TurnEngine(FakeLLM(["沒有標籤的回覆。"]), persona="p").send("嗨"))
    assert events == [Sentence("沒有標籤的回覆。", "neutral"), Done()]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeTTS:
    """Test double for the speech-synthesis boundary."""

    mime_type = "audio/fake"

    def __init__(self, clock=None, delay=0.0):
        self.clock = clock
        self.delay = delay
        self.calls = []

    def synthesize(self, text):
        if self.clock is not None:
            self.clock.now += self.delay
        self.calls.append(text)
        return f"audio:{text}".encode()


def test_every_sentence_gets_matching_audio_in_original_order():
    engine = TurnEngine(FakeLLM(["[happy]你好呀!今天好嗎?"]), persona="p", tts=FakeTTS())
    events = list(engine.send("嗨"))
    assert events == [
        Sentence("你好呀!", "happy"),
        Audio(0, "你好呀!", "audio:你好呀!".encode(), "audio/fake", "happy"),
        Sentence("今天好嗎?", "happy"),
        Audio(1, "今天好嗎?", "audio:今天好嗎?".encode(), "audio/fake", "happy"),
        Done(),
    ]


def test_done_reports_time_to_first_audio_in_milliseconds():
    clock = FakeClock()
    engine = TurnEngine(
        FakeLLM(["[happy]你好呀!今天好嗎?"]),
        persona="p",
        tts=FakeTTS(clock, delay=0.42),
        clock=clock,
    )
    events = list(engine.send("嗨"))
    assert events[-1].first_audio_ms == pytest.approx(420)


def test_first_audio_arrives_before_the_llm_has_finished_streaming():
    llm = FakeLLM(["[happy]你好呀!", "今天過", "得好嗎?", "我很想你"])
    stream = TurnEngine(llm, persona="p", tts=FakeTTS()).send("嗨")
    seen = []
    for event in stream:
        seen.append(event)
        if isinstance(event, Audio):
            break
    assert llm.consumed < 4


def test_conversation_survives_a_restart(tmp_path):
    db = tmp_path / "chat.db"
    first = TurnEngine(FakeLLM(["[happy]你好呀!"]), persona="p", history_store=SqliteHistory(db))
    list(first.send("嗨"))

    llm = FakeLLM(["[neutral]我是小晴。"])
    second = TurnEngine(llm, persona="p", history_store=SqliteHistory(db))  # "restart"
    list(second.send("你是誰"))

    assert llm.calls[0]["messages"] == [
        {"role": "user", "content": "嗨"},
        {"role": "assistant", "content": "[happy]你好呀!"},
        {"role": "user", "content": "你是誰"},
    ]


def test_llm_only_sees_the_most_recent_turns_plus_the_new_message():
    llm = FakeLLM(["[neutral]好。"])
    engine = TurnEngine(llm, persona="p", max_turns=2)
    for question in ["一", "二", "三"]:
        list(engine.send(question))
    list(engine.send("四"))
    assert llm.calls[3]["messages"] == [
        {"role": "user", "content": "二"},
        {"role": "assistant", "content": "[neutral]好。"},
        {"role": "user", "content": "三"},
        {"role": "assistant", "content": "[neutral]好。"},
        {"role": "user", "content": "四"},
    ]


def test_history_returns_the_full_conversation_for_display_beyond_the_llm_window():
    engine = TurnEngine(FakeLLM(["[happy]好的。"]), persona="p", max_turns=1)
    for question in ["一", "二", "三"]:
        list(engine.send(question))
    history = engine.history()
    assert len(history) == 6
    assert history[0] == {"role": "user", "text": "一"}
    assert history[1] == {"role": "assistant", "text": "好的。", "emotions": ["happy"]}
    assert history[-2] == {"role": "user", "text": "三"}


def test_saved_conversation_can_be_shown_again_after_a_restart(tmp_path):
    db = tmp_path / "chat.db"
    list(TurnEngine(FakeLLM(["[sad]好難過。"]), persona="p", history_store=SqliteHistory(db)).send("今天很糟"))
    reopened = TurnEngine(FakeLLM(["[neutral]嗯"]), persona="p", history_store=SqliteHistory(db))
    assert reopened.history() == [
        {"role": "user", "text": "今天很糟"},
        {"role": "assistant", "text": "好難過。", "emotions": ["sad"]},
    ]


class FailingLLM:
    """Streams `before` chunks, then fails the way a real adapter would."""

    def __init__(self, kind, before=()):
        self.kind = kind
        self.before = before

    def stream(self, system, messages):
        yield from self.before
        raise LLMError(self.kind)


def test_llm_failure_becomes_a_friendly_failure_event_instead_of_crashing():
    engine = TurnEngine(FailingLLM("rate_limit"), persona="p")
    events = list(engine.send("嗨"))
    assert len(events) == 1
    assert isinstance(events[0], Failure)
    assert events[0].kind == "rate_limit"
    assert events[0].message  # something friendly to show the user


class FlakyLLM(FakeLLM):
    """Fails on the first call, then behaves like FakeLLM."""

    def __init__(self, chunks, kind):
        super().__init__(chunks)
        self.kind = kind

    def stream(self, system, messages):
        if not self.calls:
            self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
            raise LLMError(self.kind)
        yield from super().stream(system, messages)


def test_a_failed_turn_is_not_saved_so_retrying_never_duplicates_it():
    llm = FlakyLLM(["[happy]你好呀!"], "timeout")
    engine = TurnEngine(llm, persona="p")
    first = list(engine.send("嗨"))
    assert isinstance(first[-1], Failure)
    assert engine.history() == []  # nothing half-saved

    retry = list(engine.send("嗨"))
    assert retry[-1] == Done()
    assert llm.calls[1]["messages"] == [{"role": "user", "content": "嗨"}]
    assert [m["role"] for m in engine.history()] == ["user", "assistant"]


def test_a_failure_in_the_middle_of_a_reply_ends_with_failure_and_saves_nothing():
    engine = TurnEngine(FailingLLM("timeout", before=["[happy]你好呀!", "今天過"]), persona="p")
    events = list(engine.send("嗨"))
    assert events[0] == Sentence("你好呀!", "happy")
    assert isinstance(events[-1], Failure) and events[-1].kind == "timeout"
    assert [e.text for e in events if isinstance(e, Sentence)] == ["你好呀!"]  # the cut-off fragment is not spoken
    assert engine.history() == []


class BrokenTTS:
    mime_type = "audio/fake"

    def __init__(self):
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        raise RuntimeError("speech service unreachable")


def test_when_speech_fails_the_reply_continues_as_text_with_one_notice():
    tts = BrokenTTS()
    engine = TurnEngine(FakeLLM(["[happy]你好呀!今天好嗎?"]), persona="p", tts=tts)
    events = list(engine.send("嗨"))

    assert not any(isinstance(e, Audio) for e in events)
    assert [e for e in events if isinstance(e, Sentence)] == [Sentence("你好呀!", "happy"), Sentence("今天好嗎?", "happy")]
    assert len([e for e in events if isinstance(e, Notice)]) == 1
    assert events[-1] == Done()
    assert len(tts.calls) == 1  # gave up for this turn instead of timing out on every sentence
    assert len(engine.history()) == 2  # the text reply was still saved


# ---- long-term memory (ticket 07) ----

CHAT = "[neutral]好。"
# What the memory fold's structured-output call returns: dated journal events + the new long-term facts.
SUMMARY = {"events": [{"date": "2026-10-01", "text": "聊過貓"}],
           "facts": {"user": ["使用者喜歡貓"], "shared": ["聊過貓和咖啡"], "self": [], "followups": []}}


def run_in_place(fn):
    fn()  # test stand-in for "run in the background": do it right now


class SequenceLLM:
    """Replies with the next scripted text on every call, whatever the call is for."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def stream(self, system, messages):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        yield self.replies[len(self.calls) - 1]

    def generate_structured(self, system, messages, schema):
        """The memory summary's call: one scripted object (or exception) per call, in the same
        sequence as everything else, so "calls 0-3 chat, 4 summary" still reads the same."""
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "schema": schema})
        reply = self.replies[len(self.calls) - 1]
        if isinstance(reply, BaseException):
            raise reply
        return reply


def memory_engine(llm, **extra):
    return TurnEngine(
        llm, persona="p", summarize=True, max_turns=3, summary_batch=2,
        background=run_in_place, **extra,
    )


def test_old_turns_are_replaced_by_a_summary_once_the_history_gets_too_long():
    llm = SequenceLLM([CHAT, CHAT, CHAT, CHAT, SUMMARY, CHAT])
    engine = memory_engine(llm)
    for question in ["一", "二", "三", "四"]:
        list(engine.send(question))
    list(engine.send("五"))

    request = llm.calls[5]  # calls 0-3 chat, 4 = the summary, 5 = this turn
    assert request["messages"] == [
        {"role": "user", "content": "三"},
        {"role": "assistant", "content": CHAT},
        {"role": "user", "content": "四"},
        {"role": "assistant", "content": CHAT},
        {"role": "user", "content": "五"},
    ]
    assert "聊過貓和咖啡" in request["system"]


def summarized_engine_and_llm(**extra):
    """Four turns, then the summary call, ready for a fifth turn (calls 0-3 chat, 4 summary)."""
    llm = SequenceLLM([CHAT, CHAT, CHAT, CHAT, SUMMARY, CHAT])
    engine = memory_engine(llm, **extra)
    for question in ["一", "二", "三", "四"]:
        list(engine.send(question))
    return engine, llm


def test_facts_about_the_user_are_carried_into_later_system_prompts():
    engine, llm = summarized_engine_and_llm()
    list(engine.send("五"))
    assert "使用者喜歡貓" in llm.calls[5]["system"]


def test_summarizing_does_not_happen_on_every_turn():
    llm = SequenceLLM([CHAT, CHAT, CHAT, CHAT, SUMMARY, CHAT])
    engine = memory_engine(llm)
    for question in ["一", "二", "三"]:
        list(engine.send(question))
    assert len(llm.calls) == 3  # history still short enough: no extra call
    list(engine.send("四"))
    assert len(llm.calls) == 5  # this turn pushed it over: exactly one summary call
    list(engine.send("五"))
    assert len(llm.calls) == 6  # back to one call per turn


def test_the_summary_is_asked_for_as_structured_output_with_a_schema_not_as_free_text():
    engine, llm = summarized_engine_and_llm()
    schema = llm.calls[4]["schema"]  # call 4 is the summary; it never went through the chat stream
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"events", "facts"}
    assert set(schema["required"]) == {"events", "facts"}
    assert "JSON" not in llm.calls[4]["system"]  # the schema carries the format now, not the prompt


GOOD_FACTS = {"user": ["使用者喜歡貓"], "shared": [], "self": [], "followups": []}
UNUSABLE_SUMMARIES = [
    {"events": [], "facts": {**GOOD_FACTS, "user": "使用者喜歡貓"}},  # a section that is not a list
    {"events": [], "facts": {"user": []}},  # sections missing
    {"events": [], "facts": "使用者喜歡貓"},  # facts is not an object
    {"events": "none", "facts": GOOD_FACTS},  # events is not a list
    {"facts": GOOD_FACTS},  # events missing
    None,
    ["not", "an", "object"],
    LLMError("timeout"),  # the call itself failed
    ValueError("the model returned no structured output"),
]


@pytest.mark.parametrize("unusable", UNUSABLE_SUMMARIES, ids=lambda u: type(u).__name__ + ":" + str(u)[:30])
def test_an_unusable_summary_never_breaks_the_conversation_and_is_retried_on_a_later_turn(unusable):
    llm = SequenceLLM([CHAT, CHAT, CHAT, CHAT, unusable, CHAT, SUMMARY])
    engine = memory_engine(llm)
    for question in ["一", "二", "三", "四"]:
        list(engine.send(question))  # the 4th turn triggers a summary that comes back unusable
    events = list(engine.send("五"))

    assert events[-1] == Done()
    assert len(llm.calls[5]["messages"]) == 7  # no summary yet: still the last 3 turns + the new message
    assert "聊過貓和咖啡" not in llm.calls[5]["system"]
    assert len(llm.calls) == 7  # retried after turn five, not in a tight loop within one turn


def test_facts_are_cleaned_up_even_when_the_structure_is_right():
    messy = {"events": [], "facts": {"user": ["  使用者喜歡貓 ", "", 3, None, "使用者住台北"], "shared": ["  聊過貓  "],
                                     "self": [], "followups": []}}
    llm = SequenceLLM([CHAT, CHAT, CHAT, CHAT, messy, CHAT])
    engine = memory_engine(llm)
    for question in ["一", "二", "三", "四", "五"]:
        list(engine.send(question))

    system = llm.calls[5]["system"]
    assert "- 聊過貓" in system and "  聊過貓" not in system  # trimmed
    assert "- 使用者喜歡貓" in system and "- 使用者住台北" in system
    assert system.count("\n- ") == 3  # the empty / non-string entries are dropped


def test_memory_survives_a_restart(tmp_path):
    db = tmp_path / "chat.db"
    engine, _ = summarized_engine_and_llm(history_store=SqliteHistory(db))

    llm = SequenceLLM([CHAT])
    reopened = memory_engine(llm, history_store=SqliteHistory(db))
    list(reopened.send("五"))
    assert "使用者喜歡貓" in llm.calls[0]["system"]
    assert len(llm.calls[0]["messages"]) == 5  # summarized turns stay summarized after the restart


def test_a_later_summary_is_asked_to_merge_with_what_is_already_remembered():
    llm = SequenceLLM([CHAT, CHAT, CHAT, CHAT, SUMMARY, CHAT, CHAT, SUMMARY])
    engine = memory_engine(llm)
    for question in ["一", "二", "三", "四", "五", "六"]:
        list(engine.send(question))  # turn 6 pushes the tail over the limit a second time

    second_request = llm.calls[7]["messages"][0]["content"]
    assert "聊過貓和咖啡" in second_request  # the earlier summary
    assert "使用者喜歡貓" in second_request  # the earlier facts
    assert "三" in second_request and "四" in second_request  # the newly folded-in turns


# ---- Ticket 09: an emotion tag is never spoken, wherever the model puts it ----


def test_a_tag_that_follows_a_full_stop_is_not_spoken():
    events = list(TurnEngine(FakeLLM(["[happy]好啊。[sad]可是我有點累…"]), persona="p").send("嗨"))
    assert events == [Sentence("好啊。", "happy"), Sentence("可是我有點累…", "sad"), Done()]


def test_a_tag_in_the_middle_of_a_sentence_is_not_spoken_and_ends_the_sentence_before_it():
    # The reported bug: no full stop before the second tag, so both halves used to be glued together.
    events = list(TurnEngine(FakeLLM(["[happy]好啊[sad]我有點累。"]), persona="p").send("嗨"))
    assert events == [Sentence("好啊", "happy"), Sentence("我有點累。", "sad"), Done()]


def test_the_exact_reply_from_the_bug_report_is_spoken_cleanly():
    # Regression for the reported bug. Written after the fix; the same input was shown failing
    # against the old engine with a throwaway reproduction script.
    reply = "[thinking]我想想看要怎麼解決這個問題[neutral]算了,不想了"
    events = list(TurnEngine(FakeLLM([reply]), persona="p").send("嗨"))
    assert events == [
        Sentence("我想想看要怎麼解決這個問題", "happy"),  # [thinking] is outside the set and speech follows
        Sentence("算了,不想了", "neutral"),
        Done(),
    ]


def test_a_tag_split_across_stream_chunks_is_still_recognised_and_not_spoken():
    # Characterization: passed as soon as it was written; guards against regressions.
    events = list(TurnEngine(FakeLLM(["[happy]好啊。[sa", "d]可是我有點累。"]), persona="p").send("嗨"))
    assert events == [Sentence("好啊。", "happy"), Sentence("可是我有點累。", "sad"), Done()]


@pytest.mark.parametrize("tag", ["【sad】", "[SAD]", "[ sad ]"])
def test_full_width_uppercase_and_spaced_tags_are_recognised_too(tag):
    events = list(TurnEngine(FakeLLM([f"[happy]好啊。{tag}可是我有點累。"]), persona="p").send("嗨"))
    assert events == [Sentence("好啊。", "happy"), Sentence("可是我有點累。", "sad"), Done()]


# Characterization: the cases below passed as soon as they were written, because the
# general tag rule from the cycles above already covers them. They pin the behavior down.


def test_a_full_width_tag_at_the_start_of_the_reply_sets_its_emotion():
    events = list(TurnEngine(FakeLLM(["【happy】你好呀!"]), persona="p").send("嗨"))
    assert events == [Sentence("你好呀!", "happy"), Done()]


def test_any_short_bracketed_word_counts_as_a_tag_even_in_chinese():
    events = list(TurnEngine(FakeLLM(["[笑]太好了。"]), persona="p").send("嗨"))
    assert events == [Sentence("太好了。", "happy"), Done()]


def test_a_long_bracketed_phrase_is_kept_as_ordinary_text():
    note = "[這段說明的長度已經超過十六個字元所以不是標籤]"
    events = list(TurnEngine(FakeLLM([f"[happy]請看{note}謝謝。"]), persona="p").send("嗨"))
    assert events == [Sentence(f"請看{note}謝謝。", "happy"), Done()]


def test_a_tag_left_dangling_at_the_end_of_the_reply_produces_no_sentence():
    events = list(TurnEngine(FakeLLM(["[happy]好啊。[sad]"]), persona="p").send("嗨"))
    assert events == [Sentence("好啊。", "happy"), Done()]


def test_history_shows_a_reply_without_any_of_its_tags():
    engine = TurnEngine(FakeLLM(["[happy]好啊[sad]我有點累。"]), persona="p")
    list(engine.send("嗨"))
    assert engine.history()[1] == {"role": "assistant", "text": "好啊我有點累。", "emotions": ["happy", "sad"]}


def test_history_shows_the_same_emotion_the_reply_was_spoken_with_for_an_unknown_tag():
    # Characterization: passed as soon as it was written.
    engine = TurnEngine(FakeLLM(["[furious]走開!"]), persona="p")
    list(engine.send("嗨"))
    assert engine.history()[1]["emotions"] == ["happy"]


def test_summarizing_never_hands_stray_tags_to_the_model():
    # Characterization: passed as soon as it was written.
    llm = SequenceLLM(["[happy]好啊[sad]我有點累。"] * 4 + [SUMMARY, CHAT])
    engine = memory_engine(llm)
    for question in ["一", "二", "三", "四"]:
        list(engine.send(question))
    summary_request = llm.calls[4]["messages"][0]["content"]
    assert "好啊我有點累。" in summary_request
    assert "[happy]" not in summary_request and "[sad]" not in summary_request


def test_a_finished_sentence_is_not_held_back_by_a_tag_that_is_still_arriving():
    # Characterization: passed as soon as it was written.
    llm = FakeLLM(["[happy]好啊。[sa", "d]可是我有點累。"])
    stream = TurnEngine(llm, persona="p").send("嗨")
    assert next(stream) == Sentence("好啊。", "happy")
    assert llm.consumed == 1  # spoken before the rest of the reply had even arrived


# ---- Ticket 10: every sentence carries its own emotion ----


def test_each_sentence_carries_the_emotion_it_was_tagged_with():
    events = list(TurnEngine(FakeLLM(["[surprised]咦?[happy]太好了!"]), persona="p").send("嗨"))
    assert events == [Sentence("咦?", "surprised"), Sentence("太好了!", "happy"), Done()]


def test_a_sentence_without_a_tag_keeps_the_emotion_of_the_one_before():
    # Characterization: passed as soon as it was written (the segmenter keeps the current emotion).
    events = list(TurnEngine(FakeLLM(["[happy]好啊。可是我累。"]), persona="p").send("嗨"))
    assert events == [Sentence("好啊。", "happy"), Sentence("可是我累。", "happy"), Done()]


def test_a_reply_that_starts_without_a_tag_is_neutral_until_the_first_tag():
    # Characterization
    events = list(TurnEngine(FakeLLM(["你好。[happy]太好了。"]), persona="p").send("嗨"))
    assert events == [Sentence("你好。", "neutral"), Sentence("太好了。", "happy"), Done()]


def test_consecutive_tags_use_the_last_one_even_when_they_arrive_in_separate_chunks():
    # Characterization
    events = list(TurnEngine(FakeLLM(["[happy]", "[sad]嗯。"]), persona="p").send("嗨"))
    assert events == [Sentence("嗯。", "sad"), Done()]


def test_every_audio_clip_carries_the_emotion_of_its_own_sentence():
    # Characterization
    engine = TurnEngine(FakeLLM(["[surprised]咦?[happy]太好了!"]), persona="p", tts=FakeTTS())
    audio = [e for e in engine.send("嗨") if isinstance(e, Audio)]
    assert [(a.index, a.emotion) for a in audio] == [(0, "surprised"), (1, "happy")]


def test_history_shows_the_emotion_of_every_sentence_of_a_reply():
    engine = TurnEngine(FakeLLM(["[happy]好啊。可是我累。[sad]好難過。"]), persona="p")
    list(engine.send("嗨"))
    assert engine.history()[1] == {
        "role": "assistant", "text": "好啊。可是我累。好難過。", "emotions": ["happy", "happy", "sad"],
    }


class EmptyTTS:
    """Some very short sentences can legitimately come back from edge-tts with no audio at all."""

    mime_type = "audio/fake"

    def __init__(self):
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        return b""


def test_a_sentence_whose_synthesis_comes_back_empty_is_shown_but_gets_no_broken_audio_clip():
    tts = EmptyTTS()
    engine = TurnEngine(FakeLLM(["[happy]你好呀!今天好嗎?"]), persona="p", tts=tts)
    events = list(engine.send("嗨"))

    assert [e for e in events if isinstance(e, Sentence)] == [Sentence("你好呀!", "happy"), Sentence("今天好嗎?", "happy")]
    assert not any(isinstance(e, Audio) for e in events)  # never hand the browser an unplayable zero-byte clip
    assert not any(isinstance(e, Notice) for e in events)  # not a whole-turn failure: no need to alarm the user
    assert len(tts.calls) == 4  # each sentence retries once on the same engine before giving up (ticket 23)
    assert events[-1] == Done()


# ---- speech-synthesis retry and fallback (ticket 23) ----


class ScriptedTTS:
    """Test double for the speech-synthesis boundary: returns (or, for an exception instance,
    raises) one scripted result per call (b"" for "nothing to say"), then b"" for any call
    beyond the end of the script."""

    mime_type = "audio/scripted"

    def __init__(self, results, mime_type=None):
        self.results = list(results)
        if mime_type is not None:
            self.mime_type = mime_type
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        result = self.results.pop(0) if self.results else b""
        if isinstance(result, BaseException):
            raise result
        return result


def test_empty_result_is_retried_once_on_the_same_engine_before_giving_up():
    tts = ScriptedTTS([b"", b"audio:retry-worked"])
    engine = TurnEngine(FakeLLM(["[happy]你好呀!"]), persona="p", tts=tts)
    events = list(engine.send("嗨"))

    assert Audio(0, "你好呀!", b"audio:retry-worked", "audio/scripted", "happy") in events
    assert len(tts.calls) == 2  # first call empty, one same-engine retry, no more


def test_fallback_engine_is_used_only_after_the_primary_stays_empty_through_its_retry():
    primary = ScriptedTTS([b"", b""])
    fallback = ScriptedTTS([b"audio:fallback-worked"], mime_type="audio/fallback")
    engine = TurnEngine(FakeLLM(["[happy]你好呀!"]), persona="p", tts=primary, tts_fallback=fallback)
    events = list(engine.send("嗨"))

    assert Audio(0, "你好呀!", b"audio:fallback-worked", "audio/fallback", "happy") in events
    assert len(primary.calls) == 2  # first call + one same-engine retry, then handed off
    assert len(fallback.calls) == 1  # fallback is not itself retried


def test_when_fallback_is_also_empty_only_that_sentence_is_skipped_not_the_rest_of_the_turn():
    primary = ScriptedTTS([b"", b""])
    fallback = ScriptedTTS([b""])
    engine = TurnEngine(FakeLLM(["[happy]你好呀!今天好嗎?"]), persona="p", tts=primary, tts_fallback=fallback)
    events = list(engine.send("嗨"))

    assert [e for e in events if isinstance(e, Sentence)] == [Sentence("你好呀!", "happy"), Sentence("今天好嗎?", "happy")]
    assert not any(isinstance(e, Audio) for e in events)  # neither engine had anything to say for either sentence
    assert not any(isinstance(e, Notice) for e in events)  # still not treated as a whole-service failure
    assert events[-1] == Done()


def test_a_later_sentence_can_succeed_on_the_primary_after_an_earlier_one_needed_the_fallback():
    primary = ScriptedTTS([b"", b"", b"audio:second-sentence"])
    fallback = ScriptedTTS([b"audio:fallback-worked"])
    engine = TurnEngine(FakeLLM(["[happy]你好呀!今天好嗎?"]), persona="p", tts=primary, tts_fallback=fallback)
    events = list(engine.send("嗨"))

    assert Audio(0, "你好呀!", b"audio:fallback-worked", "audio/scripted", "happy") in events
    assert Audio(1, "今天好嗎?", b"audio:second-sentence", "audio/scripted", "happy") in events


def test_primary_exception_still_disables_the_rest_of_the_turn_even_with_a_fallback_configured():
    """The hard-won ticket 17/18 invariant — a genuine exception means the whole service is
    down for this turn, not "try the fallback" — is unaffected by adding fallback support."""
    primary = BrokenTTS()
    fallback = ScriptedTTS([b"audio:should-not-be-used"])
    engine = TurnEngine(FakeLLM(["[happy]你好呀!今天好嗎?"]), persona="p", tts=primary, tts_fallback=fallback)
    events = list(engine.send("嗨"))

    assert not any(isinstance(e, Audio) for e in events)
    assert len([e for e in events if isinstance(e, Notice)]) == 1
    assert len(primary.calls) == 1  # gave up for this turn instead of trying the fallback
    assert len(fallback.calls) == 0


# ---- Bugs reported by the user testing continuous listening (post-ticket-17) ----


def test_consecutive_ending_punctuation_is_not_split_into_a_lone_unspeakable_mark():
    # The reported bug: "…" is a sentence ending, so "……" used to be cut after the first
    # character, leaving a second "sentence" that is just "…" on its own — no real content for
    # speech synthesis to say (see the edge-tts fix below for what that used to trigger).
    events = list(TurnEngine(FakeLLM(["[happy]我……才不是那個意思!"]), persona="p").send("嗨"))
    assert events == [
        Sentence("我……", "happy"),
        Sentence("才不是那個意思!", "happy"),
        Done(),
    ]


def test_a_turn_superseded_before_it_finishes_saves_nothing_and_stops_quietly():
    # Barge-in aborts the browser's fetch of the in-flight turn and immediately starts a new
    # one; the old turn's generator can still be mid-stream server-side when that happens. It
    # must not go on to save its (now-irrelevant) reply into the shared history, and must not
    # share timing/failure state with the turn that superseded it.
    llm = SequenceLLM(["[happy]第一輪的話。", "[sad]第二輪的話。"])
    engine = TurnEngine(llm, persona="p")

    stream_a = engine.send("問題A")
    assert next(stream_a) == Sentence("第一輪的話。", "happy")  # turn A is now paused mid-flight

    assert list(engine.send("問題B")) == [Sentence("第二輪的話。", "sad"), Done()]

    assert list(stream_a) == []  # turn A quietly gives up once it notices it was superseded
    assert engine.history() == [
        {"role": "user", "text": "問題B"},
        {"role": "assistant", "text": "第二輪的話。", "emotions": ["sad"]},
    ]


def test_calling_send_again_supersedes_the_previous_call_even_before_either_is_read():
    # send() must register a new turn as soon as it is called, not only once its stream starts
    # being iterated (a plain generator function does not run any of its body until the first
    # next() on it) — otherwise two calls made back to back, before anything reads either one,
    # would not reliably supersede in call order.
    llm = SequenceLLM(["[happy]第一輪的話。", "[sad]第二輪的話。"])
    engine = TurnEngine(llm, persona="p")

    stream_a = engine.send("問題A")  # not iterated yet
    stream_b = engine.send("問題B")

    assert list(stream_a) == []
    assert list(stream_b) == [Sentence("第二輪的話。", "sad"), Done()]


# ---- an unavailable speech engine hands over to the fallback (ticket 25) ----


def test_an_unavailable_primary_hands_the_sentence_to_the_fallback_without_any_notice():
    primary = ScriptedTTS([TTSUnavailable("connection refused")])
    fallback = ScriptedTTS([b"audio:fallback"], mime_type="audio/fallback")
    engine = TurnEngine(FakeLLM(["[happy]你好呀!"]), persona="p", tts=primary, tts_fallback=fallback)
    events = list(engine.send("嗨"))

    assert Audio(0, "你好呀!", b"audio:fallback", "audio/fallback", "happy") in events
    assert not any(isinstance(e, Notice) for e in events)  # the user just hears the other voice
    assert len(primary.calls) == 1  # no same-engine retry against a server that is down


def test_once_the_primary_is_known_to_be_down_the_rest_of_the_turn_skips_it():
    primary = ScriptedTTS([TTSUnavailable("timed out")])
    fallback = ScriptedTTS([b"audio:one", b"audio:two"])
    engine = TurnEngine(FakeLLM(["[happy]你好呀!今天好嗎?"]), persona="p", tts=primary, tts_fallback=fallback)
    events = list(engine.send("嗨"))

    assert [e.data for e in events if isinstance(e, Audio)] == [b"audio:one", b"audio:two"]
    assert len(primary.calls) == 1  # not one slow timeout per sentence
    assert len(fallback.calls) == 2


def test_the_next_turn_tries_the_primary_again_in_case_it_came_back():
    primary = ScriptedTTS([TTSUnavailable("down"), b"audio:primary-back"])
    fallback = ScriptedTTS([b"audio:fallback"])
    engine = TurnEngine(FakeLLM(["[happy]好。"]), persona="p", tts=primary, tts_fallback=fallback)

    first = list(engine.send("嗨"))
    second = list(engine.send("再來"))

    assert [e.data for e in first if isinstance(e, Audio)] == [b"audio:fallback"]
    assert [e.data for e in second if isinstance(e, Audio)] == [b"audio:primary-back"]


def test_an_unavailable_primary_with_no_fallback_behaves_like_any_other_failure():
    primary = ScriptedTTS([TTSUnavailable("down")])
    engine = TurnEngine(FakeLLM(["[happy]你好呀!今天好嗎?"]), persona="p", tts=primary)
    events = list(engine.send("嗨"))

    assert not any(isinstance(e, Audio) for e in events)
    assert len([e for e in events if isinstance(e, Notice)]) == 1
    assert len(primary.calls) == 1  # gave up for the turn, as before


def test_when_the_fallback_breaks_too_the_rest_of_the_turn_goes_quiet_with_one_notice():
    primary = ScriptedTTS([TTSUnavailable("down")])
    fallback = ScriptedTTS([RuntimeError("edge-tts broke")])
    engine = TurnEngine(FakeLLM(["[happy]你好呀!今天好嗎?"]), persona="p", tts=primary, tts_fallback=fallback)
    events = list(engine.send("嗨"))

    assert not any(isinstance(e, Audio) for e in events)
    assert len([e for e in events if isinstance(e, Notice)]) == 1
    assert len(fallback.calls) == 1  # no more attempts once both engines are out for this turn


# ---- affection and mood (ticket 26) ----


def affection_after(reply, start=None, engine_kwargs=None):
    """Run one turn whose model reply is `reply`; return (events, store)."""
    store = InMemoryHistory()
    if start is not None:
        store.save_affection(start)
    engine = TurnEngine(FakeLLM([reply]), persona="p", history_store=store, **(engine_kwargs or {}))
    return list(engine.send("嗨")), store


def test_affection_and_mood_tags_are_never_shown_spoken_or_turned_into_sentences():
    events, store = affection_after("[happy]謝謝你!好開心。[好感+2][心情:溫柔]")
    assert events == [Sentence("謝謝你!", "happy"), Sentence("好開心。", "happy"), Done()]
    engine = TurnEngine(FakeLLM([]), persona="p", history_store=store)
    assert engine.history()[1]["text"] == "謝謝你!好開心。"  # nor in the on-screen history


def test_a_tag_in_the_middle_of_a_sentence_neither_splits_it_nor_changes_the_emotion():
    events, _ = affection_after("[sad]我好[好感+1]難過。")
    assert events == [Sentence("我好難過。", "sad"), Done()]


def test_an_affection_tag_split_across_stream_chunks_is_still_found_and_never_leaks():
    store = InMemoryHistory()
    engine = TurnEngine(FakeLLM(["[happy]好。[好", "感+2]"]), persona="p", history_store=store)
    assert list(engine.send("嗨")) == [Sentence("好。", "happy"), Done()]
    assert store.load_affection() == 52.0


def test_affection_and_emotion_tags_can_share_a_sentence_without_disturbing_each_other():
    events, store = affection_after("[好感+1][happy]謝謝!")
    assert events == [Sentence("謝謝!", "happy"), Done()]
    assert store.load_affection() == 51.0


def test_a_malformed_affection_tag_is_swallowed_and_is_not_mistaken_for_an_emotion():
    events, store = affection_after("[sad]難過。[好感很多]")
    assert events == [Sentence("難過。", "sad"), Done()]
    assert store.load_affection() == 50.0  # unparsable: no change


def test_a_new_relationship_starts_at_the_neutral_middle():
    _, store = affection_after("[happy]嗨。")
    assert store.load_affection() == 50.0


def test_a_negative_tag_lowers_affection():
    _, store = affection_after("[angry]太過分了。[好感-3]")
    assert store.load_affection() == 47.0


def test_only_one_affection_change_is_applied_per_turn_even_if_the_model_writes_several():
    _, store = affection_after("[happy]好。[好感+2]再來。[好感+3]")
    assert store.load_affection() == 52.0  # the first one; the rest are ignored, no runaway turn


def test_a_single_turn_cannot_move_affection_by_more_than_a_few_points():
    _, store = affection_after("[happy]好。[好感+99]")
    assert store.load_affection() == 55.0  # clamped to +5 at the neutral middle


def test_it_gets_harder_to_gain_affection_the_higher_it_already_is():
    _, near_top = affection_after("[happy]好。[好感+3]", start=90)
    _, middle = affection_after("[happy]好。[好感+3]", start=50)
    assert near_top.load_affection() - 90 < middle.load_affection() - 50
    assert near_top.load_affection() == pytest.approx(90.6)


def test_it_is_just_as_hard_to_fall_the_lower_it_already_is():
    _, store = affection_after("[sad]唉。[好感-3]", start=10)
    assert store.load_affection() == pytest.approx(9.4)


def test_affection_stays_within_zero_to_one_hundred():
    _, top = affection_after("[happy]好。[好感+5]", start=100)
    _, bottom = affection_after("[angry]哼。[好感-5]", start=0)
    assert top.load_affection() == 100.0
    assert bottom.load_affection() == 0.0


def test_affection_works_without_long_term_memory_summarising_being_switched_on():
    _, store = affection_after("[happy]好。[好感+2]", engine_kwargs={"summarize": False})
    assert store.load_affection() == 52.0


def test_the_current_affection_and_mood_are_told_to_the_model_on_the_next_turn():
    store = InMemoryHistory()
    llm = FakeLLM(["[happy]好。[好感+3][心情:溫柔]"])
    engine = TurnEngine(llm, persona="p", history_store=store)
    list(engine.send("第一句"))
    list(engine.send("第二句"))

    first, second = llm.calls[0]["system"], llm.calls[1]["system"]
    assert "好感度:50/100" in first and "你目前的心情" not in first
    assert "好感度:53/100" in second and "你目前的心情:溫柔" in second


def test_the_model_is_told_how_to_write_the_tags_and_that_they_are_optional():
    llm = FakeLLM(["[happy]好。"])
    list(TurnEngine(llm, persona="p").send("嗨"))
    system = llm.calls[0]["system"]
    assert "[好感+" in system and "[心情:" in system


def test_affection_survives_a_restart_but_mood_does_not(tmp_path):
    db = tmp_path / "history.db"
    first = TurnEngine(FakeLLM(["[happy]好。[好感+3][心情:溫柔]"]), persona="p", history_store=SqliteHistory(db))
    list(first.send("嗨"))

    llm = FakeLLM(["[happy]嗨。"])
    second = TurnEngine(llm, persona="p", history_store=SqliteHistory(db))  # a new process, same file
    list(second.send("我回來了"))

    system = llm.calls[0]["system"]
    assert "好感度:53/100" in system
    assert "你目前的心情" not in system


def test_a_failed_turn_changes_neither_affection_nor_mood():
    store = InMemoryHistory()
    llm = FlakyLLM(["[happy]好。[好感+3][心情:溫柔]"], "timeout")
    engine = TurnEngine(llm, persona="p", history_store=store)
    assert isinstance(list(engine.send("嗨"))[-1], Failure)
    assert store.load_affection() == 50.0

    list(engine.send("再來"))  # the retry succeeds and only now counts
    assert store.load_affection() == 53.0


def test_a_superseded_turn_does_not_change_affection():
    store = InMemoryHistory()
    llm = SequenceLLM(["[happy]第一輪的話。[好感+5]", "[sad]第二輪的話。"])
    engine = TurnEngine(llm, persona="p", history_store=store)

    stream_a = engine.send("問題A")
    assert next(stream_a) == Sentence("第一輪的話。", "happy")
    list(engine.send("問題B"))
    assert list(stream_a) == []

    assert store.load_affection() == 50.0  # A's +5 belonged to a reply that was abandoned


# ---- affection drifts back towards neutral while the user is away (ticket 27) ----

DAY = 86400.0


class WallClock:
    """Test double for the wall clock (epoch seconds) the engine uses to tell how long the
    user has been away."""

    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


def shown_affection(llm, call=0):
    """The affection number the model was told on the given LLM call."""
    import re

    return int(re.search(r"好感度:(\d+)/100", llm.calls[call]["system"]).group(1))


def away_engine(reply="[happy]嗨。", start=80, seen_at=0.0, now=0.0, **engine_kwargs):
    store = InMemoryHistory()
    store.save_affection(start, at=seen_at)
    clock = WallClock(now)
    llm = FakeLLM([reply])
    return TurnEngine(llm, persona="p", history_store=store, wall_clock=clock, **engine_kwargs), llm, store, clock


def test_a_short_absence_does_not_change_affection():
    engine, llm, store, _ = away_engine(now=0.5 * DAY)
    list(engine.send("嗨"))
    assert shown_affection(llm) == 80


def test_after_the_grace_period_plus_one_half_life_the_gap_to_neutral_has_halved():
    engine, llm, store, _ = away_engine(now=15 * DAY)  # 1 day grace + 14 day half-life
    list(engine.send("我回來了"))
    assert shown_affection(llm) == 65  # 50 + (80 - 50) / 2


def test_low_affection_also_drifts_up_towards_neutral():
    engine, llm, _, _ = away_engine(start=20, now=15 * DAY)
    list(engine.send("我回來了"))
    assert shown_affection(llm) == 35  # 50 - (50 - 20) / 2


def test_it_never_overshoots_neutral_however_long_the_absence():
    engine, llm, store, _ = away_engine(start=80, now=3650 * DAY)
    list(engine.send("好久不見"))
    assert shown_affection(llm) == 50
    assert store.load_affection() >= 50.0

    engine, llm, store, _ = away_engine(start=10, now=3650 * DAY)
    list(engine.send("好久不見"))
    assert store.load_affection() <= 50.0


def test_the_decayed_value_is_what_the_turn_saves_and_it_is_not_decayed_again_straight_after():
    engine, llm, store, clock = away_engine(now=15 * DAY)
    list(engine.send("我回來了"))
    assert store.load_affection() == 65.0
    assert store.load_last_interaction() == 15 * DAY

    list(engine.send("再說一句"))  # no time has passed
    assert store.load_affection() == 65.0


def test_a_turns_own_change_is_applied_on_top_of_the_decayed_value():
    engine, llm, store, _ = away_engine(reply="[happy]好。[好感+3]", now=15 * DAY)
    list(engine.send("我回來了"))
    assert store.load_affection() == pytest.approx(67.1)  # 65, then +3 * (100-65)/50


def test_steady_conversation_never_decays_even_when_it_adds_up_to_a_long_time():
    engine, llm, store, clock = away_engine(now=0.0)
    for turn in range(20):
        clock.now = turn * 2 * 3600.0  # a message every two hours, for 40 hours
        list(engine.send("嗨"))
    assert store.load_affection() == 80.0  # each gap is well inside the grace period


def test_a_failed_turn_does_not_save_the_decay_and_the_retry_works_it_out_again():
    store = InMemoryHistory()
    store.save_affection(80, at=0.0)
    llm = FlakyLLM(["[happy]好。"], "timeout")
    engine = TurnEngine(llm, persona="p", history_store=store, wall_clock=WallClock(15 * DAY))
    assert isinstance(list(engine.send("嗨"))[-1], Failure)
    assert store.load_affection() == 80.0 and store.load_last_interaction() == 0.0

    list(engine.send("嗨"))
    assert store.load_affection() == 65.0


def test_grace_period_and_half_life_are_configurable():
    engine, llm, _, _ = away_engine(now=1 * DAY, affection_grace_s=0.0, affection_half_life_s=1 * DAY)
    list(engine.send("嗨"))
    assert shown_affection(llm) == 65


def test_a_half_life_of_zero_switches_decay_off():
    engine, llm, _, _ = away_engine(now=1000 * DAY, affection_half_life_s=0)
    list(engine.send("嗨"))
    assert shown_affection(llm) == 80


def test_with_no_recorded_last_interaction_nothing_decays():
    store = InMemoryHistory()
    store.save_affection(80)  # e.g. a relationship recorded before this feature existed
    llm = FakeLLM(["[happy]嗨。"])
    list(TurnEngine(llm, persona="p", history_store=store, wall_clock=WallClock(1000 * DAY)).send("嗨"))
    assert shown_affection(llm) == 80


def test_a_clock_that_moved_backwards_does_not_decay_anything():
    engine, llm, _, _ = away_engine(seen_at=100 * DAY, now=0.0)
    list(engine.send("嗨"))
    assert shown_affection(llm) == 80


def test_decay_does_not_depend_on_the_background_summary_job_ever_running():
    jobs = []
    engine, llm, _, _ = away_engine(now=15 * DAY, summarize=True, background=jobs.append)  # never runs them
    list(engine.send("嗨"))
    assert shown_affection(llm) == 65


def test_the_last_interaction_time_survives_a_restart(tmp_path):
    db = tmp_path / "history.db"
    first = TurnEngine(FakeLLM(["[happy]嗨。"]), persona="p", history_store=SqliteHistory(db),
                       wall_clock=WallClock(1000.0))
    list(first.send("嗨"))
    assert SqliteHistory(db).load_last_interaction() == 1000.0


# ---- proactive speaking (ticket 29) ----


class FakeScheduler:
    """Test double for the delayed-call boundary: records every (delay_s, fn) it was asked to
    schedule, and every cancel() call, without ever running anything on its own. The test
    fires a job by calling its captured `fn` directly."""

    def __init__(self):
        self.scheduled = []  # [(delay_s, fn)], oldest first
        self.cancelled = 0

    def __call__(self, delay_s, fn):
        self.scheduled.append((delay_s, fn))
        cancelled = []

        def cancel():
            cancelled.append(True)
            self.cancelled += 1

        return cancel

    def fire_latest(self):
        self.scheduled[-1][1]()


def proactive_engine(reply, min_idle_s=600, max_idle_s=1200, **kwargs):
    scheduler = FakeScheduler()
    sent = []
    store = InMemoryHistory()
    engine = TurnEngine(FakeLLM([reply]), persona="p", history_store=store, scheduler=scheduler,
                        proactive_idle_range_s=(min_idle_s, max_idle_s), on_proactive=sent.append, **kwargs)
    return engine, scheduler, sent, store


def test_enabling_proactive_mode_schedules_one_attempt_within_the_configured_range():
    engine, scheduler, _, _ = proactive_engine("[happy]嗨。", min_idle_s=600, max_idle_s=1200)
    assert scheduler.scheduled == []

    engine.set_proactive(True)

    assert len(scheduler.scheduled) == 1
    assert 600 <= scheduler.scheduled[0][0] <= 1200


def test_when_it_fires_the_reply_goes_through_the_normal_events_and_out_the_on_proactive_hook():
    engine, scheduler, sent, _ = proactive_engine("[happy]晚安,今天過得好嗎?")
    engine.set_proactive(True)

    scheduler.fire_latest()

    assert Sentence("晚安,今天過得好嗎?", "happy") in sent
    assert isinstance(sent[-1], Done)


def test_the_proactive_prompt_is_never_shown_in_history_but_the_reply_is():
    engine, scheduler, _, store = proactive_engine("[happy]在想你在做什麼。")
    engine.set_proactive(True)
    scheduler.fire_latest()

    assert engine.history() == [{"role": "assistant", "text": "在想你在做什麼。", "emotions": ["happy"]}]
    assert len(store.load()) == 2  # still saved as a normal user/assistant pair, just filtered for display


def test_the_model_is_told_this_is_its_own_idea_and_that_silence_is_fine():
    engine, scheduler, _, _ = proactive_engine("[happy]嗨。")
    engine.set_proactive(True)
    scheduler.fire_latest()

    llm = engine._llm
    prompt = llm.calls[0]["messages"][-1]["content"]
    assert "不是使用者" in llm.calls[0]["system"] or "不是使用者" in prompt


def test_choosing_not_to_speak_saves_nothing_and_calls_the_hook_with_nothing():
    engine, scheduler, sent, store = proactive_engine("")  # the model wrote nothing
    engine.set_proactive(True)
    scheduler.fire_latest()

    assert sent == []
    assert store.load() == []
    assert engine.history() == []


def test_only_a_few_tags_and_no_actual_words_also_counts_as_choosing_silence():
    engine, scheduler, sent, store = proactive_engine("[happy][sad]")
    engine.set_proactive(True)
    scheduler.fire_latest()

    assert sent == []
    assert store.load() == []


def test_after_a_reply_the_next_attempt_is_scheduled_again():
    engine, scheduler, _, _ = proactive_engine("[happy]嗨。")
    engine.set_proactive(True)
    scheduler.fire_latest()

    assert len(scheduler.scheduled) == 2  # the original firing, plus a fresh one after it


def test_after_choosing_silence_the_next_attempt_is_still_scheduled():
    engine, scheduler, _, _ = proactive_engine("")
    engine.set_proactive(True)
    scheduler.fire_latest()

    assert len(scheduler.scheduled) == 2


def test_an_ordinary_user_message_resets_the_idle_clock_too():
    engine, scheduler, _, _ = proactive_engine("[happy]好。")
    engine.set_proactive(True)
    assert len(scheduler.scheduled) == 1

    list(engine.send("嗨"))  # an ordinary message, not the scheduled one firing

    assert len(scheduler.scheduled) == 2
    assert scheduler.cancelled == 1  # the old pending attempt is cancelled, not left to also fire later


def test_turning_it_off_cancels_the_pending_attempt_and_nothing_fires_after():
    engine, scheduler, sent, store = proactive_engine("[happy]嗨。")
    engine.set_proactive(True)
    pending = scheduler.scheduled[0][1]

    engine.set_proactive(False)
    assert scheduler.cancelled == 1

    pending()  # simulates a timer that was already in flight the instant it was turned off
    assert sent == []
    assert store.load() == []


def test_turning_it_off_and_back_on_does_not_leave_two_pending_attempts():
    engine, scheduler, _, _ = proactive_engine("[happy]嗨。")
    engine.set_proactive(True)
    engine.set_proactive(False)
    engine.set_proactive(True)
    assert scheduler.cancelled == 1
    assert len(scheduler.scheduled) == 2  # the first (cancelled) one, and the new one


def test_it_is_off_by_default_and_an_ordinary_conversation_never_schedules_anything():
    engine, scheduler, sent, _ = proactive_engine("[happy]嗨。")
    list(engine.send("嗨"))
    assert scheduler.scheduled == []
    assert sent == []


def test_the_user_speaking_while_a_proactive_reply_is_still_generating_is_an_ordinary_interruption():
    scheduler = FakeScheduler()
    sent = []
    llm = SequenceLLM(["[happy]我正在主動說話", "[sad]這是使用者打斷後的新回覆。"])
    store = InMemoryHistory()
    engine = TurnEngine(llm, persona="p", history_store=store, scheduler=scheduler,
                        proactive_idle_range_s=(1, 1), on_proactive=sent.append)
    engine.set_proactive(True)

    # The proactive attempt starts generating (mid-stream, not finished) when the user barges in.
    proactive_stream = engine._attempt_proactive_stream()
    next(proactive_stream)
    events = list(engine.send("等等我在跟你說話"))

    assert list(proactive_stream) == []  # the superseded proactive turn quietly abandons
    assert Sentence("這是使用者打斷後的新回覆。", "sad") in events
    assert store.load()[-1]["content"] == "[sad]這是使用者打斷後的新回覆。"


def test_a_failed_proactive_attempt_changes_nothing_and_is_not_shown():
    scheduler = FakeScheduler()
    sent = []
    store = InMemoryHistory()
    llm = FlakyLLM(["[happy]嗨。"], "timeout")
    engine = TurnEngine(llm, persona="p", history_store=store, scheduler=scheduler,
                        proactive_idle_range_s=(1, 1), on_proactive=sent.append)
    engine.set_proactive(True)

    scheduler.fire_latest()

    assert sent == []
    assert store.load() == []


def test_disabling_when_nothing_was_ever_enabled_does_not_error():
    engine, scheduler, _, _ = proactive_engine("[happy]嗨。")
    engine.set_proactive(False)  # never was on
    assert scheduler.cancelled == 0


def test_the_real_scheduler_actually_schedules_a_call_and_can_cancel_it():
    # The one part of this feature that cannot go through TurnEngine's fakes: check the default
    # scheduler itself uses real timers correctly (short delay, and cancellable).
    import time as time_module

    from companion.engine import _real_scheduler

    fired = []
    cancel = _real_scheduler(0.02, lambda: fired.append(True))
    time_module.sleep(0.06)
    assert fired == [True]

    fired.clear()
    cancel2 = _real_scheduler(0.02, lambda: fired.append(True))
    cancel2()
    time_module.sleep(0.06)
    assert fired == []


# ---- image attachments (ticket 30) ----

from companion.engine import UserImage  # noqa: E402

PHOTO = UserImage(b"\x89PNG\r\n\x1a\n...fake-bytes...", "image/png")


def test_an_attached_image_is_sent_to_the_model_alongside_the_text():
    llm = FakeLLM(["[happy]好可愛的貓!"])
    list(TurnEngine(llm, persona="p").send("你看我家貓", image=PHOTO))
    last = llm.calls[0]["messages"][-1]
    assert last["content"] == "你看我家貓"
    assert last["image"] is PHOTO


def test_a_message_without_an_image_has_no_image_key_at_all():
    # Regression: the ordinary path's message shape must be byte-for-byte what it was before
    # this ticket, not merely "image is None" — some future _parts()-style code might do
    # `"image" in message` rather than `.get("image")`.
    llm = FakeLLM(["[happy]嗨。"])
    list(TurnEngine(llm, persona="p").send("嗨"))
    assert "image" not in llm.calls[0]["messages"][-1]


def test_history_shows_that_a_message_had_an_image_but_never_the_bytes():
    engine = TurnEngine(FakeLLM(["[happy]好可愛!"]), persona="p")
    list(engine.send("你看我家貓", image=PHOTO))

    assert engine.history()[0] == {"role": "user", "text": "你看我家貓", "has_image": True}
    stored = engine._store.load()[0]["content"]
    assert PHOTO.data not in stored.encode("utf-8", "ignore")  # the raw bytes are never persisted


def test_an_image_with_no_typed_text_is_allowed():
    engine = TurnEngine(FakeLLM(["[happy]這是誰呀?"]), persona="p")
    list(engine.send("", image=PHOTO))
    assert engine.history()[0] == {"role": "user", "text": "", "has_image": True}


def test_a_later_turn_replays_an_earlier_images_marker_as_text_not_the_original_bytes():
    llm = FakeLLM(["[happy]好可愛!", "[happy]牠幾歲了?"])
    engine = TurnEngine(llm, persona="p")
    list(engine.send("你看我家貓", image=PHOTO))
    list(engine.send("三歲"))

    earlier_user_message = llm.calls[1]["messages"][0]
    assert "image" not in earlier_user_message  # not resent: cost stays bounded as history grows
    assert "你看我家貓" in earlier_user_message["content"]


def test_a_failed_turn_with_an_image_saves_nothing():
    llm = FlakyLLM(["[happy]好可愛!"], "timeout")
    engine = TurnEngine(llm, persona="p")
    assert isinstance(list(engine.send("你看", image=PHOTO))[-1], Failure)
    assert engine.history() == []


# ---- a stray escape character the model sometimes writes in front of a tag -------------------------------------------

def test_a_lone_backslash_before_the_next_tag_is_not_a_sentence_of_its_own():
    events = list(TurnEngine(FakeLLM(["[happy]第一句。\n\\[neutral]第二句。"]), persona="p").send("嗨"))
    assert [e.text for e in events if isinstance(e, Sentence)] == ["第一句。", "第二句。"]


def test_a_backslash_left_at_the_very_end_is_not_a_sentence_either():
    events = list(TurnEngine(FakeLLM(["[happy]第一句。\n\\"]), persona="p").send("嗨"))
    assert [e.text for e in events if isinstance(e, Sentence)] == ["第一句。"]


def test_a_backslash_stuck_to_real_words_is_removed_from_them():
    events = list(TurnEngine(FakeLLM(["[happy]第一句\\[neutral]第二句。"]), persona="p").send("嗨"))
    assert [e.text for e in events if isinstance(e, Sentence)] == ["第一句", "第二句。"]
