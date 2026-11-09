"""She decides to change clothes herself by opening a reply with [換裝:服裝名] (spec Part 12,
ticket 76) — in conversation or on her own initiative."""
import pytest

from companion.engine import Done, OutfitChange, PROACTIVE_TRIGGER, Sentence, TurnEngine
from companion.history import InMemoryHistory
from companion.outfits import Wardrobe
from companion.state import InMemoryState


class ScriptedLLM:
    def __init__(self, reply):
        self.reply = reply
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        yield self.reply


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def __call__(self, delay_s, fn):
        self.jobs.append(fn)
        return lambda: None


@pytest.fixture
def closet(tmp_path):
    clips = tmp_path / "clips"
    names = ["日常", "睡衣"]

    def build(reply, outfits=names, **engine_kwargs):
        for name in outfits:
            (clips / name).mkdir(parents=True, exist_ok=True)
            (clips / name / "idle.webm").write_bytes(b"v")
        state = InMemoryState()
        llm = ScriptedLLM(reply)
        settings = {"default": "日常", "aliases": {"睡衣": ["睡袍", "pajamas"]}}
        engine = TurnEngine(llm, persona="p", history_store=InMemoryHistory(),
                            wardrobe=Wardrobe(clips, state, settings=lambda: settings), **engine_kwargs)
        return engine, llm, state

    return build


def worn(state):
    return state.load()["outfit"]


def changes(events):
    return [e for e in events if isinstance(e, OutfitChange)]


def test_a_tag_at_the_start_changes_her_clothes_before_she_speaks(closet):
    engine, _, state = closet("[換裝:睡衣][happy]好,我去換!")
    events = list(engine.send("晚安"))
    assert [type(e).__name__ for e in events][:2] == ["OutfitChange", "Sentence"]
    assert events[0].name == "睡衣" and worn(state) == "睡衣"


@pytest.mark.parametrize("written", ["睡袍", "PAJAMAS", " 睡衣 "])
def test_an_alias_or_a_different_spelling_of_the_name_works_too(closet, written):
    engine, _, state = closet(f"[換裝:{written}]好。")
    list(engine.send("嗨"))
    assert worn(state) == "睡衣"


def test_a_name_she_does_not_own_is_ignored_and_she_still_speaks(closet):
    engine, _, state = closet("[換裝:蕾絲]好。")
    events = list(engine.send("嗨"))
    assert changes(events) == [] and worn(state) is None
    assert events == [Sentence("好。", "neutral"), Done()]


def test_a_tag_in_the_middle_of_a_reply_changes_nothing(closet):
    engine, _, state = closet("好啊。[換裝:睡衣]等我。")
    assert changes(list(engine.send("嗨"))) == [] and worn(state) is None


def test_choosing_what_she_already_wears_sends_no_event(closet):
    engine, _, _ = closet("[換裝:日常]好。")
    assert changes(list(engine.send("嗨"))) == []


def test_the_user_asking_and_her_tag_in_the_same_turn_change_clothes_once(closet):
    engine, _, state = closet("[換裝:睡衣]好,換好了。")
    assert len(changes(list(engine.send("換成睡衣")))) == 1 and worn(state) == "睡衣"


def test_on_a_polluted_turn_the_tag_is_ignored(closet):
    engine, _, state = closet("[換裝:睡衣]好。")
    assert changes(list(engine.send("嗨", polluted=True))) == [] and worn(state) is None


# ---- telling her the tag exists ------------------------------------------------------------------------------

def test_with_more_than_one_outfit_she_is_told_how_to_change(closet):
    engine, llm, _ = closet("好。")
    list(engine.send("嗨"))
    assert "[換裝:服裝名]" in llm.systems[0]


def test_with_a_single_outfit_the_tag_is_not_mentioned_at_all(closet):
    engine, llm, _ = closet("好。", outfits=["日常"])
    list(engine.send("嗨"))
    assert "[換裝" not in llm.systems[0]


# ---- on her own initiative ----------------------------------------------------------------------------------

def proactive(closet, reply):
    scheduler, sent = FakeScheduler(), []
    engine, llm, state = closet(reply, scheduler=scheduler, on_proactive=sent.append,
                                proactive_idle_range_s=(600, 1200))
    engine.set_proactive(True)
    scheduler.jobs[-1]()
    return sent, state


def test_when_she_changes_while_speaking_up_the_page_gets_the_outfit_event_with_her_words(closet):
    sent, state = proactive(closet, "[換裝:睡衣][happy]我去換睡衣囉。")
    assert [type(e).__name__ for e in sent][:2] == ["OutfitChange", "Sentence"] and worn(state) == "睡衣"


def test_when_she_changes_without_saying_anything_the_page_still_hears_about_it(closet):
    sent, state = proactive(closet, "[換裝:睡衣]")
    assert [e.name for e in changes(sent)] == ["睡衣"] and worn(state) == "睡衣"
    assert not any(isinstance(e, Sentence) for e in sent)


def test_a_silent_attempt_that_changes_nothing_sends_nothing(closet):
    sent, _ = proactive(closet, "")
    assert sent == []
