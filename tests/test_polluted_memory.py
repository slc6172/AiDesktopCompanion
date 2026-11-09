"""A turn that used the web is never a source of memory (spec Part 12, sections 4 and 8, ticket 87). Whatever a page
managed to put into her reply stays out of what is folded into long-term facts and out of what is looked up later;
the only trace is that she looked something up, and what the user asked for."""
from companion import timesense
from companion.engine import POLLUTED_PLACEHOLDER, TurnEngine
from companion.history import InMemoryHistory

NOW = 1_800_000_000.0
DAY = 86400.0
WEB_FACT = "獨特網頁內容XYZ"
TODAY = f"{timesense.local_datetime(NOW, None):%Y-%m-%d}"


class FakeSearch:
    def search(self, query):
        return [{"title": "標題", "snippet": WEB_FACT, "url": "https://news.example.com/w"}]


class Llm:
    """Chats (the reply for a search turn mentions what the page said) and records every folding request."""

    def __init__(self, fold_answer=None):
        self.fold_requests, self.fold_answer = [], fold_answer
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        searched = "【網路搜尋】" in system
        yield f"[neutral]網頁說{WEB_FACT}。" if searched else "[neutral]好的。"

    def generate_structured(self, system, messages, schema):
        self.fold_requests.append(messages[0]["content"])
        return self.fold_answer or {"events": [], "facts": {"user": ["使用者喜歡貓"], "shared": [], "self": [], "followups": []}}


def build(memory=True, store=None, fold_answer=None):
    llm = Llm(fold_answer)
    store = store if store is not None else InMemoryHistory()
    engine = TurnEngine(llm, persona="p", history_store=store, summarize=memory, max_turns=3, summary_batch=2,
                        background=lambda fn: fn(), wall_clock=lambda: NOW, search=FakeSearch(),
                        memory_settings={"long_term_max_chars": 2000, "recent_notes_max_chars": 600})
    return engine, llm, store


def chat(engine, *messages):
    for message in messages:
        list(engine.send(message))


# ---- folding -----------------------------------------------------------------------------------------------

def test_what_a_search_turn_said_never_reaches_the_folding_call_only_that_she_looked_something_up():
    engine, llm, _ = build()
    chat(engine, "上網查台北天氣", "謝謝", "再問你", "還有一個", "最後一個")
    request = llm.fold_requests[0]
    assert WEB_FACT not in request
    assert "上網查台北天氣" in request                                  # what the user said stays
    assert POLLUTED_PLACEHOLDER.format(query="台北天氣") in request


def test_the_other_turns_are_folded_as_before():
    engine, llm, _ = build()
    chat(engine, "上網查台北天氣", "謝謝", "再問你", "還有一個", "最後一個")
    assert "角色:好的。" in llm.fold_requests[0]


def test_the_long_term_facts_cannot_contain_what_the_page_said_since_the_folding_call_never_saw_it():
    engine, llm, store = build()
    chat(engine, "上網查台北天氣", "謝謝", "再問你", "還有一個", "最後一個")
    assert WEB_FACT not in str(store.load_facts())


def test_a_polluted_turn_without_a_note_of_what_was_looked_up_is_still_kept_out():
    store = InMemoryHistory()
    store.append_turn("隨便問問", f"[neutral]有人說{WEB_FACT}。", at=NOW - 3 * DAY, polluted=True)
    engine, llm, _ = build(store=store)
    chat(engine, "一", "二", "三", "四")
    request = llm.fold_requests[0]
    assert WEB_FACT not in request and "網頁內容未納入" in request and "隨便問問" in request


def test_what_the_user_wrote_in_a_polluted_turn_is_still_folded():
    store = InMemoryHistory()
    store.append_turn("我下週三要面試,幫我查一下流程", f"[搜尋:面試流程][neutral]網頁說{WEB_FACT}。", at=NOW - 3 * DAY, polluted=True)
    engine, llm, _ = build(store=store)
    chat(engine, "一", "二", "三", "四")
    assert "我下週三要面試" in llm.fold_requests[0]


# ---- the journal ---------------------------------------------------------------------------------------------

def test_the_program_notes_in_the_journal_that_she_looked_something_up_with_only_the_users_own_words():
    engine, _, store = build()
    chat(engine, "上網查台北天氣")
    assert [e["text"] for e in store.load_all_events()] == ["查過:台北天氣"]
    assert store.load_all_events()[0]["date"] == TODAY and WEB_FACT not in str(store.load_all_events())


def test_a_search_that_could_not_be_made_leaves_no_journal_line():
    class Down:
        def search(self, query):
            raise RuntimeError("down")

    llm = Llm()
    store = InMemoryHistory()
    engine = TurnEngine(llm, persona="p", history_store=store, summarize=True, wall_clock=lambda: NOW, search=Down())
    chat(engine, "上網查台北天氣")
    assert store.load_all_events() == []


def test_with_memory_switched_off_nothing_is_written():
    engine, _, store = build(memory=False)
    chat(engine, "上網查台北天氣")
    assert store.load_all_events() == []


# ---- looking things up later --------------------------------------------------------------------------------------

def test_a_polluted_reply_is_never_dug_up_again_but_what_the_user_said_can_be():
    store = InMemoryHistory()
    store.append_turn("我在學潛水證照", f"[neutral]網頁說潛水證照很貴,{WEB_FACT}。", at=NOW - 60 * DAY, polluted=True)
    for n in range(4):
        store.append_turn(f"閒聊{n}", "[neutral]嗯。", at=NOW - 3600 + n)
    engine, llm, _ = build(store=store)
    list(engine.send("潛水證照學得怎麼樣"))
    system = llm.systems[-1]
    found = system.split("【可能相關的記憶】")[1] if "【可能相關的記憶】" in system else ""
    assert "我在學潛水證照" in found and WEB_FACT not in system.split("【可能相關的記憶】")[-1]


def test_an_ordinary_old_reply_is_still_found():
    store = InMemoryHistory()
    store.append_turn("你今天想做什麼", "[neutral]我想去爬山看日出。", at=NOW - 60 * DAY)
    for n in range(4):
        store.append_turn(f"閒聊{n}", "[neutral]嗯。", at=NOW - 3600 + n)
    engine, llm, _ = build(store=store)
    list(engine.send("你上次說想爬山"))
    assert "爬山看日出" in llm.systems[-1].split("【可能相關的記憶】")[1]
