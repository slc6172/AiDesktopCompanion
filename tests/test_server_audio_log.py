"""With stt.debug_log on, every voice clip gets an "[audio]" line next to its "[stt]" line, saying how
loud it was and whether the character was talking when it started (sent by the page in X-Clip-Meta).
That pair of lines is what lets the echo problem be measured instead of guessed at."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from companion.server import create_app

META = "peak=0.134;during_speech=1;started_speaking=1;boost=2.5"


class HeardNothing:
    def transcribe(self, data, mime):
        return ""


class RecordingLLM:
    def stream(self, system, messages):
        yield "[happy]好。"


def make_client(tmp_path, monkeypatch, debug_log):
    monkeypatch.setenv("COMPANION_FAKE", "1")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"stt": {"debug_log": debug_log}}), encoding="utf-8")
    monkeypatch.setattr("companion.config.config_path", lambda: path)
    return TestClient(create_app(llm=RecordingLLM(), stt=HeardNothing(), persona="test persona"))


def post(client, meta=META):
    headers = {"Content-Type": "audio/webm"}
    if meta is not None:
        headers["X-Clip-Meta"] = meta
    return client.post("/chat/audio", content=b"\x00" * 4321, headers=headers)


def audio_lines(capsys, caplog):
    out = [l for l in capsys.readouterr().out.splitlines() if l.startswith("[audio]")]
    logged = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[audio]")]
    return out, logged


def test_a_clip_is_logged_with_its_size_and_what_the_page_measured(tmp_path, monkeypatch, capsys, caplog):
    client = make_client(tmp_path, monkeypatch, debug_log=True)
    with caplog.at_level(logging.INFO):
        post(client)
    out, logged = audio_lines(capsys, caplog)
    assert len(out) == 1 and len(logged) == 1                       # console AND the log file
    for line in (out[0], logged[0]):
        assert "4321 bytes" in line and META in line


def test_nothing_is_logged_when_the_debug_log_is_off(tmp_path, monkeypatch, capsys, caplog):
    client = make_client(tmp_path, monkeypatch, debug_log=False)
    with caplog.at_level(logging.INFO):
        post(client)
    assert audio_lines(capsys, caplog) == ([], [])


def test_a_clip_without_the_header_is_still_logged_with_unknown_details(tmp_path, monkeypatch, capsys, caplog):
    client = make_client(tmp_path, monkeypatch, debug_log=True)
    with caplog.at_level(logging.INFO):
        post(client, meta=None)
    out, _ = audio_lines(capsys, caplog)
    assert len(out) == 1 and "4321 bytes" in out[0] and "?" in out[0]


@pytest.mark.parametrize("hostile", [
    "peak=0.1] | [stt] kept | 99 bytes | '我說了這句話'",        # pretending to be a recognition result
    "peak=0.1\x1b[31m red",                                      # terminal control characters
    "peak=0.1;" + "x" * 5000,                                    # absurd length
    "峰值=0.1;during_speech=1",                                  # not what the page sends
], ids=["forged-stt-line", "terminal-control-chars", "absurdly-long", "not-ascii"])
def test_the_header_can_never_forge_or_flood_the_log(tmp_path, monkeypatch, capsys, caplog, hostile):
    client = make_client(tmp_path, monkeypatch, debug_log=True)
    with caplog.at_level(logging.INFO):
        post(client, meta=hostile.encode("utf-8"))   # raw bytes: whatever a client cares to send
    out, logged = audio_lines(capsys, caplog)
    assert len(out) == 1 and len(out[0]) < 260
    assert out[0].count("[") == 1 and "[stt]" not in out[0] and "\x1b" not in out[0]
    assert out[0].count("|") == 1               # only our own separator between the size and what the page measured
    assert not any(l.startswith("[stt]") for l in capsys.readouterr().out.splitlines())


def test_the_header_never_changes_what_happens_to_the_clip(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, debug_log=True)
    with_header = post(client)
    without_header = post(client, meta=None)
    assert with_header.text == without_header.text and with_header.status_code == 200
