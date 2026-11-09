"""Does remembering things slow her first words down? (spec Part 12, section 8, ticket 83)

Compares the delay until the first sentence with memory and character state OFF against ON, where "on" is
loaded the way an app that has been used for months would be: long-term facts and the journal near their
limits, her state filled in, a long archive to search. The budget is about half a second more. The real run
needs the real model — `python smoke_gemini.py --compare`; the rest is checked with stand-in models.
"""
import time
from dataclasses import dataclass
from statistics import median

from .config import DEFAULT_CONFIG, resolve_time_config
from .engine import Sentence, TurnEngine
from .history import InMemoryHistory
from .state import InMemoryState

BUDGET_S = 0.5
MESSAGES = ("嗨,你今天好嗎?", "上次聊的潛水證照後來怎麼樣了")
NOW = 1_800_000_000.0
DAY = 86400.0


def _seed(store, state):
    """Memory the size of long use: facts and journal close to their limits, an archive to search."""
    store.save_facts({
        "使用者": "\n".join(f"- 使用者的第{i}件小事,例如喜歡的東西和平常的習慣" for i in range(18)),
        "共同經歷": "\n".join(f"- 我們一起聊過第{i}個話題,印象很深" for i in range(14)),
        "待跟進": "- 下週要問使用者面試的結果",
    })
    from datetime import datetime
    today = f"{datetime.fromtimestamp(NOW).astimezone():%Y-%m-%d}"
    store.append_events([{"date": today, "time": f"{h:02d}:00", "kind": "事件", "text": f"今天的第{h}件事,聊了一些日常"} for h in range(1, 12)])
    topics = ["今天的午餐", "週末的計畫", "喜歡的電影", "最近的天氣", "公司的同事", "家裡的貓"]
    for i in range(60):
        said = f"我在準備潛水證照的考試,第{i}週" if i in (11, 41) else f"很久以前聊過的第{i}件事,關於{topics[i % len(topics)]}"
        store.append_turn(said, "[neutral]我記得,那時候你很認真。", at=NOW - (90 - i) * DAY)
    state.set_location("咖啡廳")
    state.set_items(["紅洋裝", "筆記本", "鑰匙"])


def build_engine(llm, persona, loaded):
    """The same app twice: `loaded` False = memory and state off; True = both on and filled in."""
    store, state = InMemoryHistory(), InMemoryState()
    if loaded:
        _seed(store, state)
    settings = dict(DEFAULT_CONFIG["companion_state"], enabled=loaded)
    return TurnEngine(llm, persona=persona, history_store=store, summarize=loaded, wall_clock=lambda: NOW,
                      time_config=resolve_time_config(),  # as the person has it set: not what is being compared
                      character_state=state, state_settings=settings, max_turns=10)


def first_sentence_latency(engine, message, clock=time.perf_counter):
    start = clock()
    for event in engine.send(message):
        if isinstance(event, Sentence):
            return clock() - start
    raise RuntimeError("no sentence came out")


def measure(make_llm, persona, runs=3, clock=time.perf_counter):
    """{"off": [...], "on": [...]} — first-sentence delays, runs x len(MESSAGES) each, each on a fresh engine."""
    return {side: [first_sentence_latency(build_engine(make_llm(), persona, loaded), message, clock)
                   for _ in range(runs) for message in MESSAGES]
            for side, loaded in (("off", False), ("on", True))}


@dataclass
class Report:
    off: list
    on: list

    @property
    def difference(self):
        return median(self.on) - median(self.off)

    @property
    def within_budget(self):
        return self.difference <= BUDGET_S + 1e-9

    def text(self):
        lines = [f"記憶與狀態「關」:中位數 {median(self.off):.2f}s(共 {len(self.off)} 次:{', '.join(f'{x:.2f}' for x in self.off)})",
                 f"記憶與狀態「開」:中位數 {median(self.on):.2f}s(共 {len(self.on)} 次:{', '.join(f'{x:.2f}' for x in self.on)})",
                 f"差距:{self.difference:+.2f}s(預算:不超過 {BUDGET_S:.1f}s)"]
        if self.within_budget:
            lines.append("在預算內。")
        else:
            lines.append("超過預算。不要就這樣上線:請把這份結果貼回對話,再決定要調降哪個上限"
                         "(memory.long_term_max_chars、recent_notes_max_chars、retrieval_k、archive_scan_limit)。")
        return "\n".join(lines)


def summarize(off, on):
    return Report(list(off), list(on))
