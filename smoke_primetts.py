"""Manual smoke test against your local OpenAI-compatible PrimeTTS server.
Set COMPANION_PRIMETTS_URL (e.g. http://127.0.0.1:8880/v1) and, if your server needs them,
COMPANION_PRIMETTS_MODEL / COMPANION_PRIMETTS_VOICE / COMPANION_PRIMETTS_API_KEY first.
Usage: python smoke_primetts.py [text]   -> writes hello_primetts.<wav|mp3>"""
import sys
import time

from companion.primetts_adapter import PrimeTTS

text = sys.argv[1] if len(sys.argv) > 1 else "你好呀,今天過得好嗎?Nice to meet you."
tts = PrimeTTS()
start = time.perf_counter()
data = tts.synthesize(text)
elapsed = time.perf_counter() - start

ext = {"audio/wav": "wav", "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/flac": "flac"}[tts.mime_type]
path = f"hello_primetts.{ext}"
open(path, "wb").write(data)
print(f"合成耗時 {elapsed:.2f}s,{len(data)} bytes ({tts.mime_type}) -> {path}")
print("請播放這個檔案,確認聲音、台灣腔與斷句是否可以接受。" if data else "回傳是空的:伺服器沒有給出音訊。")
