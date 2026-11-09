import json
from pathlib import Path

import pytest

from companion.config import (
    DEFAULT_CONFIG,
    load_config,
    resolve_engine,
    resolve_proactive_config,
    resolve_tts_config,
    save_config,
)


def test_a_missing_config_file_gives_back_the_built_in_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    assert load_config() == DEFAULT_CONFIG


def test_a_partial_config_file_is_deep_merged_over_the_defaults_not_replacing_them(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tts": {"edge": {"voice": "zh-TW-YunJheNeural"}}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)

    config = load_config()
    assert config["tts"]["edge"]["voice"] == "zh-TW-YunJheNeural"  # overridden
    assert config["tts"]["edge"]["rate"] == DEFAULT_CONFIG["tts"]["edge"]["rate"]  # untouched sibling kept
    assert config["tts"]["openai"] == DEFAULT_CONFIG["tts"]["openai"]  # untouched section kept whole


def test_a_corrupt_config_file_is_treated_as_empty_not_a_crash(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    assert load_config() == DEFAULT_CONFIG


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "config.json"  # parent folder does not exist yet
    monkeypatch.setattr("companion.config.config_path", lambda: path)

    custom = {"tts": {"engine": "edge", "edge": {"voice": "x", "rate": "+10%", "volume": "+0%", "pitch": "+0Hz"}}}
    save_config(custom)
    assert path.exists()
    assert load_config()["tts"]["edge"]["voice"] == "x"


def test_an_env_var_overrides_the_config_file_which_overrides_the_default(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tts": {"edge": {"voice": "from-config-file"}}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)

    monkeypatch.delenv("COMPANION_VOICE", raising=False)
    assert resolve_tts_config()["edge_voice"] == "from-config-file"

    monkeypatch.setenv("COMPANION_VOICE", "from-env-var")
    assert resolve_tts_config()["edge_voice"] == "from-env-var"


def test_every_tts_setting_can_be_overridden_by_its_own_env_var(tmp_path, monkeypatch):
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("COMPANION_TTS", "edge")
    monkeypatch.setenv("COMPANION_VOICE", "v")
    monkeypatch.setenv("COMPANION_RATE", "+20%")
    monkeypatch.setenv("COMPANION_VOLUME", "-10%")
    monkeypatch.setenv("COMPANION_PITCH", "+5Hz")
    monkeypatch.setenv("COMPANION_PRIMETTS_URL", "http://x/v1")
    monkeypatch.setenv("COMPANION_PRIMETTS_MODEL", "m")
    monkeypatch.setenv("COMPANION_PRIMETTS_VOICE", "pv")
    monkeypatch.setenv("COMPANION_PRIMETTS_FORMAT", "mp3")
    monkeypatch.setenv("COMPANION_PRIMETTS_API_KEY", "k")
    monkeypatch.setenv("COMPANION_PRIMETTS_TIMEOUT_S", "9")
    monkeypatch.setenv("COMPANION_TTS_FALLBACK", "off")

    settings = resolve_tts_config()
    assert settings == {
        "enabled": True, "engine": "edge", "fallback": False,
        "edge_voice": "v", "edge_rate": "+20%", "edge_volume": "-10%", "edge_pitch": "+5Hz",
        "primetts_url": "http://x/v1", "primetts_model": "m", "primetts_voice": "pv",
        "primetts_format": "mp3", "primetts_api_key": "k", "primetts_timeout_s": 9.0,
    }


def test_fallback_defaults_to_the_config_files_value_when_the_env_var_is_not_set(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tts": {"fallback": False}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.delenv("COMPANION_TTS_FALLBACK", raising=False)
    assert resolve_tts_config()["fallback"] is False


@pytest.mark.parametrize("primetts_url,expected", [(None, "edge"), ("http://x/v1", "primetts")])
def test_auto_picks_primetts_only_when_a_server_address_is_configured(primetts_url, expected):
    assert resolve_engine("auto", primetts_url) == expected


def test_an_explicit_engine_choice_is_never_overridden_by_auto_detection():
    assert resolve_engine("edge", "http://x/v1") == "edge"  # explicit "edge" wins even with a URL set
    assert resolve_engine("off", "http://x/v1") == "off"


# ---- proactive speaking lives in the same config file ----


def test_proactive_speaking_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "config.json")
    for var in ("COMPANION_PROACTIVE", "COMPANION_PROACTIVE_MIN_MINUTES", "COMPANION_PROACTIVE_MAX_MINUTES"):
        monkeypatch.delenv(var, raising=False)
    assert resolve_proactive_config() == {"enabled": False, "min_minutes": 10.0, "max_minutes": 30.0}


def test_turning_it_on_is_one_line_in_the_config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"proactive": {"enabled": True}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    for var in ("COMPANION_PROACTIVE", "COMPANION_PROACTIVE_MIN_MINUTES", "COMPANION_PROACTIVE_MAX_MINUTES"):
        monkeypatch.delenv(var, raising=False)
    settings = resolve_proactive_config()
    assert settings["enabled"] is True
    assert settings["min_minutes"] == 10.0  # untouched siblings keep their defaults


def test_the_env_var_still_overrides_the_config_file_for_proactive_too(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"proactive": {"enabled": True}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    monkeypatch.setenv("COMPANION_PROACTIVE", "0")
    monkeypatch.setenv("COMPANION_PROACTIVE_MIN_MINUTES", "5")
    monkeypatch.setenv("COMPANION_PROACTIVE_MAX_MINUTES", "6")
    assert resolve_proactive_config() == {"enabled": False, "min_minutes": 5.0, "max_minutes": 6.0}


# ---- "ui" section (spec Part 9, ticket 35) ----

from companion.config import resolve_ui_config  # noqa: E402


@pytest.fixture
def ui_config_file(tmp_path, monkeypatch):
    """Point the config at a temp file and clear the UI env vars; returns a writer for it."""
    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    for name in ("COMPANION_AUTO_LISTEN", "COMPANION_ON_TOP_LEVEL", "COMPANION_HIT_WIDTH_RATIO", "COMPANION_SPEAKING_BOOST", "COMPANION_DUCK_LEVEL"):
        monkeypatch.delenv(name, raising=False)

    def write(ui):
        path.write_text(json.dumps({"ui": ui}), encoding="utf-8")

    return write


def test_ui_defaults_when_nothing_is_configured(ui_config_file):
    assert resolve_ui_config() == {"auto_listen": False, "on_top_level": "normal", "hit_width_ratio": 0.6, "speaking_boost": 1.0, "duck_level": 0.4}


def test_a_partial_ui_section_keeps_the_other_defaults(ui_config_file):
    ui_config_file({"auto_listen": True})
    assert resolve_ui_config() == {"auto_listen": True, "on_top_level": "normal", "hit_width_ratio": 0.6, "speaking_boost": 1.0, "duck_level": 0.4}


def test_valid_values_for_every_ui_field_are_honoured(ui_config_file):
    ui_config_file({"auto_listen": True, "on_top_level": "screen-saver", "hit_width_ratio": 0.35, "speaking_boost": 1.0, "duck_level": 0.6})
    assert resolve_ui_config() == {"auto_listen": True, "on_top_level": "screen-saver", "hit_width_ratio": 0.35, "speaking_boost": 1.0, "duck_level": 0.6}


@pytest.mark.parametrize("bad_ratio", [0.19, 1.01, 0, -1, 5, "wide", None, True, [0.5], float("nan")])
def test_a_hit_width_ratio_outside_0_2_to_1_falls_back_to_the_default(ui_config_file, bad_ratio):
    ui_config_file({"hit_width_ratio": bad_ratio})
    assert resolve_ui_config()["hit_width_ratio"] == 0.6


@pytest.mark.parametrize("ok_ratio", [0.2, 1.0, 1])
def test_the_ratio_boundaries_themselves_are_valid(ui_config_file, ok_ratio):
    ui_config_file({"hit_width_ratio": ok_ratio})
    assert resolve_ui_config()["hit_width_ratio"] == float(ok_ratio)


@pytest.mark.parametrize("bad_level", ["Normal", "top", "", None, 1, True])
def test_an_unknown_on_top_level_falls_back_to_normal(ui_config_file, bad_level):
    ui_config_file({"on_top_level": bad_level})
    assert resolve_ui_config()["on_top_level"] == "normal"


@pytest.mark.parametrize("bad_flag", ["yes", 1, 0, None, "true"])
def test_an_auto_listen_that_is_not_a_real_boolean_falls_back_to_off(ui_config_file, bad_flag):
    ui_config_file({"auto_listen": bad_flag})
    assert resolve_ui_config()["auto_listen"] is False


def test_one_bad_ui_field_does_not_spoil_its_valid_neighbours(ui_config_file):
    ui_config_file({"auto_listen": True, "on_top_level": "nonsense", "hit_width_ratio": 9})
    assert resolve_ui_config() == {"auto_listen": True, "on_top_level": "normal", "hit_width_ratio": 0.6, "speaking_boost": 1.0, "duck_level": 0.4}


def test_a_ui_section_that_is_not_an_object_does_not_break_loading(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"ui": "oops"}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    for name in ("COMPANION_AUTO_LISTEN", "COMPANION_ON_TOP_LEVEL", "COMPANION_HIT_WIDTH_RATIO", "COMPANION_SPEAKING_BOOST", "COMPANION_DUCK_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    assert resolve_ui_config() == {"auto_listen": False, "on_top_level": "normal", "hit_width_ratio": 0.6, "speaking_boost": 1.0, "duck_level": 0.4}


def test_env_vars_override_the_ui_section_of_the_config_file(ui_config_file, monkeypatch):
    ui_config_file({"auto_listen": False, "on_top_level": "normal", "hit_width_ratio": 0.6, "speaking_boost": 1.0, "duck_level": 0.4})
    monkeypatch.setenv("COMPANION_AUTO_LISTEN", "1")
    monkeypatch.setenv("COMPANION_ON_TOP_LEVEL", "screen-saver")
    monkeypatch.setenv("COMPANION_HIT_WIDTH_RATIO", "0.8")
    assert resolve_ui_config() == {"auto_listen": True, "on_top_level": "screen-saver", "hit_width_ratio": 0.8, "speaking_boost": 1.0, "duck_level": 0.4}


def test_an_invalid_env_var_does_not_beat_a_valid_config_file(ui_config_file, monkeypatch):
    ui_config_file({"on_top_level": "screen-saver", "hit_width_ratio": 0.4})
    monkeypatch.setenv("COMPANION_ON_TOP_LEVEL", "bogus")
    monkeypatch.setenv("COMPANION_HIT_WIDTH_RATIO", "wide")
    # an unusable override is treated as unset, so the valid file value underneath still applies
    assert resolve_ui_config()["on_top_level"] == "screen-saver"
    assert resolve_ui_config()["hit_width_ratio"] == 0.4


def test_the_existing_sections_are_untouched_by_the_ui_section(ui_config_file):
    ui_config_file({"auto_listen": True})
    config = load_config()
    assert config["tts"] == DEFAULT_CONFIG["tts"]
    assert config["proactive"] == DEFAULT_CONFIG["proactive"]


# ---- "time" section (spec Part 11, ticket 45) ----

from companion.config import resolve_time_config  # noqa: E402


@pytest.fixture
def time_config_file(tmp_path, monkeypatch):
    """Point the config at a temp file; returns a writer for its "time" section."""
    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)

    def write(time_section):
        path.write_text(json.dumps({"time": time_section}), encoding="utf-8")

    return write


def hm(h, m=0):
    return h * 60 + m


def test_time_defaults_when_nothing_is_configured(time_config_file):
    cfg = resolve_time_config()
    assert cfg["enabled"] is True
    assert cfg["timezone"] is None  # None = the computer's own local time zone
    assert cfg["gap_marker_minutes"] == 30
    assert cfg["quiet_hours"] == {"enabled": True, "start": hm(0), "end": hm(7)}
    assert [(r["name"], r["start"], r["end"]) for r in cfg["routine"]] == [
        ("早餐", hm(7), hm(9)),
        ("午餐", hm(12), hm(13, 30)),
        ("晚餐", hm(18), hm(19, 30)),
        ("深夜", hm(23), hm(7)),  # crosses midnight: the end is "earlier" than the start
    ]
    assert all(r["hint"].strip() for r in cfg["routine"])


def test_the_master_switch_can_be_turned_off(time_config_file):
    time_config_file({"enabled": False})
    assert resolve_time_config()["enabled"] is False


@pytest.mark.parametrize("bad", ["yes", 1, 0, None, "false"])
def test_a_master_switch_that_is_not_a_real_boolean_stays_on(time_config_file, bad):
    time_config_file({"enabled": bad})
    assert resolve_time_config()["enabled"] is True


@pytest.mark.parametrize("good", [1, 45, 90.5])
def test_a_positive_gap_threshold_is_used(time_config_file, good):
    time_config_file({"gap_marker_minutes": good})
    assert resolve_time_config()["gap_marker_minutes"] == good


@pytest.mark.parametrize("bad", [0, -5, "30", None, True, False, [30], float("nan"), float("inf")])
def test_a_gap_threshold_that_is_not_a_positive_number_falls_back_to_30(time_config_file, bad):
    time_config_file({"gap_marker_minutes": bad})
    assert resolve_time_config()["gap_marker_minutes"] == 30


def test_a_valid_iana_time_zone_name_is_used(time_config_file):
    time_config_file({"timezone": "Asia/Taipei"})
    tz = resolve_time_config()["timezone"]
    assert tz is not None and tz.key == "Asia/Taipei"


@pytest.mark.parametrize("bad", ["Not/AZone", "", "  ", "../etc/passwd", 8, True, None, ["Asia/Taipei"], "Asia/Taipei\n; rm"])
def test_a_time_zone_that_cannot_be_found_falls_back_to_local(time_config_file, bad):
    time_config_file({"timezone": bad})
    assert resolve_time_config()["timezone"] is None


def entry(name, start, end, hint="提示"):
    return {"name": name, "start": start, "end": end, "hint": hint}


def test_a_routine_you_provide_replaces_the_default_one_instead_of_merging(time_config_file):
    time_config_file({"routine": [entry("下午茶", "15:00", "16:00", "可以聊聊下午茶")]})
    routine = resolve_time_config()["routine"]
    assert routine == [{"name": "下午茶", "hint": "可以聊聊下午茶", "start": hm(15), "end": hm(16)}]


def test_an_empty_routine_means_no_routine_at_all(time_config_file):
    time_config_file({"routine": []})
    assert resolve_time_config()["routine"] == []


@pytest.mark.parametrize("not_a_list", ["早餐", 7, {"name": "早餐"}, None, True])
def test_a_routine_that_is_not_a_list_is_treated_as_not_set(time_config_file, not_a_list):
    time_config_file({"routine": not_a_list})
    assert [r["name"] for r in resolve_time_config()["routine"]] == ["早餐", "午餐", "晚餐", "深夜"]


def test_routine_order_is_kept_because_it_decides_overlaps(time_config_file):
    time_config_file({"routine": [entry("B", "10:00", "12:00"), entry("A", "08:00", "11:00")]})
    assert [r["name"] for r in resolve_time_config()["routine"]] == ["B", "A"]


def test_a_routine_entry_may_cross_midnight(time_config_file):
    time_config_file({"routine": [entry("夜貓", "22:30", "02:15")]})
    assert resolve_time_config()["routine"][0]["start"] == hm(22, 30)
    assert resolve_time_config()["routine"][0]["end"] == hm(2, 15)


GOOD = entry("午茶", "15:00", "16:00")


@pytest.mark.parametrize("bad_entry", [
    "not an object", 5, None, ["早餐"],
    {"start": "07:00", "end": "09:00", "hint": "x"},                          # no name
    {"name": "  ", "start": "07:00", "end": "09:00", "hint": "x"},            # blank name
    {"name": 7, "start": "07:00", "end": "09:00", "hint": "x"},               # name not text
    {"name": "早餐", "start": "07:00", "end": "09:00"},                       # no hint
    {"name": "早餐", "start": "07:00", "end": "09:00", "hint": "  "},         # blank hint
    entry("早餐", "7:00", "09:00"),                                           # not zero padded
    entry("早餐", "24:00", "09:00"),
    entry("早餐", "07:60", "09:00"),
    entry("早餐", "07:00", "9am"),
    entry("早餐", "07:00:00", "09:00"),
    entry("早餐", 700, "09:00"),
    entry("早餐", None, "09:00"),
    entry("早餐", "07:00", "07:00"),                                          # empty range
])
def test_one_bad_routine_entry_is_dropped_and_its_neighbours_survive(time_config_file, bad_entry):
    time_config_file({"routine": [GOOD, bad_entry, entry("散步", "20:00", "21:00")]})
    assert [r["name"] for r in resolve_time_config()["routine"]] == ["午茶", "散步"]


def test_a_routine_where_every_entry_is_bad_ends_up_empty_not_default(time_config_file):
    time_config_file({"routine": [{"name": "x"}, "y", entry("z", "07:00", "07:00")]})
    assert resolve_time_config()["routine"] == []


def test_a_bad_routine_entry_does_not_spoil_the_other_time_settings(time_config_file):
    time_config_file({"enabled": False, "gap_marker_minutes": 45, "routine": [{"name": "x"}]})
    cfg = resolve_time_config()
    assert cfg["enabled"] is False and cfg["gap_marker_minutes"] == 45 and cfg["routine"] == []


def test_quiet_hours_can_be_changed(time_config_file):
    time_config_file({"quiet_hours": {"start": "23:00", "end": "08:30"}})
    assert resolve_time_config()["quiet_hours"] == {"enabled": True, "start": hm(23), "end": hm(8, 30)}


def test_quiet_hours_can_be_turned_off_and_that_is_valid(time_config_file):
    time_config_file({"quiet_hours": {"enabled": False}})
    assert resolve_time_config()["quiet_hours"] == {"enabled": False, "start": hm(0), "end": hm(7)}


@pytest.mark.parametrize("bad", ["yes", 1, 0, None])
def test_a_quiet_hours_switch_that_is_not_a_real_boolean_stays_on(time_config_file, bad):
    time_config_file({"quiet_hours": {"enabled": bad}})
    assert resolve_time_config()["quiet_hours"]["enabled"] is True


@pytest.mark.parametrize("bad_times", [
    {"start": "7am", "end": "08:00"},
    {"start": "23:00", "end": 8},
    {"start": "25:00", "end": "08:00"},
    {"start": "08:00", "end": "08:00"},   # an empty range
    {"start": None, "end": None},
])
def test_unusable_quiet_hours_times_fall_back_to_the_default_range_but_keep_the_switch(time_config_file, bad_times):
    time_config_file({"quiet_hours": {"enabled": False, **bad_times}})
    assert resolve_time_config()["quiet_hours"] == {"enabled": False, "start": hm(0), "end": hm(7)}


@pytest.mark.parametrize("not_an_object", ["00:00-07:00", 7, [1, 2], None, True])
def test_quiet_hours_that_is_not_an_object_means_the_default(time_config_file, not_an_object):
    time_config_file({"quiet_hours": not_an_object})
    assert resolve_time_config()["quiet_hours"] == {"enabled": True, "start": hm(0), "end": hm(7)}


def test_setting_only_one_nested_field_keeps_its_siblings_at_their_defaults(time_config_file):
    time_config_file({"quiet_hours": {"start": "22:00"}})
    assert resolve_time_config()["quiet_hours"] == {"enabled": True, "start": hm(22), "end": hm(7)}


@pytest.mark.parametrize("not_an_object", ["off", 5, [1], None, True])
def test_a_time_section_that_is_not_an_object_means_all_defaults(tmp_path, monkeypatch, not_an_object):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"time": not_an_object}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    cfg = resolve_time_config()
    assert cfg["enabled"] is True and cfg["gap_marker_minutes"] == 30 and len(cfg["routine"]) == 4


def test_the_time_section_does_not_disturb_the_other_sections(time_config_file):
    time_config_file({"enabled": False})
    config = load_config()
    assert config["tts"] == DEFAULT_CONFIG["tts"]
    assert config["proactive"] == DEFAULT_CONFIG["proactive"]
    assert config["ui"] == DEFAULT_CONFIG["ui"]


def test_the_example_config_file_documents_exactly_the_built_in_defaults(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parent.parent / "config.example.json"
    assert "time" in json.loads(example.read_text(encoding="utf-8"))  # it must show the section at all
    monkeypatch.setattr("companion.config.config_path", lambda: example)
    from_example = resolve_time_config()
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "nothing-here.json")
    assert from_example == resolve_time_config()


# ---- "stt" section: guarding against things the recogniser "hears" that nobody said ----

from companion.config import parse_stt_config, resolve_stt_config  # noqa: E402


@pytest.fixture
def stt_config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)

    def write(stt_section):
        path.write_text(json.dumps({"stt": stt_section}), encoding="utf-8")

    return write


STT_DEFAULTS = {"enabled": True, "language": None, "filter": True, "allowed_languages": ["zh", "en", "ja"],
                "ignore_phrases": ["thank you", "thanks", "okay", "yes", "music", "and the", "you", "bye"],
                "prompt": None, "no_speech_prob_max": 0.6, "avg_logprob_min": -1.0, "debug_log": False}


def test_stt_defaults_when_nothing_is_configured(stt_config_file, tmp_path):
    assert resolve_stt_config() == STT_DEFAULTS


def test_parsing_with_nothing_given_gives_the_same_defaults_without_touching_any_file():
    assert parse_stt_config(None) == STT_DEFAULTS
    assert parse_stt_config({}) == STT_DEFAULTS
    assert parse_stt_config("junk") == STT_DEFAULTS


@pytest.mark.parametrize("given, expected", [("zh", "zh"), ("EN", "en"), (" ja ", "ja"), ("yue", "yue")])
def test_a_language_hint_is_a_short_lowercase_code(stt_config_file, given, expected):
    stt_config_file({"language": given})
    assert resolve_stt_config()["language"] == expected


@pytest.mark.parametrize("bad", ["", "  ", "chinese", "z", "zhzhz", "z1", 5, True, ["zh"], None])
def test_anything_that_is_not_a_language_code_means_detect_automatically(stt_config_file, bad):
    stt_config_file({"language": bad})
    assert resolve_stt_config()["language"] is None


def test_the_allowed_languages_list_is_cleaned_up(stt_config_file):
    stt_config_file({"allowed_languages": [" ZH ", "Chinese", "en", "", 5, None, "ja", "en"]})
    assert resolve_stt_config()["allowed_languages"] == ["zh", "chinese", "en", "ja"]  # trimmed, lower-cased, no junk, no repeats


def test_an_empty_allowed_list_is_valid_and_means_accept_any_language(stt_config_file):
    stt_config_file({"allowed_languages": []})
    assert resolve_stt_config()["allowed_languages"] == []


@pytest.mark.parametrize("not_a_list", ["zh", 5, {"zh": 1}, None, True])
def test_an_allowed_languages_value_that_is_not_a_list_means_the_default(stt_config_file, not_a_list):
    stt_config_file({"allowed_languages": not_a_list})
    assert resolve_stt_config()["allowed_languages"] == ["zh", "en", "ja"]


@pytest.mark.parametrize("good", [0.1, 0.5, 1, 1.0])
def test_a_no_speech_threshold_between_zero_and_one_is_used(stt_config_file, good):
    stt_config_file({"no_speech_prob_max": good})
    assert resolve_stt_config()["no_speech_prob_max"] == good


@pytest.mark.parametrize("bad", [0, -0.1, 1.01, 5, "0.5", None, True, [0.5], float("nan")])
def test_a_no_speech_threshold_outside_zero_to_one_falls_back(stt_config_file, bad):
    stt_config_file({"no_speech_prob_max": bad})
    assert resolve_stt_config()["no_speech_prob_max"] == 0.6


@pytest.mark.parametrize("good", [-0.2, -1, -1.5, -3, 0])
def test_a_confidence_floor_that_is_zero_or_negative_is_used(stt_config_file, good):
    stt_config_file({"avg_logprob_min": good})
    assert resolve_stt_config()["avg_logprob_min"] == good


@pytest.mark.parametrize("bad", [0.5, 2, "−1", None, True, [-1], float("nan"), float("-inf")])
def test_a_confidence_floor_that_is_not_a_zero_or_negative_number_falls_back(stt_config_file, bad):
    stt_config_file({"avg_logprob_min": bad})
    assert resolve_stt_config()["avg_logprob_min"] == -1.0


@pytest.mark.parametrize("name", ["filter", "debug_log"])
def test_the_two_switches_must_be_real_booleans(stt_config_file, name):
    stt_config_file({name: not STT_DEFAULTS[name]})
    assert resolve_stt_config()[name] is (not STT_DEFAULTS[name])
    for bad in ("yes", 1, 0, None, "false"):
        stt_config_file({name: bad})
        assert resolve_stt_config()[name] is STT_DEFAULTS[name]


def test_one_bad_stt_field_does_not_spoil_the_others(stt_config_file):
    stt_config_file({"language": "zh", "no_speech_prob_max": 9, "debug_log": True, "allowed_languages": "x"})
    assert resolve_stt_config() == {**STT_DEFAULTS, "language": "zh", "debug_log": True}


def test_the_stt_section_does_not_disturb_the_other_sections(stt_config_file):
    stt_config_file({"filter": False})
    config = load_config()
    assert config["tts"] == DEFAULT_CONFIG["tts"] and config["ui"] == DEFAULT_CONFIG["ui"]
    assert config["time"] == DEFAULT_CONFIG["time"] and config["proactive"] == DEFAULT_CONFIG["proactive"]


def test_the_example_config_documents_exactly_the_built_in_stt_defaults(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parent.parent / "config.example.json"
    assert "stt" in json.loads(example.read_text(encoding="utf-8"))
    monkeypatch.setattr("companion.config.config_path", lambda: example)
    from_example = resolve_stt_config()
    monkeypatch.setattr("companion.config.config_path", lambda: tmp_path / "nothing-here.json")
    assert from_example == resolve_stt_config() == STT_DEFAULTS


# ---- ui.speaking_boost: how much louder you must be to cut in while she is talking ----

def test_the_speaking_boost_is_off_by_default(ui_config_file):
    assert resolve_ui_config()["speaking_boost"] == 1.0


@pytest.mark.parametrize("good", [1, 1.5, 2.5, 4, 10])
def test_a_boost_from_one_to_ten_is_used(ui_config_file, good):
    ui_config_file({"speaking_boost": good})
    assert resolve_ui_config()["speaking_boost"] == good


@pytest.mark.parametrize("bad", [0, 0.5, 0.99, -1, 10.01, 100, "2.5", None, True, [2], float("nan"), float("inf")])
def test_a_boost_outside_one_to_ten_means_no_boost(ui_config_file, bad):
    ui_config_file({"speaking_boost": bad})
    assert resolve_ui_config()["speaking_boost"] == 1.0


def test_an_env_var_can_set_the_boost_and_a_bad_one_falls_back_to_the_file(ui_config_file, monkeypatch):
    ui_config_file({"speaking_boost": 3})
    monkeypatch.setenv("COMPANION_SPEAKING_BOOST", "2.5")
    assert resolve_ui_config()["speaking_boost"] == 2.5
    monkeypatch.setenv("COMPANION_SPEAKING_BOOST", "loud")
    assert resolve_ui_config()["speaking_boost"] == 3


def test_the_ignored_phrases_list_is_cleaned_up(stt_config_file):
    stt_config_file({"ignore_phrases": [" Thank  You ", "OKAY", "", 5, None, "okay", "bye"]})
    assert resolve_stt_config()["ignore_phrases"] == ["thank you", "okay", "bye"]  # trimmed, one space, lower-cased, no junk, no repeats


def test_an_empty_ignore_list_is_valid_and_means_nothing_is_ignored(stt_config_file):
    stt_config_file({"ignore_phrases": []})
    assert resolve_stt_config()["ignore_phrases"] == []


@pytest.mark.parametrize("not_a_list", ["thank you", 5, {"a": 1}, None, True])
def test_an_ignore_phrases_value_that_is_not_a_list_means_the_default(stt_config_file, not_a_list):
    stt_config_file({"ignore_phrases": not_a_list})
    assert resolve_stt_config()["ignore_phrases"] == STT_DEFAULTS["ignore_phrases"]


def test_a_prompt_is_kept_trimmed(stt_config_file):
    stt_config_file({"prompt": "  使用者主要以繁體中文對話。  "})
    assert resolve_stt_config()["prompt"] == "使用者主要以繁體中文對話。"


@pytest.mark.parametrize("bad", ["", "   ", "\n", 5, True, ["a"], {"a": 1}, None])
def test_a_prompt_that_is_blank_or_not_text_means_no_prompt(stt_config_file, bad):
    stt_config_file({"prompt": bad})
    assert resolve_stt_config()["prompt"] is None


# ---- ui.duck_level: how loud she stays while a possible interruption is being checked ----

def test_she_is_turned_down_to_forty_percent_by_default(ui_config_file):
    assert resolve_ui_config()["duck_level"] == 0.4


@pytest.mark.parametrize("good", [0.1, 0.2, 0.4, 0.5, 0.75, 1, 1.0])
def test_a_duck_level_from_a_tenth_to_one_is_used(ui_config_file, good):
    ui_config_file({"duck_level": good})
    assert resolve_ui_config()["duck_level"] == good


@pytest.mark.parametrize("bad", [0, 0.09, -0.5, 1.01, 2, 10, "0.5", None, True, [0.5], float("nan"), float("inf")])
def test_a_duck_level_outside_a_tenth_to_one_means_the_default(ui_config_file, bad):
    ui_config_file({"duck_level": bad})
    assert resolve_ui_config()["duck_level"] == 0.4


def test_an_env_var_can_set_the_duck_level_and_a_bad_one_falls_back_to_the_file(ui_config_file, monkeypatch):
    ui_config_file({"duck_level": 0.3})
    monkeypatch.setenv("COMPANION_DUCK_LEVEL", "0.6")
    assert resolve_ui_config()["duck_level"] == 0.6
    monkeypatch.setenv("COMPANION_DUCK_LEVEL", "quiet")
    assert resolve_ui_config()["duck_level"] == 0.3
    monkeypatch.setenv("COMPANION_DUCK_LEVEL", "5")          # out of range: also ignored
    assert resolve_ui_config()["duck_level"] == 0.3
