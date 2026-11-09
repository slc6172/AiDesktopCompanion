"""She decides to look something up herself by opening a reply with [搜尋:關鍵字] (spec Part 12, section 4,
ticket 85). The moment the tag is read, the rest of that first pass is thrown away unspoken, the search is made,
and a second pass answers from what was found."""
import pytest

from companion.engine import Done, Notice, Sentence, TurnEngine
from companion.history import InMemoryHistory
from companion.tinyfish_adapter import SearchUnavailable

RESULTS = [{"title": "台北今日天氣", "snippet": "多雲時晴,氣溫 24 度。", "url": "https://news.example.com/w"}]


class FakeSearch:
    def __init__(self, results=RESULTS, error=None):
        self.results, self.error, self.queries = results, error, []

    def search(self, query):
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.results


class SequenceLLM:
    """Each model call answers with the next scripted reply (a string or a list of chunks)."""

    def __init__(self, *replies):
        self.replies, self.systems, self.closed = list(replies), [], 0

    def stream(self, system, messages):
        self.systems.append(system)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        chunks = [reply] if isinstance(reply, str) else reply
        try:
            yield from chunks
        finally:
            self.closed += 1

    def generate_structured(self, *args):
        return None


def build(*replies, search=None, store=None, **kwargs):
    search = FakeSearch() if search is None else search
    llm = SequenceLLM(*replies)
    store = store if store is not None else InMemoryHistory()
    engine = TurnEngine(llm, persona="p", history_store=store, search=search, nonce_factory=lambda: "N0NCE",
                        search_settings={"max_results": 5, "blocked_domains": [], "cooldown_s": 20}, **kwargs)
    return engine, llm, search, store


def say(engine, text="今天台北天氣怎麼樣", **kwargs):
    return list(engine.send(text, **kwargs))


FIRST = "[搜尋:台北今天天氣]我猜應該是晴天吧,不過我不太確定,你自己看看。"
SECOND = "[neutral]查到了,多雲時晴,24 度。"


def test_the_tag_ends_the_first_pass_unspoken_and_a_second_pass_answers_from_the_results():
    engine, llm, search, _ = build(FIRST, SECOND)
    events = say(engine)
    assert events == [Notice("search", "🔍 查詢:台北今天天氣"), Sentence("查到了,多雲時晴,24 度。", "neutral"), Done()]
    assert search.queries == ["台北今天天氣"] and len(llm.systems) == 2
    assert "多雲時晴" not in llm.systems[0] and "多雲時晴" in llm.systems[1] and "<<<DATA-N0NCE" in llm.systems[1]


def test_nothing_of_the_first_pass_is_spoken_or_kept_not_even_what_came_in_the_same_chunk_as_the_tag():
    engine, _, _, store = build(FIRST, SECOND)
    say(engine)
    assert "我猜應該是晴天" not in str(store.load())
    assert store.load()[1]["content"] == "[搜尋:台北今天天氣]" + SECOND


def test_the_first_pass_is_actually_stopped_not_just_ignored():
    engine, llm, _, _ = build(["[搜尋:台北今天天氣]", "我猜應該", "是晴天。"] + ["很長"] * 50, SECOND)
    say(engine)
    assert llm.closed == 2                          # the first stream was closed as soon as the tag was read


def test_the_tag_may_come_in_pieces_and_may_follow_an_emotion_tag():
    engine, _, search, _ = build(["[happy][搜", "尋:台北今", "天天氣]先說一句。"], SECOND)
    events = say(engine)
    assert search.queries == ["台北今天天氣"] and events[0] == Notice("search", "🔍 查詢:台北今天天氣")
    assert [e.text for e in events if isinstance(e, Sentence)] == ["查到了,多雲時晴,24 度。"]


def test_a_reply_made_only_of_the_tag_still_searches():
    engine, _, search, _ = build("[搜尋:台北今天天氣]", SECOND)
    events = say(engine)
    assert search.queries == ["台北今天天氣"] and Sentence("查到了,多雲時晴,24 度。", "neutral") in events


def test_a_tag_in_the_middle_of_a_reply_searches_nothing_and_is_not_spoken():
    engine, llm, search, _ = build("我想想。[搜尋:台北今天天氣]大概晴天。")
    events = say(engine)
    assert search.queries == [] and len(llm.systems) == 1
    assert [e.text for e in events if isinstance(e, Sentence)] == ["我想想。", "大概晴天。"]


def test_a_search_stands_alone_so_other_actions_written_with_it_are_dropped():
    calls = []
    engine, _, _, _ = build("[換裝:睡衣][搜尋:台北今天天氣]好。", SECOND, tag_handlers={"換裝": calls.append})
    say(engine)
    assert calls == []


# ---- only once ---------------------------------------------------------------------------------------------------

def test_a_second_search_tag_in_the_answer_is_ignored_so_searches_never_chain():
    engine, llm, search, _ = build(FIRST, "[搜尋:別的東西][neutral]查到了。")
    events = say(engine)
    assert search.queries == ["台北今天天氣"] and len(llm.systems) == 2
    assert [e.text for e in events if isinstance(e, Sentence)] == ["查到了。"]


def test_even_after_a_failed_search_she_cannot_ask_again():
    engine, llm, search, _ = build(FIRST, "[搜尋:再試一次][sad]查不到耶。", search=FakeSearch(error=SearchUnavailable("rate limited")))
    events = say(engine)
    assert len(search.queries) == 1 and len(llm.systems) == 2 and "連不上網" in llm.systems[1]
    assert [e.text for e in events if isinstance(e, Sentence)] == ["查不到耶。"]


def test_the_answer_after_a_search_has_every_tag_but_the_mood_ignored():
    calls = []
    engine, llm, _, store = build(FIRST, "[換裝:睡衣][照片:現在|x][好感+5][心情:雀躍]好。", tag_handlers={"換裝": calls.append, "照片": calls.append})
    store.save_affection(50.0)
    say(engine)
    assert calls == [] and store.load_affection() == 50.0
    say(engine, "再說")                                             # (an ordinary turn again: the mood she named is now hers)
    assert "你目前的心情:雀躍" in llm.systems[-1]
    assert store.load_polluted()[:2] == [True, True]            # and the turn is marked as one that used the web


# ---- a tag that cannot be acted on ----------------------------------------------------------------------------------

@pytest.mark.parametrize("payload", ["", " ", "a"])
def test_a_tag_with_nothing_worth_looking_up_is_ignored_and_the_reply_goes_on(payload):
    engine, llm, search, _ = build(f"[搜尋:{payload}]好,我直接回答。")
    events = say(engine)
    assert search.queries == [] and len(llm.systems) == 1
    assert [e.text for e in events if isinstance(e, Sentence)] == ["好,我直接回答。"]


def test_what_she_wrote_is_only_ever_a_search_word_never_an_address_to_visit():
    engine, _, search, _ = build("[搜尋:https://evil.example/steal?x=1 這個網站]好。", SECOND)
    say(engine)
    assert len(search.queries) == 1
    assert search.queries == ["https://evil.example/steal?x=1 這個網站"]        # handed to the search engine as words, nothing else


def test_the_search_words_are_cut_to_a_hundred_characters():
    engine, _, search, _ = build("[搜尋:" + "字" * 110 + "]好。", SECOND)
    say(engine)
    assert len(search.queries[0]) == 100


def test_without_search_available_the_tag_is_just_removed_and_she_goes_on_speaking():
    llm = SequenceLLM(FIRST)
    engine = TurnEngine(llm, persona="p", history_store=InMemoryHistory())
    events = say(engine)
    assert [e.text for e in events if isinstance(e, Sentence)] == ["我猜應該是晴天吧,不過我不太確定,你自己看看。"]
    assert len(llm.systems) == 1


def test_a_proactive_turn_cannot_start_a_search():
    from companion.engine import PROACTIVE_TRIGGER

    engine, llm, search, _ = build("[搜尋:台北今天天氣]我來打聲招呼。")
    events = say(engine, PROACTIVE_TRIGGER)
    assert search.queries == [] and len(llm.systems) == 1
    assert "【上網查資料】" not in llm.systems[0]


# ---- telling her it exists -----------------------------------------------------------------------------------------------

def test_when_search_is_available_she_is_told_when_and_how_to_use_the_tag():
    engine, llm, _, _ = build("[neutral]好。")
    say(engine)
    system = llm.systems[0]
    assert "【上網查資料】" in system and "[搜尋:關鍵字]" in system and "最一開頭" in system


def test_when_search_is_not_available_she_is_not_told_about_it_at_all():
    llm = SequenceLLM("[neutral]好。")
    say(TurnEngine(llm, persona="p", history_store=InMemoryHistory()))
    assert "【上網查資料】" not in llm.systems[0] and "[搜尋" not in llm.systems[0]


def test_on_a_turn_where_the_search_already_happened_the_tag_is_no_longer_explained():
    engine, llm, _, _ = build("[neutral]好。")
    say(engine, "上網查台北今天的天氣")
    assert "【上網查資料】" not in llm.systems[0]


def test_the_second_pass_does_not_carry_the_explanation_of_the_tag():
    engine, llm, _, _ = build(FIRST, SECOND)
    say(engine)
    assert "【上網查資料】" in llm.systems[0] and "【上網查資料】" not in llm.systems[1]
