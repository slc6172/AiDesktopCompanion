"""Photos she takes (spec Part 12, section 5): [照片:…] at the start of a reply -> a picture made in the
background -> a `photo` event on the push channel.

The turn engine only decides WHEN the tag may act (tags.py); everything about photos is here.
"""
import logging
import threading
from datetime import datetime, timezone

from .cloudflare_adapter import ImageError
from .engine import HISTORY_MARKER, Notice, Photo
from .imageprep import shrink_reference

log = logging.getLogger(__name__)

DAY = 86400
TOO_SOON_NOTICE = "📷 離上一張太近了,晚一點再拍。"
NOT_TODAY_NOTICE = "📷 今天不方便再拍照了。"
OUT_OF_ALLOWANCE_NOTICE = "📷 今天的免費額度用完了,明天再拍。"
TRY_LATER_NOTICE = "📷 現在拍不了,等一下再試。"
TOO_LARGE_NOTICE = "📷 這張的資料太大,拍不了。"
SWITCHED_OFF_NOTICE = "📷 拍照功能因為設定問題已關閉(Cloudflare 回報 {code}),請檢查 image 設定與模型後重新啟動。"
NOT_TODAY_HELP = ("\n\n【拍照】今天不方便拍照(不要寫任何照片標籤)。如果使用者想看照片,請用你自己的口吻"
                  "婉拒,例如說今天不方便,改天再拍。")
# Cloudflare's own codes (spec section 5): what each one means for the program.
ALLOWANCE_GONE = {3036}                 # the day's free allowance is used up (authoritative)
PASSING = {3040, 3007}                  # temporarily out of capacity / too slow
WRONG_SETUP = {5035, 5007, 5004}        # needs a paid plan / wrong model id / wrong data format
TOO_LARGE = {3006}
BUSY_NOTICE = "📷 上一張照片還在生成,這次先不拍。"
FAILED_BECAUSE = "📷 這張照片沒拍成({why})。"
PHOTO_HELP = (
    "\n\n【拍照】你可以拍照給使用者看。想拍(或答應了使用者要拍)時,在回覆最一開頭(說任何話之前)寫 "
    "[照片:現在|場景描述],場景描述請用英文寫,例如 [照片:現在|sitting by the window, soft afternoon light]"
    "好,我拍給你看!。三種拍法:現在的你 → [照片:現在|…];過去某個時間或場景的你 → [照片:當時|…],"
    "若要穿某套已有的服裝就寫 [照片:當時@服裝名|…];某件物品(例如你買的洋裝,只拍東西、不拍人)→ [照片:物品|…]。"
    "照片會在背景生成,稍後才會出現,所以不要說已經拍好了。只在真的要拍的時候才寫,一次回覆最多一個。"
)
KEEP_HER_IN_THAT_OUTFIT = "Keep the same person and the outfit of the reference image."
CHANGE_ONLY_THE_OUTFIT = ("Keep the same person, face, hairstyle and body shape as in the reference image, "
                          "but change ONLY the outfit to: ")
KEEP_HER_THE_SAME = "Keep the same person, face, hairstyle, body shape and outfit as in the reference image."


def _kind_of_picture(data):
    """The file extension for what the service sent back, or None when it is not a picture we know."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class PhotoStarted:
    """Returned by the tag handler: a picture is being made under this file name (without its extension, which is
    only known once the service has answered). Never sent to the page; the engine writes `history_marker`
    into the saved reply, so that after a restart the picture can be shown again."""

    def __init__(self, stem):
        self.stem = stem
        self.history_marker = HISTORY_MARKER.format(stem=stem)


def _in_thread(fn):
    threading.Thread(target=fn, daemon=True).start()


class PhotoStudio:
    def __init__(self, adapter, settings, wardrobe, push, photos_dir, wall_clock, state, runner=_in_thread):
        self._adapter = adapter
        self._settings = settings
        self._wardrobe = wardrobe
        self._push = push                  # where finished pictures go (the page's push channel)
        self._photos_dir = photos_dir
        self._wall_clock = wall_clock
        self._runner = runner
        self._state = state                # where the day's count and the "allowance gone" mark live (survive a restart)
        self._switched_off = False         # a setup problem: until the program is restarted, no calls and no mention
        self._last_started = None
        self._lock = threading.Lock()
        self._used_stems = set()
        self._busy = False  # one picture at a time: from the moment one is accepted until it is saved or has failed

    def handlers(self):
        return {"照片": self.handle}

    def prompt_help(self):
        """What she is told about taking photos — said only while she really can."""
        if self._switched_off:
            return ""
        return NOT_TODAY_HELP if self._allowance_used_up() else PHOTO_HELP

    def _today(self):
        return datetime.fromtimestamp(self._wall_clock(), timezone.utc).strftime("%Y-%m-%d")

    def _allowance_used_up(self):
        values = self._state.load()
        until = values.get("photo_exhausted_until")
        if until is not None and self._wall_clock() < until:
            return True                    # Cloudflare itself said so; the local count is only an estimate
        return values.get("photo_day") == self._today() and (values.get("photo_count") or 0) >= self._settings["max_per_day"]

    def handle(self, payload):
        mode, _, description = payload.partition("|")
        mode, _, named = mode.strip().partition("@")
        if mode not in ("現在", "當時", "物品"):
            return ()                            # something she made up: nothing to take, no slot used
        if self._switched_off:
            return ()                      # she was not told about photos; if she writes one anyway, nothing happens
        with self._lock:
            if self._allowance_used_up():
                return [Notice("photo", NOT_TODAY_NOTICE)]
            if self._busy:
                return [Notice("photo", BUSY_NOTICE)]
            now = self._wall_clock()
            if self._last_started is not None and now - self._last_started < self._settings["cooldown_s"]:
                return [Notice("photo", TOO_SOON_NOTICE)]
            self._busy, self._last_started = True, now
        try:
            prompt, reference = self._plan(mode, named.strip(), description.strip())
            stem = self._new_stem()
            self._runner(lambda: self._make(prompt, reference, stem))
        except Exception as error:
            # Whatever went wrong here, her reply must still reach the person: a photo is never worth a broken turn.
            log.exception("photo: could not get the picture ready")
            self._busy = False
            return [Notice("photo", FAILED_BECAUSE.format(why=f"程式錯誤:{type(error).__name__}"))]
        return [PhotoStarted(stem)]

    def _plan(self, mode, named, description):
        """(prompt, reference picture or None). The fixed parts are written here, never by her: she only
        supplies the scene / clothes / object. Settled now, not in the background job — the outfit she wears
        can change in between (even later in this very reply)."""
        if mode == "物品":
            return description, None             # the thing itself: no person, nothing uploaded
        scan = self._wardrobe.scan()
        worn = self._wardrobe.current(scan)
        wanted = self._wardrobe.folder_for(named, scan) if named else None
        if mode == "當時" and wanted is not None and wanted in scan.bases:
            return f"{KEEP_HER_IN_THAT_OUTFIT} {description}", shrink_reference(scan.bases[wanted].read_bytes())
        base = self._wardrobe.base_photo(worn, scan) if worn is not None else None
        if base is not None:
            reference = shrink_reference(base.read_bytes())
            if mode == "當時":
                return f"{CHANGE_ONLY_THE_OUTFIT}{description}", reference
            return f"{KEEP_HER_THE_SAME} {description}", reference
        outfit_line = self._wardrobe.description(worn, scan) if worn is not None else None
        return ". ".join(part for part in (self._settings["appearance"].strip(), outfit_line, description) if part), None

    def _new_stem(self):
        """The file name (no extension) this picture will have: the time, and -2, -3… when that second is taken.
        Chosen before the picture exists because the history needs it right away."""
        stamp = datetime.fromtimestamp(self._wall_clock(), timezone.utc).strftime("%Y%m%d-%H%M%S")
        stem, n = stamp, 1
        while stem in self._used_stems or any(self._photos_dir.glob(stem + ".*")):
            n += 1
            stem = f"{stamp}-{n}"
        self._used_stems.add(stem)
        return stem

    def _make(self, prompt, reference, stem):
        try:
            self._push(self._take_with_one_retry(prompt, reference, stem))
        except ImageError as error:
            self._push_what_went_wrong(error)
        except Exception as error:
            log.exception("photo failed unexpectedly")
            self._push(Notice("photo", FAILED_BECAUSE.format(why=f"程式錯誤:{type(error).__name__}")))
        finally:
            self._busy = False

    def _take_with_one_retry(self, prompt, reference, stem):
        try:
            return self._take(prompt, reference, stem)
        except ImageError as error:
            if error.code in PASSING or error.timed_out or error.status == 408:
                log.warning("photo: passing trouble (%s); trying once more", error)
                return self._take(prompt, reference, stem)
            raise

    def _push_what_went_wrong(self, error):
        log.warning("photo failed: %s (http %s, code %s, timeout %s)", error, error.status, error.code, error.timed_out)
        if error.code in ALLOWANCE_GONE:
            midnight = (self._wall_clock() // DAY + 1) * DAY       # the next 00:00 UTC
            self._state.set_photo_exhausted_until(midnight)
            self._push(Notice("photo", OUT_OF_ALLOWANCE_NOTICE))
        elif error.code in WRONG_SETUP:
            self._switched_off = True
            self._push(Notice("photo", SWITCHED_OFF_NOTICE.format(code=error.code)))
        elif error.code in TOO_LARGE:
            self._push(Notice("photo", TOO_LARGE_NOTICE))
        elif error.code in PASSING or error.timed_out or error.status == 408:
            self._push(Notice("photo", TRY_LATER_NOTICE))
        else:
            # Not a case we know: say what Cloudflare said (status, code, its own words — never the token).
            self._push(Notice("photo", FAILED_BECAUSE.format(why=error)))

    def _take(self, prompt, reference, stem):
        picture = self._adapter.generate(prompt, reference, self._settings["width"], self._settings["height"])
        extension = _kind_of_picture(picture)
        if extension is None:
            raise ValueError("the service did not send back a picture")
        self._photos_dir.mkdir(parents=True, exist_ok=True)
        name = f"{stem}.{extension}"
        (self._photos_dir / name).write_bytes(picture)
        self._state.record_photo(self._today())
        return Photo(name, f"/photos/{name}")


def startup_warnings(settings, wardrobe):
    """Said once at startup: with no base photo and no written appearance her pictures have nothing to keep
    her the same person. A warning only — she still tries."""
    if settings["appearance"].strip():
        return []
    scan = wardrobe.scan()
    missing = [name for name in scan.outfits if name not in scan.bases]
    if scan.outfits and not missing:
        return []
    which = ("服裝「" + "」、「".join(missing) + "」沒有基底照(base.png)") if missing else "目前沒有可用的服裝(也就沒有基底照)"
    return [f"拍照功能已啟用,但{which},config.json 的 image.appearance 也是空的,"
            "拍出來的人物可能每張都不一樣。請放一張基底照,或填寫 image.appearance(英文外觀描述)。"]
