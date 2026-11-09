"""Manual smoke test against the real Gemini API. Needs GEMINI_API_KEY.

    python smoke_gemini.py                 # one turn, prints every event and the first-sentence delay
    python smoke_gemini.py "你好"          # the same with your own message
    python smoke_gemini.py --compare [N]   # first-sentence delay with memory and state OFF vs ON (N runs, default 3)
"""
import sys
import time

from companion.engine import Sentence, TurnEngine
from companion.gemini_llm import GeminiLLM

try:
    persona = open("persona.md", encoding="utf-8").read()
except FileNotFoundError:
    raise SystemExit("找不到 persona.md。請把 persona.example.md 複製一份,命名為 persona.md。")

if "--compare" in sys.argv:
    from companion.latencysmoke import measure, summarize

    rest = [a for a in sys.argv[1:] if a != "--compare"]
    runs = int(rest[0]) if rest else 3
    print(f"對照記憶與狀態「關/開」的首句延遲:每邊 {runs * 2} 次真實呼叫,需要一點時間……")
    results = measure(GeminiLLM, persona, runs=runs)
    report = summarize(results["off"], results["on"])
    print(report.text())
    sys.exit(0 if report.within_budget else 1)

engine = TurnEngine(GeminiLLM(), persona=persona)
message = sys.argv[1] if len(sys.argv) > 1 else "嗨,你今天好嗎?"

start = time.perf_counter()
first = None
for event in engine.send(message):
    now = time.perf_counter() - start
    if isinstance(event, Sentence) and first is None:
        first = now
    print(f"[{now:5.2f}s] {event}")
print(f"\n首句延遲: {first:.2f}s" if first is not None else "\n沒有收到任何句子")
