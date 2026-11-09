class ScriptedSTT:
    """Offline stand-in so the voice-input path can be tried without a Groq key or network:
    always returns the same canned transcript, as if the user had said this out loud."""

    def transcribe(self, data, mime_type):
        return "你好呀,今天過得好嗎?"
