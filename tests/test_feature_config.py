"""The settings blocks added in Part 12 (spec section 6): outfit, image, tinyfish, memory,
companion_state. Each has its own resolver that keeps whatever is valid and falls back to the
default for anything that is not — a typo in a hand-edited file must never stop the app starting."""
import json
from pathlib import Path

import pytest

from companion import config as cfg


@pytest.fixture
def write(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    for name in ("CF_ACCOUNT_ID", "COMPANION_MEMORY"):
        monkeypatch.delenv(name, raising=False)

    def put(data):
        path.write_text(json.dumps(data), encoding="utf-8")

    return put


def test_the_defaults_match_the_spec_contract(write):
    assert cfg.resolve_outfit_config() == {"default": "日常", "aliases": {"睡衣": ["睡袍", "pajamas"]}}
    assert cfg.resolve_image_config() == {
        "enabled": False, "model": "flux-2-klein-9b", "account_id": None, "width": 576, "height": 1024,
        "max_per_day": 6, "cooldown_s": 30.0, "timeout_s": 120.0, "appearance": ""}
    assert cfg.resolve_tinyfish_config() == {
        "enabled": False, "location": "TW", "language": "zh", "max_results": 5,
        "quarantine": True, "blocked_domains": []}
    assert cfg.resolve_memory_config() == {
        "enabled": True, "long_term_max_chars": 2000, "recent_notes_max_chars": 600, "retrieval_k": 3,
        "retrieval_snippet_chars": 200, "retrieval_min_message_chars": 3, "retrieval_min_score": 0.6,
        "archive_scan_limit": 20000}
    assert cfg.resolve_companion_state_config() == {
        "enabled": True, "default_location": "家裡",
        "status_ttl_hours": {"微醺": 3, "酒醉": 8, "疲倦": 10, "感冒": 72},
        "default_status_ttl_hours": 12.0, "max_items": 20}


def test_a_value_set_in_config_json_wins_and_its_siblings_keep_their_defaults(write):
    write({"image": {"enabled": True, "appearance": "a young woman, black hair"}})
    image = cfg.resolve_image_config()
    assert image["enabled"] is True and image["appearance"] == "a young woman, black hair"
    assert image["width"] == 576


@pytest.mark.parametrize("block, field, bad, expected", [
    ("image", "width", "寬", 576), ("image", "width", 50, 576), ("image", "width", 5000, 576),   # 256..1920 only
    ("image", "max_per_day", -1, 6), ("image", "max_per_day", True, 6), ("image", "cooldown_s", "x", 30.0),
    ("image", "enabled", "yes", False), ("image", "model", "", "flux-2-klein-9b"),
    ("tinyfish", "max_results", 0, 5), ("tinyfish", "max_results", 99, 5), ("tinyfish", "quarantine", "no", True),
    ("tinyfish", "blocked_domains", "evil.com", []),
    ("memory", "long_term_max_chars", 10, 2000), ("memory", "retrieval_k", 0, 3), ("memory", "retrieval_min_score", 0, 0.6), ("memory", "retrieval_min_score", "高", 0.6), ("memory", "enabled", 1, True),
    ("companion_state", "max_items", 0, 20), ("companion_state", "default_location", "", "家裡"),
    ("companion_state", "default_status_ttl_hours", -3, 12.0),
])
def test_a_bad_value_falls_back_to_that_fields_default_only(write, block, field, bad, expected):
    write({block: {field: bad}})
    assert getattr(cfg, f"resolve_{block}_config")()[field] == expected


def test_status_lifetimes_keep_the_good_entries_and_drop_the_bad_ones(write):
    write({"companion_state": {"status_ttl_hours": {"微醺": 5, "發呆": "很久", "累": -2, "感冒": 48}}})
    ttl = cfg.resolve_companion_state_config()["status_ttl_hours"]
    assert ttl["微醺"] == 5 and ttl["感冒"] == 48
    assert "發呆" not in ttl and "累" not in ttl


def test_outfit_aliases_must_be_lists_of_names(write):
    write({"outfit": {"default": "睡衣", "aliases": {"睡衣": ["睡袍"], "壞": "不是清單", "空": []}}})
    outfit = cfg.resolve_outfit_config()
    assert outfit["default"] == "睡衣"
    assert outfit["aliases"] == {"睡衣": ["睡袍"]}


def test_the_account_id_may_come_from_the_environment_which_wins_over_the_file(write, monkeypatch):
    write({"image": {"account_id": "from-file"}})
    assert cfg.resolve_image_config()["account_id"] == "from-file"
    monkeypatch.setenv("CF_ACCOUNT_ID", "from-env")
    assert cfg.resolve_image_config()["account_id"] == "from-env"


def test_the_environment_switch_turns_memory_off_whatever_the_file_says(write, monkeypatch):
    write({"memory": {"enabled": True}})
    assert cfg.resolve_memory_config()["enabled"] is True
    monkeypatch.setenv("COMPANION_MEMORY", "off")
    assert cfg.resolve_memory_config()["enabled"] is False


def test_the_example_file_documents_exactly_the_built_in_defaults_of_every_new_block(monkeypatch):
    example = Path(__file__).resolve().parent.parent / "config.example.json"
    on_disk = json.loads(example.read_text(encoding="utf-8"))
    for block in ("outfit", "image", "tinyfish", "memory", "companion_state"):
        assert block in on_disk, f"config.example.json does not show the {block} section"
    monkeypatch.setattr("companion.config.config_path", lambda: example)
    from_example = {b: getattr(cfg, f"resolve_{b}_config")()
                    for b in ("outfit", "image", "tinyfish", "memory", "companion_state")}
    monkeypatch.setattr("companion.config.config_path", lambda: example.with_name("does-not-exist.json"))
    assert from_example == {b: getattr(cfg, f"resolve_{b}_config")()
                            for b in ("outfit", "image", "tinyfish", "memory", "companion_state")}
