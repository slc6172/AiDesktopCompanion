"""Outfits: each sub-folder of clips/ is one set of clothes with its own animations (spec Part 12).

    clips/日常/idle.webm, talking-happy.webm, ...
    clips/睡衣/idle.webm, ...

An outfit needs at least an `idle` clip. A folder whose name starts with "_" is a draft and is
ignored. Clips in clips/ itself (the layout before outfits existed) are NOT used and NOT moved:
the person is told to put them in a folder. Clips are only ever looked up inside the chosen
outfit — a missing one is never borrowed from another outfit.
"""
from dataclasses import dataclass, field
from urllib.parse import quote

CLIP_EXTENSIONS = ("mp4", "webm")  # webm last so it wins when both exist
BASE_PHOTO_EXTENSIONS = ("png", "jpg", "jpeg", "webp")  # base.<ext>: the photo of her in this outfit, the reference for her pictures


@dataclass
class OutfitScan:
    outfits: dict = field(default_factory=dict)   # name -> {state: url}, sorted by name
    descriptions: dict = field(default_factory=dict)  # name -> the one line in outfit.txt (when there is one)
    bases: dict = field(default_factory=dict)  # name -> Path of its base photo (only the outfits that have one)
    warnings: list = field(default_factory=list)  # plain-language lines for the log and the chat


def _clips_in(folder, url_prefix):
    found = {}
    for ext in CLIP_EXTENSIONS:
        for path in sorted(folder.glob(f"*.{ext}")):
            found[path.stem.replace("-", ":", 1)] = f"{url_prefix}/{quote(path.name)}"
    return found


def _first_line(path):
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                return line.strip()
    except (OSError, UnicodeDecodeError):
        pass
    return None


# Where the tutorial for making character animation lives (the start-up notices point at it).
ANIMATION_TUTORIAL = "docs/animation-tutorial.md"


def scan_outfits(clips_dir):
    scan = OutfitScan()
    if not clips_dir.exists():
        scan.warnings.append(f"找不到 clips 資料夾,先用表情符號代替。想讓角色動起來,請看 {ANIMATION_TUTORIAL}。")
        return scan
    for folder in sorted(p for p in clips_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
        clips = _clips_in(folder, f"/clips/{quote(folder.name)}")
        if "idle" not in clips:
            scan.warnings.append(f"服裝資料夾「{folder.name}」裡沒有 idle 影片,已略過。")
            continue
        scan.outfits[folder.name] = clips
        base = next((folder / f"base.{ext}" for ext in BASE_PHOTO_EXTENSIONS if (folder / f"base.{ext}").is_file()), None)
        if base is not None:
            scan.bases[folder.name] = base
        description = _first_line(folder / "outfit.txt")
        if description:
            scan.descriptions[folder.name] = description
    if not scan.outfits:
        scan.warnings.append(
            f"找不到任何可用的服裝資料夾(需要 clips/<服裝名>/idle.webm),先用表情符號代替。想讓角色動起來,請看 {ANIMATION_TUTORIAL}。")
    return scan


def pick_outfit(names, remembered, default):
    """What she wears: the remembered outfit if its folder still exists, else the configured
    default if it exists, else the first by name. None when there are no outfits at all."""
    for candidate in (remembered, default):
        if candidate in names:
            return candidate
    return min(names) if names else None


# ---- asking her to change ---------------------------------------------------------------------------
# Deliberately narrow: only a short, clear command ("換成睡衣", "穿上睡袍") counts. Before the
# verb there may only be politeness words, after the name only sentence-final particles and
# punctuation. That one rule is what keeps questions ("…好嗎?"), refusals ("不要…", "別…") and plain
# talk about clothes from changing anything — wrongly changing the picture of her on screen is
# worse than needing the person to ask again.

_VERBS = ("換成", "換上", "換到", "穿上", "穿著", "換", "穿")
_LEADING = "請麻煩幫我給我你可以先快點就再好嗯那對,\uff0c "
_TRAILING = "吧啊啦喔哦囉呀嘛~\uff5e!\uff01\u3002.\u2026,\uff0c "


class Wardrobe:
    """The clothes she owns (clips/ sub-folders), which she wears, and the asking-to-change rule.

    Folders are looked at fresh on every use, so a folder added while the app runs is picked up.
    `settings` returns {"default": name, "aliases": {folder: [other names]}}.
    """

    def __init__(self, clips_dir, state, settings=None):
        if settings is None:
            from .config import resolve_outfit_config as settings
        self._clips_dir = clips_dir
        self._state = state
        self._settings = settings

    def scan(self):
        return scan_outfits(self._clips_dir)

    def current(self, scan=None):
        scan = scan or self.scan()
        return pick_outfit(scan.outfits, self._state.load()["outfit"], self._settings()["default"])

    def switch(self, name):
        self._state.set_outfit(name)

    def base_photo(self, name, scan=None):
        """The base photo (Path) of that outfit, or None when it has none (or there is no such outfit)."""
        return (scan or self.scan()).bases.get(name)

    def description(self, name, scan=None):
        """The one English line in that outfit's outfit.txt, or None."""
        return (scan or self.scan()).descriptions.get(name)

    def match_request(self, text, scan=None):
        """The outfit this message clearly asks her to put on, or None."""
        scan = scan or self.scan()
        text = text.strip()
        if not scan.outfits or not text:
            return None
        lowered = text.lower()
        for name, folder in self._names(scan):
            for verb in _VERBS:
                head, found, tail = lowered.partition(verb)
                if not found:
                    continue
                after_verb = tail.lstrip("上成到一下件那你的 ")
                if after_verb.startswith(name) and all(c in _LEADING + " " for c in head) \
                        and all(c in _TRAILING for c in after_verb[len(name):]):
                    return folder
        return None

    def folder_for(self, written, scan=None):
        """The folder a name or alias written by the model points at (any capitalisation), else None."""
        scan = scan or self.scan()
        wanted = written.lower()
        return next((folder for name, folder in self._names(scan) if name == wanted), None)

    def _names(self, scan):
        """Every name she answers to -> its folder. The strict ending rule above means a longer name
        ("睡衣外套") can never be mistaken for a shorter one inside it ("睡衣"), whatever the order."""
        names = {folder: folder for folder in scan.outfits}
        for folder, aliases in self._settings().get("aliases", {}).items():
            if folder in scan.outfits:
                for alias in aliases:
                    names.setdefault(alias, folder)
        return [(n.lower(), f) for n, f in names.items()]

    def prompt_lines(self, scan, switched_to=None):
        """The same, as bare lines — for folding into the one state block."""
        worn = self.current(scan)
        if worn is None:
            return []
        lines = [f"你目前穿著:{worn}" + (f"({scan.descriptions[worn]})" if worn in scan.descriptions else "") + "。"]
        if len(scan.outfits) > 1:
            lines.append(f"你可以換的服裝只有:{'、'.join(scan.outfits)}。使用者要你換成清單以外的衣服時,"
                         "你沒有那一件,請用自己的口吻自然地回應,不要假裝換了。")
            lines.append("你自己想換衣服、或答應了使用者要換時,在回覆最一開頭(說任何話之前)寫 [換裝:服裝名],"
                         "再接著說話,例如 [換裝:睡衣]好,我去換!。只在真的要換的時候才寫,不要為了好玩亂寫。")
        if switched_to is not None:
            lines.append(f"使用者剛請你換成『{switched_to}』,已換好,請自然地回應(不要再說一次要去換)。")
        return lines
