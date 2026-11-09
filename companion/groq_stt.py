import logging
import os

import groq
from groq import Groq

from .apikey import MissingApiKey, get_api_key
from .config import parse_stt_config
from .debuglog import default_log
from .errors import LLMError


# Whisper reports a language by name ("russian") or code ("ru") depending on who answers, so both
# are understood. Only languages listed here can ever be thrown away: a detected language we do not
# recognise is left alone, because wrongly discarding something you really said is worse than
# letting a stray phrase through.
LANGUAGE_CODES = {
    "chinese": "zh", "english": "en", "japanese": "ja", "korean": "ko", "russian": "ru",
    "portuguese": "pt", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
    "dutch": "nl", "polish": "pl", "turkish": "tr", "arabic": "ar", "hindi": "hi", "thai": "th",
    "vietnamese": "vi", "indonesian": "id", "malay": "ms", "ukrainian": "uk", "swedish": "sv",
    "cantonese": "yue", "tagalog": "tl", "greek": "el", "hebrew": "he", "czech": "cs",
}
_KNOWN_CODES = set(LANGUAGE_CODES.values())


def language_code(value):
    """A language as a short code (\"English\" / \"en\" -> \"en\"), or None if not one we recognise."""
    if not isinstance(value, str):
        return None
    value = value.split("(")[0].strip().lower()  # Groq sometimes adds a note: "Malay (macrolanguage)"
    return LANGUAGE_CODES.get(value) or (value if value in _KNOWN_CODES else None)


def _plain(text):
    """A phrase for comparing: lower case, no punctuation at either end, one space between words."""
    return " ".join(text.casefold().strip(" \t\n.,!?;:\"'…。，、！？；：「」『』()（）-").split())


def _field(obj, name):
    """A field from an answer object or a plain dict (extra fields from the API arrive as dicts)."""
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def to_stt_error(exc):
    """Translate Groq SDK/network exceptions into LLMError; None if we do not recognise it."""
    if isinstance(exc, groq.RateLimitError):
        return LLMError("rate_limit", str(exc))
    if isinstance(exc, groq.APIConnectionError):  # covers APITimeoutError, its subclass
        return LLMError("timeout", str(exc))
    if isinstance(exc, groq.APIStatusError):
        return LLMError("unavailable", str(exc))
    return None


class GroqSTT:
    """Speech-to-text boundary: turns a recorded voice message into plain text via Groq's
    hosted Whisper (whisper-large-v3-turbo). A genuinely silent or unintelligible recording
    comes back as an empty string — that is not a failure, and callers must be able to tell
    the two apart (an empty transcript vs. a raised LLMError) rather than treating both as
    "no text" the same way.

    Verified only against SDK types in the sandbox (no network to Groq here); run
    smoke_stt.py on your machine to verify end to end.
    """

    def __init__(self, api_key=None, model=None, settings=None, log=default_log):
        api_key = api_key or get_api_key("groq")
        if not api_key:
            raise MissingApiKey(
                "找不到 Groq API 金鑰。請設定環境變數 GROQ_API_KEY,"
                "或執行 app.py --set-key-groq 把金鑰存進 Windows 憑證管理員。"
            )
        self._client = Groq(api_key=api_key)
        self._model = model or os.environ.get("COMPANION_STT_MODEL", "whisper-large-v3-turbo")
        # The `stt` settings (config.resolve_stt_config()); None = the built-in defaults.
        self._settings = settings if settings is not None else parse_stt_config(None)
        self._log = log  # only used when stt.debug_log is on

    def transcribe(self, data, mime_type):
        # A filename with the right extension is all Groq needs to know the container format;
        # the codecs parameter (e.g. "audio/webm;codecs=opus") isn't a valid extension, so only
        # the part before ";" is used, matching how MAX_AUDIO_BYTES-style mime parsing already
        # works elsewhere in this project (see server.py's Content-Type handling).
        ext = mime_type.split(";")[0].split("/")[-1].strip() or "webm"
        request = {"model": self._model, "file": (f"voice.{ext}", data, mime_type)}
        if self._settings["language"]:
            request["language"] = self._settings["language"]
        if self._settings["prompt"]:
            request["prompt"] = self._settings["prompt"]  # opt-in hint (stt.prompt); absent means the request is as it always was
        if self._settings["filter"] or self._settings["debug_log"]:
            request["response_format"] = "verbose_json"  # adds the detected language and per-stretch confidence
        try:
            result = self._client.audio.transcriptions.create(**request)
        except Exception as exc:
            translated = to_stt_error(exc)
            if translated is None:
                raise
            raise translated from exc
        text = (result.text or "").strip()
        final, verdict = self._decide(result, text)
        if self._settings["debug_log"]:
            self._write_log(len(data), result, text, final, verdict)
        return final

    def _decide(self, result, text):
        """(text to use, why part of it was dropped or None). "" means thrown away entirely — the
        same as "heard nothing usable", which the caller treats as "didn't catch that"."""
        if not (self._settings["filter"] and text):
            return text, None
        if self._wrong_language(result):
            return "", f"language {_field(result, 'language')}"
        if self._is_ignored_phrase(result, text):
            return "", f"ignored phrase {_plain(text)!r}"
        kept = self._without_doubtful_stretches(result, text)
        if kept == text:
            return text, None
        return kept, ("doubtful" if kept == "" else "partly doubtful")

    def _write_log(self, size, result, text, final, verdict):
        segments = [sg for sg in (_field(result, "segments") if isinstance(_field(result, "segments"), list) else [])]
        numbers = lambda name: [v for v in (_field(sg, name) for sg in segments) if isinstance(v, (int, float)) and not isinstance(v, bool)]
        no_speech, logprob = numbers("no_speech_prob"), numbers("avg_logprob")
        shown = lambda values, pick: "?" if not values else f"{pick(values):g}"
        outcome = ("dropped" if final == "" and text else "kept") + (f" ({verdict})" if verdict else "")
        if not self._settings["filter"]:
            outcome += " (filter off)"
        clip = text if len(text) <= 80 else text[:80] + "..."
        line = (f"[stt] {outcome} | {size} bytes | language={_field(result, 'language') or '?'}"
                f" | no_speech_prob={shown(no_speech, max)} | avg_logprob={shown(logprob, min)} | {clip!r}")
        try:
            self._log(line)
        except Exception:
            pass  # a broken log must never break a conversation

    def _doubtful(self, segment):
        """Whisper's own rule of thumb: a stretch it thinks is probably not speech AND is unsure
        about is almost always an invented phrase. Both numbers must be present and past the line."""
        no_speech, logprob = _field(segment, "no_speech_prob"), _field(segment, "avg_logprob")
        numbers = [x for x in (no_speech, logprob) if isinstance(x, (int, float)) and not isinstance(x, bool)]
        return (len(numbers) == 2
                and no_speech > self._settings["no_speech_prob_max"]
                and logprob < self._settings["avg_logprob_min"])

    def _without_doubtful_stretches(self, result, text):
        segments = _field(result, "segments")
        if not isinstance(segments, list) or not segments:
            return text
        flags = [self._doubtful(segment) for segment in segments]
        if not any(flags):
            return text
        if all(flags):
            return ""
        kept = [_field(sg, "text") for sg, bad in zip(segments, flags) if not bad]
        if not all(isinstance(t, str) for t in kept):
            return text  # cannot rebuild the sentence safely: keep what was heard
        return "".join(kept).strip()

    def _is_ignored_phrase(self, result, text):
        """The whole transcript is one of the invented phrases AND it was heard as a language other than your
        main one. Both must hold: the same words detected as your main language are left alone, and a language
        we cannot tell leaves it alone too (wrongly discarding something you said is worse than a stray phrase)."""
        detected = language_code(_field(result, "language"))
        main = self._main_language()
        if detected is None or main is None or detected == main:
            return False
        return _plain(text) in {_plain(p) for p in self._settings["ignore_phrases"]}

    def _main_language(self):
        main = self._settings["language"] or (self._settings["allowed_languages"] or [None])[0]
        return language_code(main) or main

    def _wrong_language(self, result):
        detected = language_code(_field(result, "language"))
        if detected is None:
            return False
        allowed = {language_code(a) or a for a in self._settings["allowed_languages"]}
        return bool(allowed) and detected not in allowed
