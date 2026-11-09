"""Nothing sent to a model, and nothing the smoke report prints, may assume the character's gender (ticket 08).
Allowed: 他 / 你 / 等. Forbidden: 她, 妳, she, her, hers. The model that folds memory does not know the
persona, so it is told "角色"; the character herself is spoken to as 你."""
import json
import re

import pytest

from companion.config import resolve_time_config
from companion.engine import PROACTIVE_SYSTEM_ADDENDUM, TurnEngine
from companion.history import InMemoryHistory
from companion.outfits import Wardrobe
from companion.state import InMemoryState
from tests.test_memory_fold import FoldLLM, chat, engine_for, fold_answer

GENDERED = re.compile(r"[她妳]|\b(she|her|hers|herself)\b", re.IGNORECASE)
NOW = 1_800_000_000.0
STATE = {"enabled": True, "default_location": "家裡", "status_ttl_hours": {}, "default_status_ttl_hours": 12.0, "max_items": 20}


def gendered(text):
    return sorted({m.group() for m in GENDERED.finditer(text)})


class SpyLLM:
    def __init__(self):
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        yield "[neutral]好。"

    def generate_structured(self, system, messages, schema):
        return None


@pytest.fixture
def full_prompt(tmp_path, monkeypatch):
    """The system prompt of a turn with memory, journal, state, time and outfits all switched on."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"time": {"timezone": "Asia/Taipei"}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    for name in ("日常", "睡衣"):
        (tmp_path / "clips" / name).mkdir(parents=True)
        (tmp_path / "clips" / name / "idle.webm").write_bytes(b"v")
    store = InMemoryHistory()
    store.save_facts({"使用者": "- 喜歡黑咖啡", "角色自己的事": "- 怕打雷", "待跟進": "- 面試"})
    state, llm = InMemoryState(), SpyLLM()
    engine = TurnEngine(llm, persona="我是小桃。", history_store=store, summarize=True, max_turns=3, wall_clock=lambda: NOW,
                        time_config=resolve_time_config(), character_state=state, state_settings=STATE,
                        wardrobe=Wardrobe(tmp_path / "clips", state, settings=lambda: {"default": "日常", "aliases": {}}))
    list(engine.send("嗨"))
    return llm.systems[-1]


def test_the_system_prompt_with_every_feature_on_has_no_gendered_words(full_prompt):
    assert gendered(full_prompt) == []


def test_the_proactive_instructions_have_no_gendered_words():
    assert gendered(PROACTIVE_SYSTEM_ADDENDUM) == []


def test_the_memory_folding_call_has_no_gendered_words_in_what_it_is_told_or_asked_to_return():
    llm = FoldLLM(fold_answer())
    engine, _ = engine_for(llm)
    chat(engine, 5)
    assert llm.fold_requests, "folding should have happened"
    for request in llm.fold_requests:
        assert gendered(request["system"]) == []
        assert gendered(request["request"]) == []
        assert gendered(json.dumps(request["schema"], ensure_ascii=False)) == []


def test_what_the_character_says_about_herself_is_kept_under_a_neutral_section_name():
    llm = FoldLLM(fold_answer(own=("怕打雷",)))
    engine, store = engine_for(llm)
    chat(engine, 5)
    assert store.load_facts()["角色自己的事"] == "- 怕打雷"
    assert "她自己的事" not in store.load_facts()


def test_the_memory_section_is_shown_to_the_character_as_角色自己的事(full_prompt):
    assert "〔角色自己的事〕" in full_prompt and "- 怕打雷" in full_prompt


def test_the_state_smoke_report_has_no_gendered_words():
    from companion.statesmoke import OracleLLM, evaluate, run_all

    report = evaluate(run_all(OracleLLM(), persona="p"))
    assert gendered(report.text()) == []
