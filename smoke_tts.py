"""Manual smoke test of edge-tts. Writes hello.mp3 and prints the synthesis time."""
import sys
import time

from companion.edge_tts_adapter import EdgeTTS

text = sys.argv[1] if len(sys.argv) > 1 else "你好呀,今天過得好嗎?"
start = time.perf_counter()
data = EdgeTTS().synthesize(text)
print(f"合成耗時 {time.perf_counter() - start:.2f}s,{len(data)} bytes")
open("hello.mp3", "wb").write(data)
print("已寫入 hello.mp3,雙擊播放確認聲音")
