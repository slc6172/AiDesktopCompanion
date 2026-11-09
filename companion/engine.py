import logging
import random
import re
import secrets
import threading
import time
from datetime import timedelta
from dataclasses import dataclass, field

from . import memoryblock, retrieval, searchintent, statebox, websafety
from . import tags as tagtable
from . import timesense
from .errors import LLMError, TTSUnavailable
from .history import NEUTRAL_AFFECTION, SECTIONS, InMemoryHistory

log = logging.getLogger(__name__)

SENTENCE_ENDINGS = set("。!?！？…\n")
EMOTIONS = ("neutral", "happy", "angry", "sad", "surprised")
RULES = (
    "\n\n【回覆格式】你說的每一句話,開頭都必須先寫一個情緒標籤,格式為 [情緒],"
    "情緒只能是這五個詞之一,一字不差:{emotions}。"
    "絕對不要自己發明或翻譯新的情緒詞(例如「心疼」「同情」「無奈」都不行),"
    "如果你想表達的情緒不在這五個裡面,直接選最接近的一個就好,"
    "標籤裡不要寫除了這五個詞以外的任何文字。標籤之後才是那一句要說的話。"
    "每一句都要以標點符號(。!?…)結尾,句子中間不要插入標籤。第一句請簡短。"
    "\n\n【選填標籤】在你這一輪回覆的最後(最後一句之後),可以再加:"
    "[好感+N] 或 [好感-N]——N 是 1 到 3 的整數,表示這一輪的互動讓你對使用者的好感增減多少,"
    "一輪最多寫一個,沒有明顯變化就不要寫;"
    "[心情:詞]——用一個詞描述你現在的心情,例如 [心情:溫柔],想更新心情時才寫。這些標籤不會被唸出來。"
)
FRIENDLY = {
    "rate_limit": "我今天說太多話了,先讓我休息一下,晚點再聊好嗎?",
    "timeout": "網路好像不太順,可以再說一次嗎?",
    "unavailable": "我剛剛恍神了一下,可以再說一次嗎?",
}
# Added to FOLD_SYSTEM only when time awareness is on (the lines it refers to carry dates then).
FOLD_DATE_RULE = (
    "新對話中每一行開頭方括號裡的是那句話的日期。事件、計畫與時間請以「絕對日期」記錄"
    "(例如「2026-10-12 前後有面試」),把「下週」「明天」「上個月」這類相對說法"
    "依該句話的日期換算成日期,不要原樣照抄相對說法。"
)
FOLD_SYSTEM = (
    "你是記憶整理助手。根據「目前的長期記憶」與「要併入的新對話」,整理出兩樣東西:\n"
    "1. events:這批新對話裡發生的事件,每項一句話(80 字內)並附 YYYY-MM-DD 日期,最多 10 項。這是只增不改的日誌。\n"
    "2. facts:長期記憶的『完整新版本』(會整組取代舊版),分成 user(關於使用者:喜好、家人、工作、習慣)、"
    "shared(你們一起經歷或約定的事)、self(角色自己說過的偏好、經歷、承諾)、followups(待跟進的事)、"
    "earlier_summary(更早的摘要,可再濃縮;沒有就不要寫)。\n"
    "刪除過時或被推翻的項目,合併重複的,留下長期有用的。總長度要控制在上限以內,太長就壓縮。"
    "不要把角色目前的地點、身體狀態、穿著、持有物品寫成事實(系統另外記錄;事件可以記,例如「角色買了一件紅洋裝」)。"
    "只記對話裡真的說過的內容,不要編造。用繁體中文。"
)
# The reply format is enforced by the API (structured output) rather than described in the prompt.
# (English keys: they are the schema's own words; the sections are named in Chinese where she sees them.)
_LIST_OF_TEXT = {"type": "array", "items": {"type": "string"}}
FOLD_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"},
                               "text": {"type": "string", "description": "一句話,80 字內"}},
                "required": ["date", "text"],
            },
            "description": "這批對話裡發生的事件,最多 10 項",
        },
        "facts": {
            "type": "object",
            "properties": {"user": _LIST_OF_TEXT, "shared": _LIST_OF_TEXT, "self": _LIST_OF_TEXT,
                           "followups": _LIST_OF_TEXT,
                           "earlier_summary": {"type": "string", "description": "更早的摘要,沒有就省略"}},
            "required": ["user", "shared", "self", "followups"],
        },
    },
    "required": ["events", "facts"],
}
FOLD_SECTIONS = {"user": "使用者", "shared": "共同經歷", "self": "角色自己的事", "followups": "待跟進"}
MAX_EVENTS, MAX_EVENT_CHARS = 10, 80
# What the folding call sees in place of her words in a turn that used the web (the page's content is never folded).
POLLUTED_PLACEHOLDER = "(那天查過:{query};網頁內容未納入)"
POLLUTED_PLACEHOLDER_UNKNOWN = "(那天用到網頁內容;網頁內容未納入)"
# What a saved reply keeps of a photo she took: the file name only (never the picture). The word 已拍 is not one
# of the kinds she can write, so if she copies the marker the tag is simply ignored.
HISTORY_MARKER = "[照片:已拍|{stem}]"
_PHOTO_MARKER = re.compile(r"^(?:\[搜尋:[^\]]*\])?\[照片:已拍\|([0-9A-Za-z][0-9A-Za-z._-]*)\]")
_SEARCH_NOTE = re.compile(r"^\[搜尋:([^\]]*)\]")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Any half- or full-width bracket pair holding 1-16 characters counts as an emotion tag.
TAG = re.compile(r"[\[【]([^\[\]【】]{1,16})[\]】]")
# Affection / mood tags share the bracket syntax with emotion tags, so they must be recognised
# *before* the "any other tag counts as happy" fallback in resolve_emotion — by their prefix,
# not by parsing success: a garbled "[好感很多]" is still swallowed as a meta tag (and ignored)
# rather than being mistaken for an emotion change.
_AFFECTION_TAG = re.compile(r"^好感\s*[::]?\s*([+\-＋－−])\s*(\d{1,3})$")
_MOOD_TAG = re.compile(r"^心情\s*[::]?\s*(\S.{0,9})$")
AFFECTION_MAX_STEP = 5  # the most one turn may move affection, whatever the model writes
AFFECTION_GRACE_S = 24 * 3600  # being away for less than this changes nothing
AFFECTION_HALF_LIFE_S = 14 * 24 * 3600  # beyond the grace period, the gap to neutral halves this often
PROACTIVE_IDLE_RANGE_S = (10 * 60, 30 * 60)  # how long both sides must be idle before the character might speak up; tune to taste
PROACTIVE_TRIGGER = object()  # identifies a proactive attempt to _run(); never sent to the LLM or stored
IMAGE_MARKER = "[圖片] "  # prefixed onto a saved message that had an image; see UserImage below
PROACTIVE_PROMPT = "(你自己選擇在這個時間點開口,不是使用者傳來的訊息。)"
PROACTIVE_SYSTEM_ADDENDUM = (
    "\n\n【主動開口】這一次不是使用者傳訊息給你,而是你自己選擇在這個時間點開口——"
    "想到剛剛聊過的事、單純想打聲招呼都可以。如果現在沒有特別想說的話,"
    "就不要輸出任何文字,不用勉強講話,下次有機會再說。"
)


@dataclass(frozen=True)
class UserImage:
    """An image the user attached to one message, exactly as uploaded (the model looks at it
    directly, this turn only — see IMAGE_MARKER for why it is not kept around after that)."""

    data: bytes
    mime_type: str


@dataclass(frozen=True)
class Transcript:
    """What the user's voice message was recognised as. Shown on screen and saved; never
    spoken. TurnEngine itself no longer produces this event — it is
    built by server.py from the speech-to-text result before the turn even starts, and is
    kept here only because Audio/Sentence/Failure/etc. all live in this same module."""

    text: str


@dataclass(frozen=True)
class Sentence:
    text: str
    emotion: str


@dataclass(frozen=True)
class Audio:
    index: int
    text: str
    data: bytes
    mime_type: str
    emotion: str


@dataclass(frozen=True)
class Failure:
    """The turn could not be completed. Nothing was saved, so retrying is safe."""

    kind: str
    message: str


@dataclass(frozen=True)
class Notice:
    """Something worth telling the user that does not stop the reply."""

    kind: str
    message: str


@dataclass(frozen=True)
class OutfitChange:
    """She now wears `name`; `clips` is that outfit's animations (state -> URL), for the page to preload."""
    name: str
    clips: dict


@dataclass(frozen=True)
class Photo:
    """A picture she took has been saved. `url` is a path on this machine (never a remote address);
    it arrives on the push channel because the reply that promised it has usually finished by then."""
    file: str
    url: str


@dataclass(frozen=True)
class Done:
    # Not part of equality: it is a measurement, not content.
    first_audio_ms: float | None = field(default=None, compare=False)


def _in_thread(fn):
    threading.Thread(target=fn, daemon=True).start()


def _real_scheduler(delay_s, fn):
    """Runs fn() once, delay_s from now, in a daemon thread; returns a callable that cancels
    it (a no-op if it has already fired)."""
    timer = threading.Timer(delay_s, fn)
    timer.daemon = True
    timer.start()
    return timer.cancel


def _without_stray_escapes(text):
    """`text` without the backslash the model sometimes writes in front of a tag ("…。\\[neutral]…"), which
    would otherwise come out as a "sentence" of its own that is shown and read aloud."""
    return text.strip().strip("\\").strip()


def normalize_fold(data, fallback_date):
    """(events, facts) from the folding call's structured reply; None if it is unusable.

    The API guarantees the shape, not the content, so it is checked here. `events` are journal rows
    (at most 10, each cut to 80 characters, an unreadable date replaced by `fallback_date`); `facts`
    maps a section name to its text, empty sections left out, and carries "更早的摘要" only when the
    model gave one. A reply whose facts are missing a section or are not lists is unusable.
    """
    if not isinstance(data, dict) or not isinstance(data.get("events"), list) or not isinstance(data.get("facts"), dict):
        return None
    raw = data["facts"]
    if any(not isinstance(raw.get(key), list) for key in FOLD_SECTIONS):
        return None
    events = []
    for item in data["events"]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            continue
        date = item.get("date")
        date = date if isinstance(date, str) and _ISO_DATE.fullmatch(date.strip()) else fallback_date
        events.append({"date": date.strip(), "time": None, "kind": "事件", "text": item["text"].strip()[:MAX_EVENT_CHARS]})
    facts = {}
    for key, name in FOLD_SECTIONS.items():
        lines = [f.strip() for f in raw[key] if isinstance(f, str) and f.strip()]
        if lines:
            facts[name] = "\n".join("- " + line for line in lines)
    if isinstance(raw.get("earlier_summary"), str) and raw["earlier_summary"].strip():
        facts["更早的摘要"] = raw["earlier_summary"].strip()
    return events[:MAX_EVENTS], facts


def resolve_emotion(name):
    """A tag inside the allowed set is used as it is; any other tag followed by speech counts as happy."""
    name = name.strip().lower()
    return name if name in EMOTIONS else "happy"


def parse_meta_tag(name):
    """None for an ordinary emotion tag; otherwise ("affection", int) / ("mood", str) /
    ("ignore", None) for a 好感/心情 tag that is well-formed / well-formed / garbled."""
    name = name.strip()
    if name.startswith("好感"):
        match = _AFFECTION_TAG.match(name)
        if not match:
            return "ignore", None
        amount = int(match.group(2))
        return "affection", -amount if match.group(1) in "-－−" else amount
    if name.startswith("心情"):
        match = _MOOD_TAG.match(name)
        return ("mood", match.group(1).strip()) if match else ("ignore", None)
    return None


def apply_affection(current, delta):
    """New affection (0-100) after one turn's change. The further from the middle it already
    is, the smaller a step towards the nearer end counts, so it saturates instead of racing to
    an extreme; a step back towards the middle counts in full or more."""
    delta = max(-AFFECTION_MAX_STEP, min(AFFECTION_MAX_STEP, delta))
    scale = (100 - current) / 50 if delta > 0 else current / 50
    return round(max(0.0, min(100.0, current + delta * scale)), 2)


def decay_affection(current, last_interaction, now, grace_s, half_life_s):
    """Affection after the user has been away since `last_interaction`: after a grace period it
    drifts towards neutral, halving its distance from it every `half_life_s`. Exponential, so it
    can approach neutral from either side but never cross it. Nothing recorded, a clock that
    went backwards, or a half-life of 0 or less (decay switched off) all mean no change."""
    if last_interaction is None or half_life_s <= 0:
        return current
    away = now - last_interaction
    if away <= grace_s:
        return current
    factor = 0.5 ** ((away - grace_s) / half_life_s)
    return round(NEUTRAL_AFFECTION + (current - NEUTRAL_AFFECTION) * factor, 2)


def relationship_lines(affection, mood):
    lines = [f"好感度:{round(affection)}/100(0 是冷淡疏遠,50 是普通熟識,100 是非常親近信任)。"]
    if mood:
        lines.append(f"你目前的心情:{mood}。")
    lines.append("請讓你的語氣、稱呼與親密程度自然反映這個關係,但不要直接說出數字。")
    return lines


def relationship_block(affection, mood):
    return "\n\n【你和使用者的關係】\n" + "\n".join(relationship_lines(affection, mood))


class _Segmenter:
    """Cuts the model's raw text into (emotion, sentence) pairs.

    Every emotion tag is removed wherever it appears, and it ends the text before it.
    Affection and mood tags are removed too but are only collected (see parse_meta_tag).
    Text without a tag of its own keeps the emotion of the one before it (neutral until the first tag).
    """

    def __init__(self, polluted=False):
        self._buffer = ""
        self._emotion = "neutral"
        self._polluted = polluted  # the turn used web content: see tags.py for what that switches off
        self.affection_deltas = []  # every 好感 tag seen, in order (the engine applies only one)
        self.mood = None  # the latest 心情 tag, if any
        self.state_tags = []  # (name, payload) of 地點/狀態/得到/失去 that passed validation and the per-turn limits
        self._state_used = {}  # budget group -> how many have been taken
        self._spoken = False  # has anything speakable come out yet? Action tags only count before that
        self._lead_actions = []  # (name, payload) of action tags found at the start
        self._lead_open = True  # still at the start of the reply
        self._released = False

    def release_actions(self):
        """The action tags to run, once the start of the reply is over (the first words have come
        out, or the reply ended) — never before, so a search can tell whether it stands alone."""
        if self._lead_open or self._released:
            return []
        self._released = True
        if self._polluted:
            return []
        chosen = []
        for name, payload in self._lead_actions:
            if all(name != taken for taken, _ in chosen):  # one of each kind per turn
                chosen.append((name, payload))
        searches = [item for item in chosen if item[0] == "搜尋"]
        return searches[:1] if searches else chosen

    def _take_state_tag(self, name, payload):
        spec = tagtable.REGISTRY[name]
        value = tagtable.valid_payload(name, payload)
        key = spec.group or name
        if self._polluted or value is None or self._state_used.get(key, 0) >= spec.per_turn:
            return
        self._state_used[key] = self._state_used.get(key, 0) + 1
        self.state_tags.append((name, value))

    def feed(self, chunk):
        self._buffer += chunk
        return list(self._drain())

    def finish(self):
        pairs = list(self._drain())
        rest, self._buffer = _without_stray_escapes(self._buffer), ""
        if rest:
            pairs.append((self._emotion, rest))
        self._lead_open = False
        return pairs

    def _drain(self):
        while True:
            # A registry tag that is still arriving may hold sentence-ending punctuation in its
            # payload; nothing from its opening bracket on may be cut into sentences yet.
            opener = tagtable.OPEN_REGISTRY_TAG.search(self._buffer)
            horizon = opener.start() if opener else len(self._buffer)
            end = next((i for i, c in enumerate(self._buffer[:horizon]) if c in SENTENCE_ENDINGS), -1)
            tag = TAG.search(self._buffer)
            registry = tagtable.REGISTRY_TAG.search(self._buffer)
            if registry and (tag is None or registry.start() <= tag.start()) and (end < 0 or registry.start() < end):
                self._take_registry_tag(registry)
                continue
            if tag and (end < 0 or tag.start() < end):
                meta = parse_meta_tag(tag.group(1))
                if meta is not None:
                    # Not an emotion: record it, and cut it out without ending the sentence it
                    # sits in or changing the emotion.
                    kind, value = meta
                    if kind == "affection" and not self._polluted:
                        self.affection_deltas.append(value)
                    elif kind == "mood":
                        self.mood = value
                    self._buffer = self._buffer[: tag.start()] + self._buffer[tag.end():]
                    continue
                before = _without_stray_escapes(self._buffer[: tag.start()])
                self._buffer = self._buffer[tag.end():]
                if before:
                    self._spoke()
                    yield self._emotion, before
                self._emotion = resolve_emotion(tag.group(1))
                continue
            if end < 0:
                return
            # A run of ending punctuation (e.g. "……", "?!") belongs to one sentence; cutting
            # after only the first character would peel off a lone punctuation mark as its own
            # "sentence" — which has no speakable content and can trip up speech synthesis.
            while end + 1 < len(self._buffer) and self._buffer[end + 1] in SENTENCE_ENDINGS:
                end += 1
            sentence, self._buffer = self._buffer[: end + 1].strip(), self._buffer[end + 1:]
            if sentence:
                self._spoke()
                yield self._emotion, sentence

    def _spoke(self):
        self._spoken = True
        self._lead_open = False

    def _take_registry_tag(self, match):
        name, payload = match.group(1), match.group(2)
        at_the_start = self._lead_open and not self._spoken and not self._buffer[: match.start()].strip()
        self._buffer = self._buffer[: match.start()] + self._buffer[match.end():]
        spec = tagtable.REGISTRY[name]
        if spec.family == "action":
            if at_the_start:
                self._lead_actions.append((name, payload.strip()))
            # anywhere else: removed above, and deliberately not run
        else:
            self._take_state_tag(name, payload)


def parse_reply(raw):
    """A stored reply as [(emotion, sentence)], tags removed."""
    segmenter = _Segmenter()
    return segmenter.feed(raw) + segmenter.finish()


@dataclass
class _Turn:
    """Per-call state that used to live on the engine instance. Keeping it local (instead of
    on `self`) is what makes it safe for a new `send()` call to start before an older one has
    finished: the two no longer share `_turn_start` / `_tts_failed` / `_first_audio_s`."""

    start: float
    first_audio_s: float | None = None
    tts_failed: bool = False
    primary_tts_down: bool = False  # the primary engine was unreachable earlier in this same turn
    markers: list = field(default_factory=list)  # what handlers want kept in the saved reply (see _handle_tags)


class TurnEngine:
    def __init__(self, llm, persona="", tts=None, tts_fallback=None, clock=time.perf_counter, history_store=None,
                 max_turns=20, summarize=False, summary_batch=10, background=None, wall_clock=time.time, time_config=None,
                 affection_grace_s=AFFECTION_GRACE_S, affection_half_life_s=AFFECTION_HALF_LIFE_S,
                 scheduler=_real_scheduler, on_proactive=None, proactive_idle_range_s=PROACTIVE_IDLE_RANGE_S,
                 tag_handlers=None, prompt_extras=None, startup_notices=None, wardrobe=None, character_state=None, state_settings=None,
                 memory_settings=None, search=None, search_settings=None, nonce_factory=None, fetch=None, quarantine_llm=None):
        self._llm = llm
        # tag name -> callable(payload) that may return events for the stream. The engine only
        # decides WHEN a tag is acted on (see tags.py); what happens is the feature's business, so
        # no feature logic lives in here. A tag without a handler is removed and otherwise ignored.
        self._tag_handlers = dict(tag_handlers or {})
        # callables returning a piece of the system prompt (or "") — how a feature tells her about its own tag.
        # Asked every turn, so a feature that cannot work right now simply says nothing (spec: no advertising).
        self._prompt_extras = list(prompt_extras or ())
        self._wardrobe = wardrobe  # None = the outfit feature is not part of this engine
        self._character_state = character_state  # her place, body, belongings (state.py); None = feature absent
        self._state_settings = state_settings
        from .config import DEFAULT_CONFIG

        self._memory_settings = {**DEFAULT_CONFIG["memory"], **(memory_settings or {})}  # limits and retrieval knobs; unspecified ones keep their defaults
        if character_state is not None and state_settings["enabled"]:
            for name, handler in (("地點", self._set_location), ("狀態", self._set_status),
                                  ("得到", self._gain_item), ("失去", self._lose_item)):
                self._tag_handlers.setdefault(name, handler)
        if wardrobe is not None:
            self._tag_handlers.setdefault("換裝", self._change_outfit_from_tag)
        self._search = search  # None = looking things up on the web is not part of this engine
        self._fetch = fetch  # reads one page in full, only for a careful ("深入") search
        self._quarantine_llm = quarantine_llm  # the separate, persona-less model that reads pages; default: the same one
        self._search_settings = {"max_results": 5, "blocked_domains": [], "cooldown_s": 20, "quarantine": True, **(search_settings or {})}
        self._nonce = nonce_factory or (lambda: secrets.token_hex(8))
        self._search_blocked_until = 0.0  # after a failure the service is left alone until then (engine clock)
        self._startup_notices = list(startup_notices or ())  # shown once, at the head of the first turn
        self._tts = tts
        self._tts_fallback = tts_fallback
        self._clock = clock
        self._wall_clock = wall_clock  # epoch seconds: how long the user has been away, not latency
        # The resolved `time` settings (config.resolve_time_config()); None = no sense of time at all.
        self._time = time_config if time_config and time_config.get("enabled") else None
        self._affection_grace_s = affection_grace_s
        self._affection_half_life_s = affection_half_life_s
        # Proactive speaking: off by default (see set_proactive). `_proactive_cancel` is the
        # cancel handle for whichever attempt is currently scheduled, if any — always cancelled
        # before a new one is scheduled, so there is never more than one pending at a time.
        self._scheduler = scheduler
        self._on_proactive = on_proactive
        self._proactive_min_s, self._proactive_max_s = proactive_idle_range_s
        self._proactive_enabled = False
        self._proactive_cancel = None
        self._max_turns = max_turns
        self._summarize = summarize
        self._fold_lock = threading.Lock()  # one fold at a time
        self._summary_batch = summary_batch
        self._background = background or _in_thread
        self._store = history_store if history_store is not None else InMemoryHistory()
        self._mood = ""  # session-only: deliberately never saved, so a restart starts fresh
        self._system = persona + RULES.format(emotions=", ".join(EMOTIONS))
        if character_state is not None and state_settings["enabled"]:
            self._system += statebox.TAG_RULES  # beside the other optional tags in the format rules
        # The engine still assumes a single user, but not a single turn in flight: barge-in
        # aborts the browser's fetch of the old turn and immediately starts a new one, and the
        # old turn's generator can keep running server-side for a little while after that (a
        # cancelled fetch does not reach into the server and stop it). `_generation` lets an
        # old turn notice it has been superseded and quietly stop — without saving anything,
        # and without overwriting the state a newer, still-running turn is using.
        self._lock = threading.Lock()
        self._generation = 0

    def _maybe_summarize(self):
        """Fold the oldest turns into the memory once the unfolded tail is too long: one structured call
        gives dated journal events and a complete new version of the long-term facts. Only one fold at a
        time; a failure leaves everything as it was, so the same turns are tried again on a later turn."""
        if not self._fold_lock.acquire(blocking=False):
            return
        try:
            self._fold()
        except Exception:
            log.exception("memory maintenance failed; the conversation is unaffected")
        finally:
            self._fold_lock.release()

    def _fold(self):
        long_term = self._store.load_facts()
        cursor = self._store.load_fold_progress()
        tail = self._store.load()[cursor:]
        if len(tail) // 2 <= self._max_turns:
            return
        old = tail[: 2 * self._summary_batch]
        tz = self._time["timezone"] if self._time is not None else None
        # With time awareness on, each line is dated (when known) so "next week" can be turned into a
        # real date. These dates only go to the folding call; nothing is saved with them.
        times = self._store.load_times()
        polluted = self._store.load_polluted()
        lines = []
        for i, message in enumerate(old):
            when = times[cursor + i] if self._time is not None else None
            dated = "" if when is None else "[" + timesense.format_date(when, tz) + "] "
            if message["role"] == "user":
                lines.append(dated + "使用者:" + message["content"])
            elif cursor + i < len(polluted) and polluted[cursor + i]:
                # She spoke with web content in front of her: none of her words from that turn is folded.
                note = _SEARCH_NOTE.match(message["content"])
                lines.append(dated + "角色:" + (POLLUTED_PLACEHOLDER.format(query=note.group(1)) if note else POLLUTED_PLACEHOLDER_UNKNOWN))
            else:
                lines.append(dated + "角色:" + "".join(text for _, text in parse_reply(message["content"])))
        limit = self._memory_settings["long_term_max_chars"]
        size = sum(len(text) for text in long_term.values())
        shown = "\n".join(f"〔{name}〕\n{long_term[name]}" for name in SECTIONS if long_term.get(name)) or "無"
        request = (
            f"【目前的長期記憶】(共 {size} 字,上限 {limit} 字)\n" + shown
            + "\n\n【要併入的新對話】\n" + "\n".join(lines)
        )
        system = FOLD_SYSTEM + (FOLD_DATE_RULE if self._time is not None else "")
        data = self._llm.generate_structured(system, [{"role": "user", "content": request}], FOLD_SCHEMA)
        first_time = times[cursor] if cursor < len(times) else None
        fallback = f"{timesense.local_datetime(first_time if first_time is not None else self._wall_clock(), tz):%Y-%m-%d}"
        parsed = normalize_fold(data, fallback)
        if parsed is None:
            log.warning("memory fold reply was not usable; will retry on a later turn")
            return
        events, facts = parsed
        kept = {name: text for name, text in facts.items() if name != "更早的摘要"}
        if not kept and any(long_term.get(name) for name in FOLD_SECTIONS.values()):
            log.warning("memory fold reply would have erased every remembered fact; not trusted, will retry")
            return
        facts.setdefault("更早的摘要", long_term.get("更早的摘要", "")) if long_term.get("更早的摘要") else None
        if sum(len(text) for text in facts.values()) > limit:
            log.warning("memory fold: the new long-term facts are over the %d-character limit; keeping the old ones", limit)
            facts = None  # never cut: the old version stands, the events are still recorded
        self._store.apply_fold(events, facts, cursor + len(old))

    def history(self):
        """The full saved conversation, cleaned up for showing on screen (no tags, emotion per sentence)."""
        shown = []
        for message in self._store.load():
            if message["role"] == "user":
                if message["content"] == PROACTIVE_PROMPT:
                    continue  # the character talking to itself, not something the user said
                text = message["content"]
                if text.startswith(IMAGE_MARKER):
                    shown.append({"role": "user", "text": text[len(IMAGE_MARKER):], "has_image": True})
                else:
                    shown.append({"role": "user", "text": text})
            else:
                pairs = parse_reply(message["content"])
                item = {
                    "role": "assistant",
                    "text": "".join(text for _, text in pairs),
                    "emotions": [emotion for emotion, _ in pairs],
                }
                photo = _PHOTO_MARKER.match(message["content"])
                if photo:
                    item["photo"] = {"stem": photo.group(1)}
                shown.append(item)
        return shown

    def _stale(self, generation):
        """True once a newer call to send() has started: this one should abandon quietly."""
        return generation != self._generation

    @staticmethod
    def _say(tts, sentence, emotion):
        """One synthesize call. The sentence's emotion is handed over only to an engine that
        declares `supports_emotion` (today: Fish Audio, which reads it as an inline tag). Every
        other engine is called exactly as before, so a tag can never be spoken aloud by an engine
        that would read it as text."""
        if getattr(tts, "supports_emotion", False):
            return tts.synthesize(sentence, emotion=emotion)
        return tts.synthesize(sentence)

    def _synthesize(self, sentence, turn, emotion=None):
        """(audio bytes, mime type) for one sentence, routing around an engine that cannot help.

        Two different situations, kept apart on purpose:
        - an *empty result* (this sentence had nothing to say) gets one same-engine retry and
          then one attempt on the fallback engine, if there is one;
        - an engine that is *unavailable* (TTSUnavailable: not running, timed out, server-side
          error) goes straight to the fallback, with no retry against a service that is down,
          and the rest of the turn skips the primary too — otherwise a hung server would cost
          one full timeout per sentence.
        All state lives in plain locals and the per-call `turn`, never on the shared engine
        (see _Turn/_generation for why that matters when turns can overlap).
        """
        fallback = self._tts_fallback
        if not turn.primary_tts_down:
            try:
                data = self._say(self._tts, sentence, emotion)
                if not data:
                    data = self._say(self._tts, sentence, emotion)  # one same-engine retry
                if data or fallback is None:
                    return data, self._tts.mime_type
            except TTSUnavailable:
                if fallback is None:
                    raise
                log.warning("primary speech engine unavailable; using the fallback for this turn")
                turn.primary_tts_down = True
        return self._say(fallback, sentence, emotion), fallback.mime_type

    def _speak(self, sentence, index, emotion, turn):
        yield Sentence(sentence, emotion)
        if self._tts is None or turn.tts_failed:
            return
        spoken = websafety.strip_urls(sentence)  # an address is shown, never read out
        if not spoken:
            return
        try:
            data, mime = self._synthesize(spoken, turn, emotion)
        except Exception:
            # Anything that is neither "no audio for this sentence" nor "the primary engine is
            # unreachable" (see _synthesize) is not something we know how to route around: a
            # bad request, a fallback that is broken too, a bug. That keeps the ticket 17/18
            # behavior — the voice service is treated as failed for the rest of this turn — so
            # a real failure is never silently reinterpreted as "just try the other engine".
            log.exception("speech synthesis failed; continuing as text")
            turn.tts_failed = True
            yield Notice("tts_unavailable", "語音暫時不能用,先用文字陪你聊。")
            return
        if not data:
            # Not a broken service: don't hand the browser an unplayable zero-byte Audio event,
            # and don't give up on the rest of the turn over what is likely a one-off,
            # sentence-specific quirk (e.g. a fragment left over from stray punctuation).
            log.warning("speech synthesis returned no audio for a sentence of %d characters; skipping just this sentence", len(sentence))
            return
        if turn.first_audio_s is None:
            turn.first_audio_s = self._clock() - turn.start
        yield Audio(index, sentence, data, mime, emotion)

    def _with_gap_marker(self, message, previous_time, at):
        """A COPY of `message` with a "(距上一句約 …)" line in front when it follows a long
        silence. The copy is only what the model is sent — what gets saved is always the
        user's own words."""
        if previous_time is None or at is None or at - previous_time < self._time["gap_marker_minutes"] * 60:
            return message
        return {**message, "content": timesense.gap_marker(at - previous_time) + "\n" + message["content"]}

    def set_proactive(self, enabled):
        """Turn proactive speaking on or off. Idempotent, and safe to call from any thread:
        turning it on (re-)schedules one attempt within proactive_idle_range_s from now;
        turning it off cancels whatever is pending, so nothing fires again until it is
        re-enabled — there is never more than one attempt scheduled at a time.
        """
        with self._lock:
            self._proactive_enabled = enabled
            self._cancel_scheduled_proactive()
            if enabled:
                self._schedule_next_proactive()

    def _cancel_scheduled_proactive(self):
        if self._proactive_cancel is not None:
            self._proactive_cancel()
            self._proactive_cancel = None

    def _schedule_next_proactive(self):
        delay = random.uniform(self._proactive_min_s, self._proactive_max_s)
        self._proactive_cancel = self._scheduler(delay, self._attempt_proactive)

    def _attempt_proactive(self):
        """What the scheduler calls when an idle period has elapsed: work out whether the
        character has anything to say (see PROACTIVE_SYSTEM_ADDENDUM) and, if so, deliver every
        event to on_proactive — there is no HTTP request in flight for this turn to ride along
        on, so the caller that wired on_proactive up is responsible for getting the events to
        the browser (see server.py)."""
        if not self._proactive_enabled:
            return  # turned off in the narrow window between the scheduler firing and this running
        if self._time is not None and timesense.in_quiet_hours(self._wall_clock(), self._time["timezone"],
                                                                self._time["quiet_hours"]):
            # Quiet hours: no unprompted speech. Skip THIS attempt entirely (the model isn't asked,
            # nothing is saved) and line up the next one as usual.
            with self._lock:
                if self._proactive_enabled:
                    self._schedule_next_proactive()
            return
        events = list(self._attempt_proactive_stream())
        if self._on_proactive is not None:
            if any(isinstance(e, Sentence) for e in events):
                for event in events:
                    self._on_proactive(event)
            else:
                # Silent, but she may still have changed clothes — that is saved, so the page must hear of it.
                for event in events:
                    if isinstance(event, OutfitChange):
                        self._on_proactive(event)

    def _attempt_proactive_stream(self):
        """The raw, not-yet-consumed generator for a proactive attempt (split out from
        _attempt_proactive so a test can step through one manually, e.g. to interrupt it
        partway through exactly like a real barge-in)."""
        return self.send(PROACTIVE_TRIGGER)

    def send(self, user_message, image=None, polluted=False):
        # Bump the generation counter here, synchronously, rather than inside the generator
        # below: send() itself is lazy (nothing in a generator function body runs until it is
        # first iterated), and a turn must be able to supersede an older one as soon as it is
        # called, even if the caller hasn't started reading either stream yet.
        with self._lock:
            self._generation += 1
            my_generation = self._generation
        return self._run(user_message, my_generation, image, polluted)

    # ---- what she declares about herself (tags are checked and capped in tags.py; these just apply them) ----

    def _journal(self, text, kind="狀態"):
        """A line in the journal about a change that really happened. Written by the program, never by the model,
        and only while memory is on."""
        if not self._summarize:
            return
        when = timesense.local_datetime(self._wall_clock(), self._time["timezone"] if self._time is not None else None)
        self._store.append_events([{"date": f"{when:%Y-%m-%d}", "time": f"{when:%H:%M}", "kind": kind, "text": text}])

    def _set_location(self, place):
        if place != self._character_state.load()["location"]:
            self._journal(f"地點→{place}")
        self._character_state.set_location(place)
        return ()

    def _set_status(self, word):
        now = self._wall_clock()
        current = self._character_state.load()
        holding = statebox.effective_status(current["status"], current["status_set_at"], now, self._state_settings)
        if word == "正常":
            if holding:
                self._journal("狀態→正常")
            self._character_state.set_status(None)
        else:
            if word != holding:
                self._journal(f"狀態→{word}")
            self._character_state.set_status(word, at=now)
        return ()

    def _gain_item(self, item):
        items = self._character_state.load()["items"]
        if item not in items and len(items) < self._state_settings["max_items"]:
            self._character_state.set_items(items + [item])
            self._journal(f"得到:{item}")
        return ()

    def _lose_item(self, name):
        items = self._character_state.load()["items"]
        # The exact name, or a part of a name when only one thing fits — never a guess between several.
        fits = [name] if name in items else [i for i in items if name in i]
        if len(fits) == 1:
            self._character_state.set_items([i for i in items if i != fits[0]])
            self._journal(f"失去:{fits[0]}")
        return ()

    def _change_outfit_from_tag(self, payload):
        """She wrote [換裝:name]: put it on if it is one of hers and not what she already wears."""
        scan = self._wardrobe.scan()
        folder = self._wardrobe.folder_for(payload, scan)
        if folder is None or folder == self._wardrobe.current(scan):
            return ()
        self._wardrobe.switch(folder)
        self._journal(f"換裝→{folder}")
        return [OutfitChange(folder, scan.outfits[folder])]

    def _asked_to_search(self, actions, searched, polluted, is_proactive):
        """The words of a [搜尋:…] she wrote at the start of her reply, if a search may be made now."""
        if self._search is None or is_proactive or searched is not None or polluted:
            return None
        payload = next((p for name, p in actions if name == "搜尋"), None)
        if payload is None:
            return None
        words, deep = searchintent.split_depth(payload)  # only the first pass can ask for depth
        query = searchintent.clean_query(words)
        return None if query is None else (query, deep)

    def _look_up_on_the_web(self, query, deep=False):
        """(what to tell her, whether web content is now in the turn). One search, never retried; after a
        failure the service is left alone for a short while."""
        if self._clock() < self._search_blocked_until:
            return websafety.unavailable_block(query), False
        try:
            raw = self._search.search(query)
        except Exception as error:  # a limit, the network, a broken answer: all the same to her
            log.warning("web search failed (%s); the turn goes on without it", type(error).__name__)
            self._search_blocked_until = self._clock() + self._search_settings["cooldown_s"]
            return websafety.unavailable_block(query), False
        results = websafety.usable_results(raw, self._search_settings["blocked_domains"], self._search_settings["max_results"])
        if not results:
            return websafety.no_results_block(query), False
        page = None
        if deep and self._fetch is not None:
            url = websafety.pick_fetch_url(raw, self._search_settings["blocked_domains"])
            page = self._read_page(query, url) if url else None
        self._journal(f"查過:{query}", kind="事件")  # only that she looked, and what the user wanted — never what was found
        return websafety.results_block(query, results, self._nonce(), page=page), True

    def _read_page(self, query, url):
        """The facts from one page, ready to show her — or None. By default the page goes through a separate
        persona-less model first and only its short plain-text notes are passed on; any failure just means
        she answers from the search snippets."""
        try:
            raw_text = self._fetch.fetch(url)["text"]
        except Exception as error:
            log.warning("reading a page failed (%s); using the search snippets only", type(error).__name__)
            return None
        if websafety.looks_like_injection(raw_text):
            log.warning("a page from %s tried to give instructions; dropped", websafety.domain_of(url))
            return None
        text = websafety.clean_snippet(raw_text, websafety.PAGE_CHARS)
        if not self._search_settings["quarantine"]:
            return text or None
        try:
            llm = self._quarantine_llm or self._llm
            request = websafety.summarizer_request(query, text, self._nonce())
            notes = "".join(llm.stream(websafety.SUMMARIZER_SYSTEM, [{"role": "user", "content": request}]))
        except Exception as error:
            log.warning("summarising a page failed (%s); the page is dropped", type(error).__name__)
            return None
        return websafety.clean_snippet(notes, websafety.SUMMARY_CHARS) or None

    def _look_up(self, message, everything, window_start, facts, now):
        """Things remembered that are not already in front of her, matching what was just said."""
        settings = self._memory_settings
        if len(message.strip()) < settings["retrieval_min_message_chars"]:
            return ""
        tz = self._time["timezone"] if self._time is not None else None
        times = self._store.load_times()

        def day_of(epoch):
            return "" if epoch is None else f"{timesense.local_datetime(epoch, tz):%Y-%m-%d}"

        docs = [{"text": line, "date": "", "label": "記得"}
                for line in memoryblock.left_out_fact_lines(facts, settings["long_term_max_chars"])]
        today = timesense.local_datetime(now, tz)
        resident_days = {f"{today:%Y-%m-%d}", f"{today - timedelta(days=1):%Y-%m-%d}"}
        docs += [{"text": e["text"], "date": e["date"], "label": "事件"}
                 for e in self._store.load_all_events() if e["date"] not in resident_days]
        first = max(0, len(everything) - settings["archive_scan_limit"])  # the most recent N of the whole archive
        polluted = self._store.load_polluted()
        for i in range(first, window_start):  # the messages in the recent window are already in front of her
            message_i = everything[i]
            if message_i["content"] == PROACTIVE_PROMPT:
                continue
            if message_i["role"] == "assistant" and i < len(polluted) and polluted[i]:
                continue  # what she said with web content in front of her is never remembered
            if message_i["role"] == "user":
                text, label = message_i["content"].removeprefix(IMAGE_MARKER), "使用者說"
            else:
                text, label = "".join(t for _, t in parse_reply(message_i["content"])), "你說"
            if text.strip():
                docs.append({"text": text, "date": day_of(times[i] if i < len(times) else None), "label": label})
        hits = retrieval.retrieve(message, docs, settings["retrieval_k"], settings["retrieval_snippet_chars"],
                                  settings["retrieval_min_score"])
        return retrieval.retrieval_block(hits)

    def _handle_tags(self, tags, turn):
        """Runs the handlers for these (name, payload) tags, in order; their events join the stream. A result that
        carries a `history_marker` is not an event: its text is kept in the saved reply instead."""
        for name, payload in tags:
            handler = self._tag_handlers.get(name)
            if handler is not None:
                for item in handler(payload) or ():
                    marker = getattr(item, "history_marker", None)
                    if marker is None:
                        yield item
                    else:
                        turn.markers.append(marker)

    def _run(self, user_message, my_generation, image=None, polluted=False):
        # `polluted` is set by the web-search flow: this turn's reply was written with web content
        # in front of the model, so every tag but the mood is ignored (see tags.py).
        # A proactive attempt is just an ordinary turn whose "user message" the character wrote
        # for itself — same generation/barge-in handling, same history storage, same everything
        # below, so the special-casing here is deliberately this small.
        is_proactive = user_message is PROACTIVE_TRIGGER
        if is_proactive:
            user_message = PROACTIVE_PROMPT
        turn = _Turn(start=self._clock())
        with self._lock:
            notices, self._startup_notices = self._startup_notices, []
        for message in notices:
            yield Notice("feature", message)
        facts = self._store.load_facts() if self._summarize else {}
        cursor = self._store.load_fold_progress() if self._summarize else 0
        everything = self._store.load()
        tail = everything[cursor:]
        past = tail[-2 * self._max_turns:]  # turns are stored in user/assistant pairs
        # Decay is worked out here, when the user comes back, from the stored time of the last
        # interaction — not by a timer or a background job. That is what lets the very first
        # reply after a long absence already reflect it, and it costs nothing while they are away.
        # Nothing is saved until the turn itself is (below), so a failed turn leaves no trace and
        # the retry simply works it out again from the same stored state.
        now = self._wall_clock()
        affection = decay_affection(self._store.load_affection(), self._store.load_last_interaction(),
                                    now, self._affection_grace_s, self._affection_half_life_s)
        system = self._system
        if self._summarize:
            tz = self._time["timezone"] if self._time is not None else None
            today = timesense.local_datetime(now, tz)
            days = [f"{today - timedelta(days=1):%Y-%m-%d}", f"{today:%Y-%m-%d}"]
            events = self._store.load_events(days)
            system += memoryblock.long_term_block(facts, self._memory_settings["long_term_max_chars"])
            system += memoryblock.journal_block(
                days[0], days[1], [e for e in events if e["date"] == days[0]],
                [e for e in events if e["date"] == days[1]], self._memory_settings["recent_notes_max_chars"])
        outfit_lines, switched_to = [], None
        if self._wardrobe is not None:
            scan = self._wardrobe.scan()
            if not is_proactive:  # her own made-up prompt is never a request
                asked = self._wardrobe.match_request(user_message, scan)
                if asked is not None and asked != self._wardrobe.current(scan):
                    self._wardrobe.switch(asked)
                    self._journal(f"換裝→{asked}")
                    switched_to = asked
                    yield OutfitChange(asked, scan.outfits[asked])
            outfit_lines = self._wardrobe.prompt_lines(scan, switched_to)
        if self._character_state is not None and self._state_settings["enabled"]:
            # One block: what she is, wears and carries, and how close she is to the person.
            system += statebox.state_block(self._character_state.load(), outfit_lines,
                                           relationship_lines(affection, self._mood), now, self._state_settings)
        else:
            system += relationship_block(affection, self._mood)
            if outfit_lines:
                system += "\n\n【服裝】\n" + "\n".join(outfit_lines)
        if self._time is not None:
            times = self._store.load_times()
            tz = self._time["timezone"]
            period = timesense.current_period(now, tz, self._time["routine"])
            # The reminder is only for the first turn after ENTERING a period — otherwise she would
            # ask about lunch with every single message. A proactive turn is exempt: the character
            # can always choose to stay silent, and a chat at 12:05 must not stop her saying
            # something about lunch at 12:30.
            if period is not None and not is_proactive and times and times[-1] is not None:
                earlier = timesense.current_period(times[-1], tz, self._time["routine"])
                if earlier is not None and (timesense.period_instance(times[-1], tz, earlier)
                                            == timesense.period_instance(now, tz, period)):
                    period = None
            system += timesense.time_block(now, tz, times[-1] if times else None, period)
        if self._summarize and not is_proactive:
            system += self._look_up(user_message, everything, len(everything) - len(past), facts, now)
        if is_proactive:
            system += PROACTIVE_SYSTEM_ADDENDUM
        message = {"role": "user", "content": user_message}
        if image is not None:
            message["image"] = image  # this turn only: see IMAGE_MARKER for why it isn't kept
        if self._time is not None:
            times = self._store.load_times()
            first = len(tail) - len(past) + cursor  # where `past` starts in the full history
            past = [
                m if m["role"] != "user" or m["content"] == PROACTIVE_PROMPT  # the character's own made-up prompt
                else self._with_gap_marker(m, times[first + i - 1] if first + i > 0 else None, times[first + i])
                for i, m in enumerate(past)
            ]
            if not is_proactive:
                message = self._with_gap_marker(message, times[-1] if times else None, now)
        searched = None
        can_search = self._search is not None and not is_proactive and not polluted
        # Features' own tag help — left out of any pass that carries web content, where their tags are ignored anyway.
        extras = "" if polluted else "".join(extra() for extra in self._prompt_extras)
        stage_system = system + extras
        if can_search:
            request = searchintent.match_search_request(user_message)
            if request is not None:  # the user's own order: no first pass at all
                searched = request.query
                yield Notice("search", f"🔍 查詢:{request.query}")
                block, used_web = self._look_up_on_the_web(request.query, request.deep)
                stage_system = system + block + ("" if used_web else extras)
                polluted = used_web  # from here on the turn carries someone else's words: see tags.py
            else:
                stage_system = system + extras + websafety.SEARCH_HELP + (" " + websafety.SEARCH_HELP_DEEP if self._fetch is not None else "")  # she may choose to look something up herself
        messages = past + [message]
        while True:  # at most two passes: the model's own, then — if it asked to look something up — the answer
            reply = ""
            segmenter = _Segmenter(polluted=polluted)
            index = 0
            asked = None
            try:
                stream = self._llm.stream(stage_system, messages)
                try:
                    for chunk in stream:
                        if self._stale(my_generation):
                            return  # a newer turn took over; abandon this one, nothing saved
                        reply += chunk
                        pairs = segmenter.feed(chunk)
                        actions = segmenter.release_actions()
                        asked = self._asked_to_search(actions, searched, polluted, is_proactive)
                        if asked is not None:
                            break  # drop the rest of this pass: nothing of it is spoken or kept
                        yield from self._handle_tags(actions, turn)
                        for emotion, text in pairs:
                            yield from self._speak(text, index, emotion, turn)
                            index += 1
                finally:
                    getattr(stream, "close", lambda: None)()
            except LLMError as exc:
                if self._stale(my_generation):
                    return
                yield Failure(exc.kind, FRIENDLY.get(exc.kind, FRIENDLY["unavailable"]))
                return
            if self._stale(my_generation):
                return
            if asked is None:
                pairs = segmenter.finish()
                actions = segmenter.release_actions()
                asked = self._asked_to_search(actions, searched, polluted, is_proactive)
                if asked is None:
                    yield from self._handle_tags(actions, turn)
                    for emotion, text in pairs:
                        yield from self._speak(text, index, emotion, turn)
                        index += 1
            if asked is None:
                break
            searched = asked[0]
            yield Notice("search", f"🔍 查詢:{asked[0]}")
            block, used_web = self._look_up_on_the_web(*asked)
            stage_system = system + block  # (the explanation of the tag is not repeated: she has used it)
            polluted = used_web
        if self._stale(my_generation):
            return
        if not (is_proactive and index == 0):
            # The one case that saves nothing at all: a proactive attempt where the character
            # chose silence (see PROACTIVE_SYSTEM_ADDENDUM) — index stays 0 when no (emotion,
            # text) pair ever reached _speak, whether the model wrote nothing at all or wrote
            # only tags with no actual words. Checking `index` rather than raw `reply` text
            # matters exactly for that second case: tag-only output is still a non-empty string.
            stored_user_text = (IMAGE_MARKER + user_message) if image is not None else user_message
            kept_reply = tagtable.strip_action_tags(reply)
            if polluted:  # shown in the panel as she said it, but no web address is kept in the history
                kept_reply = websafety.strip_urls(kept_reply)
            if searched is not None:  # a note of what she looked up — never what she found
                kept_reply = f"[搜尋:{searched}]" + kept_reply  # (the wording was already cleaned of brackets)
            if turn.markers:  # after the search note, which other code expects at the very start
                note = _SEARCH_NOTE.match(kept_reply)
                cut = note.end() if note else 0
                kept_reply = kept_reply[:cut] + "".join(turn.markers) + kept_reply[cut:]
            self._store.append_turn(stored_user_text, kept_reply, at=now, polluted=polluted)
            # Committed only here, with the saved turn: a failed or superseded turn returned
            # above, so a reply that was abandoned never moves the relationship.
            # Every saved turn records when it happened — even one without a tag — or an active
            # conversation would look like an absence.
            if segmenter.affection_deltas:
                affection = apply_affection(affection, segmenter.affection_deltas[0])
            self._store.save_affection(affection, at=now)
            if segmenter.mood is not None:
                self._mood = segmenter.mood
            yield from self._handle_tags(segmenter.state_tags, turn)  # state tags count only for a saved turn
            if self._summarize:
                self._background(self._maybe_summarize)
        first_ms = None if turn.first_audio_s is None else turn.first_audio_s * 1000
        yield Done(first_audio_ms=first_ms)
        # Only a turn that made it all the way here (not stale, not failed) reschedules — the
        # loser of a barge-in returned earlier and the turn that superseded it will schedule the
        # next attempt when it, in turn, finishes.
        with self._lock:
            if self._proactive_enabled and not self._stale(my_generation):
                self._cancel_scheduled_proactive()
                self._schedule_next_proactive()
