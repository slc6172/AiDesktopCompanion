"""Harness server: runs a project's FastAPI app offline (COMPANION_FAKE=1) on PORT.

PROJ must contain the `companion/` python package (our project root, or the Part-15 `.../companion` dir).
STT answers are controllable WITHOUT touching production code: if COMPANION_STT_MODE_FILE is set, each
transcription reads that file: `text` (default, canned sentence), `empty` (STT hears nothing -> stt_empty),
or `say:<words>` (a specific transcript).
"""
import os
import sys

proj = os.environ["PROJ"]
sys.path.insert(0, proj)
os.chdir(proj)
os.environ.setdefault("COMPANION_FAKE", "1")
# A fresh clone has no persona.md (it is the user's own file); the example is enough for the harness.
os.environ.setdefault("COMPANION_PERSONA", "persona.example.md")

import uvicorn  # noqa: E402

from companion.fake_stt import ScriptedSTT  # noqa: E402
from companion.server import create_app  # noqa: E402


class ControllableSTT(ScriptedSTT):
    def __init__(self, mode_file):
        self.mode_file = mode_file

    def transcribe(self, data, mime_type):
        try:
            mode = open(self.mode_file, encoding="utf-8").read().strip() or "text"
        except OSError:
            mode = "text"
        if mode == "empty":
            return ""
        if mode.startswith("say:"):
            return mode[4:]
        return super().transcribe(data, mime_type)


import companion.config as _cfg  # noqa: E402

if os.environ.get("COMPANION_DEBUG_LOG") == "1":   # harness-side switch for stt.debug_log ([audio]/[stt] lines)
    _orig_stt_cfg = _cfg.resolve_stt_config        # create_app imports this inside the function, at call time
    _cfg.resolve_stt_config = lambda: {**_orig_stt_cfg(), "debug_log": True}

mode_file = os.environ.get("COMPANION_STT_MODE_FILE")
app = create_app(stt=ControllableSTT(mode_file)) if mode_file else create_app()
uvicorn.run(app, host="127.0.0.1", port=int(os.environ["PORT"]), log_level="warning")
