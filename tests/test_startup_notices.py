"""Things the person should hear once per run (a feature that could not start) travel on the
engine's own event stream, at the head of the first turn — so they reach the chat panel by the
same path as everything else, with no extra endpoint."""
from companion.engine import Done, Notice, Sentence, TurnEngine
from companion.history import InMemoryHistory


class FakeLLM:
    def stream(self, system, messages):
        yield "好啊。"


def engine(notices):
    return TurnEngine(FakeLLM(), persona="p", history_store=InMemoryHistory(), startup_notices=notices)


def test_each_startup_notice_comes_out_once_before_the_first_reply():
    e = engine(["拍照功能已啟用,但缺少金鑰", "上網查資料先關閉"])
    assert list(e.send("嗨")) == [
        Notice("feature", "拍照功能已啟用,但缺少金鑰"), Notice("feature", "上網查資料先關閉"),
        Sentence("好啊。", "neutral"), Done()]


def test_the_second_turn_does_not_repeat_them():
    e = engine(["缺金鑰"])
    list(e.send("嗨"))
    assert list(e.send("再來")) == [Sentence("好啊。", "neutral"), Done()]


def test_an_engine_without_notices_behaves_exactly_as_before():
    assert list(engine(None).send("嗨")) == [Sentence("好啊。", "neutral"), Done()]
    assert list(engine(()).send("嗨")) == [Sentence("好啊。", "neutral"), Done()]


def test_a_notice_is_not_lost_when_the_first_turn_fails():
    from companion.errors import LLMError

    class FailingOnce:
        calls = 0

        def stream(self, system, messages):
            FailingOnce.calls += 1
            if FailingOnce.calls == 1:
                raise LLMError("timeout", "slow")
            yield "好啊。"

    e = TurnEngine(FailingOnce(), persona="p", history_store=InMemoryHistory(), startup_notices=["缺金鑰"])
    first = list(e.send("嗨"))
    assert Notice("feature", "缺金鑰") in first        # it was shown, even though the reply then failed
    assert Notice("feature", "缺金鑰") not in list(e.send("嗨"))   # and is not shown again on the retry
