import base64
import json
import logging
import os
import queue
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .history import InMemoryHistory, SqliteHistory
from .tinyfish_adapter import TinyFishFetch, TinyFishSearch
from .paths import project_dir, user_dir
from .apikey import MissingApiKey
from .engine import (EMOTIONS, Audio, Done, Failure, Notice, OutfitChange, Photo, Sentence, Transcript, TurnEngine,
                     UserImage)

class NoCacheStaticFiles(StaticFiles):
    """StaticFiles that makes the browser re-check (ETag) on every load, so a re-encoded clip is
    picked up on the next start instead of being served from Electron's disk cache. (Found in real
    use: replacing a .webm kept playing the old one. "no-cache" does not mean "don't store" — it
    means "ask first": an unchanged file still costs only a 304. Range requests are untouched, so
    video seeking works as before.)"""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


log = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # a request to Gemini may carry at most 20 MB in total
MAX_IMAGE_BYTES = MAX_AUDIO_BYTES  # same request-size ceiling, just a more readable name at the call site
MAX_MESSAGE_CHARS = 8000  # one typed message; far above anything typed, far below "forward megabytes to Gemini"
MAX_IMAGE_BASE64_CHARS = MAX_IMAGE_BYTES * 4 // 3 + 4  # the base64 text of a maximal image: refused before it is decoded
MAX_PROACTIVE_LISTENERS = 4  # the page opens one; a few spare for a reconnect that overlaps its dying predecessor
PROACTIVE_KEEPALIVE_S = 15  # how often an idle push stream writes a comment line, so a closed connection is noticed
# The only names this server answers to. It listens on 127.0.0.1 for the pet window alone; a request that
# names any other host got here by DNS rebinding (a web page making its own domain point at this machine).
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})


def host_of(host_header):
    """The host part of a Host header value ("127.0.0.1:8000" -> "127.0.0.1"); "" when it cannot be read."""
    try:
        return (urlsplit("//" + (host_header or "")).hostname or "").lower()
    except ValueError:
        return ""


def origin_is_local(origin):
    """True for an Origin header value that names this machine ("http://127.0.0.1:8000")."""
    try:
        return (urlsplit(origin).hostname or "").lower() in LOCAL_HOSTS
    except ValueError:
        return False


class ChatRequest(BaseModel):
    message: str = Field(max_length=MAX_MESSAGE_CHARS)
    image_data: str | None = Field(default=None, max_length=MAX_IMAGE_BASE64_CHARS)  # base64-encoded, no data: URL prefix
    image_mime: str | None = None


def build_llm():
    if os.environ.get("COMPANION_FAKE") == "1":
        from .fake_llm import ScriptedLLM

        return ScriptedLLM()
    from .gemini_llm import GeminiLLM

    return GeminiLLM()


def build_store():
    path = os.environ.get("COMPANION_DB")
    if path is None and os.environ.get("COMPANION_FAKE") == "1":
        return InMemoryHistory()  # offline demo should not write your real history
    path = Path(path) if path else user_dir() / "data" / "history.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteHistory(path)


def build_state_store():
    """Her own state (outfit, place, ...) lives in the same database file as the history."""
    from .config import resolve_companion_state_config
    from .state import InMemoryState, SqliteState

    place = resolve_companion_state_config()["default_location"]
    path = os.environ.get("COMPANION_DB")
    if path is None and os.environ.get("COMPANION_FAKE") == "1":
        return InMemoryState(default_location=place)
    path = Path(path) if path else user_dir() / "data" / "history.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteState(path, default_location=place)


def build_tts():
    """(primary, fallback) speech engines; either may be None.

    Settings come from config.resolve_tts_config() — config.json (next to persona.md) with
    environment variables as an override on top of it, same precedence apikey.py uses for API
    keys. COMPANION_FAKE=1 still short-circuits everything to the offline beep double, same as
    every other adapter this app builds.
    """
    from .config import resolve_engine, resolve_tts_config

    settings = resolve_tts_config()
    if not settings["enabled"]:
        return None, None  # text only: nothing below (engine, voices, keys) is even looked at
    if os.environ.get("COMPANION_FAKE") == "1":
        from .fake_tts import BeepTTS

        return BeepTTS(), None

    engine = resolve_engine(settings["engine"], settings["primetts_url"])
    if engine == "off":
        return None, None

    from .edge_tts_adapter import EdgeTTS

    edge = EdgeTTS(voice=settings["edge_voice"], rate=settings["edge_rate"],
                   volume=settings["edge_volume"], pitch=settings["edge_pitch"])
    if engine == "edge":
        return edge, None

    if engine == "fish":
        from .config import resolve_fish_config
        from .fish_adapter import FishTTS

        fish = resolve_fish_config()
        if fish["model"] not in KNOWN_FISH_MODELS:
            # Fish answers a request whose model name it does not recognise with its PAID default model.
            # The name is still used (a model released after this was written must keep working), but a
            # typo for the free model should not turn into a bill without anyone noticing.
            log.warning("Fish 模型 %r 不是已知的型號(%s);Fish 對不認得的型號會改用付費的 s2.1-pro。"
                        "想用免費的請設成 s2.1-pro-free。", fish["model"], "、".join(KNOWN_FISH_MODELS))
        try:
            primary = FishTTS(model=fish["model"], reference_id=fish["reference_id"],
                              response_format=fish["format"], timeout=fish["timeout_s"],
                              emotion_tags=fish["emotion_tags"])
        except MissingApiKey:
            # Chosen but not usable: the person is told once (features.py); meanwhile she speaks with edge.
            log.warning("TTS 引擎設為 fish,但找不到 Fish API 金鑰;改用 edge-tts。")
            return edge, None
        return primary, (edge if settings["fallback"] else None)

    from .primetts_adapter import PrimeTTS

    primary = PrimeTTS(base_url=settings["primetts_url"], model=settings["primetts_model"],
                       voice=settings["primetts_voice"], response_format=settings["primetts_format"],
                       api_key=settings["primetts_api_key"], timeout=settings["primetts_timeout_s"])
    return primary, (edge if settings["fallback"] else None)


def build_stt():
    if os.environ.get("COMPANION_FAKE") == "1":
        from .fake_stt import ScriptedSTT

        return ScriptedSTT()
    from .config import resolve_stt_config
    from .groq_stt import GroqSTT

    return GroqSTT(settings=resolve_stt_config())


_PHOTO_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*")  # what photos.py names its files; nothing that could climb out of the folder
_META_ALLOWED = re.compile(r"[^A-Za-z0-9_=.;:,-]")


def clip_meta(raw):
    """The page's measurements of one clip, made safe to write into the log: only the characters the
    page ever sends, and short — so a header can neither forge another log line nor flood the file."""
    if not raw:
        return "meta=?"
    return _META_ALLOWED.sub("", raw)[:160] or "meta=?"


def event_to_dict(event):
    if isinstance(event, Transcript):
        return {"type": "transcript", "text": event.text}
    if isinstance(event, Sentence):
        return {"type": "sentence", "text": event.text, "emotion": event.emotion}
    if isinstance(event, Audio):
        return {
            "type": "audio",
            "index": event.index,
            "emotion": event.emotion,
            "mime": event.mime_type,
            "data": base64.b64encode(event.data).decode("ascii"),
        }
    if isinstance(event, Notice):
        return {"type": "notice", "kind": event.kind, "message": event.message}
    if isinstance(event, OutfitChange):
        return {"type": "outfit", "name": event.name, "clips": event.clips}
    if isinstance(event, Photo):
        return {"type": "photo", "file": event.file, "url": event.url}
    if isinstance(event, Failure):
        return {"type": "error", "kind": event.kind, "message": event.message}
    if isinstance(event, Done):
        return {"type": "done", "first_audio_ms": event.first_audio_ms}
    raise TypeError(event)


def find_fillers(fillers_dir):
    names = [
        path.name
        for path in sorted(fillers_dir.iterdir())
        if path.suffix.lower() in (".mp3", ".wav", ".ogg")
    ] if fillers_dir.exists() else []
    return [f"/fillers/{name}" for name in names]


KNOWN_FISH_MODELS = ("s1", "s2-pro", "s2.1-pro", "s2.1-pro-free")  # the `model` header values Fish documents

# Whisper sometimes emits generic audio-caption words (e.g. "Music") for residual playback or non-speech
# audio. In continuous mode, discard only a small allowlist of such captions; ordinary Chinese/English
# transcripts are left untouched. (The invented phrases that DO depend on the detected language, like
# "Thank you.", are handled by the speech adapter: stt.ignore_phrases, see groq_stt.py.)
_CAPTIONS_ANY_LENGTH = {"thank you for watching", "thanks for watching", "please subscribe", "字幕由 amara.org 社群提供"}
_CAPTIONS_SHORT_ONLY = {"music", "applause", "laughter", "silence", "background noise", "subscribe"}
_SHORT_CLIP_MS = 2500


def is_likely_non_speech_transcript(text, voice_mode, duration_ms=None):
    if (voice_mode or "").strip().lower() != "continuous":
        return False
    normalized = " ".join((text or "").casefold().strip().rstrip(".!?,，。！？").split())
    if normalized in _CAPTIONS_ANY_LENGTH:
        return True
    # A single generic audio caption is suspicious only for a short continuous-mode segment.
    return normalized in _CAPTIONS_SHORT_ONLY and (duration_ms is None or duration_ms <= _SHORT_CLIP_MS)


def create_app(llm=None, persona=None, tts=None, store=None, stt=None, tts_fallback=None, state_store=None, search=None,
               image=None):
    if persona is None:
        path = user_dir() / os.environ.get("COMPANION_PERSONA", "persona.md")
        if not path.exists():
            raise FileNotFoundError(
                f"找不到人設檔:{path}\n請把專案資料夾裡的 persona.example.md 複製一份,命名為 persona.md,"
                "再依照裡面的說明改成你想要的角色。")
        persona = path.read_text(encoding="utf-8")
    from .config import (resolve_companion_state_config, resolve_image_config, resolve_memory_config,
                         resolve_tinyfish_config)
    from .features import resolve_features

    features = resolve_features()
    if state_store is None:
        # A caller that supplied its own history store (tests, demos) must not have us write her
        # state into the real database next to the app.
        from .state import InMemoryState

        state_store = InMemoryState(default_location=resolve_companion_state_config()["default_location"]) \
            if store is not None else build_state_store()
    from .outfits import Wardrobe

    web = resolve_tinyfish_config()
    page_reader = None
    if not web["enabled"]:
        search = None  # switched off: nothing is searched and she is told nothing about searching
    elif search is None and features.tinyfish:
        search = TinyFishSearch(location=web["location"], language=web["language"])
    if search is not None and features.tinyfish:
        try:
            page_reader = TinyFishFetch()
        except MissingApiKey:  # (the key check in features.py already passed; this is only a safety net)
            page_reader = None

    wardrobe = Wardrobe(user_dir() / "clips", state_store)
    outfit_warnings = wardrobe.scan().warnings
    for warning in outfit_warnings:
        log.warning(warning)
    memory_on = features.memory and os.environ.get("COMPANION_FAKE") != "1"
    if tts is None:
        tts, tts_fallback = build_tts()
    # Proactive speaking pushes events with no HTTP request in flight to ride along on, so they
    # go on a queue that /chat/proactive's long-lived stream (below) drains as they arrive.
    # One app, one such queue: this is the same single-user assumption the rest of the app
    # already makes (one engine, one history).
    proactive_events = queue.Queue()
    listener_lock = threading.Lock()
    listeners = {"open": 0}  # how many /chat/proactive streams are open
    # Photos: built only when switched on and usable — so a program without them never loads Pillow, and she
    # is told nothing about them (the studio supplies her tag help; no studio, no help).
    photo_settings = resolve_image_config()
    studio, photo_warnings = None, []
    if photo_settings["enabled"]:
        if image is None and features.image:
            from .apikey import get_api_key
            from .cloudflare_adapter import CloudflareImage

            image = CloudflareImage(get_api_key("cloudflare"), photo_settings["account_id"],
                                    model=photo_settings["model"], timeout=photo_settings["timeout_s"])
        if image is not None:
            import time

            from .photos import PhotoStudio, startup_warnings

            studio = PhotoStudio(image, photo_settings, wardrobe, push=proactive_events.put,
                                 photos_dir=user_dir() / "data" / "photos", wall_clock=time.time,
                                 state=state_store)
            photo_warnings = startup_warnings(photo_settings, wardrobe)
            for warning in photo_warnings:
                log.warning(warning)
    from .config import resolve_proactive_config, resolve_time_config

    from .config import resolve_stt_config
    from .debuglog import default_log

    debug_audio = resolve_stt_config()["debug_log"]
    proactive_settings = resolve_proactive_config()
    engine = TurnEngine(llm or build_llm(), persona=persona, tts=tts, tts_fallback=tts_fallback,
                        history_store=store if store is not None else build_store(),
                        summarize=memory_on,
                        time_config=resolve_time_config(),
                        affection_grace_s=float(os.environ.get("COMPANION_AFFECTION_GRACE_HOURS", "24")) * 3600,
                        affection_half_life_s=float(os.environ.get("COMPANION_AFFECTION_HALF_LIFE_DAYS", "14")) * 86400,
                        startup_notices=list(features.notices) + outfit_warnings + photo_warnings,
                        wardrobe=wardrobe,
                        character_state=state_store, state_settings=resolve_companion_state_config(),
                        memory_settings=resolve_memory_config(),
                        search=search, search_settings=web, fetch=page_reader,
                        tag_handlers=studio.handlers() if studio else None,
                        prompt_extras=[studio.prompt_help] if studio else None,
                        on_proactive=proactive_events.put,
                        proactive_idle_range_s=(proactive_settings["min_minutes"] * 60,
                                                proactive_settings["max_minutes"] * 60))
    if proactive_settings["enabled"]:
        engine.set_proactive(True)
    # Listening: switched off (or no key, see features.py) means no recogniser at all. A recogniser
    # handed in by the caller is used unless the person switched listening off.
    if not resolve_stt_config()["enabled"]:
        stt = None
    elif stt is None:
        stt = build_stt() if features.stt else None
    app = FastAPI()

    @app.middleware("http")
    async def only_this_machine(request: Request, call_next):
        """Refuse a request that is not plainly from the pet window: a Host other than this machine (DNS
        rebinding) or an Origin other than this machine (another web page). A request with no Origin — the
        window's own page loads, curl — passes; the Host rule already covers it."""
        if host_of(request.headers.get("host")) not in LOCAL_HOSTS:
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and not origin_is_local(origin):
            return JSONResponse({"error": "forbidden origin"}, status_code=403)
        return await call_next(request)

    @app.get("/history")
    def history():
        shown = engine.history()
        folder = user_dir() / "data" / "photos"
        for item in shown:
            if "photo" in item:  # the saved reply only knows the file's name; whether it is still there is for the disk to say
                found = next(iter(sorted(folder.glob(item["photo"]["stem"] + ".*"))), None)
                item["photo"] = ({"file": found.name, "url": f"/photos/{found.name}", "exists": True} if found
                                 else {"file": None, "url": None, "exists": False})
        return shown

    @app.get("/chat/proactive")
    def chat_proactive():
        """A long-lived stream the page opens once: whatever the character says on its own
        initiative (see TurnEngine.set_proactive) arrives here, in the same event shape as a
        normal reply. Harmless to leave open when proactive speaking is off — nothing is ever
        put on the queue, so this just waits without sending anything but a comment line now and then.

        The comment line is what lets a connection that has gone away be noticed: the write fails, the
        generator ends and its worker thread is freed (a stream that only ever waited would hold one
        thread of the server's small pool for good, and enough of them would stop every other request)."""
        with listener_lock:
            if listeners["open"] >= MAX_PROACTIVE_LISTENERS:
                return JSONResponse({"error": "too many open streams"}, status_code=429)
            listeners["open"] += 1

        def events():
            try:
                while True:
                    try:
                        event = proactive_events.get(timeout=PROACTIVE_KEEPALIVE_S)
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    yield "data: " + json.dumps(event_to_dict(event), ensure_ascii=False) + "\n\n"
            finally:
                with listener_lock:
                    listeners["open"] -= 1

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/avatar")
    def avatar():
        """What the page draws: the outfit she is wearing and ONLY that outfit's clips (state -> URL)."""
        scan = wardrobe.scan()
        worn = wardrobe.current(scan)
        return {
            "emotions": list(EMOTIONS),
            "outfit": worn,
            "outfits": list(scan.outfits),
            "clips": scan.outfits.get(worn, {}),
            "fillers": find_fillers(user_dir() / "fillers"),
        }

    @app.get("/config")
    def config():
        """Settings the browser can't read from the environment itself."""
        from .config import resolve_ui_config

        ui = resolve_ui_config()
        return {
            "vadSilenceMs": int(os.environ.get("COMPANION_VAD_SILENCE_MS", 700)),
            "vadMinMs": int(os.environ.get("COMPANION_VAD_MIN_MS", 500)),
            "ui": {"autoListen": ui["auto_listen"], "hitWidthRatio": ui["hit_width_ratio"],
                   "speakingBoost": ui["speaking_boost"], "duckLevel": ui["duck_level"]},
            "stt": {"enabled": stt is not None},   # the page hides the microphone controls when false
        }

    for name in ("clips", "fillers"):  # user content, editable next to the app
        (user_dir() / name).mkdir(exist_ok=True)
        app.mount(f"/{name}", NoCacheStaticFiles(directory=user_dir() / name), name=name)
    @app.get("/photos/{name}")
    def photo_file(name: str):
        """One of her photos, by file name only. The folder need not exist (it is made when the first picture is
        saved), and a file the person deleted is simply not found — never an error."""
        path = user_dir() / "data" / "photos" / name
        if not _PHOTO_NAME.fullmatch(name) or not path.is_file():
            return JSONResponse({"error": "沒有這張照片"}, status_code=404)
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    # The app's own scripts get the same treatment: after an upgrade the window must not keep running
    # yesterday's JavaScript out of its cache.
    app.mount("/static", NoCacheStaticFiles(directory=project_dir() / "static"), name="static")

    @app.get("/")
    def index():
        return FileResponse(project_dir() / "static" / "index.html", headers={"Cache-Control": "no-cache"})

    def stream_turn(user_input, transcript=None, image=None):
        def events():
            if transcript is not None:
                # Known before the reply even starts (the recording was already transcribed),
                # so it goes out first — the user's own bubble must appear before the
                # character's reply, not after it (see static/index.html's `send()`).
                yield "data: " + json.dumps(event_to_dict(Transcript(transcript)), ensure_ascii=False) + "\n\n"
            try:
                for event in engine.send(user_input, image=image):
                    if isinstance(event, Done) and event.first_audio_ms is not None:
                        print(f"[latency] first audio ready in {event.first_audio_ms:.0f} ms")
                    yield "data: " + json.dumps(event_to_dict(event), ensure_ascii=False) + "\n\n"
            except Exception:  # anything the engine did not anticipate: never crash the stream
                log.exception("unexpected error while handling a chat turn")
                payload = {"type": "error", "kind": "unknown", "message": "出了點狀況,請再試一次。"}
                yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    def stream_failure(kind, message):
        """A turn that never gets to `TurnEngine` at all (nothing to transcribe): still an SSE
        stream, so the browser's one code path for `/chat` and `/chat/audio` handles it exactly
        like any other `error` event — no separate JSON-error branch needed on that side."""
        def events():
            yield "data: " + json.dumps(event_to_dict(Failure(kind, message)), ensure_ascii=False) + "\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/chat")
    def chat(req: ChatRequest):
        image = None
        if req.image_data:
            try:
                data = base64.b64decode(req.image_data, validate=True)
            except Exception:
                return JSONResponse({"error": "圖片格式錯誤"}, status_code=400)
            if len(data) > MAX_IMAGE_BYTES:
                return JSONResponse({"error": "圖片太大"}, status_code=413)
            mime = (req.image_mime or "").split(";")[0].strip().lower()
            if not mime.startswith("image/"):
                return JSONResponse({"error": "不是圖片格式"}, status_code=415)
            image = UserImage(data, mime)
        return stream_turn(req.message, image=image)

    @app.post("/chat/audio")
    async def chat_audio(request: Request):
        """A voice message: the raw recording as the body, its format in Content-Type."""
        if stt is None:
            return stream_failure("stt_disabled", "語音輸入目前是關閉的,請改用打字。")
        declared = request.headers.get("content-length", "")
        if declared.isascii() and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
            return JSONResponse({"error": "錄音太大"}, status_code=413)  # refused before a byte is read
        chunks, total = [], 0
        async for chunk in request.stream():  # counted as it arrives: a body without a Content-Length is capped too
            total += len(chunk)
            if total > MAX_AUDIO_BYTES:
                return JSONResponse({"error": "錄音太大"}, status_code=413)
            chunks.append(chunk)
        data = b"".join(chunks)
        mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if not data:
            return JSONResponse({"error": "沒有收到錄音"}, status_code=400)
        if not mime.startswith("audio/"):
            return JSONResponse({"error": "不是音訊格式"}, status_code=415)
        if len(data) > MAX_AUDIO_BYTES:
            return JSONResponse({"error": "錄音太大"}, status_code=413)
        if debug_audio:  # stt.debug_log: next to the "[stt]" line, how loud this clip was and whether she was talking
            default_log(f"[audio] {len(data)} bytes | {clip_meta(request.headers.get('x-clip-meta'))}")
        voice_mode = request.headers.get("x-voice-mode", "").strip().lower()
        duration_header = request.headers.get("x-voice-duration-ms", "")
        voice_duration_ms = int(duration_header) if duration_header.isascii() and duration_header.isdigit() else None  # "²".isdigit() is True but int("²") raises
        try:
            text = stt.transcribe(data, mime).strip()
        except Exception:
            # A real STT failure (network/rate-limit/service down) — not "we heard silence".
            # Nothing is built or sent to TurnEngine: same "no history, safe to just retry"
            # contract a Failure from the engine itself already gives text turns.
            log.exception("speech-to-text failed")
            return stream_failure("stt_unavailable", "語音辨識暫時不能用,可以再說一次或用打字嗎?")
        if is_likely_non_speech_transcript(text, voice_mode, voice_duration_ms):
            log.info("discarding likely non-speech STT caption in continuous mode (%d characters)", len(text))
            return stream_failure("stt_empty", "沒聽清楚,可以再說一次嗎?")
        if not text:
            # Groq genuinely heard nothing usable — distinguishable from the exception case
            # above at the adapter boundary (see companion/groq_stt.py), but both end this turn
            # the same way here: no message, no TurnEngine call.
            return stream_failure("stt_empty", "沒聽清楚,可以再說一次嗎?")
        return stream_turn(text, transcript=text)

    return app
