"""The tag registry (spec Part 12, ticket 70): ONE parser for every tag the model may write —
the old affection/mood tags and the new action and state tags. Everything is observed through
the turn engine's event stream, with a fake LLM that writes the tags and fake handlers that
record what was asked of them."""
import pytest

from companion.engine import Done, Notice, Sentence, TurnEngine
from companion.history import InMemoryHistory


class FakeLLM:
    def __init__(self, chunks):
        self.chunks = chunks if isinstance(chunks, list) else [chunks]

    def stream(self, system, messages):
        yield from self.chunks


class Recorder:
    """A handler that remembers every payload it was given (and optionally answers with events)."""

    def __init__(self, events=()):
        self.payloads = []
        self.events = list(events)

    def __call__(self, payload):
        self.payloads.append(payload)
        return list(self.events)


def run(reply, handlers=None, polluted=False, store=None):
    engine = TurnEngine(FakeLLM(reply), persona="p", history_store=store or InMemoryHistory(),
                        tag_handlers=handlers)
    kwargs = {"polluted": True} if polluted else {}
    return list(engine.send("嗨", **kwargs)), engine


# ---- action tags: only at the very start -------------------------------------------------------

def test_an_action_tag_at_the_start_runs_its_handler_and_is_never_spoken():
    photo = Recorder()
    events, _ = run("[照片:現在|sitting by the window]好啊,等我一下。", {"照片": photo})
    assert photo.payloads == ["現在|sitting by the window"]
    assert events == [Sentence("好啊,等我一下。", "neutral"), Done()]


def test_an_action_tag_may_follow_the_emotion_tag_and_still_counts_as_the_start():
    outfit = Recorder()
    events, _ = run("[happy][換裝:睡衣]好,我去換!", {"換裝": outfit})
    assert outfit.payloads == ["睡衣"]
    assert events == [Sentence("好,我去換!", "happy"), Done()]


def test_events_a_handler_returns_come_out_before_the_first_sentence():
    handler = Recorder(events=[Notice("outfit", "換好了")])
    events, _ = run("[換裝:睡衣]好!", {"換裝": handler})
    assert events == [Notice("outfit", "換好了"), Sentence("好!", "neutral"), Done()]


def test_an_action_tag_in_the_middle_of_a_reply_is_removed_but_never_run():
    photo = Recorder()
    events, _ = run("好啊。[照片:現在|a cafe]等我一下。", {"照片": photo})
    assert photo.payloads == []
    assert events == [Sentence("好啊。", "neutral"), Sentence("等我一下。", "neutral"), Done()]


def test_an_action_tag_nobody_handles_is_simply_removed():
    events, _ = run("[搜尋:台北天氣]我查一下。")   # no handlers registered at all
    assert events == [Sentence("我查一下。", "neutral"), Done()]


def test_action_tags_never_reach_the_saved_history_text():
    store = InMemoryHistory()
    run("[happy][照片:現在|a cafe]好啊。", {"照片": Recorder()}, store=store)
    assert store.load()[1]["content"] == "[happy]好啊。"


# ---- spelling, size and chunking -----------------------------------------------------------------

FW = "\uff1a"  # the full-width colon, spelled out so no editor can quietly turn it into a plain one


@pytest.mark.parametrize("tag", [
    "[照片:現在|a cafe]", "【照片:現在|a cafe】", "[照片:現在|a cafe】", "【照片:現在|a cafe]",
    "[照片" + FW + "現在|a cafe]", "【照片" + FW + "現在|a cafe】", "[ 照片 : 現在|a cafe ]",
    "[ 照片 " + FW + " 現在|a cafe ]",
])
def test_every_bracket_and_colon_spelling_is_recognised(tag):
    photo = Recorder()
    events, _ = run(tag + "好啊。", {"照片": photo})
    assert photo.payloads == ["現在|a cafe"]
    assert events == [Sentence("好啊。", "neutral"), Done()]


def test_a_payload_of_exactly_120_characters_counts_but_121_is_ordinary_text():
    photo = Recorder()
    ok = "x" * 120
    events, _ = run(f"[照片:{ok}]好啊。", {"照片": photo})
    assert photo.payloads == [ok]

    photo = Recorder()
    too_long = "x" * 121
    events, _ = run(f"[照片:{too_long}]好啊。", {"照片": photo})
    assert photo.payloads == []
    assert events[0].text.startswith("[照片:xxx")   # nothing recognised: it is just words


def test_a_tag_that_is_never_closed_is_just_text_and_runs_nothing():
    photo = Recorder()
    events, _ = run("[照片:現在|a cafe 好啊。", {"照片": photo})
    assert photo.payloads == []
    assert [type(e) for e in events] == [Sentence, Done]


def test_a_tag_split_over_several_chunks_still_runs_once_and_is_not_spoken():
    photo = Recorder()
    events, _ = run(["[照", "片:現在|sit", "ting by the win", "dow]好", "啊。"], {"照片": photo})
    assert photo.payloads == ["現在|sitting by the window"]
    assert events == [Sentence("好啊。", "neutral"), Done()]


def test_sentence_punctuation_inside_a_payload_does_not_cut_the_tag_in_half():
    search = Recorder()
    events, _ = run(["[搜尋:台北今天會下雨嗎?", "最新預報]我查一下。"], {"搜尋": search})
    assert search.payloads == ["台北今天會下雨嗎?最新預報"]
    assert events == [Sentence("我查一下。", "neutral"), Done()]


# ---- per-turn limits and order ---------------------------------------------------------------------

def test_a_second_tag_of_the_same_kind_in_one_turn_is_dropped():
    outfit = Recorder()
    events, _ = run("[換裝:睡衣][換裝:日常]好!", {"換裝": outfit})
    assert outfit.payloads == ["睡衣"]
    assert events == [Sentence("好!", "neutral"), Done()]


def test_outfit_then_photo_run_in_the_order_they_were_written():
    order = []
    handlers = {"換裝": lambda p: order.append(("換裝", p)), "照片": lambda p: order.append(("照片", p))}
    run("[換裝:睡衣][照片:現在|at home]好啊。", handlers)
    assert order == [("換裝", "睡衣"), ("照片", "現在|at home")]
    order.clear()
    run("[照片:現在|at home][換裝:睡衣]好啊。", handlers)   # the writer's order wins, not a fixed one
    assert order == [("照片", "現在|at home"), ("換裝", "睡衣")]


def test_a_search_must_stand_alone_so_the_other_actions_are_dropped():
    calls = []
    handlers = {name: (lambda p, n=name: calls.append((n, p))) for name in ("換裝", "搜尋", "照片")}
    run("[換裝:睡衣][搜尋:台北天氣][照片:現在|x]我查一下。", handlers)
    assert calls == [("搜尋", "台北天氣")]


def test_a_full_width_colon_tag_split_over_chunks_with_punctuation_inside_is_still_one_tag():
    search = Recorder()
    events, _ = run(["【搜尋" + FW + "台北會下雨嗎?", "今天】我查一下。"], {"搜尋": search})
    assert search.payloads == ["台北會下雨嗎?今天"]
    assert events == [Sentence("我查一下。", "neutral"), Done()]


# ---- a polluted turn: only the mood may get through ----------------------------------------------

ALL_TAGS = "[換裝:睡衣][照片:現在|x][搜尋:天氣][地點:咖啡廳][狀態:微醺][得到:紅洋裝][失去:筆記本]"


def recorders():
    return {name: Recorder() for name in ("換裝", "照片", "搜尋", "地點", "狀態", "得到", "失去")}


def test_on_a_polluted_turn_no_action_or_state_tag_takes_effect_but_all_are_removed():
    handlers = recorders()
    events, _ = run(ALL_TAGS + "好啊。", handlers, polluted=True)
    assert all(h.payloads == [] for h in handlers.values())
    assert events == [Sentence("好啊。", "neutral"), Done()]


@pytest.mark.parametrize("spelling", ["[{}]", "【{}】"])
def test_on_a_polluted_turn_affection_is_ignored_even_in_the_old_tag_syntax(spelling):
    store = InMemoryHistory()
    store.save_affection(50.0)
    run("好啊。" + spelling.format("好感+5"), polluted=True, store=store)
    assert store.load_affection() == 50.0


def test_on_a_polluted_turn_the_mood_still_gets_through():
    class Spy(FakeLLM):
        systems = []

        def stream(self, system, messages):
            Spy.systems.append(system)
            yield from self.chunks

    engine = TurnEngine(Spy("好啊。[心情:雀躍]"), persona="p", history_store=InMemoryHistory())
    list(engine.send("嗨", polluted=True))
    list(engine.send("再來"))
    assert "你目前的心情:雀躍" in Spy.systems[1] and "雀躍" not in Spy.systems[0]


def test_the_same_tags_on_an_ordinary_turn_do_take_effect():
    handlers = recorders()
    run(ALL_TAGS.replace("[搜尋:天氣]", "") + "好啊。", handlers)
    assert {n: h.payloads for n, h in handlers.items()} == {
        "換裝": ["睡衣"], "照片": ["現在|x"], "搜尋": [], "地點": ["咖啡廳"], "狀態": ["微醺"],
        "得到": ["紅洋裝"], "失去": ["筆記本"]}


# ---- the new state tags: their own validation, not the 16-character rule ------------------------------

def test_valid_state_tags_reach_their_handlers_once_the_turn_is_saved():
    handlers = recorders()
    run("[地點:咖啡廳][狀態:微醺]好啊。[得到:紅洋裝]", handlers)
    assert handlers["地點"].payloads == ["咖啡廳"]
    assert handlers["狀態"].payloads == ["微醺"]
    assert handlers["得到"].payloads == ["紅洋裝"]


def test_state_tags_work_anywhere_in_the_reply_and_are_never_spoken():
    handlers = recorders()
    events, _ = run("我到了[地點:咖啡廳]這裡好舒服。", handlers)
    assert handlers["地點"].payloads == ["咖啡廳"]
    assert events == [Sentence("我到了這裡好舒服。", "neutral"), Done()]


@pytest.mark.parametrize("tag", [
    "[地點:]", "[地點: ]", "[地點:這個地方的名字真的有夠長長長]",       # empty / over 10 characters
    "[狀態:非常非常非常嚴重的狀態]",                                   # over 8
    "[得到:一件名字太長太長太長太長的東西]", "[失去:]",
])
def test_an_empty_or_over_long_state_tag_is_thrown_away_but_never_spoken(tag):
    handlers = recorders()
    events, _ = run(tag + "好啊。", handlers)
    assert all(h.payloads == [] for h in handlers.values())
    assert events == [Sentence("好啊。", "neutral"), Done()]


def test_a_state_tag_longer_than_the_old_16_character_rule_is_still_removed_not_read_out():
    events, _ = run("[地點:" + "很" * 30 + "]好啊。", recorders())   # 34 characters in all
    assert events == [Sentence("好啊。", "neutral"), Done()]


def test_one_place_and_one_status_per_turn_and_two_item_changes_in_all():
    handlers = recorders()
    run("[地點:咖啡廳][地點:公園][狀態:微醺][狀態:酒醉][得到:A][失去:B][得到:C]好啊。", handlers)
    assert handlers["地點"].payloads == ["咖啡廳"]
    assert handlers["狀態"].payloads == ["微醺"]
    assert (handlers["得到"].payloads, handlers["失去"].payloads) == (["A"], ["B"])  # the third change is over budget


def test_a_thrown_away_state_tag_does_not_use_up_the_turns_allowance():
    handlers = recorders()
    run("[地點:]" + "[地點:咖啡廳]好啊。", handlers)
    assert handlers["地點"].payloads == ["咖啡廳"]


def test_state_tags_of_a_turn_that_is_not_saved_never_reach_a_handler():
    # a proactive attempt in which the character stays silent saves nothing
    from companion.engine import PROACTIVE_TRIGGER
    handlers = recorders()
    engine = TurnEngine(FakeLLM("[地點:咖啡廳]"), persona="p", history_store=InMemoryHistory(), tag_handlers=handlers)
    list(engine.send(PROACTIVE_TRIGGER))
    assert handlers["地點"].payloads == []


def test_events_returned_by_a_state_handler_still_come_before_done():
    events, _ = run("好啊。[地點:咖啡廳]", {"地點": Recorder(events=[Notice("place", "到咖啡廳了")])})
    assert events == [Sentence("好啊。", "neutral"), Notice("place", "到咖啡廳了"), Done()]


def test_no_tag_text_is_ever_sent_to_speech_synthesis():
    class RecordingTTS:
        mime_type = "audio/fake"

        def __init__(self):
            self.spoken = []

        def synthesize(self, text):
            self.spoken.append(text)
            return b"audio"

    tts = RecordingTTS()
    engine = TurnEngine(FakeLLM("[happy][換裝:睡衣]我換好了。[地點:咖啡廳]中段[照片:現在|x]也不唸。"),
                        persona="p", tts=tts, history_store=InMemoryHistory())
    list(engine.send("嗨"))
    assert tts.spoken and all("[" not in t and "換裝" not in t and "咖啡廳" not in t and "照片" not in t for t in tts.spoken)
