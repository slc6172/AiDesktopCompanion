class LLMError(Exception):
    """Raised by an LLM adapter for failures the engine knows how to explain.

    kind: "rate_limit" | "timeout" | "unavailable"
    """

    def __init__(self, kind, message=""):
        super().__init__(message or kind)
        self.kind = kind


class TTSUnavailable(Exception):
    """Raised by a speech adapter when the engine itself cannot be reached or is failing on
    its side (server not running, timed out, 5xx) — as opposed to one sentence simply having
    nothing to say (an empty result) or a configuration mistake (a 4xx). TurnEngine hands the
    sentence to the fallback engine for this, when there is one."""
