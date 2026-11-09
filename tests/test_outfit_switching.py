"""Changing clothes by asking (spec Part 12, ticket 74): "換成睡衣" really changes what she
wears — remembered across restarts — and a request for something she does not own is left to her
to answer in her own voice. Observed through the turn engine's event stream and the prompt it sends."""
import pytest

from companion.engine import Done, OutfitChange, Sentence, TurnEngine
from companion.history import InMemoryHistory
from companion.outfits import Wardrobe
from companion.state import InMemoryState


class SpyLLM:
    def __init__(self):
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        yield "好啊。"


@pytest.fixture
def closet(tmp_path):
    """clips/ with two outfits. `build()` returns (engine, llm, state); calling it again with the
    same state is a restart."""
    clips = tmp_path / "clips"
    for name, extra in (("日常", None), ("睡衣", "a soft cotton pajama set")):
        (clips / name).mkdir(parents=True)
        (clips / name / "idle.webm").write_bytes(b"v")
        (clips / name / "talking-happy.webm").write_bytes(b"v")
        if extra:
            (clips / name / "outfit.txt").write_text(extra + "\n", encoding="utf-8")
    state = InMemoryState()

    def build(state=state, settings=None, extra_folders=()):
        for folder in extra_folders:
            (clips / folder).mkdir(exist_ok=True)
            (clips / folder / "idle.webm").write_bytes(b"v")
        settings = settings or {"default": "日常", "aliases": {"睡衣": ["睡袍", "pajamas"]}}
        llm = SpyLLM()
        engine = TurnEngine(llm, persona="p", history_store=InMemoryHistory(),
                            wardrobe=Wardrobe(clips, state, settings=lambda: settings))
        return engine, llm, state

    build.state = state
    return build


def say(engine, text):
    return list(engine.send(text))


def worn(state):
    return state.load()["outfit"]


# ---- the request is understood ------------------------------------------------------------------

def test_asking_to_change_really_changes_her_clothes_and_the_page_is_told_before_she_answers(closet):
    engine, llm, state = closet()
    events = say(engine, "換成睡衣")
    assert events[0] == OutfitChange("睡衣", {"idle": "/clips/%E7%9D%A1%E8%A1%A3/idle.webm",
                                              "talking:happy": "/clips/%E7%9D%A1%E8%A1%A3/talking-happy.webm"})
    assert events[1:] == [Sentence("好啊。", "neutral"), Done()]
    assert worn(state) == "睡衣"


def test_the_new_outfit_is_remembered_after_a_restart(closet):
    engine, _, state = closet()
    say(engine, "換成睡衣")
    restarted, llm, _ = closet(state=state)
    say(restarted, "嗨")
    assert "你目前穿著:睡衣" in llm.systems[0]


@pytest.mark.parametrize("request_text", ["穿上睡袍", "換上 pajamas", "請換成睡衣", "幫我換成睡衣吧", "穿睡衣!", "換睡衣喔"])
def test_short_clear_requests_by_name_or_alias_all_work(closet, request_text):
    engine, _, state = closet()
    assert any(isinstance(e, OutfitChange) for e in say(engine, request_text))
    assert worn(state) == "睡衣"


@pytest.mark.parametrize("not_a_request", [
    "你覺得換成睡衣好嗎?", "不要換成睡衣", "別穿睡衣", "換成睡衣好不好", "你今天穿睡衣好看",
    "我昨天看到有人穿睡衣上班", "睡衣是什麼材質", "換成睡衣了嗎", "可不可以換成睡衣", "你有睡衣嗎",
    "換成睡衣好看",            # nothing but a trailing remark blocks this one
    "我不用換成睡衣",           # nothing but what stands in front of the verb blocks this one
])
def test_questions_refusals_and_chatter_never_change_her_clothes(closet, not_a_request):
    engine, _, state = closet()
    assert not any(isinstance(e, OutfitChange) for e in say(engine, not_a_request))
    assert worn(state) is None


def test_when_one_outfit_name_contains_another_the_longest_name_wins(closet):
    engine, _, state = closet(extra_folders=("睡衣外套",))
    say(engine, "換成睡衣外套")
    assert worn(state) == "睡衣外套"
    say(engine, "換成睡衣")
    assert worn(state) == "睡衣"


def test_asking_for_what_she_already_wears_changes_nothing_and_sends_no_event(closet):
    engine, _, state = closet()
    say(engine, "換成睡衣")
    assert not any(isinstance(e, OutfitChange) for e in say(engine, "換成睡衣"))


def test_a_proactive_turn_never_changes_clothes_even_if_her_own_prompt_read_like_a_request(closet, monkeypatch):
    from companion import engine as engine_module

    monkeypatch.setattr(engine_module, "PROACTIVE_PROMPT", "換成睡衣")   # worst case: her own words look like an order
    engine, _, state = closet()
    say(engine, engine_module.PROACTIVE_TRIGGER)
    assert worn(state) is None


# ---- what she is told ----------------------------------------------------------------------------------------

def test_she_is_told_what_she_wears_and_what_else_she_owns(closet):
    engine, llm, _ = closet()
    say(engine, "嗨")
    system = llm.systems[0]
    assert "你目前穿著:日常" in system
    assert "日常" in system and "睡衣" in system.split("你可以換的服裝")[1]


def test_the_one_line_description_of_the_outfit_reaches_her(closet):
    engine, llm, _ = closet()
    say(engine, "換成睡衣")
    assert "a soft cotton pajama set" in llm.systems[0]


def test_after_a_request_she_is_told_it_was_done(closet):
    engine, llm, _ = closet()
    say(engine, "換成睡衣")
    assert "使用者剛請你換成『睡衣』,已換好" in llm.systems[0]
    say(engine, "謝謝")
    assert "已換好" not in llm.systems[1]


def test_asking_for_clothes_she_does_not_own_changes_nothing_and_the_list_is_in_front_of_her(closet):
    engine, llm, state = closet()
    events = say(engine, "換成蕾絲睡衣")
    assert not any(isinstance(e, OutfitChange) for e in events) and worn(state) is None
    assert "你可以換的服裝只有:日常、睡衣" in llm.systems[0]


def test_with_a_single_outfit_she_is_only_told_what_she_wears(closet, tmp_path):
    import shutil

    shutil.rmtree(tmp_path / "clips" / "睡衣")
    engine, llm, _ = closet()
    say(engine, "嗨")
    assert "你目前穿著:日常" in llm.systems[0] and "你可以換的服裝" not in llm.systems[0]


def test_without_a_wardrobe_the_prompt_is_exactly_what_it_was_before(closet):
    llm_without = SpyLLM()
    list(TurnEngine(llm_without, persona="p", history_store=InMemoryHistory()).send("嗨"))
    engine, llm_with, _ = closet()
    say(engine, "嗨")
    assert llm_with.systems[0].startswith(llm_without.systems[0])
    assert "服裝" not in llm_without.systems[0]


FW_BANG, FW_QUESTION, FW_COMMA, FW_PERIOD = "\uff01", "\uff1f", "\uff0c", "\u3002"


@pytest.mark.parametrize("request_text", ["換成睡衣" + FW_BANG, "換成睡衣" + FW_PERIOD, "好,換成睡衣" + FW_PERIOD.replace(FW_PERIOD, ""),
                                          "換成睡衣" + "\u2026", "換成睡衣" + "\uff5e"])
def test_full_width_punctuation_after_the_request_is_fine(closet, request_text):
    engine, _, state = closet()
    say(engine, request_text)
    assert worn(state) == "睡衣"


@pytest.mark.parametrize("not_a_request", ["換成睡衣" + FW_QUESTION, "你覺得換成睡衣好看嗎" + FW_QUESTION, "不要換成睡衣" + FW_BANG])
def test_a_full_width_question_mark_still_means_it_is_a_question(closet, not_a_request):
    engine, _, state = closet()
    say(engine, not_a_request)
    assert worn(state) is None
