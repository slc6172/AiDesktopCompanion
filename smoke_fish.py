"""Manual smoke test against the real Fish Audio API (needs internet and a Fish key).
Set the key first:  python app.py --set-key-fish   (or the FISH_API_KEY environment variable).
It uses the same settings as the app (config.json `tts.fish`, then the COMPANION_FISH_* variables).
Usage: python smoke_fish.py [text] [emotion]   -> writes hello_fish.<mp3|wav>
  emotion: neutral | happy | sad | angry | surprised  (adds that emotion's tag, exactly as the app would;
  LISTEN for a tag being read aloud instead of acted on: that cannot be checked by a test)

Run it a few times: the first call includes the connection setup, and the free tier promises
no latency, so look at the typical time rather than the first one."""
import sys
import time

from companion.config import resolve_fish_config
from companion.fish_adapter import FishTTS

text = sys.argv[1] if len(sys.argv) > 1 else "你好呀,今天過得好嗎?Nice to meet you."
emotion = sys.argv[2] if len(sys.argv) > 2 else None
settings = resolve_fish_config()
tts = FishTTS(model=settings["model"], reference_id=settings["reference_id"], response_format=settings["format"],
              timeout=settings["timeout_s"], emotion_tags=settings["emotion_tags"])
print(f"模型 {settings['model']} | 聲音 {settings['reference_id'] or '(預設)'} | 格式 {settings['format']} | 情緒 {emotion or '(無)'}"
      f" | 實際送出:{tts._tagged(text, emotion)!r}")
for attempt in (1, 2, 3):
    start = time.perf_counter()
    data = tts.synthesize(text, emotion=emotion)
    elapsed = time.perf_counter() - start
    print(f"第 {attempt} 次:合成耗時 {elapsed:.2f}s,{len(data)} bytes ({tts.mime_type})")

ext = {"audio/mpeg": "mp3", "audio/wav": "wav"}[tts.mime_type]
path = f"hello_fish.{ext}"
open(path, "wb").write(data)
print(f"已寫入 {path}。請播放確認聲音、台灣腔與斷句是否可以接受;有加情緒時,也聽聽標籤有沒有被念出來。" if data else "回傳是空的:Fish 沒有給出音訊。")
