import time


class ScriptedLLM:
    """Offline stand-in so the page can be tried without an API key."""

    def stream(self, system, messages):
        last = messages[-1]["content"]
        for chunk in ["[happy]", "嗨!我是小星。", "[surprised]", f"咦?你剛剛說「{last}」?", "[happy]", "今天想聊什麼呢?"]:
            time.sleep(0.25)
            yield chunk

    def generate_structured(self, system, messages, schema):
        """The memory fold's call. The offline demo has no model to fold with, so there is no structured
        answer: the fold treats it as unusable and tries again on a later turn (this only honours the
        two-method LLM interface the real models have)."""
        return None
