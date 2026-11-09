"""She takes a photo of herself as she is now: [照片:現在|描述] at the start of a reply (spec Part 12,
section 5, ticket 89). Observed through the turn engine's event stream and the push channel, with a fake
Cloudflare and a background runner the test steps by hand — so \"she speaks first, the picture comes later\"
is something the test can actually see."""
import pytest

from companion.cloudflare_adapter import ImageError
from companion.engine import Done, Notice, Photo, Sentence, TurnEngine
from companion.history import InMemoryHistory
from companion.photos import PhotoStudio
from companion.state import InMemoryState

NOW = 1_800_000_000.0           # 2027-01-15 08:00:00 UTC
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-picture"


class FakeCloudflare:
    """What the studio sees of Cloudflare: one call, a prompt and maybe a reference picture, one picture back."""

    def __init__(self, picture=PNG):
        self.picture, self.calls = picture, []

    def generate(self, prompt, reference=None, width=576, height=1024):
        self.calls.append({"prompt": prompt, "reference": reference, "width": width, "height": height})
        return self.picture


class Jobs:
    """A background runner that waits: nothing happens until the test says so."""

    def __init__(self):
        self.pending = []

    def __call__(self, fn):
        self.pending.append(fn)

    def run_all(self):
        while self.pending:
            self.pending.pop(0)()


class ScriptedLLM:
    def __init__(self, reply):
        self.reply, self.systems, self.sent = reply, [], []

    def stream(self, system, messages):
        self.systems.append(system)
        self.sent.append(list(messages))
        yield self.reply


class Rig:
    pass


def picture_file(path, size, color=(200, 50, 50), mode="RGB"):
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color).save(path)


def size_of(data):
    import io

    from PIL import Image

    return Image.open(io.BytesIO(data)).size


@pytest.fixture(params=["memory", "sqlite"])
def rig(tmp_path, request):
    """`build(reply, outfits={name: {"base": (w, h) or None, "text": one line or None}}, ...)`."""
    from companion.outfits import Wardrobe

    def build(reply, outfits=None, appearance="a young woman with long black hair", photos=True, llm=None, engine_kwargs=None, items=(), again=None, now=NOW, **settings):
        r = Rig()
        r.adapter, r.jobs, r.pushed = FakeCloudflare(), Jobs(), []
        r.root, r.photos_dir = tmp_path, tmp_path / "data" / "photos"
        for name, spec in (outfits or {}).items():
            (tmp_path / "clips" / name).mkdir(parents=True, exist_ok=True)
            (tmp_path / "clips" / name / "idle.webm").write_bytes(b"v")
            if spec.get("base"):
                picture_file(tmp_path / "clips" / name / "base.png", spec["base"])
            if spec.get("text"):
                (tmp_path / "clips" / name / "outfit.txt").write_text(spec["text"], encoding="utf-8")
        r.now = now
        if again is not None:                      # a restart: the same state store, history and photo folder
            r.state = again.state
        elif request.param == "sqlite":
            from companion.state import SqliteState

            r.state = SqliteState(tmp_path / "state.db")
        else:
            r.state = InMemoryState()
        wardrobe = Wardrobe(tmp_path / "clips", r.state, settings=lambda: {"default": "日常", "aliases": {"睡衣": ["睡袍"]}})
        r.llm = llm or ScriptedLLM(reply)
        r.studio = studio = PhotoStudio(
            r.adapter, {"width": 576, "height": 1024, "appearance": appearance, "max_per_day": 6, "cooldown_s": 0, **settings},
            wardrobe=wardrobe, push=r.pushed.append, photos_dir=r.photos_dir, wall_clock=lambda: r.now,
            runner=r.jobs, state=r.state)
        r.store = again.store if again is not None else InMemoryHistory()
        r.state.set_items(list(items))
        state_kwargs = dict(character_state=r.state, state_settings={
            "enabled": True, "default_location": "家裡", "status_ttl_hours": {}, "default_status_ttl_hours": 12.0,
            "max_items": 20}) if items else {}
        extra = dict(tag_handlers=studio.handlers(), prompt_extras=[studio.prompt_help]) if photos else {}
        r.engine = TurnEngine(r.llm, persona="p", history_store=r.store, wardrobe=wardrobe, **extra, **state_kwargs, **(engine_kwargs or {}))
        return r

    return build


def test_she_speaks_first_and_the_picture_arrives_later_as_a_photo_event(rig):
    r = rig("[照片:現在|sitting by the window][happy]好啊,等我一下。")
    events = list(r.engine.send("拍張現在的樣子給我看"))
    assert events == [Sentence("好啊,等我一下。", "happy"), Done()]
    assert r.adapter.calls == [] and r.pushed == []          # still in the background
    r.jobs.run_all()
    assert len(r.adapter.calls) == 1
    assert r.pushed == [Photo("20270115-080000.png", "/photos/20270115-080000.png")]
    assert (r.photos_dir / "20270115-080000.png").read_bytes() == PNG


def test_without_a_base_photo_it_is_text_only_and_starts_with_her_appearance(rig):
    r = rig("[照片:現在|sitting by the window][happy]好啊。")
    list(r.engine.send("拍一張"))
    r.jobs.run_all()
    assert r.adapter.calls[0]["reference"] is None
    assert r.adapter.calls[0]["prompt"] == "a young woman with long black hair. sitting by the window"
    assert (r.adapter.calls[0]["width"], r.adapter.calls[0]["height"]) == (576, 1024)


def test_with_a_base_photo_the_reference_is_shrunk_below_512_and_the_prompt_keeps_her_the_same(rig):
    r = rig("[照片:現在|sitting by the window][happy]好啊。", outfits={"日常": {"base": (800, 1200)}})
    list(r.engine.send("拍一張"))
    r.jobs.run_all()
    call = r.adapter.calls[0]
    width, height = size_of(call["reference"])
    assert width <= 511 and height <= 511 and (width, height) != (800, 1200)
    assert call["prompt"] == ("Keep the same person, face, hairstyle, body shape and outfit as in the reference image. "
                              "sitting by the window")


def test_changing_clothes_and_taking_a_photo_in_one_reply_uses_the_new_outfits_base_photo(rig):
    r = rig("[換裝:睡衣][照片:現在|lying on the bed][happy]好,我換好了拍給你。",
            outfits={"日常": {"base": (800, 1200)}, "睡衣": {"base": (300, 400)}})
    list(r.engine.send("換睡衣拍張照"))
    r.jobs.run_all()
    assert r.state.load()["outfit"] == "睡衣"
    assert size_of(r.adapter.calls[0]["reference"]) == (300, 400)     # her pyjamas, not the day clothes


def test_a_second_request_while_one_is_being_made_is_ignored_with_a_notice(rig):
    r = rig("[照片:現在|by the window][happy]好啊。")
    list(r.engine.send("拍一張"))                       # the first one is now "being made" (the runner is holding it)
    second = list(r.engine.send("再拍一張"))
    assert [e for e in second if isinstance(e, Notice)] and second[-1] == Done()
    assert all(e.kind == "photo" and e.message for e in second if isinstance(e, Notice))
    r.jobs.run_all()
    assert len(r.adapter.calls) == 1 and len(r.pushed) == 1       # the service was asked once, and one picture came back


def test_when_the_picture_could_not_be_made_the_person_is_told_and_she_can_try_again(rig):
    r = rig("[照片:現在|by the window][happy]好啊。")
    r.adapter.generate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("service down"))
    list(r.engine.send("拍一張"))
    r.jobs.run_all()
    assert [type(e).__name__ for e in r.pushed] == ["Notice"] and r.pushed[0].kind == "photo"
    r.adapter.generate = FakeCloudflare().generate
    list(r.engine.send("再拍一次"))
    r.jobs.run_all()
    assert [type(e).__name__ for e in r.pushed] == ["Notice", "Photo"]


def test_a_photo_already_under_way_still_arrives_when_a_newer_turn_takes_over(rig):
    r = rig("[照片:現在|by the window][happy]好啊。")
    first = r.engine.send("拍一張")
    assert next(first) == Sentence("好啊。", "happy")        # the tag has been acted on; the reply is mid-way
    list(r.engine.send("算了,先聊別的"))                      # the user barges in: the older turn is abandoned
    assert list(first) == []                                  # (and says nothing more)
    r.jobs.run_all()
    assert [type(e).__name__ for e in r.pushed] == ["Photo"]


def test_two_pictures_in_the_same_second_do_not_overwrite_each_other(rig):
    r = rig("[照片:現在|by the window][happy]好啊。")
    r.adapter.picture = PNG + b"-one"
    list(r.engine.send("拍一張")); r.jobs.run_all()
    r.adapter.picture = PNG + b"-two"
    list(r.engine.send("再拍一張")); r.jobs.run_all()
    names = [e.file for e in r.pushed]
    assert len(set(names)) == 2
    assert sorted((r.photos_dir / n).read_bytes() for n in names) == [PNG + b"-one", PNG + b"-two"]


def test_an_answer_that_is_not_a_picture_is_a_failure_and_nothing_is_saved(rig):
    r = rig("[照片:現在|by the window][happy]好啊。")
    r.adapter.picture = b"<html>sorry</html>"
    list(r.engine.send("拍一張")); r.jobs.run_all()
    assert [type(e).__name__ for e in r.pushed] == ["Notice"]
    assert not r.photos_dir.exists() or list(r.photos_dir.iterdir()) == []


def test_without_a_base_photo_her_outfit_line_joins_the_text_only_prompt(rig):
    r = rig("[照片:現在|by the window][happy]好啊。", outfits={"日常": {"text": "a white knit sweater and jeans"}})
    list(r.engine.send("拍一張")); r.jobs.run_all()
    assert r.adapter.calls[0]["prompt"] == "a young woman with long black hair. a white knit sweater and jeans. by the window"


def test_a_base_photo_with_a_see_through_background_is_laid_on_white_not_black(rig, tmp_path):
    from PIL import Image

    r = rig("[照片:現在|by the window][happy]好啊。")
    (tmp_path / "clips" / "日常").mkdir(parents=True)
    (tmp_path / "clips" / "日常" / "idle.webm").write_bytes(b"v")
    Image.new("RGBA", (200, 300), (0, 0, 0, 0)).save(tmp_path / "clips" / "日常" / "base.png")
    list(r.engine.send("拍一張")); r.jobs.run_all()
    import io

    corner = Image.open(io.BytesIO(r.adapter.calls[0]["reference"])).getpixel((0, 0))
    assert min(corner) >= 240


def test_she_is_told_how_to_ask_for_a_photo_only_when_photos_work(rig):
    on = rig("[happy]好啊。")
    list(on.engine.send("嗨"))
    assert "[照片:現在|" in on.llm.systems[0]
    off = rig("[照片:現在|by the window][happy]好啊。", photos=False)
    events = list(off.engine.send("拍一張"))
    assert "照片" not in off.llm.systems[0]                     # no word of it in what she is told
    assert events == [Sentence("好啊。", "happy"), Done()]       # a tag she writes anyway is only cut out
    off.jobs.run_all()
    assert off.adapter.calls == [] and off.pushed == []


class TwoPassLLM:
    """Pass one asks for a web search; pass two answers (and tries to take a photo as well)."""

    def __init__(self, *replies):
        self.replies, self.systems = replies, []

    def stream(self, system, messages):
        self.systems.append(system)
        yield self.replies[len(self.systems) - 1]


class FakeSearch:
    def search(self, query):
        return [{"position": 1, "site_name": "news.example.com", "title": "台北天氣", "snippet": "多雲。",
                 "url": "https://news.example.com/w"}]


SEARCHING = dict(search=FakeSearch(), search_settings={"max_results": 5, "blocked_domains": [], "cooldown_s": 20})


def test_after_reading_a_web_page_a_photo_tag_in_her_answer_is_ignored_and_she_is_not_told_about_it(rig):
    llm = TwoPassLLM("[搜尋:台北天氣]", "[照片:現在|by the window][happy]查到了,多雲。")
    r = rig("", llm=llm, engine_kwargs=SEARCHING)
    events = list(r.engine.send("幫我看看台北天氣"))
    assert Sentence("查到了,多雲。", "happy") in events
    r.jobs.run_all()
    assert r.adapter.calls == [] and r.pushed == []
    assert "[照片:現在|" in llm.systems[0] and "[照片:現在|" not in llm.systems[1]


def test_the_same_holds_when_the_user_ordered_the_search_so_there_was_only_one_pass(rig):
    llm = TwoPassLLM("[照片:現在|by the window][happy]查到了,多雲。")
    r = rig("", llm=llm, engine_kwargs=SEARCHING)
    list(r.engine.send("上網查台北今天的天氣"))
    r.jobs.run_all()
    assert r.adapter.calls == [] and "[照片:現在|" not in llm.systems[0]


def test_a_turn_handed_over_as_already_polluted_neither_tells_her_about_photos_nor_acts_on_the_tag(rig):
    r = rig("[照片:現在|by the window][happy]好啊。")
    events = list(r.engine.send("拍一張", polluted=True))
    assert Sentence("好啊。", "happy") in events and "[照片:現在|" not in r.llm.systems[0]
    r.jobs.run_all()
    assert r.adapter.calls == []


# ---- ticket 90: [照片:當時|…], [照片:當時@服裝|…], [照片:物品|…] ----

TWO_OUTFITS = {"日常": {"base": (800, 1200)}, "睡衣": {"base": (300, 400)}}
ONLY_DAY_BASE = {"日常": {"base": (800, 1200)}, "睡衣": {}}
CHANGE_ONLY_THE_OUTFIT = ("Keep the same person, face, hairstyle and body shape as in the reference image, "
                          "but change ONLY the outfit to: ")


def taken(r, tag, outfits):
    r = r(f"{tag}[happy]好啊。", outfits=outfits) if callable(r) else r
    list(r.engine.send("拍給我看")); r.jobs.run_all()
    return r.adapter.calls[0]


def test_then_with_an_existing_outfit_named_uses_that_outfits_base_photo_and_keeps_her_in_it(rig):
    call = taken(rig, "[照片:當時@睡衣|at a cafe, laughing]", TWO_OUTFITS)
    assert size_of(call["reference"]) == (300, 400)
    assert call["prompt"] == "Keep the same person and the outfit of the reference image. at a cafe, laughing"


@pytest.mark.parametrize("tag", ["[照片:當時|a red dress at the beach]", "[照片:當時@不存在的衣服|a red dress at the beach]"])
def test_then_without_a_known_outfit_uses_the_current_base_photo_and_changes_only_the_clothes(rig, tag):
    call = taken(rig, tag, TWO_OUTFITS)
    assert max(size_of(call["reference"])) <= 511
    assert size_of(call["reference"]) != (300, 400)                                   # the day clothes, not the pyjamas
    assert call["prompt"] == CHANGE_ONLY_THE_OUTFIT + "a red dress at the beach"


def test_then_with_no_base_photo_at_all_is_text_only_after_her_appearance(rig):
    call = taken(rig, "[照片:當時@睡衣|at a cafe]", {"日常": {}, "睡衣": {}})
    assert call["reference"] is None
    assert call["prompt"] == "a young woman with long black hair. at a cafe"


def test_a_named_outfit_with_no_base_photo_falls_back_to_the_current_ones(rig):
    call = taken(rig, "[照片:當時@睡衣|at a cafe]", ONLY_DAY_BASE)
    assert max(size_of(call["reference"])) <= 511 and call["prompt"].startswith(CHANGE_ONLY_THE_OUTFIT)


def test_an_object_photo_is_text_only_with_no_person_and_no_reference(rig):
    call = taken(rig, "[照片:物品|a red summer dress on a hanger]", TWO_OUTFITS)
    assert call["reference"] is None
    assert call["prompt"] == "a red summer dress on a hanger"


def test_what_she_holds_is_in_what_she_is_told_so_an_object_photo_has_something_to_go_on(rig):
    r = rig("[happy]好啊。", items=["紅洋裝"])
    list(r.engine.send("給我看你買的洋裝"))
    assert "紅洋裝" in r.llm.systems[0]


@pytest.mark.parametrize("tag", ["[照片:當時|x]", "[照片:當時@睡衣|x]", "[照片:物品|x]"])
def test_every_mode_obeys_one_at_a_time_polluted_turns_and_switched_off(rig, tag):
    r = rig(f"{tag}[happy]好啊。", outfits=TWO_OUTFITS)
    list(r.engine.send("拍")); busy = list(r.engine.send("再拍"))
    assert any(isinstance(e, Notice) for e in busy)
    r.jobs.run_all()
    assert len(r.adapter.calls) == 1
    polluted = rig(f"{tag}[happy]好啊。", outfits=TWO_OUTFITS)
    list(polluted.engine.send("拍", polluted=True)); polluted.jobs.run_all()
    off = rig(f"{tag}[happy]好啊。", outfits=TWO_OUTFITS, photos=False)
    list(off.engine.send("拍")); off.jobs.run_all()
    assert polluted.adapter.calls == [] and off.adapter.calls == []


def test_she_is_taught_all_three_kinds_of_photo(rig):
    r = rig("[happy]好。")
    list(r.engine.send("嗨"))
    for tag in ("[照片:現在|", "[照片:當時|", "[照片:當時@服裝名|", "[照片:物品|"):
        assert tag in r.llm.systems[0]


def test_a_kind_of_photo_she_made_up_takes_nothing_and_does_not_block_the_next_one(rig):
    r = rig("[照片:亂寫|x][happy]好啊。", outfits=TWO_OUTFITS)
    list(r.engine.send("拍")); r.jobs.run_all()
    assert r.adapter.calls == [] and r.pushed == []
    r.llm.reply = "[照片:物品|a red dress][happy]好啊。"
    list(r.engine.send("再拍")); r.jobs.run_all()
    assert len(r.adapter.calls) == 1


def test_an_outfit_can_be_named_by_one_of_its_aliases(rig):
    call = taken(rig, "[照片:當時@睡袍|at a cafe]", TWO_OUTFITS)           # the fixture's aliases: 睡衣 = 睡袍
    assert size_of(call["reference"]) == (300, 400)


# ---- ticket 91: what the history keeps of a photo ----

def test_the_saved_turn_keeps_only_a_marker_with_the_file_name_and_the_model_is_later_shown_only_that(rig):
    r = rig("[照片:現在|by the window][happy]好啊。")
    list(r.engine.send("拍一張")); r.jobs.run_all()
    r.llm.reply = "[happy]嗯。"
    list(r.engine.send("好看嗎"))
    past = r.llm.sent[1]
    assert past[1] == {"role": "assistant", "content": "[照片:已拍|20270115-080000][happy]好啊。"}
    assert PNG.decode("latin-1") not in str(past) and "image" not in "".join(m["role"] for m in past)


def test_the_screen_history_shows_the_photo_beside_her_words_and_the_other_fields_are_unchanged(rig):
    r = rig("[照片:現在|by the window][happy]好啊。")
    list(r.engine.send("拍一張")); r.jobs.run_all()
    user, her = r.engine.history()
    assert user == {"role": "user", "text": "拍一張"}
    assert her == {"role": "assistant", "text": "好啊。", "emotions": ["happy"], "photo": {"stem": "20270115-080000"}}


def test_a_request_that_was_turned_away_leaves_no_marker_and_no_photo_item(rig):
    r = rig("[照片:現在|by the window][happy]好啊。")
    list(r.engine.send("拍一張")); list(r.engine.send("再拍一張")); r.jobs.run_all()
    assert [m.get("photo") for m in r.engine.history() if m["role"] == "assistant"] == [{"stem": "20270115-080000"}, None]


class BrokenSearch:
    def search(self, query):
        raise RuntimeError("down")


def test_a_photo_marker_follows_a_search_note_and_never_replaces_it(rig):
    # the search failed, so the turn is not polluted and her photo tag is honoured
    llm = TwoPassLLM("[搜尋:台北天氣]", "[照片:現在|by the window][happy]查不到,不過拍給你。")
    r = rig("", llm=llm, engine_kwargs=dict(SEARCHING, search=BrokenSearch()))
    list(r.engine.send("幫我看看台北天氣"))
    assert r.store.load()[1]["content"] == "[搜尋:台北天氣][照片:已拍|20270115-080000][happy]查不到,不過拍給你。"
    assert r.engine.history()[1]["photo"] == {"stem": "20270115-080000"}


# ---- ticket 92: allowance, cooldown and Cloudflare's error codes ----

TAG = "[照片:現在|by the window][happy]好啊。"
MIDNIGHT_UTC = 1_800_057_600.0          # 2027-01-16 00:00:00 UTC, the first midnight after NOW
ADVERTISED = "[照片:現在|"


def failing_with(*errors):
    """An adapter that raises these in turn, then succeeds."""
    queue = list(errors)

    def generate(prompt, reference=None, width=576, height=1024):
        if queue:
            raise queue.pop(0)
        return PNG

    return generate


def ask(r, n=1):
    for _ in range(n):
        list(r.engine.send("拍一張")); r.jobs.run_all()


def notices(r):
    return [e.message for e in r.pushed if isinstance(e, Notice)]


def test_at_the_daily_limit_no_call_is_made_and_she_is_told_today_is_not_a_day_for_photos(rig):
    r = rig(TAG, max_per_day=2)
    ask(r, 2)
    assert len(r.adapter.calls) == 2
    turned_away = list(r.engine.send("再拍一張"))
    r.jobs.run_all()
    assert len(r.adapter.calls) == 2 and any(isinstance(e, Notice) for e in turned_away)
    assert "今天不方便拍照" in r.llm.systems[-1] and ADVERTISED not in r.llm.systems[-1]


def test_the_next_utc_day_starts_the_count_again(rig):
    r = rig(TAG, max_per_day=1)
    ask(r)
    r.now = MIDNIGHT_UTC + 60
    ask(r)
    assert len(r.adapter.calls) == 2 and ADVERTISED in r.llm.systems[-1]


def test_cloudflare_saying_the_free_allowance_is_gone_stops_calls_until_midnight_utc_even_after_a_restart(rig):
    r = rig(TAG)
    r.adapter.generate = failing_with(ImageError("limit", status=429, code=3036))
    ask(r)
    assert r.state.load()["photo_exhausted_until"] == MIDNIGHT_UTC
    assert notices(r) == ["📷 今天的免費額度用完了,明天再拍。"]
    again = rig(TAG, again=r)                                   # restart: same store, new engine
    ask(again)
    assert again.adapter.calls == [] and "今天不方便拍照" in again.llm.systems[-1] and ADVERTISED not in again.llm.systems[-1]
    later = rig(TAG, again=r, now=MIDNIGHT_UTC)                 # the clock crosses 00:00 UTC
    ask(later)
    assert len(later.adapter.calls) == 1 and ADVERTISED in later.llm.systems[-1]


@pytest.mark.parametrize("error", [ImageError("busy", status=429, code=3040), ImageError("slow", status=408, code=3007),
                                   ImageError("timeout", timed_out=True)])
def test_a_passing_trouble_is_retried_once_and_then_she_is_told_to_try_later_without_ending_the_day(rig, error):
    r = rig(TAG)
    r.adapter.generate = failing_with(error, error)
    ask(r)
    assert notices(r) == ["📷 現在拍不了,等一下再試。"] and not [e for e in r.pushed if isinstance(e, Photo)]
    assert r.state.load()["photo_exhausted_until"] is None and ADVERTISED in r.llm.systems[-1]


def test_one_passing_failure_followed_by_a_success_gives_the_picture(rig):
    r = rig(TAG)
    r.adapter.generate = failing_with(ImageError("busy", status=429, code=3040))
    ask(r)
    assert [type(e).__name__ for e in r.pushed] == ["Photo"]


@pytest.mark.parametrize("status, code", [(403, 5035), (400, 5007), (400, 5004)])
def test_a_setup_problem_switches_photos_off_with_one_notice_and_no_more_calls_or_advertising(rig, status, code):
    r = rig(TAG)
    calls = []
    r.adapter.generate = lambda *a, **k: (calls.append(1), failing_with(ImageError("bad", status=status, code=code))(*a, **k))[1]
    ask(r)
    assert len(notices(r)) == 1
    again = list(r.engine.send("再拍")); r.jobs.run_all()
    assert len(calls) == 1 and len(notices(r)) == 1 and not [e for e in again if isinstance(e, Notice)]
    assert ADVERTISED not in r.llm.systems[-1] and "今天不方便拍照" not in r.llm.systems[-1]


def test_a_request_too_large_is_logged_and_declined_but_photos_stay_on(rig, caplog):
    r = rig(TAG)
    r.adapter.generate = failing_with(ImageError("big", status=413, code=3006))
    with caplog.at_level("WARNING"):
        ask(r)
    assert any("3006" in record.getMessage() for record in caplog.records)
    assert len(notices(r)) == 1
    ask(r)                                                       # still on: the next request goes through
    assert [type(e).__name__ for e in r.pushed][-1] == "Photo"


def test_two_requests_closer_than_the_cooldown_let_only_the_first_through(rig):
    r = rig(TAG, cooldown_s=30)
    ask(r)
    r.now += 10
    blocked = list(r.engine.send("再拍")); r.jobs.run_all()
    assert len(r.adapter.calls) == 1 and any(isinstance(e, Notice) for e in blocked)
    r.now += 25                                                  # 35 s after the first
    ask(r)
    assert len(r.adapter.calls) == 2


def test_resetting_her_state_does_not_give_back_the_allowance(rig):
    r = rig(TAG, max_per_day=1)
    ask(r)
    r.state.reset()
    again = rig(TAG, again=r, max_per_day=1)
    ask(again)
    assert again.adapter.calls == []


# ---- found on the first real run: a photo problem must never break the conversation, and must leave a trail ----

def test_an_unexpected_error_while_getting_a_photo_ready_never_breaks_her_reply(rig, caplog):
    r = rig("[照片:現在|by the window][happy]好啊。", outfits={"日常": {"base": (800, 1200)}})
    r.studio._wardrobe.base_photo = lambda *a, **k: (_ for _ in ()).throw(OSError("disk went away"))   # only photos use this
    with caplog.at_level("ERROR"):
        events = list(r.engine.send("拍一張"))
    assert Sentence("好啊。", "happy") in events and events[-1] == Done()
    assert [e.kind for e in events if isinstance(e, Notice)] == ["photo"]
    assert any(record.exc_info for record in caplog.records)             # the full traceback is in the log
    del r.studio._wardrobe.base_photo
    r.llm.reply = "[照片:現在|by the window][happy]好啊。"
    list(r.engine.send("再拍")); r.jobs.run_all()
    assert len(r.adapter.calls) == 1                                       # and the slot was not left taken


def test_an_unexpected_error_in_the_background_leaves_a_traceback_in_the_log(rig, caplog):
    r = rig("[照片:現在|by the window][happy]好啊。")
    r.adapter.generate = lambda *a, **k: (_ for _ in ()).throw(KeyError("surprise"))
    with caplog.at_level("ERROR"):
        ask(r)
    assert any(record.exc_info for record in caplog.records) and notices(r) == ["📷 這張照片沒拍成(程式錯誤:KeyError)。"]


def test_when_cloudflare_refuses_for_a_reason_we_do_not_know_the_panel_says_what_it_said(rig):
    r = rig(TAG)
    r.adapter.generate = failing_with(ImageError("http 400 code 9999: prompt was refused", status=400, code=9999))
    ask(r)
    assert notices(r) == ["📷 這張照片沒拍成(http 400 code 9999: prompt was refused)。"]


def test_when_getting_ready_fails_the_panel_names_the_kind_of_error_but_not_its_text(rig):
    r = rig(TAG, outfits={"日常": {"base": (800, 1200)}})
    r.studio._wardrobe.base_photo = lambda *a, **k: (_ for _ in ()).throw(OSError("C:\\secret\\path"))
    events = list(r.engine.send("拍一張"))
    [notice] = [e for e in events if isinstance(e, Notice)]
    assert notice.message == "📷 這張照片沒拍成(程式錯誤:OSError)。"
