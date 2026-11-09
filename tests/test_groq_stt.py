import groq
import httpx
import pytest

from companion.config import parse_stt_config
from companion.errors import LLMError
from companion.groq_stt import GroqSTT


class _Transcription:
    def __init__(self, text):
        self.text = text


class _FakeTranscriptions:
    """Stands in for client.audio.transcriptions: pops one scripted result (a transcript
    string) or raises one scripted exception per call."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        step = self._script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return _Transcription(step) if isinstance(step, str) else step


class _FakeAudio:
    def __init__(self, script):
        self.transcriptions = _FakeTranscriptions(script)


class _FakeClient:
    def __init__(self, script):
        self.audio = _FakeAudio(script)


def make_stt(monkeypatch, script, log=None, **settings):
    monkeypatch.setattr("companion.groq_stt.Groq", lambda **kwargs: _FakeClient(script))
    extra = {} if log is None else {"log": log}
    return GroqSTT(api_key="test-key", settings=parse_stt_config(settings) if settings else None, **extra)


def _status_error(cls, status_code):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions")
    return cls("boom", response=httpx.Response(status_code=status_code, request=request), body=None)


def test_a_normal_recording_comes_back_as_its_transcript(monkeypatch):
    stt = make_stt(monkeypatch, ["你好呀,今天過得好嗎?"])
    assert stt.transcribe(b"fake-audio-bytes", "audio/webm") == "你好呀,今天過得好嗎?"


def test_the_recording_and_its_format_are_passed_through_to_groq(monkeypatch):
    stt = make_stt(monkeypatch, ["嗨"])
    stt.transcribe(b"\x00\x01raw-bytes", "audio/webm;codecs=opus")
    call = stt._client.audio.transcriptions.calls[0]
    assert call["model"] == "whisper-large-v3-turbo"
    filename, data, mime = call["file"]
    assert data == b"\x00\x01raw-bytes"
    assert mime == "audio/webm;codecs=opus"
    assert filename.endswith(".webm")  # extension derived from the mime type, codecs param ignored


def test_a_silent_or_unintelligible_recording_comes_back_as_an_empty_string_not_an_exception(monkeypatch):
    stt = make_stt(monkeypatch, [""])
    assert stt.transcribe(b"fake-audio-bytes", "audio/webm") == ""


def test_a_whitespace_only_transcript_is_treated_as_empty(monkeypatch):
    stt = make_stt(monkeypatch, ["   \n"])
    assert stt.transcribe(b"fake-audio-bytes", "audio/webm") == ""


def test_rate_limit_is_translated_into_a_distinguishable_error_not_an_empty_string(monkeypatch):
    stt = make_stt(monkeypatch, [_status_error(groq.RateLimitError, 429)])
    with pytest.raises(LLMError) as exc_info:
        stt.transcribe(b"fake-audio-bytes", "audio/webm")
    assert exc_info.value.kind == "rate_limit"


def test_a_connection_timeout_is_translated_to_a_timeout_error(monkeypatch):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions")
    stt = make_stt(monkeypatch, [groq.APITimeoutError(request=request)])
    with pytest.raises(LLMError) as exc_info:
        stt.transcribe(b"fake-audio-bytes", "audio/webm")
    assert exc_info.value.kind == "timeout"


def test_a_server_error_is_translated_to_an_unavailable_error(monkeypatch):
    stt = make_stt(monkeypatch, [_status_error(groq.InternalServerError, 500)])
    with pytest.raises(LLMError) as exc_info:
        stt.transcribe(b"fake-audio-bytes", "audio/webm")
    assert exc_info.value.kind == "unavailable"


def test_an_unrecognised_exception_is_not_swallowed(monkeypatch):
    stt = make_stt(monkeypatch, [ValueError("something the adapter has no translation for")])
    with pytest.raises(ValueError):
        stt.transcribe(b"fake-audio-bytes", "audio/webm")


def test_missing_api_key_raises_a_clear_error(monkeypatch):
    from companion.apikey import MissingApiKey

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("companion.groq_stt.get_api_key", lambda provider: None)
    with pytest.raises(MissingApiKey):
        GroqSTT(api_key=None)


# ---- recordings the recogniser itself doubts, or in a language you never speak ----

class _Heard:
    """A detailed ("verbose_json") answer: text, the language it detected, and per-stretch confidence."""

    def __init__(self, text, language=None, segments=None):
        self.text = text
        if language is not None:
            self.language = language
        if segments is not None:
            self.segments = segments


def seg(text, no_speech_prob=0.0, avg_logprob=-0.2):
    return {"text": text, "no_speech_prob": no_speech_prob, "avg_logprob": avg_logprob}


def call_of(stt):
    return stt._client.audio.transcriptions.calls[0]


def test_by_default_the_detailed_answer_is_asked_for_but_no_language_is_forced(monkeypatch):
    stt = make_stt(monkeypatch, ["嗨"])
    stt.transcribe(b"x", "audio/webm")
    assert call_of(stt)["response_format"] == "verbose_json"
    assert "language" not in call_of(stt)


def test_a_language_hint_from_the_settings_is_sent(monkeypatch):
    stt = make_stt(monkeypatch, ["嗨"], language="zh")
    stt.transcribe(b"x", "audio/webm")
    assert call_of(stt)["language"] == "zh"


def test_with_filtering_and_logging_both_off_the_request_is_exactly_what_it_always_was(monkeypatch):
    stt = make_stt(monkeypatch, ["嗨"], filter=False, debug_log=False)
    stt.transcribe(b"x", "audio/webm")
    assert set(call_of(stt)) == {"model", "file"}


@pytest.mark.parametrize("detected", ["russian", "Russian", "ru", "portuguese", "pt", "korean", "ko", "Korean", "spanish"])
def test_a_recording_detected_as_a_language_you_never_speak_is_thrown_away(monkeypatch, detected):
    stt = make_stt(monkeypatch, [_Heard("Доброе утро!", language=detected, segments=[seg("Доброе утро!")])])
    assert stt.transcribe(b"x", "audio/webm") == ""


@pytest.mark.parametrize("detected", ["chinese", "Chinese", "zh", "english", "English", "en", "japanese", "ja"])
def test_the_languages_you_do_speak_are_kept(monkeypatch, detected):
    stt = make_stt(monkeypatch, [_Heard("你好", language=detected, segments=[seg("你好")])])
    assert stt.transcribe(b"x", "audio/webm") == "你好"


@pytest.mark.parametrize("odd", [None, "", "Mandarin Chinese", "some-new-name", 5])
def test_when_the_detected_language_is_missing_or_not_one_we_recognise_nothing_is_thrown_away(monkeypatch, odd):
    result = _Heard("你好", segments=[seg("你好")])
    if odd is not None:
        result.language = odd
    assert make_stt(monkeypatch, [result]).transcribe(b"x", "audio/webm") == "你好"


def test_the_allowed_languages_come_from_the_settings(monkeypatch):
    heard = _Heard("hello", language="english", segments=[seg("hello")])
    assert make_stt(monkeypatch, [heard], allowed_languages=["zh"]).transcribe(b"x", "audio/webm") == ""
    assert make_stt(monkeypatch, [heard], allowed_languages=["en"]).transcribe(b"x", "audio/webm") == "hello"
    assert make_stt(monkeypatch, [heard], allowed_languages=["English"]).transcribe(b"x", "audio/webm") == "hello"  # names work too


def test_an_empty_allowed_list_accepts_any_language(monkeypatch):
    heard = _Heard("Obrigada.", language="portuguese", segments=[seg("Obrigada.")])
    assert make_stt(monkeypatch, [heard], allowed_languages=[]).transcribe(b"x", "audio/webm") == "Obrigada."


def test_with_filtering_switched_off_no_language_is_ever_rejected(monkeypatch):
    heard = _Heard("Obrigada.", language="portuguese", segments=[seg("Obrigada.")])
    assert make_stt(monkeypatch, [heard], filter=False, debug_log=True).transcribe(b"x", "audio/webm") == "Obrigada."


def heard(*segments, language="english", text=None):
    return _Heard(text if text is not None else "".join(s["text"] for s in segments), language=language, segments=list(segments))


def test_a_stretch_the_recogniser_thinks_is_not_speech_and_is_unsure_about_is_thrown_away(monkeypatch):
    phantom = heard(seg("It's not just a...", no_speech_prob=0.85, avg_logprob=-1.4))   # English, so the language check lets it by
    assert make_stt(monkeypatch, [phantom]).transcribe(b"x", "audio/webm") == ""


@pytest.mark.parametrize("no_speech_prob, avg_logprob", [
    (0.85, -0.3),    # "probably not speech" but it is confident about what it wrote: keep
    (0.10, -2.0),    # unsure, but it does think it is speech: keep
    (0.60, -1.5),    # exactly at the line is not over it
    (0.90, -1.0),    # same on the other side
])
def test_both_signals_must_agree_before_anything_is_thrown_away(monkeypatch, no_speech_prob, avg_logprob):
    result = heard(seg("I'm here", no_speech_prob=no_speech_prob, avg_logprob=avg_logprob))
    assert make_stt(monkeypatch, [result]).transcribe(b"x", "audio/webm") == "I'm here"


def test_the_two_thresholds_come_from_the_settings(monkeypatch):
    doubtful = heard(seg("hmm", no_speech_prob=0.5, avg_logprob=-0.8))
    assert make_stt(monkeypatch, [doubtful]).transcribe(b"x", "audio/webm") == "hmm"
    strict = {"no_speech_prob_max": 0.4, "avg_logprob_min": -0.5}
    assert make_stt(monkeypatch, [doubtful], **strict).transcribe(b"x", "audio/webm") == ""


def test_only_the_doubtful_stretches_are_dropped_from_a_longer_recording(monkeypatch):
    mixed = heard(seg("今天天氣不錯", 0.01, -0.2), seg("Thank you.", 0.9, -1.8), seg("我們出去走走", 0.02, -0.3), language="chinese")
    assert make_stt(monkeypatch, [mixed]).transcribe(b"x", "audio/webm") == "今天天氣不錯我們出去走走"


def test_a_recording_where_every_stretch_is_doubtful_is_thrown_away(monkeypatch):
    nothing = heard(seg("Obrigada.", 0.9, -1.8), seg("Thank you.", 0.8, -1.6))
    assert make_stt(monkeypatch, [nothing]).transcribe(b"x", "audio/webm") == ""


def test_stretches_given_as_objects_work_the_same_as_dicts(monkeypatch):
    class Segment:
        text, no_speech_prob, avg_logprob = "Thank you.", 0.9, -1.8
    result = _Heard("Thank you.", language="english", segments=[Segment()])
    assert make_stt(monkeypatch, [result]).transcribe(b"x", "audio/webm") == ""


@pytest.mark.parametrize("segments", [
    None, [], "junk", 5,
    [{"text": "hi"}],                                                 # no numbers at all
    [{"text": "hi", "no_speech_prob": None, "avg_logprob": None}],
    [{"text": "hi", "no_speech_prob": "high", "avg_logprob": "low"}],
    [{"text": "hi", "no_speech_prob": 0.9}],                          # only one of the two
    [{"text": "hi", "avg_logprob": -2.0}],
    ["not a dict"],
])
def test_when_the_confidence_numbers_are_missing_or_odd_nothing_is_thrown_away(monkeypatch, segments):
    result = _Heard("hi", language="english", segments=segments)
    assert make_stt(monkeypatch, [result]).transcribe(b"x", "audio/webm") == "hi"


def test_an_answer_with_no_detail_at_all_is_simply_kept(monkeypatch):
    assert make_stt(monkeypatch, ["就是這樣"]).transcribe(b"x", "audio/webm") == "就是這樣"


def test_with_filtering_switched_off_even_a_doubtful_recording_is_kept(monkeypatch):
    phantom = heard(seg("Thank you.", 0.95, -2.0))
    assert make_stt(monkeypatch, [phantom], filter=False).transcribe(b"x", "audio/webm") == "Thank you."


# ---- the tuning log: one "[stt]" line per recording, only when asked for ----

def logged(monkeypatch, script, **settings):
    lines = []
    stt = make_stt(monkeypatch, script, log=lines.append, debug_log=True, **settings)
    return stt, lines


def test_nothing_is_logged_unless_the_log_is_switched_on(monkeypatch):
    lines = []
    stt = make_stt(monkeypatch, [heard(seg("你好", 0.01, -0.2), language="chinese")], log=lines.append)
    assert stt.transcribe(b"x", "audio/webm") == "你好" and lines == []


def test_a_kept_recording_is_logged_with_what_was_heard_and_how_sure_it_was(monkeypatch):
    stt, lines = logged(monkeypatch, [heard(seg("你好呀", 0.02, -0.31), language="chinese")])
    stt.transcribe(b"x" * 12345, "audio/webm")
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith("[stt]") and "kept" in line and "dropped" not in line
    assert "12345" in line and "chinese" in line and "0.02" in line and "-0.31" in line and "你好呀" in line


def test_a_recording_thrown_away_for_its_language_says_so_and_which_language(monkeypatch):
    stt, lines = logged(monkeypatch, [heard(seg("Доброе утро!", 0.3, -0.9), language="russian")])
    assert stt.transcribe(b"x", "audio/webm") == ""
    assert "dropped" in lines[0] and "language" in lines[0] and "russian" in lines[0] and "Доброе утро!" in lines[0]


def test_a_recording_thrown_away_as_doubtful_says_so_with_the_numbers(monkeypatch):
    stt, lines = logged(monkeypatch, [heard(seg("It's not just a...", 0.85, -1.4))])
    assert stt.transcribe(b"x", "audio/webm") == ""
    assert "dropped" in lines[0] and "doubtful" in lines[0] and "0.85" in lines[0] and "-1.4" in lines[0]


def test_a_partly_thrown_away_recording_is_logged_as_kept_with_a_note_that_part_was_dropped(monkeypatch):
    stt, lines = logged(monkeypatch, [heard(seg("好的", 0.01, -0.2), seg("Thank you.", 0.9, -1.8), language="chinese")])
    assert stt.transcribe(b"x", "audio/webm") == "好的"
    assert "kept" in lines[0] and "1" in lines[0] and "doubtful" in lines[0]


def test_missing_details_are_shown_as_unknown_and_never_break_anything(monkeypatch):
    stt, lines = logged(monkeypatch, ["就是這樣"])
    assert stt.transcribe(b"x", "audio/webm") == "就是這樣"
    assert "?" in lines[0] and "就是這樣" in lines[0]


def test_with_filtering_off_the_log_still_shows_what_would_have_happened_but_nothing_is_dropped(monkeypatch):
    stt, lines = logged(monkeypatch, [heard(seg("Obrigada.", 0.95, -2.0), language="portuguese")], filter=False)
    assert stt.transcribe(b"x", "audio/webm") == "Obrigada."
    assert "kept" in lines[0] and "filter off" in lines[0]


def test_a_very_long_transcript_is_shortened_in_the_log(monkeypatch):
    long_text = "很長" * 200
    stt, lines = logged(monkeypatch, [heard(seg(long_text, 0.0, -0.1), language="chinese")])
    stt.transcribe(b"x", "audio/webm")
    assert len(lines[0]) < 300


def test_a_log_that_fails_never_breaks_a_conversation(monkeypatch):
    def broken(_line):
        raise OSError("disk full")
    stt = make_stt(monkeypatch, [heard(seg("你好", 0.0, -0.1), language="chinese")], log=broken, debug_log=True)
    assert stt.transcribe(b"x", "audio/webm") == "你好"


def test_by_default_the_log_goes_to_the_console_where_the_launcher_already_collects_it(monkeypatch, capsys):
    monkeypatch.setattr("companion.groq_stt.Groq", lambda **kwargs: _FakeClient([heard(seg("你好", 0.0, -0.1), language="chinese")]))
    GroqSTT(api_key="k", settings=parse_stt_config({"debug_log": True})).transcribe(b"x", "audio/webm")
    assert "[stt]" in capsys.readouterr().out


def test_by_default_the_log_also_lands_in_the_log_file_not_only_on_the_console(monkeypatch, caplog):
    # data/app.log is fed by the logging module; a bare print() only reaches it in the windowed exe.
    import logging
    monkeypatch.setattr("companion.groq_stt.Groq", lambda **kwargs: _FakeClient([heard(seg("你好", 0.0, -0.1), language="chinese")]))
    with caplog.at_level(logging.INFO):
        GroqSTT(api_key="k", settings=parse_stt_config({"debug_log": True})).transcribe(b"x", "audio/webm")
    assert any(r.levelno == logging.INFO and "[stt]" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("name, code", [
    ("Malay (macrolanguage)", "ms"),   # exactly as it appeared in a real app.log
    ("Chinese (Mandarin)", "zh"),
    ("  english  (US) ", "en"),
])
def test_a_language_name_with_a_bracketed_note_is_still_recognised(name, code):
    from companion.groq_stt import language_code
    assert language_code(name) == code


def test_a_clip_detected_as_malay_macrolanguage_is_thrown_away_as_a_language_you_never_speak(monkeypatch):
    stt = make_stt(monkeypatch, [_Heard("Dandan-dandan-dandan.", language="Malay (macrolanguage)",
                                        segments=[seg("Dandan-dandan-dandan.", 0.0, -0.567)])])
    assert stt.transcribe(b"x", "audio/webm") == ""


def test_the_bracketed_note_does_not_make_an_unknown_language_known(monkeypatch):
    from companion.groq_stt import language_code
    assert language_code("Mandarin Chinese (Taiwan)") is None          # still not one we recognise: left alone


# ---- phrases the recogniser invents from noise / her echo ("Thank you."): thrown away when not in your main language ----

def english(text):
    return _Heard(text, language="English", segments=[seg(text)])


def test_an_invented_english_phrase_is_thrown_away_when_your_main_language_is_not_english(monkeypatch):
    stt = make_stt(monkeypatch, [english("Thank you.")])
    assert stt.transcribe(b"x", "audio/webm") == ""


@pytest.mark.parametrize("heard", ["Thank you.", "THANK YOU!!", "  thank   you  ", "Thanks.", "Okay.", "okay,", "Yes", "Music", "And the...", "You", "Bye!", "Thank you。"])
def test_every_default_phrase_is_ignored_whatever_the_case_or_punctuation(monkeypatch, heard):
    assert make_stt(monkeypatch, [english(heard)]).transcribe(b"x", "audio/webm") == ""


@pytest.mark.parametrize("heard", ["Thank you very much for the help.", "Okay let's go", "Thank you, bye", "I said yes to that", "Stop"])
def test_only_a_transcript_that_is_exactly_a_listed_phrase_is_ignored(monkeypatch, heard):
    assert make_stt(monkeypatch, [english(heard)]).transcribe(b"x", "audio/webm") == heard


def test_the_same_words_detected_as_your_main_language_are_kept(monkeypatch):
    heard = _Heard("Thank you.", language="Chinese", segments=[seg("Thank you.")])
    assert make_stt(monkeypatch, [heard]).transcribe(b"x", "audio/webm") == "Thank you."


@pytest.mark.parametrize("odd", [None, "", "Mandarin Chinese", "some-new-name", 5])
def test_when_the_language_is_missing_or_unknown_a_listed_phrase_is_kept(monkeypatch, odd):
    result = _Heard("Thank you.", segments=[seg("Thank you.")])
    if odd is not None:
        result.language = odd
    assert make_stt(monkeypatch, [result]).transcribe(b"x", "audio/webm") == "Thank you."


def test_your_main_language_is_the_language_hint_when_one_is_set(monkeypatch):
    assert make_stt(monkeypatch, [english("Thank you.")], language="en").transcribe(b"x", "audio/webm") == "Thank you."
    heard = _Heard("Thank you.", language="Japanese", segments=[seg("Thank you.")])
    assert make_stt(monkeypatch, [heard], language="en").transcribe(b"x", "audio/webm") == ""


def test_without_a_language_hint_your_main_language_is_the_first_allowed_one(monkeypatch):
    assert make_stt(monkeypatch, [english("Thank you.")], allowed_languages=["en", "zh"]).transcribe(b"x", "audio/webm") == "Thank you."
    assert make_stt(monkeypatch, [english("Thank you.")], allowed_languages=["zh", "en"]).transcribe(b"x", "audio/webm") == ""


def test_with_no_main_language_to_compare_against_nothing_is_ignored(monkeypatch):
    assert make_stt(monkeypatch, [english("Thank you.")], allowed_languages=[]).transcribe(b"x", "audio/webm") == "Thank you."


def test_the_phrase_list_comes_from_the_settings(monkeypatch):
    assert make_stt(monkeypatch, [english("Hello there")], ignore_phrases=["hello there"]).transcribe(b"x", "audio/webm") == ""
    assert make_stt(monkeypatch, [english("Thank you.")], ignore_phrases=["hello there"]).transcribe(b"x", "audio/webm") == "Thank you."
    assert make_stt(monkeypatch, [english("Thank you.")], ignore_phrases=[]).transcribe(b"x", "audio/webm") == "Thank you."


def test_with_the_filter_off_no_phrase_is_ignored(monkeypatch):
    assert make_stt(monkeypatch, [_Heard("Thank you.", language="English")], filter=False, debug_log=True).transcribe(b"x", "audio/webm") == "Thank you."


def test_an_ignored_phrase_is_marked_as_such_in_the_stt_log(monkeypatch):
    lines = []
    make_stt(monkeypatch, [english("Thank you.")], log=lines.append, debug_log=True).transcribe(b"x", "audio/webm")
    assert len(lines) == 1
    assert lines[0].startswith("[stt] dropped (ignored phrase 'thank you')")
    assert "language=English" in lines[0]


def test_a_listed_phrase_written_with_punctuation_or_capitals_still_matches(monkeypatch):
    stt = make_stt(monkeypatch, [english("thank you")], ignore_phrases=["Thank you."])
    assert stt.transcribe(b"x", "audio/webm") == ""


# ---- the optional recogniser hint (stt.prompt): off unless set ----

def test_without_a_prompt_setting_no_prompt_is_sent_at_all(monkeypatch):
    for settings in ({}, {"filter": False}, {"debug_log": True}, {"prompt": None}):
        stt = make_stt(monkeypatch, ["嗨"], **settings)
        stt.transcribe(b"x", "audio/webm")
        assert "prompt" not in call_of(stt), settings


def test_a_configured_prompt_is_sent_with_the_recording(monkeypatch):
    stt = make_stt(monkeypatch, ["嗨"], prompt="使用者主要以繁體中文對話。")
    stt.transcribe(b"x", "audio/webm")
    assert call_of(stt)["prompt"] == "使用者主要以繁體中文對話。"


def test_a_prompt_changes_nothing_else_about_the_request(monkeypatch):
    plain = make_stt(monkeypatch, ["嗨"], filter=False)
    plain.transcribe(b"x", "audio/webm")
    hinted = make_stt(monkeypatch, ["嗨"], filter=False, prompt="hint")
    hinted.transcribe(b"x", "audio/webm")
    assert call_of(hinted)["prompt"] == "hint"               # sent even with the filter off: it is independent of it
    assert {k: v for k, v in call_of(hinted).items() if k != "prompt"} == call_of(plain)
