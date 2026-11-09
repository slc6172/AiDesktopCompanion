"""The comparison of first-sentence delay with memory and state OFF versus ON (spec Part 12, ticket 83). The real
numbers come from the person running smoke_gemini.py --compare on their own machine; what is checked here is the
measuring, the verdict and that the "on" side really is loaded the way a long-used app would be."""
import pytest

from companion.latencysmoke import BUDGET_S, build_engine, first_sentence_latency, measure, summarize


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class SlowLLM:
    """Takes `delay` seconds to start answering, longer when the prompt it was given is longer."""

    def __init__(self, clock, per_char=0.0, base=0.2):
        self.clock, self.per_char, self.base = clock, per_char, base
        self.systems = []

    def stream(self, system, messages):
        self.systems.append(system)
        self.clock.now += self.base + self.per_char * len(system)
        yield "好。"

    def generate_structured(self, *args):
        return None


def test_the_delay_is_the_time_until_the_first_sentence_comes_out():
    clock = FakeClock()
    engine = build_engine(SlowLLM(clock, base=0.7), persona="p", loaded=False)
    assert first_sentence_latency(engine, "嗨", clock) == pytest.approx(0.7)


def test_the_loaded_side_really_is_loaded_with_memory_state_and_journal():
    clock = FakeClock()
    llm = SlowLLM(clock)
    first_sentence_latency(build_engine(llm, persona="p", loaded=True), "上次聊的潛水證照後來怎麼樣了", clock)
    system = llm.systems[0]
    for part in ("【長期記憶", "【最近的日誌】", "【你現在的狀態】", "【時間資訊(系統提供)】", "【可能相關的記憶】"):
        assert part in system, part


def test_the_plain_side_has_none_of_it():
    clock = FakeClock()
    llm = SlowLLM(clock)
    first_sentence_latency(build_engine(llm, persona="p", loaded=False), "上次聊的潛水證照後來怎麼樣了", clock)
    system = llm.systems[0]
    assert not any(part in system for part in ("【長期記憶", "【最近的日誌】", "【你現在的狀態】", "【可能相關的記憶】"))


def test_measuring_runs_each_side_the_same_number_of_times():
    clock = FakeClock()
    results = measure(lambda: SlowLLM(clock, per_char=0.0001), persona="p", runs=3, clock=clock)
    assert len(results["off"]) == len(results["on"]) == 6      # 3 runs x 2 messages
    assert min(results["on"]) > max(results["off"]) - 1e-9     # the longer prompt costs a little more here


def test_a_small_difference_is_within_the_budget():
    report = summarize([1.0, 1.1, 1.0], [1.2, 1.3, 1.2])
    assert report.within_budget and report.difference == pytest.approx(0.2, abs=1e-9)
    assert "在預算內" in report.text()


def test_a_difference_over_the_budget_is_reported_with_the_numbers_and_no_decision_is_made_for_the_person():
    report = summarize([1.0, 1.0, 1.0], [1.0 + BUDGET_S + 0.3] * 3)
    assert not report.within_budget
    text = report.text()
    assert "超過" in text and f"{BUDGET_S:.1f}" in text and "調降" in text and "貼回" in text


def test_the_median_is_used_so_one_slow_call_does_not_decide_the_verdict():
    report = summarize([1.0, 1.0, 1.0, 1.0, 1.0], [1.1, 1.1, 1.1, 1.1, 9.0])
    assert report.within_budget


def test_exactly_at_the_budget_is_within_it():
    assert summarize([1.0], [1.0 + BUDGET_S]).within_budget
