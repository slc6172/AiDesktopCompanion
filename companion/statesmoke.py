"""Does the real model keep her state tags honest? (spec Part 12, ticket 79)

Twenty short scenarios: ten where something in HER life really changes (she should declare it with a
tag) and ten where it does not (hypotheticals, other people's lives, plain chat — she must not).
Each is run through the real turn engine and judged by what actually changed in her stored state,
not by the wording. Target: at least 90% on EACH side. The run itself needs the real model and is
done by hand with smoke_state.py; everything here is also exercised with stand-in models.
"""
import time
from dataclasses import dataclass, field

from .config import DEFAULT_CONFIG
from .engine import Failure, TurnEngine
from .history import InMemoryHistory
from .state import InMemoryState

FIELDS = ("location", "status", "items")
TARGET = 0.9


@dataclass(frozen=True)
class Scenario:
    message: str
    expect: str | None            # the state field that should change, or None = nothing should
    tag: str = ""                 # what a model that behaves perfectly writes (for the stand-in model)
    seed: dict = field(default_factory=dict)


def _s(message, expect=None, tag="", **seed):
    return Scenario(message, expect, tag, seed)


SCENARIOS = (
    # ---- something really changes: she should say so ----
    _s("我們到咖啡廳了,這裡的咖啡好香喔。", "location", "[地點:咖啡廳]"),
    _s("我們現在已經在公園裡了,風吹起來好舒服。", "location", "[地點:公園]"),
    _s("好了,我們回到你家了,終於可以休息。", "location", "[地點:家裡]", location="咖啡廳"),
    _s("我們搭計程車到了海邊,你看,是海耶。", "location", "[地點:海邊]"),
    _s("來,乾杯!你剛剛已經喝完三杯啤酒了。", "status", "[狀態:微醺]"),
    _s("你剛剛一直打噴嚏還流鼻水,應該是感冒了。", "status", "[狀態:感冒]"),
    _s("生日快樂!這件紅洋裝是我送你的,收下吧。", "items", "[得到:紅洋裝]"),
    _s("來,這本筆記本是我買給你的,收下吧。", "items", "[得到:筆記本]"),
    _s("你剛剛不小心把鑰匙掉進河裡了,撈不回來了。", "items", "[失去:鑰匙]", items=["鑰匙"]),
    _s("你把那本書借給朋友了,他說會帶回家看。", "items", "[失去:書]", items=["書"]),
    # ---- nothing changes: she must not make something up ----
    _s("你今天心情怎麼樣?"),
    _s("如果我們去咖啡廳的話,你想點什麼?"),
    _s("我昨天去了公園,人超多的。"),
    _s("我朋友昨晚喝醉了,吐了一整晚,哈哈。"),
    _s("你喜歡什麼顏色的洋裝?"),
    _s("我在想要不要買一件紅洋裝送你,你覺得好嗎?"),
    _s("晚安,明天見。"),
    _s("講個笑話給我聽吧。"),
    _s("你平常有什麼興趣?"),
    _s("我剛剛把我的錢包弄丟了,好煩。", items=["筆記本"]),
)


@dataclass
class Result:
    scenario: Scenario
    changed: frozenset
    reply: str  # what she said (tags stripped)
    raw: str = ""  # what she actually wrote, tags included — to tell a missing tag from a wrong one
    error: str | None = None  # the service failed (busy, gateway error …): this run says nothing about her

    @property
    def valid(self):
        return self.error is None

    @property
    def ok(self):
        if not self.valid:
            return False
        return self.scenario.expect in self.changed if self.scenario.expect else not self.changed


def _snapshot(state):
    loaded = state.load()
    return {"location": loaded["location"], "status": loaded["status"], "items": tuple(loaded["items"])}


class _Recording:
    """Passes everything through to the real model and keeps what it wrote, tags and all."""

    def __init__(self, llm):
        self._llm, self.raw = llm, ""

    def stream(self, system, messages):
        for chunk in self._llm.stream(system, messages):
            self.raw += chunk
            yield chunk

    def generate_structured(self, *args, **kwargs):
        return self._llm.generate_structured(*args, **kwargs)


def run_scenario(llm, scenario, persona, wall_clock=lambda: 1_800_000_000.0):
    recording = _Recording(llm)
    llm = recording
    state = InMemoryState(default_location=DEFAULT_CONFIG["companion_state"]["default_location"])
    if "location" in scenario.seed:
        state.set_location(scenario.seed["location"])
    if "items" in scenario.seed:
        state.set_items(scenario.seed["items"])
    settings = dict(DEFAULT_CONFIG["companion_state"], enabled=True)
    engine = TurnEngine(llm, persona=persona, history_store=InMemoryHistory(), wall_clock=wall_clock,
                        character_state=state, state_settings=settings)
    before = _snapshot(state)
    events = list(engine.send(scenario.message))
    failure = next((e for e in events if isinstance(e, Failure)), None)
    reply = "".join(getattr(event, "text", "") for event in events)
    after = _snapshot(state)
    return Result(scenario, frozenset(f for f in FIELDS if before[f] != after[f]), reply, recording.raw,
                  error=failure.kind if failure else None)


def run_all(llm, persona, retries=3, backoff_s=15.0, pause_s=0.0, sleep=time.sleep):
    """Every scenario, one after another. A busy service (a free plan answers 429 or a gateway error now and then)
    is not an answer: that scenario is tried again after a pause that grows, and if it keeps failing it is
    reported as unusable instead of being scored. `pause_s` spaces the calls out so twenty of them do not arrive
    at once."""
    results = []
    for number, scenario in enumerate(SCENARIOS):
        if number and pause_s:
            sleep(pause_s)
        result = run_scenario(llm, scenario, persona)
        for attempt in range(1, retries + 1):
            if result.valid:
                break
            sleep(backoff_s * attempt)
            result = run_scenario(llm, scenario, persona)
        results.append(result)
    return results


@dataclass
class Report:
    results: list

    @property
    def _valid(self):
        return [r for r in self.results if r.valid]

    @property
    def invalid(self):
        return len(self.results) - len(self._valid)

    @property
    def declared_total(self):
        return sum(1 for r in self._valid if r.scenario.expect)

    @property
    def declared_ok(self):
        return sum(1 for r in self._valid if r.scenario.expect and r.ok)

    @property
    def quiet_total(self):
        return sum(1 for r in self._valid if not r.scenario.expect)

    @property
    def quiet_ok(self):
        return sum(1 for r in self._valid if not r.scenario.expect and r.ok)

    @property
    def passed(self):
        # a verdict needs every scenario to have been answered: an unanswered one proves nothing either way
        return (self.invalid == 0
                and self.declared_ok >= TARGET * self.declared_total - 1e-9
                and self.quiet_ok >= TARGET * self.quiet_total - 1e-9)

    def text(self):
        lines = []
        for r in self.results:
            kind = f"應宣告 {r.scenario.expect}" if r.scenario.expect else "不應宣告"
            if not r.valid:
                lines.append(f"⚠ [{kind}] API 錯誤:{r.error}(重試後仍失敗,不計分)\n    你說:{r.scenario.message}")
                continue
            changed = "、".join(sorted(r.changed)) or "無"
            lines.append(f"{'✓' if r.ok else '✗'} [{kind}] 實際改變:{changed}\n    你說:{r.scenario.message}\n    角色說:{r.reply[:60]}"
                         + ("" if r.ok and r.reply.strip() else f"\n    角色實際寫的(含標籤):{r.raw[:120]}"))
        lines.append("")
        lines.append(f"該宣告時有宣告:{self.declared_ok}/{self.declared_total}")
        lines.append(f"不該宣告時沒亂宣告:{self.quiet_ok}/{self.quiet_total}")
        if self.invalid:
            kinds = ", ".join(sorted({r.error for r in self.results if not r.valid}))
            lines.append(f"有 {self.invalid} 個情境因 API 錯誤({kinds})無法判定,沒有計入分數。"
                         "請稍後(例如幾分鐘後、或避開尖峰)重跑,拉長 --pause 間隔會更穩。")
        elif self.passed:
            lines.append(f"達標(兩邊都 ≥ {int(TARGET * 100)}%)。")
        if not self.passed and not self.invalid:
            lines += [f"未達標(兩邊都要 ≥ {int(TARGET * 100)}%):不要就這樣上線,請把這份結果貼回對話再決定。",
                      "可選的備援方向(只是方向,採用前先討論):縮小範圍,例如暫時拿掉「持有物品」;"
                      "或改在記憶摺疊的結構化呼叫中順帶校正狀態。"]
        return "\n".join(lines)


def evaluate(results):
    return Report(list(results))


class OracleLLM:
    """A stand-in model that behaves perfectly: writes the right tag where a scenario calls for one and
    nothing otherwise. `forget` / `overreach` make chosen scenarios go wrong, to exercise the judging."""

    def __init__(self, forget=(), overreach=()):
        self._by_message = {s.message: s for s in SCENARIOS}
        self._forget, self._overreach = set(forget), set(overreach)

    def stream(self, system, messages):
        message = messages[-1]["content"]
        scenario = self._by_message[message]
        tag = scenario.tag
        if message in self._forget:
            tag = ""
        if message in self._overreach and not tag:
            tag = "[地點:別的地方]"
        yield f"{tag}嗯,好啊。"
