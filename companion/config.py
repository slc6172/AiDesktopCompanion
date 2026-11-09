import json
import math
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .paths import user_dir

DEFAULT_CONFIG = {
    "tts": {
        # The first question: speak at all? False = text only, and everything below (engine,
        # voices, keys) is ignored. Only when this is true does the engine choice take effect.
        "enabled": True,
        # "auto" picks the OpenAI-compatible server (PrimeTTS) when a server address is configured, edge-tts otherwise —
        # exactly the behavior this project had before this file existed (see resolve_engine).
        # Set explicitly to "edge", "openai", "fish", or "off" to pin it instead.
        "engine": "auto",
        "fallback": True,  # use the other engine for a sentence the primary one can't manage
        "edge": {
            "voice": "zh-TW-HsiaoChenNeural",
            "rate": "+0%",
            "volume": "+0%",
            "pitch": "+0Hz",
        },
        # An OpenAI-compatible speech server (PrimeTTS and the like). Its engine value may be spelt
        # "openai" or "primetts"; the section is `tts.openai`.
        "openai": {
            "url": None,  # e.g. "http://127.0.0.1:8880/v1"; required for "openai"/"auto" to use it
            "model": "primetts",
            "voice": "default",
            "format": "wav",
            "api_key": None,
            "timeout_s": 15,
        },
        # Fish Audio (cloud). Never picked by "auto": set tts.engine to "fish" to use it. The
        # API key is NOT stored here — it comes from FISH_API_KEY or the Windows Credential
        # Manager (app.py --set-key-fish), like the Gemini and Groq keys.
        "fish": {
            "model": "s2.1-pro-free",
            "reference_id": None,  # the Fish voice model id; None = Fish's default voice
            "format": "mp3",
            "timeout_s": 20,
            # The reply's emotion, spoken as an inline Fish tag in front of each sentence. ONLY
            # Fish ever receives these; edge-tts / PrimeTTS are never sent a tag (they would read
            # it aloud). "" = send that emotion as plain text. Any tag text works with the S2
            # models, e.g. "[excited]" or "[溫柔地說]". Animations are not affected by this.
            "emotion_tags": {
                "neutral": "",
                "happy": "[happy]",
                "sad": "[sad]",
                "angry": "[angry]",
                "surprised": "[surprised]",
            },
        },
    },
    "proactive": {
        # Off by default: the character only ever speaks up unprompted once this is turned on.
        "enabled": False,
        "min_minutes": 10,
        "max_minutes": 30,
    },
    "time": {
        "enabled": True,
        "timezone": None,  # an IANA name like "Asia/Taipei"; None = this computer's local time zone
        "gap_marker_minutes": 30,
        "routine": [
            {"name": "早餐", "start": "07:00", "end": "09:00",
             "hint": "這個時間通常會吃早餐,可以自然地帶到(像是問他吃了沒),不必每次都提。"},
            {"name": "午餐", "start": "12:00", "end": "13:30",
             "hint": "這個時間通常會吃午餐,可以自然地帶到(像是問他吃了沒),不必每次都提。"},
            {"name": "晚餐", "start": "18:00", "end": "19:30",
             "hint": "這個時間通常會吃晚餐,可以自然地帶到(像是問他吃了沒),不必每次都提。"},
            # 23:00 -> 07:00 crosses midnight (the end is earlier than the start).
            {"name": "深夜", "start": "23:00", "end": "07:00",
             "hint": "現在是睡覺的時間。你自己維持醒著、不要裝睡,但發現太晚時可以自然地關心他怎麼還沒睡,語氣放輕一點。"},
        ],
        "quiet_hours": {"enabled": True, "start": "00:00", "end": "07:00"},  # no unprompted speech
    },
    "stt": {
        # The first question: listen at all? False = typing only, no microphone controls, and
        # every setting below is ignored. Only when this is true do they take effect.
        "enabled": True,
        # Language hint for the recogniser, e.g. "zh". None = detect automatically (the default:
        # forcing a language makes whole sentences in OTHER languages come out garbled or
        # translated, so it is opt-in).
        "language": None,
        # Throw away recordings the recogniser itself doubts were speech, or that it detected as
        # a language you never speak. Needs Groq's detailed response (verbose_json); if a field is
        # missing from the answer, nothing is thrown away.
        "filter": True,
        "allowed_languages": ["zh", "en", "ja"],  # [] = accept any language
        # Short phrases the recogniser tends to INVENT from room noise or her own echo ("Thank you.").
        # A recording is thrown away when the whole transcript is exactly one of these (ignoring case and
        # punctuation) AND it was detected as a language other than your main one (stt.language, or the
        # first of allowed_languages). Cost: saying just "Thank you." in English is taken as "didn't catch
        # that". [] = off. Only works while "filter" is on.
        "ignore_phrases": ["thank you", "thanks", "okay", "yes", "music", "and the", "you", "bye"],
        # A hint sent along with every recording, e.g. "使用者主要以繁體中文對話,也可能使用英文。只轉錄實際聽到的語音。"
        # (it nudges the recogniser's spelling and style; Groq reads at most about 224 tokens of it). None = send
        # nothing, exactly as before. Off by default: a prompt can also make it more eager to "hear" words.
        "prompt": None,
        "no_speech_prob_max": 0.6,   # drop a stretch if "probably not speech" is above this ...
        "avg_logprob_min": -1.0,     # ... AND the recogniser's own confidence is below this
        # One "[stt]" line per recording in data/app.log (what was heard, how sure, kept or dropped)
        # — for tuning the two numbers above; no audio is stored.
        "debug_log": False,
    },
    "ui": {
        # Start continuous listening on its own as soon as the page loads. Off by default: a
        # microphone that opens by itself should be something you asked for.
        "auto_listen": False,
        # "normal" = ordinary always-on-top; "screen-saver" also covers the taskbar and some
        # full-screen programs (Windows).
        "on_top_level": "normal",
        # How much of the character's width (centre-aligned) takes the mouse; the transparent
        # sides let clicks fall through. 0.2 .. 1.0.
        "hit_width_ratio": 0.6,
        # How many times louder you must be to cut in while she is talking (her own voice leaks back
        # into the microphone). 1 = off. Needs measuring on your own speakers before raising it;
        # see docs/configuration.md.
        "speaking_boost": 1.0,
        # When something is heard while she talks, her voice is turned down (not stopped) until the
        # recogniser says whether it was really you. This is how loud she stays: 1 = not turned down at
        # all, 0.4 = about -8 dB (default), 0.2 = about -14 dB. 0.1 .. 1.0. A quieter dip makes her
        # echo leak back into the recording less; a gentler dip is less noticeable but lets more of it in.
        "duck_level": 0.4,
    },
    # ---- Part 12 ----
    "outfit": {
        # clips/<name>/ folders are outfits; this one is worn when nothing else has been chosen.
        "default": "日常",
        # Other ways of asking for an outfit: {folder name: [alternative names]}.
        "aliases": {"睡衣": ["睡袍", "pajamas"]},
    },
    # Photos she can take (Cloudflare Workers AI). Off by default; the API token is NOT stored
    # here — CF_API_TOKEN or the Windows Credential Manager (app.py --set-key-cloudflare).
    "image": {
        "enabled": False,
        "model": "flux-2-klein-9b",
        "account_id": None,  # or the CF_ACCOUNT_ID environment variable (not a secret)
        "width": 576,
        "height": 1024,
        "max_per_day": 6,
        "cooldown_s": 30,
        "timeout_s": 120,
        "appearance": "",  # an English description of her, used when there is no base photo
    },
    # Looking things up on the web (TinyFish). Off by default; the key is TINYFISH_API_KEY or the
    # Credential Manager (app.py --set-key-tinyfish), never this file.
    "tinyfish": {
        "enabled": False,
        "location": "TW",
        "language": "zh",
        "max_results": 5,
        "quarantine": True,
        "blocked_domains": [],
    },
    "memory": {
        "enabled": True,  # COMPANION_MEMORY=off in the environment turns it off regardless
        "long_term_max_chars": 2000,
        "recent_notes_max_chars": 600,
        "retrieval_k": 3,
        "retrieval_snippet_chars": 200,
        "retrieval_min_message_chars": 3,
        "retrieval_min_score": 0.6,  # how strong a match must be; higher = fewer, surer memories brought up
        "archive_scan_limit": 20000,
    },
    "companion_state": {
        "enabled": True,
        "default_location": "家裡",
        "status_ttl_hours": {"微醺": 3, "酒醉": 8, "疲倦": 10, "感冒": 72},
        "default_status_ttl_hours": 12,
        "max_items": 20,
    },
}


def config_path():
    """Next to persona.md: a plain JSON file the user can open in any text editor, not hidden
    away in an app-data folder. Looked up fresh on every call (not cached) so an edit takes
    effect the next time the app starts, without reaching into this module's internals."""
    return user_dir() / "config.json"


def _deep_merge(base, override):
    """`override`'s values win; a dict value is merged key-by-key instead of replacing the
    whole section, so a config file that sets only one field keeps every sibling default."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config():
    """DEFAULT_CONFIG, deep-merged with whatever is in config.json. A missing file or one that
    isn't valid JSON is treated as "nothing set" rather than an error — a typo in a file the
    user hand-edits should not stop the app from starting."""
    try:
        user_values = json.loads(config_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        user_values = {}
    if not isinstance(user_values, dict):
        user_values = {}
    return _deep_merge(DEFAULT_CONFIG, user_values)


def save_config(config):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_engine(engine_setting, primetts_url):
    """"auto" becomes a real choice once it is known whether a PrimeTTS address is configured;
    an explicit "edge"/"primetts"/"fish"/"off" is never second-guessed. "auto" never picks
    "fish": it is a cloud service with its own key and data-use terms, so it is opt-in."""
    if engine_setting == "auto":
        return "primetts" if primetts_url else "edge"
    if engine_setting == "openai":  # the new name for the same engine (kept as "primetts" inside)
        return "primetts"
    return engine_setting


def _bool_env(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "off", "no", "")


def resolve_proactive_config():
    """Same precedence as resolve_tts_config: COMPANION_PROACTIVE[_MIN_MINUTES/_MAX_MINUTES]
    override config.json's "proactive" section, which overrides the built-in default (off)."""
    cfg = load_config()["proactive"]
    return {
        "enabled": _bool_env("COMPANION_PROACTIVE", cfg["enabled"]),
        "min_minutes": float(os.environ.get("COMPANION_PROACTIVE_MIN_MINUTES") or cfg["min_minutes"]),
        "max_minutes": float(os.environ.get("COMPANION_PROACTIVE_MAX_MINUTES") or cfg["max_minutes"]),
    }


def resolve_tts_config():
    """The effective TTS settings: an environment variable, when set, overrides config.json,
    which overrides the built-in default — the same precedence apikey.py already uses for API
    keys. Returns plain values ready to build EdgeTTS/PrimeTTS from; "engine" is still "auto"
    here (see resolve_engine) because whether a PrimeTTS URL ends up configured is decided by
    this same function, not before it."""
    cfg = load_config()["tts"]
    edge, prime = cfg["edge"], cfg["openai"]

    def env_or(name, default):
        value = os.environ.get(name)
        return value if value not in (None, "") else default

    fallback_env = os.environ.get("COMPANION_TTS_FALLBACK")
    fallback = cfg["fallback"] if fallback_env is None else fallback_env != "off"

    return {
        "enabled": cfg["enabled"] if isinstance(cfg["enabled"], bool) else DEFAULT_CONFIG["tts"]["enabled"],
        "engine": env_or("COMPANION_TTS", cfg["engine"]),
        "fallback": fallback,
        "edge_voice": env_or("COMPANION_VOICE", edge["voice"]),
        "edge_rate": env_or("COMPANION_RATE", edge["rate"]),
        "edge_volume": env_or("COMPANION_VOLUME", edge["volume"]),
        "edge_pitch": env_or("COMPANION_PITCH", edge["pitch"]),
        "primetts_url": env_or("COMPANION_PRIMETTS_URL", prime["url"]),
        "primetts_model": env_or("COMPANION_PRIMETTS_MODEL", prime["model"]),
        "primetts_voice": env_or("COMPANION_PRIMETTS_VOICE", prime["voice"]),
        "primetts_format": env_or("COMPANION_PRIMETTS_FORMAT", prime["format"]),
        "primetts_api_key": env_or("COMPANION_PRIMETTS_API_KEY", prime["api_key"]),
        "primetts_timeout_s": float(env_or("COMPANION_PRIMETTS_TIMEOUT_S", prime["timeout_s"])),
    }


def resolve_fish_config():
    """The effective Fish Audio settings, same precedence as the other sections (environment variable >
    config.json > built-in default). Kept separate from resolve_tts_config so the existing engines'
    settings stay exactly as they were. This is a hand-edited file, so a value of the wrong type or
    out of range is treated as "not set" instead of stopping the app from starting."""
    defaults = DEFAULT_CONFIG["tts"]["fish"]
    tts = load_config().get("tts")
    cfg = tts.get("fish") if isinstance(tts, dict) else None
    if not isinstance(cfg, dict):
        cfg = {}

    def text(env_name, value, allowed=None):
        """The first of (environment, file) that is non-blank text (and, if given, one of `allowed`)."""
        def good(v):
            return isinstance(v, str) and v.strip() != "" and (allowed is None or v.strip().lower() in allowed)
        picked = _first_valid([os.environ.get(env_name), value], good, None)
        if picked is None:
            return None
        return picked.strip().lower() if allowed is not None else picked.strip()

    timeout = _first_valid(
        # an env var is always text, so it is parsed; a number in config.json must BE a number
        [_as_ratio(os.environ.get("COMPANION_FISH_TIMEOUT_S")), _real_number(cfg.get("timeout_s"))],
        lambda v: v is not None and 0 < v <= 300, defaults["timeout_s"])  # NaN and inf fail this too

    tags = cfg.get("emotion_tags", defaults["emotion_tags"])
    return {
        "model": text("COMPANION_FISH_MODEL", cfg.get("model")) or defaults["model"],
        "reference_id": text("COMPANION_FISH_REFERENCE_ID", cfg.get("reference_id")) or defaults["reference_id"],
        "format": text("COMPANION_FISH_FORMAT", cfg.get("format"), allowed=("mp3", "wav")) or defaults["format"],
        "timeout_s": float(timeout),
        "emotion_tags": {name: tag for name, tag in tags.items() if isinstance(tag, str)} if isinstance(tags, dict) else {},
    }


def _first_valid(candidates, is_valid, default):
    """The first candidate (env var, then config file) that passes `is_valid`, else `default`: an
    unusable override is treated as not set, so whatever sits underneath it still applies."""
    for value in candidates:
        if is_valid(value):
            return value
    return default


def _as_ratio(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _real_number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def resolve_ui_config():
    """The effective UI settings: env var > config.json > default, same precedence as the other
    sections. A value of the wrong type or out of range is treated as "not set" rather than as an
    error — this is a hand-edited file, and a typo must not stop the app from starting."""
    defaults = DEFAULT_CONFIG["ui"]
    cfg = load_config()["ui"]
    if not isinstance(cfg, dict):
        cfg = {}

    env_flag = os.environ.get("COMPANION_AUTO_LISTEN")
    auto_listen = _first_valid(
        [None if env_flag is None else _bool_env("COMPANION_AUTO_LISTEN", None), cfg.get("auto_listen")],
        lambda v: isinstance(v, bool), defaults["auto_listen"])

    on_top_level = _first_valid(
        [os.environ.get("COMPANION_ON_TOP_LEVEL"), cfg.get("on_top_level")],
        lambda v: v in ("normal", "screen-saver"), defaults["on_top_level"])

    ratio = _first_valid(
        [_as_ratio(os.environ.get("COMPANION_HIT_WIDTH_RATIO")), _as_ratio(cfg.get("hit_width_ratio"))],
        lambda v: v is not None and 0.2 <= v <= 1.0, defaults["hit_width_ratio"])  # NaN fails this too

    boost = _first_valid(
        # an env var is always text, so it is parsed; a number in config.json must BE a number
        [_as_ratio(os.environ.get("COMPANION_SPEAKING_BOOST")), _real_number(cfg.get("speaking_boost"))],
        lambda v: v is not None and 1 <= v <= 10, defaults["speaking_boost"])

    duck = _first_valid(
        [_as_ratio(os.environ.get("COMPANION_DUCK_LEVEL")), _real_number(cfg.get("duck_level"))],
        lambda v: v is not None and 0.1 <= v <= 1, defaults["duck_level"])

    return {"auto_listen": auto_listen, "on_top_level": on_top_level, "hit_width_ratio": ratio,
            "speaking_boost": float(boost), "duck_level": float(duck)}


_CLOCK = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")  # strict HH:MM, zero padded, 00:00 .. 23:59


def _minutes(text):
    """Minutes since midnight for a strict "HH:MM" string; None for anything else."""
    match = _CLOCK.fullmatch(text) if isinstance(text, str) else None
    return None if match is None else int(match.group(1)) * 60 + int(match.group(2))


def _parse_routine_entry(item):
    """One routine entry in usable form, or None if it is unusable — judged on its own, so a
    single typo costs only that entry."""
    if not isinstance(item, dict):
        return None
    name, hint = item.get("name"), item.get("hint")
    if not isinstance(name, str) or not name.strip() or not isinstance(hint, str) or not hint.strip():
        return None
    start, end = _minutes(item.get("start")), _minutes(item.get("end"))
    if start is None or end is None or start == end:
        return None
    return {"name": name.strip(), "hint": hint.strip(), "start": start, "end": end}


def _resolve_timezone(name):
    """A tzinfo for a valid IANA name, else None (= use the computer's local time zone). Never
    raises: a typo in a hand-edited file must not stop the app from starting. (On Windows the
    time zone database comes from the `tzdata` package — see requirements.txt.)"""
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def resolve_time_config():
    """The effective time-awareness settings, validated and parsed so the engine can use them
    directly (times become minutes since midnight)."""
    raw = load_config()["time"]
    defaults = DEFAULT_CONFIG["time"]
    if not isinstance(raw, dict):
        raw = {}

    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        enabled = defaults["enabled"]

    gap = raw.get("gap_marker_minutes")
    if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or gap <= 0:
        gap = defaults["gap_marker_minutes"]

    # A list you provide REPLACES the default one (it is not merged entry by entry); a value that
    # is not a list at all is treated as not set.
    routine_raw = raw.get("routine")
    if not isinstance(routine_raw, list):
        routine_raw = defaults["routine"]
    routine = [entry for entry in map(_parse_routine_entry, routine_raw) if entry is not None]

    quiet_raw = raw.get("quiet_hours")
    if not isinstance(quiet_raw, dict):
        quiet_raw = {}
    quiet_defaults = defaults["quiet_hours"]
    quiet_enabled = quiet_raw.get("enabled")
    if not isinstance(quiet_enabled, bool):
        quiet_enabled = quiet_defaults["enabled"]
    quiet_start, quiet_end = _minutes(quiet_raw.get("start")), _minutes(quiet_raw.get("end"))
    if quiet_start is None or quiet_end is None or quiet_start == quiet_end:
        quiet_start, quiet_end = _minutes(quiet_defaults["start"]), _minutes(quiet_defaults["end"])

    return {
        "enabled": enabled,
        "timezone": _resolve_timezone(raw.get("timezone")),
        "gap_marker_minutes": gap,
        "routine": routine,
        "quiet_hours": {"enabled": quiet_enabled, "start": quiet_start, "end": quiet_end},
    }


_LANGUAGE_CODE = re.compile(r"[a-z]{2,3}")


def parse_stt_config(raw):
    """Validated `stt` settings from the raw config section (None / junk = all defaults).
    Pure: reads no file, so the speech adapter can use it for its built-in defaults."""
    defaults = DEFAULT_CONFIG["stt"]
    raw = raw if isinstance(raw, dict) else {}

    language = raw.get("language")
    language = language.strip().lower() if isinstance(language, str) else None
    if language is None or not _LANGUAGE_CODE.fullmatch(language):
        language = None

    def switch(name):
        value = raw.get(name)
        return value if isinstance(value, bool) else defaults[name]

    def number(name, valid):
        value = raw.get(name)
        ok = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and valid(value)
        return value if ok else defaults[name]

    allowed = raw.get("allowed_languages")
    if not isinstance(allowed, list):
        allowed = defaults["allowed_languages"]
    cleaned = []
    for item in allowed:
        item = item.strip().lower() if isinstance(item, str) else ""
        if item and item not in cleaned:
            cleaned.append(item)

    phrases = raw.get("ignore_phrases")
    if not isinstance(phrases, list):
        phrases = defaults["ignore_phrases"]
    ignore = []
    for item in phrases:
        item = " ".join(item.casefold().split()) if isinstance(item, str) else ""
        if item and item not in ignore:
            ignore.append(item)

    prompt = raw.get("prompt")
    prompt = prompt.strip() if isinstance(prompt, str) else None

    return {
        "enabled": switch("enabled"),
        "language": language,
        "filter": switch("filter"),
        "allowed_languages": cleaned,
        "ignore_phrases": ignore,
        "prompt": prompt or None,
        "no_speech_prob_max": number("no_speech_prob_max", lambda v: 0 < v <= 1),
        "avg_logprob_min": number("avg_logprob_min", lambda v: v <= 0),
        "debug_log": switch("debug_log"),
    }


def resolve_stt_config():
    """The effective `stt` settings (config.json, validated)."""
    return parse_stt_config(load_config()["stt"])


# ---- Part 12 sections ---------------------------------------------------------------------------
# Every field is checked on its own: a value that does not fit is treated as not set, so the
# default applies to THAT field only and the rest of the file is still honoured.

def _is_switch(value):
    return isinstance(value, bool)


def _is_text(value):
    return isinstance(value, str) and bool(value.strip())


def _in_range(low, high):
    return lambda v: _real_number(v) is not None and math.isfinite(v) and low <= v <= high


def _is_domain_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _resolve_section(name, rules, overrides=None):
    """`name`'s section with each field validated by `rules` (field -> predicate); `overrides`
    maps a field to a value that, when not None, is tried before the file's value."""
    defaults = DEFAULT_CONFIG[name]
    raw = load_config().get(name)
    raw = raw if isinstance(raw, dict) else {}
    overrides = overrides or {}
    result = {}
    for field, default in defaults.items():
        check = rules.get(field)
        candidates = [overrides.get(field), raw.get(field)]
        value = _first_valid(candidates, lambda v, check=check: v is not None and (check is None or check(v)), default)
        result[field] = value.strip() if isinstance(value, str) else value
    return result


def resolve_outfit_config():
    section = _resolve_section("outfit", {"default": _is_text})
    raw = load_config().get("outfit")
    aliases = raw.get("aliases") if isinstance(raw, dict) else None
    if not isinstance(aliases, dict):
        return section
    clean = {}
    for folder, names in aliases.items():
        if not isinstance(folder, str) or not isinstance(names, list):
            continue
        names = [n.strip() for n in names if isinstance(n, str) and n.strip()]
        if names:
            clean[folder] = names
    section["aliases"] = clean
    return section


def resolve_image_config():
    section = _resolve_section("image", {
        "enabled": _is_switch, "model": _is_text, "account_id": _is_text,
        "width": _in_range(256, 1920), "height": _in_range(256, 1920),
        "max_per_day": _in_range(0, 1000), "cooldown_s": _in_range(0, 3600), "timeout_s": _in_range(1, 600),
        "appearance": lambda v: isinstance(v, str),
    }, overrides={"account_id": os.environ.get("CF_ACCOUNT_ID") or None})
    for field in ("width", "height", "max_per_day"):
        section[field] = int(section[field])
    for field in ("cooldown_s", "timeout_s"):
        section[field] = float(section[field])
    return section


def resolve_tinyfish_config():
    section = _resolve_section("tinyfish", {
        "enabled": _is_switch, "location": _is_text, "language": _is_text,
        "max_results": _in_range(1, 10), "quarantine": _is_switch, "blocked_domains": _is_domain_list,
    })
    section["max_results"] = int(section["max_results"])
    section["blocked_domains"] = [d.strip().lower() for d in section["blocked_domains"] if d.strip()]
    return section


def resolve_memory_config():
    section = _resolve_section("memory", {
        "enabled": _is_switch,
        "long_term_max_chars": _in_range(200, 20000), "recent_notes_max_chars": _in_range(50, 5000),
        "retrieval_k": _in_range(1, 10), "retrieval_snippet_chars": _in_range(20, 2000),
        "retrieval_min_message_chars": _in_range(1, 50), "archive_scan_limit": _in_range(100, 1000000),
        "retrieval_min_score": _in_range(0.1, 20),
    })
    for field in section:
        if field not in ("enabled", "retrieval_min_score"):
            section[field] = int(section[field])
    section["retrieval_min_score"] = float(section["retrieval_min_score"])
    if os.environ.get("COMPANION_MEMORY") == "off":  # the old switch still wins over the file
        section["enabled"] = False
    return section


def resolve_companion_state_config():
    section = _resolve_section("companion_state", {
        "enabled": _is_switch, "default_location": _is_text,
        "default_status_ttl_hours": lambda v: _in_range(0, 24 * 365)(v) and v > 0,
        "max_items": _in_range(1, 100),
    })
    section["default_status_ttl_hours"] = float(section["default_status_ttl_hours"])
    section["max_items"] = int(section["max_items"])
    raw = load_config().get("companion_state")
    raw = raw.get("status_ttl_hours") if isinstance(raw, dict) else None
    ttl = dict(DEFAULT_CONFIG["companion_state"]["status_ttl_hours"])
    if isinstance(raw, dict):
        for word, hours in raw.items():
            if isinstance(word, str) and word.strip() and _real_number(hours) is not None \
                    and math.isfinite(hours) and hours > 0:
                ttl[word.strip()] = hours
    section["status_ttl_hours"] = ttl
    return section
