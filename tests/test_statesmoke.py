"""The compliance check for the state tags (spec Part 12, ticket 79). The real run needs Gemini and is
done by the person on their own machine; what is tested here is everything around it: the scenarios,
the way a run is judged, and the verdict — using stand-in models that behave perfectly, never, or too eagerly."""
import pytest

from companion.statesmoke import (OracleLLM, SCENARIOS, evaluate, run_all, run_scenario)


class SilentLLM:
    def stream(self, system, messages):
        yield "嗯,好啊。"


class EagerLLM:
    """Declares a move in every single reply, whatever was said."""

    def stream(self, system, messages):
        yield "[地點:別的地方]好啊。"


def test_there_are_twenty_scenarios_half_that_should_declare_and_half_that_should_not():
    assert len(SCENARIOS) == 20
    assert sum(1 for s in SCENARIOS if s.expect) == 10 and sum(1 for s in SCENARIOS if not s.expect) == 10
    assert len({s.message for s in SCENARIOS}) == 20
    assert {s.expect for s in SCENARIOS if s.expect} <= {"location", "status", "items"}
    assert {"location", "status", "items"} == {s.expect for s in SCENARIOS if s.expect}   # every kind is exercised


def test_a_model_that_does_the_right_thing_every_time_passes():
    report = evaluate(run_all(OracleLLM(), persona="p"))
    assert (report.declared_ok, report.declared_total) == (10, 10)
    assert (report.quiet_ok, report.quiet_total) == (10, 10)
    assert report.passed


def test_a_model_that_never_declares_anything_fails_on_declaring_but_is_perfectly_quiet():
    report = evaluate(run_all(SilentLLM(), persona="p"))
    assert (report.declared_ok, report.quiet_ok) == (0, 10)
    assert not report.passed


def test_a_model_that_declares_everywhere_fails_on_being_quiet():
    report = evaluate(run_all(EagerLLM(), persona="p"))
    assert report.quiet_ok == 0 and not report.passed


def test_each_side_must_reach_ninety_percent_on_its_own():
    perfect = run_all(OracleLLM(), persona="p")
    one_miss_each_side = OracleLLM(forget={perfect[0].scenario.message}, overreach={perfect[-1].scenario.message})
    report = evaluate(run_all(one_miss_each_side, persona="p"))
    assert (report.declared_ok, report.quiet_ok) == (9, 9) and report.passed          # 90% exactly is enough

    two_forgotten = OracleLLM(forget={perfect[0].scenario.message, perfect[1].scenario.message})
    assert not evaluate(run_all(two_forgotten, persona="p")).passed                    # 80% on one side is not


def test_a_failing_report_says_not_to_ship_and_offers_the_fallbacks_without_choosing_one():
    text = evaluate(run_all(SilentLLM(), persona="p")).text()
    assert "未達標" in text and "不要" in text and "備援" in text


def test_a_passing_report_lists_every_scenario_with_a_mark():
    text = evaluate(run_all(OracleLLM(), persona="p")).text()
    assert text.count("✓") >= 20 and "✗" not in text


def test_a_scenario_is_judged_by_what_actually_changed_in_her_state_not_by_the_wording():
    scenario = next(s for s in SCENARIOS if s.expect == "items" and s.seed.get("items"))
    result = run_scenario(OracleLLM(), scenario, persona="p")
    assert "items" in result.changed and result.ok
    quiet = next(s for s in SCENARIOS if not s.expect)
    assert run_scenario(EagerLLM(), quiet, persona="p").changed == {"location"}


def test_changing_the_wrong_thing_does_not_count_as_declaring_the_right_one():
    wants_status = next(s for s in SCENARIOS if s.expect == "status")
    result = run_scenario(EagerLLM(), wants_status, persona="p")     # she moved instead of getting tipsy
    assert result.changed == {"location"} and not result.ok


# ---- seeing what she actually wrote (the real run's first failure had no way to tell a missing tag from a wrong one) ----

def test_a_failed_scenario_shows_exactly_what_she_wrote_tags_included():
    wants_status = next(s for s in SCENARIOS if s.expect == "status")
    result = run_scenario(EagerLLM(), wants_status, persona="p")        # writes [地點:別的地方] instead
    assert result.raw == "[地點:別的地方]好啊。"
    text = evaluate([result]).text()
    assert "[地點:別的地方]好啊。" in text and "✗" in text


def test_the_raw_output_is_kept_for_scenarios_that_passed_too():
    scenario = next(s for s in SCENARIOS if s.expect == "location")
    assert run_scenario(OracleLLM(), scenario, persona="p").raw.startswith("[地點:")


def test_the_rules_tell_her_what_counts_as_a_change_with_a_case_for_each_kind():
    from companion.statebox import TAG_RULES

    for needed in ("[地點:", "[狀態:", "[得到:", "[失去:", "已經發生", "到了", "回到", "收到", "弄丟", "最後", "假設"):
        assert needed in TAG_RULES, needed


def test_a_scenario_where_she_says_nothing_shows_what_she_wrote_even_if_it_passed():
    quiet = next(s for s in SCENARIOS if not s.expect)

    class OnlyTags:
        def stream(self, system, messages):
            yield "[neutral][心情:平靜]"

    text = evaluate([run_scenario(OnlyTags(), quiet, persona="p")]).text()
    assert "✓" in text and "[neutral][心情:平靜]" in text


# ---- when the service itself fails (a busy free tier answers 429 or a gateway error) ---------------------------------

from companion.errors import LLMError


class Flaky(OracleLLM):
    """The perfect stand-in, except that chosen calls fail: `fail` maps a message to how many times in a row."""

    def __init__(self, fail=None, partial=False):
        super().__init__()
        self.fail, self.partial, self.calls = dict(fail or {}), partial, []

    def stream(self, system, messages):
        message = messages[-1]["content"]
        self.calls.append(message)
        if self.fail.get(message, 0) > 0:
            self.fail[message] -= 1
            if self.partial:
                yield "[neutral]我想想"      # some of it arrives, then the connection drops
            raise LLMError("rate_limit", "429")
        yield from super().stream(system, messages)


class Sleeper:
    def __init__(self):
        self.naps = []

    def __call__(self, seconds):
        self.naps.append(seconds)


def test_a_failed_call_is_not_an_answer_so_it_is_not_scored_as_one():
    quiet = next(s for s in SCENARIOS if not s.expect)
    result = run_scenario(Flaky({quiet.message: 99}), quiet, persona="p")
    assert result.error == "rate_limit" and not result.valid


def test_a_call_that_breaks_off_half_way_is_a_failure_too():
    scenario = SCENARIOS[0]
    result = run_scenario(Flaky({scenario.message: 99}, partial=True), scenario, persona="p")
    assert result.error == "rate_limit"


def test_a_failed_scenario_is_tried_again_after_a_pause_that_grows_and_then_counts_normally():
    scenario = SCENARIOS[0]
    sleeper = Sleeper()
    results = run_all(Flaky({scenario.message: 2}), persona="p", retries=3, backoff_s=10, pause_s=0, sleep=sleeper)
    assert results[0].valid and results[0].ok
    assert sleeper.naps == [10, 20]


def test_a_scenario_that_keeps_failing_is_left_out_of_the_score_and_the_verdict_says_it_cannot_be_given():
    quiet = next(s for s in SCENARIOS if not s.expect)
    results = run_all(Flaky({quiet.message: 99}), persona="p", retries=1, backoff_s=0, pause_s=0, sleep=Sleeper())
    report = evaluate(results)
    assert (report.quiet_ok, report.quiet_total) == (9, 9)             # not 10/10: that one proves nothing
    assert report.invalid == 1 and not report.passed
    text = report.text()
    assert "API 錯誤" in text and "rate_limit" in text and "重跑" in text and "達標" not in text.replace("未達標", "")


def test_a_scenario_that_should_have_declared_but_hit_an_error_is_not_counted_as_a_miss():
    wants = SCENARIOS[0]
    report = evaluate(run_all(Flaky({wants.message: 99}), persona="p", retries=0, backoff_s=0, pause_s=0, sleep=Sleeper()))
    assert (report.declared_ok, report.declared_total) == (9, 9)


def test_the_run_is_paced_so_a_free_plan_is_not_hit_with_twenty_calls_at_once():
    sleeper = Sleeper()
    run_all(OracleLLM(), persona="p", retries=0, backoff_s=0, pause_s=4, sleep=sleeper)
    assert sleeper.naps.count(4) == len(SCENARIOS) - 1


def test_with_no_failures_nothing_changes_the_score_is_as_before():
    report = evaluate(run_all(OracleLLM(), persona="p", pause_s=0, sleep=Sleeper()))
    assert report.invalid == 0 and report.passed
