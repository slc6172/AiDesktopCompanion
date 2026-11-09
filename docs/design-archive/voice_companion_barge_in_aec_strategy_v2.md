> 歷史設計筆記,以程式碼為準。

# Python 持續語音 Companion：AEC、VAD、Barge-in 與低延遲實作策略

> 目的：建立一個可長時間持續收音、AI 持續播放語音、使用者可隨時插話（barge-in）的 Python Voice Companion。
>
> 核心要求：
> 1. AI 播放 TTS 時麥克風不能簡單關閉。
> 2. 麥克風會收到喇叭聲，因此必須處理 Acoustic Echo Cancellation（AEC）。
> 3. 使用者插話時，應由本機立即判斷並停止 AI 播放，而不是等待 STT / LLM / TTS API 完成。
> 4. 要考量電腦、音訊裝置、播放 buffer、網路、STT/LLM/TTS API 的延遲。
> 5. AEC 失配或過度消除時，不能讓使用者真正的語音在送往 STT 前被不明原因破壞而無法恢復。
>
> 本文件依據 2026-10-07 可取得的 WebRTC、LiveKit、OpenAI Realtime、AIRI、OHF-Voice 等公開原始碼與文件整理；其中「建議參數」屬本專案工程起始值，不是任何廠商保證值。

---

## 1. 最終建議架構

推薦不要把所有問題塞到 VAD，也不要採用「AI 說話時停止麥克風」的設計。

最穩定的責任切分如下：

```text
                           ┌─────────────────────┐
                           │      LLM / TTS API   │
                           └──────────┬──────────┘
                                      │ streaming PCM
                                      ▼
                           ┌─────────────────────┐
                           │  Playback Manager    │
                           │  queue / cancel      │
                           │  flush / timestamp   │
                           └──────────┬──────────┘
                                      │
                                  Speaker
                                      │
                              acoustic echo
                                      │
                                      ▼
Mic ──────────────► Capture ───────► AEC3 ───► NS ───► VAD
                       │                           │
                       │                           ├── speech start
                       │                           │
                       │                           └── speech end
                       │
                       └── raw ring buffer               
                                                       │
                           AI 正在說話？ ───────────────┤
                              │                         │
                              ▼                         ▼
                        Barge-in detector           STT stream
                              │                         │
                              ├──立即停止 TTS          ▼
                              ├──清空 playback       Transcript
                              └──保留 pre-roll          │
                                                        ▼
                                                       LLM
                                                        │
                                                        ▼
                                                       TTS
```

### 各層職責

| 元件 | 負責什麼 | 不應負責什麼 |
|---|---|---|
| AEC3 | 移除 speaker → mic 的聲學回音 | 判斷誰在說話、決定是否中斷 |
| NS | 降低背景噪音 | AEC 替代品 |
| VAD | 判斷是否出現 speech | 判斷內容、辨識人聲來源 |
| Barge-in detector | 判斷是否應讓 AI 讓出 turn | STT/LLM 語意理解 |
| STT | 把使用者語音變成文字 | 本機即時停止 speaker |
| Playback Manager | 播放、取消、flush、保留播放位置 | 判斷使用者意圖 |
| LLM | 產生回應 | 音訊回音消除 |
| TTS | 產生 AI 語音 | 回音消除 |

**最重要的原則：**「中斷 AI」與「理解使用者說了什麼」是兩條不同的 latency path。

---

## 2. 為什麼不能只做 `assistant_speaking = True -> ignore microphone`

AIRI 的設計可以把問題簡化為：AI 說話時不要把自己再餵進 Chat。AIRI 的公開實作/Issue 也顯示其聊天語音輸入是 VAD 觸發 MediaRecorder，而且它曾出現「缺乏 pre-roll 導致開頭 150–500 ms 語音遺失」的問題。

參考：

- AIRI repository: https://github.com/moeru-ai/airi
- AIRI issue #2092: https://github.com/moeru-ai/airi/issues/2092

這個方法適合 turn-taking，但若要求「使用者可以隨時打斷 AI」，則：

```text
AI speaking
    │
    ├─ 錄音關閉 / 完全忽略 mic  → 使用者無法 barge-in
    │
    └─ mic 持續 active + AEC + VAD → 可以 barge-in
```

因此本專案應採第二種。

---

## 3. AEC 的正確觀念：一定要有 far-end / render reference

### 3.1 麥克風實際收到的是

```text
near = user_voice + speaker_echo + room_noise + mic_noise
```

AEC 需要另一條：

```text
far = 實際送往喇叭播放的參考訊號
```

目標是估計：

```text
estimated_echo = f(far, acoustic_path)
clean ≈ near - estimated_echo
```

### 3.2 不可以簡單把「TTS 原始 PCM」當作唯一真實參考

理想的 reference 應該接近：

```text
TTS PCM
  ↓
resample / mixer / volume
  ↓
output buffer
  ↓
實際播放 frame
  └────────► AEC reverse / far-end reference
```

如果 TTS PCM 與實際送到音效裝置的資料不一致，例如：

- 播放器有 mixer
- 音量有縮放
- 不同取樣率
- stereo → mono
- output buffer 延遲
- 裝置有 DSP
- OS 重新取樣

AEC 的效果會惡化。

### 3.3 WebRTC 官方定義

WebRTC Audio Processing API 明確提供 `ProcessReverseStream()`，讓 client 將 far-end / reverse stream 傳給 APM；同時提供 `set_stream_delay_ms()`，描述 reverse frame 到對應 echo 出現在 near-end frame 的延遲。

官方來源：

- WebRTC Audio Processing API：
  https://webrtc.googlesource.com/src/+/main/modules/audio_processing/include/audio_processing.h

關鍵概念：

```text
speaker/reference ──► ProcessReverseStream
                              │
                              ▼
mic/capture ────────► ProcessStream
```

WebRTC 官方 API 對 delay 的定義，是 render/reverse 與 capture frame 之間的實際時間關係，不是 STT/LLM/TTS 的網路 RTT。

---

## 4. AEC delay 與 API network latency 必須完全分開

這是實作時最重要的時間軸切分之一。

### AEC 所關心的延遲

```text
T_AEC ≈
    audio output scheduling
  + output device buffer
  + DAC / hardware delay
  + speaker → room → microphone acoustic path
  + capture device buffer
  + application processing delay
```

### Voice Agent 所關心的端到端延遲

```text
User speech
  ↓
mic capture
  ↓
AEC + VAD
  ↓
STT network
  ↓
STT inference
  ↓
LLM network + inference
  ↓
TTS network + synthesis
  ↓
playback buffer
  ↓
speaker
```

**STT/LLM/TTS 網路慢，不應拿來當 AEC 的 delay。**

---

## 5. 可信度最高的參考實作：WebRTC APM / AEC3

WebRTC Audio Processing Module（APM）是首選的 DSP 基礎。

官方：

- WebRTC source tree: https://webrtc.googlesource.com/src/
- APM API: https://webrtc.googlesource.com/src/+/main/modules/audio_processing/include/audio_processing.h

WebRTC APM 提供的核心方向包括：

- Acoustic Echo Cancellation
- Noise Suppression
- Automatic Gain Control
- High-pass filtering
- reverse/render stream processing

### 不建議自己寫 AEC

不要自行使用：

```text
sounddevice
  + custom LMS/NLMS
  + 自己猜 delay
  + 自己判斷 residual echo
```

除非研究目的非常明確。

Voice Companion 的問題不只是「一個濾波器」，而是：

- nonlinear echo
- room impulse response
- playback delay
- buffer drift
- double-talk
- background noise
- gain changes
- far-end reference alignment

因此直接利用成熟的 WebRTC AEC3 實作會可靠很多。

---

## 6. Python 可直接採用的 WebRTC binding：pywebrtc-audio

GitHub：

https://github.com/strands-labs/pywebrtc-audio

PyPI：

https://pypi.org/project/pywebrtc-audio/

此專案目前提供 Python bindings，對接 WebRTC audio processing pipeline，包含：

- AEC3
- Noise Suppression
- AGC2
- VAD / speech probability
- high-pass filter

GitHub README 也提供 real-time、PyAudio、E2E speech preservation 等範例。

### 安裝

```bash
python -m pip install pywebrtc-audio
```

### 基本 API（依官方 API 改寫的最小範例）

```python
import numpy as np
from pywebrtc_audio import AudioProcessor

processor = AudioProcessor(
    sample_rate=16000,
    num_channels=1,
    echo_cancellation=True,
    noise_suppression=True,
    high_pass_filter=True,
    auto_gain_control=True,
    # 起始值；正式值應由量測調整
    stream_delay_ms=measured_delay_ms,
)

# near: 麥克風實際收到的訊號
# far : 實際 speaker playback reference
clean = processor.process(near, far)

speech_probability = processor.speech_probability
```

官方 README 特別指出：

- 10 ms frame 是 WebRTC AEC3 的內部處理單位。
- `far` 與 `near` 必須對應。
- `stream_delay_ms` 是 speaker buffer 寫入與 corresponding echo 出現在 mic 的時間差提示。
- 0 delay 可讓 AEC3 自己估計，但適當的起始 hint 有助於更快收斂。
- processor instance 不是 thread-safe。

來源：

https://github.com/strands-labs/pywebrtc-audio

### 官方專案提供的測試價值

尤其值得參考的 examples：

```text
examples/pyaudio_realtime.py
examples/e2e_verify.py
examples/e2e_speech.py
```

其中 `e2e_speech.py` 的設計思路正適合本專案：在 speaker 有音訊播放時，驗證真正的 speech 是否仍能被保存。

---

## 7. LiveKit：目前最值得研究的 Python 全雙工範例

LiveKit Python SDK 已經把「mic capture + APM + speaker playback + reverse reference」串成完整架構。

GitHub：

https://github.com/livekit/python-sdks

關鍵原始碼：

https://github.com/livekit/python-sdks/blob/main/livekit-rtc/livekit/rtc/media_devices.py

### LiveKit 的重要設計

`MediaDevices`：

```text
open_input()
   ↓
AudioProcessingModule
   ├─ AEC
   ├─ NS
   ├─ HPF
   └─ AGC

open_output()
   ↓
OutputPlayer
   ↓
同一個 APM 的 reverse stream
```

官方原始碼註明：使用 AEC 時，output player 必須把 reverse frame 餵回相同的 APM instance。

### 改寫成專案骨架

```python
from livekit import rtc


devices = rtc.MediaDevices()

mic = devices.open_input(
    enable_aec=True,
    noise_suppression=True,
    high_pass_filter=True,
    auto_gain_control=True,
)

player = devices.open_output()

# player 播放的音訊會走同一個 APM 的 reverse path。
# mic.source 則提供處理後的 capture stream。
```

這段不是要求你一定採用 LiveKit，而是展示一個很重要的工程原則：

> **capture APM 與 playback reverse path 應該由同一個音訊處理鏈管理。**

### LiveKit 的另一個優點

其 Python source 明確以 10 ms audio frame 為 APM 的處理單位，也有 delay estimation helper。

來源：

https://github.com/livekit/python-sdks/blob/main/livekit-rtc/livekit/rtc/media_devices.py

---

## 8. LiveKit 的 Barge-in 策略值得直接模仿

LiveKit Agents 目前提供兩種 interruption 模式：

```text
vad
adaptive
```

其中 adaptive interruption 是在 VAD 已經判斷有語音後，再用聲學模型判斷是否真的是「刻意插話」，而不是：

- uh-huh
- okay
- right
- 短暫背景語音
- 雜音

官方文件：

https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/

https://docs.livekit.io/reference/agents/turn-handling-options/

### Python 設定概念

可直接參考以下參數設計：

```python
turn_handling = {
    "interruption": {
        "mode": "vad",               # 沒有 adaptive model 時先用 VAD
        "min_duration": 0.5,          # 起始值，不是固定標準
        "min_words": 0,
        "false_interruption_timeout": 2.0,
        "resume_false_interruption": True,
    }
}
```

LiveKit 目前的預設/建議值顯示：

- interruption enabled：True
- min duration：0.5 s
- false interruption timeout：2.0 s
- 若無 adaptive capability，可退回 VAD-based interruption

來源：

https://docs.livekit.io/reference/agents/turn-handling-options/

### 重要：不要照抄 500 ms 當作本專案的 barge-in latency

`min_duration=0.5` 更像「防止誤中斷」的保守設定，而不是硬性最佳值。

如果你的需求是「快速打斷 AI」，本專案應：

```text
VAD frame       10 ms
speech confirm  約 50–150 ms
local interrupt 目標 < 150 ms
```

然後再以實測 false-positive rate 調整。

這些是**本專案的工程目標**，不是 LiveKit 或 WebRTC 的官方保證。

---

## 9. LiveKit 的 AEC warm-up 很值得採用

目前 LiveKit Agents 的 Python `AgentSession` 有 `aec_warmup_duration`；官方示例目前設定為 3 秒，原因是避免 agent 一開始播放時，AEC 尚未穩定就被自己的 echo 觸發 interruption。

參考原始碼：

https://github.com/livekit/agents/blob/main/examples/voice_agents/basic_agent.py

以及：

https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py

概念是：

```text
開始 speaker playback
       │
       ▼
短暫 AEC warm-up
       │
       ▼
開始允許 barge-in
```

但不必原封不動採用 3 秒。

對本專案較合理的是：

```text
首段 TTS 開始播放
      ↓
AEC warm-up = 可調參數
      ↓
以實測 residual echo / false interruption 決定
      ↓
恢復正常 barge-in
```

200–500 ms 可以作為部分設備的候選起測範圍，但**不是固定標準值**；若實測某些設備需要更長時間才穩定，也應允許提高。

---

## 10. False interruption：一定要有第二層防護

純 VAD 最大問題：

```text
AI 正在說話
       ↓
喇叭 echo / 使用者「嗯」/ 咳嗽 / 雜音
       ↓
VAD = speech
       ↓
AI 被打斷
```

因此建議：

```text
VAD speech-start
      ↓
立刻降低/停止 TTS（低延遲）
      ↓
保留 interruption candidate
      ↓
STT 是否真的產生內容？
      │
      ├─ 有 transcript → 真 barge-in
      │
      └─ 沒 transcript → false interruption
                              ↓
                       必要時 resume TTS
```

LiveKit 目前也採 false interruption recovery，並提供：

- `false_interruption_timeout`
- `resume_false_interruption`
- `min_duration`
- `min_words`
- turn-boundary cooldown

參考：

https://docs.livekit.io/reference/agents/turn-handling-options/

---

## 11. 為什麼「先 interrupt，再等 STT」是正確策略

錯誤：

```text
User: "等一下"
  ↓
VAD
  ↓
錄音
  ↓
STT API
  ↓
Network RTT
  ↓
STT result
  ↓
interrupt speaker
```

這樣 speaker 可能還繼續講數百毫秒以上。

正確：

```text
User speech
  ↓
本機 AEC
  ↓
本機 VAD
  ↓
本機 interruption decision
  ↓
立即 stop / flush speaker
  │
  └───────────────► STT stream
                         ↓
                     transcript
                         ↓
                        LLM
```

也就是：

> **Barge-in 是 local control path；STT/LLM/TTS 是 semantic response path。**

---

## 12. Playback Manager 必須可「取消 + flush」，不能只 cancel TTS task

假設 TTS 已經產生：

```text
chunk1 | chunk2 | chunk3 | chunk4 | chunk5
```

即使 `asyncio.Task.cancel()` 成功，chunk2~5 可能已經進入 audio device buffer。

所以 Playback Manager 至少要有：

```python
class PlaybackManager:
    async def enqueue(self, pcm: bytes) -> None:
        ...

    async def start(self) -> None:
        ...

    async def stop_immediately(self) -> None:
        """Cancel producer, clear pending chunks, and flush output."""
        ...

    def buffered_ms(self) -> float:
        ...
```

### 建議

播放 queue 不要預先累積數秒。

較適合的方向：

```text
TTS network buffer：短
Playback queue：短
Audio output buffer：短
```

因為：

```text
queue 越長 → TTS 可能更流暢
queue 越長 → barge-in 越難立即停止
```

實際 queue 長度應用測試決定，建議先從約 50–150 ms 的可控緩衝開始。

---

## 13. Pre-roll：務必保留 200–500 ms 麥克風 ring buffer

這是 AIRI Issue #2092 已經實際暴露的問題：VAD 偵測到 speech-start 後才開始 Recorder，可能造成句首遺失約 150–500 ms。

來源：

https://github.com/moeru-ai/airi/issues/2092

因此：

```text
continuous mic capture
        │
        ▼
┌────────────────────────────┐
│ 300 ms raw / AEC ring buf  │
└────────────────────────────┘
        │
        ▼
VAD speech-start
        │
        └── prepend recent audio to STT segment
```

推薦起始值：

```text
pre-roll = 300 ms
```

再用測試調整為 200–500 ms。

### Python ring buffer 概念

```python
from collections import deque

class AudioRingBuffer:
    def __init__(self, max_frames: int):
        self.frames = deque(maxlen=max_frames)

    def push(self, frame):
        self.frames.append(frame.copy())

    def snapshot(self):
        return list(self.frames)
```

正式版本應確保：

- frame sequence 有 timestamp / monotonic clock
- 不能因 deque 裡面 frame 被後續修改而污染
- ring buffer 不要阻塞 audio callback

---

## 14. 最重要的 Python 音訊執行緒原則（本節為實作關鍵）

### 14.1 HTTP / LLM / STT / TTS 絕對不要放進 audio callback

Audio callback 不應做：

```text
HTTP request
LLM request
STT await
TTS request
disk I/O
大量 logging
```

### 14.2 AEC / render-reference 也不能隨意丟到普通 asyncio worker

這點與一般「callback 只把資料丟 queue」的音訊程式不同。WebRTC APM 依 10 ms frame 與 capture/render 的實際時間關係工作；reverse stream 與 primary capture stream 必須持續、對齊地餵入，而 `stream_delay_ms` 也必須反映真實時間關係。

因此正式實作應採以下其中一種：

**方案 A：使用 LiveKit 的 APM / MediaDevices**

讓 LiveKit 管理 render/capture/APM threading；目前 Python 原始碼就是由同一 APM 接受 capture 與 reverse stream，並利用 PortAudio timing 計算 delay。

**方案 B：使用 `pywebrtc-audio` standalone**

`pywebrtc-audio` 的 `AudioProcessor` / `EchoCanceller` 明確標示為 **not thread-safe**。因此不要讓 playback callback 和 capture callback 同時直接呼叫同一個 instance。

較安全的方式是：

```text
PortAudio input callback ──► capture ring/queue ──┐
                                                 │
PortAudio output callback ─► render ring/queue ──┤
                                                 ▼
                                      single DSP worker/thread
                                      ├─ pair 10 ms frames
                                      ├─ reverse/far processing
                                      ├─ capture/near processing
                                      └─ output AEC frame
                                                 │
                                                 ▼
                                             VAD / STT
```

這個 DSP worker 必須是**固定節奏、bounded queue、持續追上 real-time** 的音訊執行緒，而不是任意延遲的 asyncio task。若 DSP queue 開始累積，表示處理已經跟不上 real-time；不得讓 queue 無限成長。

### 14.3 STT / LLM / TTS 在另一層

推薦：

```text
REAL-TIME AUDIO PATH
Mic → AEC → VAD → bounded event queue
                 │
                 ▼
        ASYNC APPLICATION PATH
        STT → LLM → TTS → Playback queue
```

這樣可以同時滿足：

- AEC / VAD：固定低延遲、穩定時間軸
- API：允許網路抖動，不污染 audio clock

## 15. 建議統一使用 10 ms audio frame

WebRTC APM 的處理模型是 10 ms frame；LiveKit 的 `MediaDevices` 也按 10 ms frame 管理 APM processing。

因此建議：

```text
16 kHz mono
10 ms = 160 samples
```

或：

```text
48 kHz mono
10 ms = 480 samples
```

Voice STT 如果最終要 16 kHz，可採：

```text
Audio device
48 kHz
  ↓
AEC3 / processing
  ↓
resample
  ↓
16 kHz STT
```

但要避免在 AEC 前後隨意變更多次 sample rate。

---

## 16. `pywebrtc-audio` 的 real-time 參考骨架

> **重要：下列程式碼是 DSP API 示意；不要把 `AudioProcessor` 同時從 input/output callback 直接呼叫。該類別目前明確標示為 not thread-safe。正式版應採單一 DSP thread，或改用 LiveKit / native WebRTC APM wiring。**

以下是「概念可執行架構」，不是聲稱複製官方 example；實際 sounddevice / PyAudio callback 需依 OS device 行為調整。

```python
import asyncio
import numpy as np
from collections import deque
from pywebrtc_audio import AudioProcessor

SAMPLE_RATE = 16000
FRAME_MS = 10
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
PRE_ROLL_FRAMES = 30          # 300 ms

class VoiceEngine:
    def __init__(self):
        self.apm = AudioProcessor(
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            echo_cancellation=True,
            noise_suppression=True,
            high_pass_filter=True,
            auto_gain_control=True,
            stream_delay_ms=measured_delay_ms,  # 應由裝置 timing / calibration 取得
        )
        self.ring = deque(maxlen=PRE_ROLL_FRAMES)
        self.assistant_speaking = False
        self.interrupt_lock = asyncio.Lock()

    def process_capture_frame(self, near_frame, far_frame):
        """
        near_frame: exactly 10 ms mic capture
        far_frame: corresponding 10 ms playback reference
        """
        clean = self.apm.process(near_frame, far_frame)
        self.ring.append(clean.copy())
        speech_prob = self.apm.speech_probability
        return clean, speech_prob

    async def on_speech_start(self):
        if self.assistant_speaking:
            await self.interrupt_assistant()

        # 送 STT 時，把 ring buffer 最近約 300ms 一起送出去。
        pre_roll = list(self.ring)
        # start_stream_to_stt(pre_roll)

    async def interrupt_assistant(self):
        async with self.interrupt_lock:
            if not self.assistant_speaking:
                return
            self.assistant_speaking = False

            # 順序很重要：
            # 1. 停止 TTS producer
            # 2. 清掉尚未播放的 TTS queue
            # 3. flush / stop output buffer
            await playback_manager.stop_immediately()
```

**真正的難點不在 `AudioProcessor` 這幾行，而在 `far_frame` 如何與實際 speaker output 對齊。**

---

## 17. Far-end reference 的工程實作

最容易犯的錯：

```python
# 不建議
far = current_tts_chunk
clean = ap.process(mic_frame, far)
```

因為 `current_tts_chunk` 不一定是此時麥克風所捕捉到的 echo 對應 frame。

比較合理的是：

```text
TTS stream
   ↓
Playback mixer
   ↓
Output buffer queue
   │
   ├── actual output frame
   │        │
   │        └── speaker
   │
   └── reference ring buffer
              │
              ▼
       delay-aligned far frame
              │
              ▼
             AEC
```

概念 Python：

```python
from collections import deque

class FarEndReference:
    def __init__(self, max_frames=300):
        self.frames = deque(maxlen=max_frames)

    def push_rendered_frame(self, frame, timestamp):
        self.frames.append((timestamp, frame.copy()))

    def get_reference(self, capture_timestamp, delay_ms):
        target = capture_timestamp - delay_ms / 1000.0
        # 實作時請以 timestamp 找最近 frame；不要只用 list index 猜。
        return self.closest_frame(target)
```

如果選用 LiveKit `MediaDevices`，優先使用它現成的 APM reverse path，而不要再次自行造一份 reference pipeline。

---

## 18. AEC 過度消除（double-talk）如何避免

真正危險的場景是：

```text
AI speaker 正在說話
        +
User 同時說話
        ↓
Mic = AI echo + User speech
```

這稱為 double-talk。

如果 AEC 設定不良，可能：

```text
AI echo 被消掉
但 user voice 也被部分消掉
```

因此要有下列原則：

1. AEC 使用正確 far-end reference。
2. render/capture delay 儘量準確。
3. 不重複套兩層 AEC。
4. 保留 raw / pre-roll ring buffer。
5. 透過實際的 double-talk 測試確認 STT WER。
6. 不要因為「AEC output 比較安靜」就認為一定正確。

---

## 19. 不要做 double AEC

以下組合要避免：

```text
Hardware DSP AEC
       ↓
OS PipeWire AEC
       ↓
WebRTC AEC3
       ↓
STT
```

除非你有明確理由並經測試，否則三層 AEC 很可能互相影響。

原則：

```text
選一個主要 AEC layer
```

### Linux 特別值得參考：PipeWire / PulseAudio

OHF-Voice 的 Linux Voice Assistant 文件直接使用：

```bash
pactl load-module module-echo-cancel source_name=aec_mic aec_method=webrtc
```

或 PipeWire：

```bash
pw-cli load-module libpipewire-module-echo-cancel \
  '{ source.props={ node.name=aec_mic } }'
```

來源：

https://github.com/OHF-Voice/linux-voice-assistant/blob/main/docs/enabling_aec.md

如果選用 OS level AEC，就不要再對同一個 input stream 再套一次 AEC3。

---

## 20. Barge-in 狀態機

建議實作下列狀態：

```text
IDLE
  │ user speech
  ▼
LISTENING
  │ end-of-turn
  ▼
THINKING
  │ first TTS chunk
  ▼
SPEAKING
  │ user speech detected
  ▼
INTERRUPT_CANDIDATE
  │
  ├─ confirmed → BARGE_IN
  │               │
  │               ├─ stop TTS
  │               ├─ flush output
  │               └─ LISTENING
  │
  └─ false → SPEAKING / resume
```

### 為什麼要 `INTERRUPT_CANDIDATE`

因為：

```text
VAD = speech
```

不等於：

```text
User wants to interrupt the agent
```

例如：

- 「嗯」
- 「喔」
- 咳嗽
- 家人聲音
- 背景電視
- TTS echo residual

都可能成為 VAD trigger。

---

## 21. 建議的 Barge-in 判斷

### 第一階段：本機快速判斷

```text
AEC output
   ↓
VAD
   ↓
speech_probability > threshold
   ↓
持續 N 個 frame
   ↓
interrupt candidate
```

### 第二階段：可選 adaptive classifier

如果沒有 LiveKit Cloud 類型的 adaptive model，可以先使用：

```text
speech duration
+ energy
+ VAD confidence
+ STT partial transcript
+ agent speaking state
```

自行做 conservative rule。

### 第三階段：false interruption recovery

```text
candidate
  ↓
停止 / 暫停 AI
  ↓
STT
  ↓
有實質 transcript ?
  ├─ yes → genuine interruption
  └─ no  → false interruption
```

---

## 22. OpenAI Realtime API 的參考意義

即使本專案並不一定使用 OpenAI Realtime，也值得參考它的 API 設計。

官方目前提供：

- `server_vad`
- `semantic_vad`
- `interrupt_response`
- `create_response`
- `silence_duration_ms`
- `threshold`
- semantic VAD 的 eagerness

官方文件：

https://developers.openai.com/api/reference/resources/realtime/server-events

https://developers.openai.com/api/reference/resources/realtime/client-events

官方 API 的 `interrupt_response` 本質上也是：

```text
VAD detects user starts speaking
       ↓
interrupt active response
```

它再次印證：

> interruption detection 應該在 response output path 之外獨立運作。

---

## 23. Network latency 的實作策略

### 不應等待整句完成才啟動所有服務

推薦：

```text
User starts speaking
       ↓
local VAD
       ↓
stream audio to STT immediately
       ↓
partial transcript
       ↓
final transcript
       ↓
LLM stream
       ↓
TTS stream
       ↓
play first audio chunk
```

### 可以做 preemptive generation 的情況

LiveKit 目前也有 preemptive generation：final transcript 到達後，在完全確認 end-of-turn 前就可開始 LLM generation，以降低 latency。

但代價是：

```text
User continues speaking
       ↓
已經產生的一部分 LLM/TTS 計算被取消
```

所以建議先把「穩定性」做好，再開啟 preemptive generation。

---

## 24. 建議明確記錄五個時間戳

每次 turn 至少記：

```text
T0 = mic capture first speech frame
T1 = local VAD confirms barge-in
T2 = speaker actually stops
T3 = STT final transcript
T4 = first TTS PCM rendered
```

可以得到：

```text
Barge-in latency = T2 - T0
STT latency      = T3 - T0
Response latency = T4 - T3
End-to-end       = T4 - T0
```

此外再記：

```text
capture queue depth
playback queue depth
AEC estimated delay
VAD probability
STT partial/final timing
TTS first-byte timing
```

這樣才能定位延遲到底來自：

```text
PC / driver
AEC / VAD
network
STT
LLM
TTS
playback
```

---

## 25. 推薦的第一版參數

以下只作為 prototype 起始值，不是標準答案。

| 項目 | 起始值 | 說明 |
|---|---:|---|
| Audio frame | 10 ms | WebRTC/APM 相容 |
| Input | 16 kHz mono 或 48 kHz mono | 依 STT / device 決定 |
| Pre-roll | 300 ms | 防止句首遺失 |
| Barge-in VAD confirmation | 50–150 ms | 先求低 latency |
| TTS queue | 50–150 ms | 避免中斷拖尾 |
| AEC warm-up | 設為可調參數；可從 200–500 ms 做候選測試 | 依裝置實測，不直接視為標準值 |
| False interruption timeout | 1–2 s 起測 | 可參考 LiveKit |
| `stream_delay_ms` | 先量測；沒有資料時可先 0 讓 AEC3 自估，或使用短暫 calibration hint | 不可永久硬編碼 |
| raw ring buffer | 500 ms | 至少涵蓋 pre-roll |

### 特別注意

不要直接把上述所有數字視為最佳值。尤其：

```text
stream_delay_ms
AEC warm-up
VAD duration
TTS queue
```

都應經由真實硬體測試調整。

---

## 26. 硬體建議

### 最容易成功：耳機 / headset

```text
speaker → ear canal
mic → near mouth
```

聲學回音極低，因此 AEC 壓力很小。

### 第二選擇：近場 USB microphone + speaker

可以成功，但應實測：

- speaker volume
- mic gain
- distance
- room reverberation
- device clock

### 第三選擇：遠場 / 房間型 Companion

建議使用：

- microphone array
- hardware DSP
- AEC
- noise suppression
- beamforming

OHF-Voice 的 Linux Voice Assistant 文件也建議 AEC/DSP 於這類情境使用。

---

## 27. AEC 正確性驗證：不要只測「聲音變小了」

至少做以下六組測試：

### Test A：AI 不說話 + User 說話

目的：

```text
確認 AEC / NS 沒有損傷正常使用者 speech
```

### Test B：AI 說話 + User 不說話

目的：

```text
確認 speaker echo 不會進入 VAD/STT
```

### Test C：AI 說話 + User 正常插話

目的：

```text
核心 barge-in
```

### Test D：AI 說話 + User 小聲插話

目的：

```text
驗證 double-talk sensitivity
```

### Test E：User 與 AI 同時長時間說話

目的：

```text
驗證 AEC 在 sustained double-talk 的穩定性
```

### Test F：背景噪音 + AI speech + User speech

例如：

- 風扇
- 鍵盤
- 電視
- 人聲

目的：

```text
驗證 false interruption
```

---

## 28. 每個測試都保存四路資料

推薦保存：

```text
01_raw_mic.wav
02_aec_output.wav
03_far_reference.wav
04_timestamps.json
```

`timestamps.json` 至少包含：

```json
{
  "capture_start": 123.456,
  "vad_start": 123.612,
  "interrupt": 123.662,
  "playback_stop": 123.705,
  "stt_final": 124.051,
  "tts_first_pcm": 124.820,
  "aec_delay_ms": 42
}
```

這會讓後續 debugging 非常容易。

---

## 29. 建議量測的品質指標

### AEC / audio quality

- ERLE（Echo Return Loss Enhancement）
- residual echo level
- user-speech SNR
- user-speech level before/after AEC
- optional SI-SDR / STOI（有乾淨 reference 時）

### STT quality

- WER
- 句首漏字比例
- AI speaking 時的 false transcript rate

### Voice-agent quality

- barge-in latency
- false interruption rate
- missed interruption rate
- time-to-first-audio
- time-to-first-token / time-to-first-TTS
- playback queue depth

**沒有 ground-truth audio 時，不要假裝能精確宣稱 AEC「完全無失真」。** 應用「相對 baseline」比較。

---

## 30. 最重要的 baseline 測試方法

建立三個模式：

```text
Mode 1：Mic only
Mode 2：Speaker + Mic，但不開 AEC
Mode 3：Speaker + Mic + AEC
```

同一個人、同一句話、同一音量、同一位置重複測試。

比較：

```text
Mode 1 vs Mode 3
```

如果 Mode 3 的 STT 明顯比 Mode 1 差很多，即使 echo 已經很小，也表示 AEC 過度消除，需要調整。

這比單純比較：

```text
「AEC output 聽起來很乾淨」
```

可靠得多。

---

## 31. 不應把 AEC 當成唯一防線

最終仍然應有 application-level suppression：

```text
                 ┌─ AEC ──┐
Microphone ──────┤         ├─ VAD ── Barge-in
                 └─ NS ────┘

                 + agent speaking state
                 + false interruption logic
                 + STT validation
                 + playback flush
```

因為即使 AEC 很好，仍可能存在：

- 非線性 speaker distortion
- 房間混響
- 家人/電視聲音
- 使用者在不同位置說話
- speaker volume 太大
- AEC 未收斂

---

## 32. 與 AIRI 的差別

### AIRI 式

```text
Mic continuously active
       ↓
VAD
       ↓
AIRI speaking ?
       ├─ yes → ignore / suppress input path
       └─ no  → STT / Chat
```

優點：

- 簡單
- 不依賴完整 AEC
- 不容易把自己的 TTS 再送入 Chat

缺點：

- 真正 barge-in 能力有限
- 使用者講話時若 AI 正在說，也可能被忽略

### 本文件推薦

```text
Mic continuously active
       ↓
WebRTC AEC3
       ↓
NS
       ↓
VAD
       ↓
Barge-in detector
       ├─ no → continue AI speech
       └─ yes → stop speaker immediately
                     ↓
                    STT
```

---

## 33. AIRI 的另一個教訓：一定要有 pre-roll

AIRI Issue #2092 很值得保留在本專案的測試 checklist：

> VAD 先觸發、Recorder 才開始，可能遺失句首 150–500 ms。

因此本專案不要：

```python
if vad_start:
    start_new_recording()
```

而要：

```python
# mic always running
ring_buffer.push(frame)

if vad_start:
    audio_segment = ring_buffer.last(300_ms)
    start_stt(audio_segment)
```

---

## 34. 具體推薦的 Python 元件

### Option A：最簡潔 standalone

```text
sounddevice / PyAudio
        +
pywebrtc-audio
        +
本機 VAD
        +
asyncio
        +
httpx / websockets
        +
OpenAI-compatible STT
        +
OpenAI-compatible LLM
        +
Fish Audio / 其他 streaming TTS
```

適合：

- 自己控制整個產品
- 不想導入 LiveKit 房間/RTC
- 需要自己的 API orchestration

### Option B：使用 LiveKit MediaDevices / APM

```text
LiveKit MediaDevices
        +
自訂 STT/LLM/TTS
```

適合：

- 希望直接利用成熟的 APM + full-duplex device handling
- 後續可能接 WebRTC / remote participant

### Option C：完整 LiveKit Agents

```text
LiveKit Agents
  ├─ VAD
  ├─ interruption handling
  ├─ false interruption recovery
  ├─ STT
  ├─ LLM
  └─ TTS
```

適合：

- 希望少寫 orchestration
- 可接受 framework lock-in

如果主要目標是「自己的 OpenAI-compatible API Companion」，建議先選 **Option A 或 B**，不要一開始就把完整 Agent framework 納入。

---

## 35. 最推薦的開發順序

### Phase 1：只做本機音訊

```text
Mic → AEC → VAD → WAV
```

確認：

- User speech 不會被破壞
- speaker echo 能降低

### Phase 2：雙工播放

```text
Mic + Speaker
      ↓
AEC + VAD
```

確認 AI 自己說話不會被 VAD 當成 user speech。

### Phase 3：加入 local barge-in

```text
AI speech
 +
User speech
 ↓
VAD
 ↓
stop speaker < 150ms target
```

此階段完全不接 STT/LLM。

### Phase 4：接 STT

```text
Barge-in
 ↓
Pre-roll
 ↓
STT streaming
```

確認不漏句首。

### Phase 5：接 LLM streaming

```text
STT final / partial
 ↓
LLM streaming
```

### Phase 6：接 streaming TTS

```text
LLM token stream
 ↓
TTS stream
 ↓
Playback queue
```

### Phase 7：false interruption recovery

加入：

```text
min duration
+ transcript validation
+ resume if false
```

### Phase 8：完整設備壓力測試

測：

```text
headset
USB mic + speaker
Bluetooth headset
HDMI monitor speaker
laptop built-in mic/speaker
```

注意 Bluetooth 常會改變 audio profile / sample rate / latency，因此應視為獨立測試類別。

---

## 36. 不建議的設計清單

### ❌ AI 說話就直接 `mic.stop()`

會失去真正 barge-in。

### ❌ VAD 一偵測 speech 就等 STT 完成才停止 AI

會產生明顯拖尾。

### ❌ 使用 TTS 原始 PCM 當作未對齊的 AEC reference

可能讓 AEC 失效。

### ❌ AEC + AEC + AEC 疊三層

容易增加不必要失真。

### ❌ 把 500 ms / 1 秒音訊作為一次 callback

會直接提高 barge-in latency。

### ❌ 不留 pre-roll

容易漏掉句首。

### ❌ 只記錄 processed audio

出了問題時完全無法判斷是 mic、AEC、VAD、STT 哪層造成。

### ❌ 在 audio callback 發 HTTP request

會造成 buffer overrun / audio glitch。

### ❌ 只用 RMS 音量判斷 barge-in

無法有效區分 echo、背景噪音與 user speech。

---

## 37. Recommended reference implementation blueprint

最終可以拆成以下 Python modules：

```text
voice_companion/
├── audio/
│   ├── capture.py          # microphone capture
│   ├── playback.py         # speaker + queue + flush
│   ├── aec.py              # WebRTC APM wrapper
│   ├── vad.py              # local VAD
│   ├── buffers.py          # raw/AEC/pre-roll ring buffers
│   └── timing.py           # monotonic timestamps + device delay
│
├── turn/
│   ├── state.py            # IDLE/LISTENING/THINKING/SPEAKING
│   ├── interruption.py     # barge-in detector
│   └── recovery.py         # false interruption recovery
│
├── services/
│   ├── stt.py              # OpenAI-compatible STT
│   ├── llm.py              # streaming LLM
│   └── tts.py              # Fish Audio / compatible TTS
│
├── metrics/
│   ├── latency.py
│   └── audio_quality.py
│
└── main.py
```

---

## 38. PlaybackManager 應至少提供這些 API

```python
class PlaybackManager:
    async def start(self): ...
    async def enqueue(self, pcm, timestamp): ...
    async def stop_immediately(self): ...
    async def pause(self): ...
    async def resume(self): ...
    async def flush(self): ...
    def is_playing(self) -> bool: ...
    def buffered_ms(self) -> float: ...
```

其中：

```text
stop_immediately()
```

是 barge-in 的核心 API。

---

## 39. InterruptionManager 應至少提供

```python
class InterruptionManager:
    async def on_vad_start(self, timestamp):
        ...

    async def on_vad_end(self, timestamp):
        ...

    async def on_stt_final(self, text):
        ...

    async def confirm(self):
        ...

    async def cancel(self):
        ...
```

狀態由：

```text
assistant_speaking
vad_active
candidate_started_at
stt_has_transcript
```

共同決定。

---

## 40. 參考程式碼與原始碼總表

### A. WebRTC Audio Processing Module

用途：AEC3 / NS / AGC / reverse stream / delay model。

- Repository: https://webrtc.googlesource.com/src/
- APM API: https://webrtc.googlesource.com/src/+/main/modules/audio_processing/include/audio_processing.h

### B. LiveKit Python SDK

用途：Python 本機 mic/speaker full duplex、APM reverse path、10 ms frame。

- Repository: https://github.com/livekit/python-sdks
- MediaDevices: https://github.com/livekit/python-sdks/blob/main/livekit-rtc/livekit/rtc/media_devices.py
- Example: https://github.com/livekit/python-sdks/blob/main/examples/basic_room.py

### C. LiveKit Agents

用途：barge-in、false interruption、adaptive interruption、AEC warm-up。

- Repository: https://github.com/livekit/agents
- Turn handling docs: https://docs.livekit.io/reference/agents/turn-handling-options/
- Adaptive interruption: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- Basic voice agent: https://github.com/livekit/agents/blob/main/examples/voice_agents/basic_agent.py
- AgentSession: https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py

### D. pywebrtc-audio

用途：較輕量的 Python WebRTC APM/AEC3 binding。

- Repository: https://github.com/strands-labs/pywebrtc-audio
- PyPI: https://pypi.org/project/pywebrtc-audio/

### E. OHF-Voice Linux Voice Assistant

用途：Linux/PipeWire/PulseAudio AEC 實務。

- Repository: https://github.com/OHF-Voice/linux-voice-assistant
- AEC guide: https://github.com/OHF-Voice/linux-voice-assistant/blob/main/docs/enabling_aec.md

### F. OpenAI Realtime API

用途：server VAD / semantic VAD / interrupt response 的 API 設計參考。

- Realtime server events: https://developers.openai.com/api/reference/resources/realtime/server-events
- Realtime client events: https://developers.openai.com/api/reference/resources/realtime/client-events

### G. AIRI

用途：持續收音、VAD-triggered voice input、實際遇到 pre-roll 問題的案例。

- Repository: https://github.com/moeru-ai/airi
- Voice input issue: https://github.com/moeru-ai/airi/issues/2092

---

## 41. 來源的可信度與用途分級

| 來源 | 類型 | 建議用途 |
|---|---|---|
| WebRTC APM | 業界成熟底層音訊處理 | **核心 AEC 技術依據** |
| LiveKit Python SDK | 大型開源 realtime stack | **Python AEC/full-duplex 實作參考** |
| LiveKit Agents | 生產導向 voice-agent framework | **barge-in / interruption 策略** |
| OpenAI Realtime API | 商用 realtime voice API | **VAD/interrupt API 行為參考** |
| OHF-Voice | 真實 Linux voice assistant | **OS-level AEC 實務** |
| pywebrtc-audio | WebRTC Python binding | **standalone Python 落地最方便的候選** |
| AIRI | AI Companion | **持續收音與 pre-roll 問題案例** |

---

## 42. 最終推薦方案

若目標是你目前規劃的：

```text
Python Companion
+
continuous mic
+
automatic segmentation
+
user can interrupt AI
+
OpenAI-compatible STT / LLM
+
Fish Audio / OpenAI-compatible TTS
```

推薦採用：

```text
                    ┌────────────────────────────┐
                    │       Companion Core       │
                    └────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
                 INPUT                       OUTPUT
                    │                           │
             Microphone capture            TTS stream
                    │                           │
                    ▼                           ▼
               WebRTC AEC3                Playback Queue
                    │                           │
                    │                     Speaker output
                    │                           │
                    └────── reverse ref ◄──────┘
                    │
                    ▼
                   NS
                    │
                    ▼
                   VAD
                    │
              ┌─────┴─────┐
              │           │
          normal turn   AI speaking
              │           │
              ▼           ▼
             STT      Barge-in detector
                          │
                          ▼
                    stop/flush speaker
                          │
                          ▼
                         STT
                          │
                          ▼
                         LLM
                          │
                          ▼
                         TTS
```

### 實作上的第一選擇

**Standalone Python：**

```text
sounddevice / PyAudio
        +
pywebrtc-audio / WebRTC APM
        +
local VAD
        +
asyncio state machine
        +
short playback queue
        +
300 ms pre-roll
        +
streaming STT/LLM/TTS
```

### 如果希望少自己處理 AEC plumbing

```text
LiveKit MediaDevices
        +
自己的 STT/LLM/TTS API
```

### 不建議第一版做的事

```text
自己寫 AEC
自己猜 delay
AI speaking 時直接停 mic
等待 STT 後才 interrupt
不保存 raw audio
不做 pre-roll
同時疊多層 AEC
```

---

## 43. 第一個可驗證 prototype 的最小閉環

正式接 LLM 前，先做這個：

```text
Mic
 ↓
WebRTC AEC3
 ↓
VAD
 ↓
Barge-in
 ↓
Speaker stop
```

測試：

```text
1. AI 播放連續 TTS
2. 使用者等待 1 秒
3. 使用者說「停」
4. 記錄：
   - raw mic
   - AEC output
   - far reference
   - VAD start
   - playback stop
5. 計算 barge-in latency
6. 檢查「停」是否完整保留
```

只有這個 prototype 通過，再接：

```text
STT → LLM → TTS
```

這樣最容易把「AEC 問題」和「API latency 問題」分開。

---

## 44. 最終設計原則（供開發時直接貼在 README）

```text
1. Mic 永遠可持續 capture。
2. AI speaking != microphone off。
3. AEC 負責移除 speaker echo，不負責 turn decision。
4. AEC 必須取得正確 far-end playback reference。
5. AEC delay 必須由本機 audio path 決定，不受網路 RTT 影響。
6. VAD 在本機運作，用來快速發現 speech start。
7. Barge-in 必須先於 STT/LLM/TTS 完成。
8. TTS 播放必須可立即 cancel + flush。
9. 所有 speech segment 保留約 200–500 ms pre-roll。
10. raw mic / AEC output / far reference / timestamps 必須可記錄。
11. 不要疊多層 AEC，除非經過實測驗證。
12. AEC 以「不傷害 user speech」為品質要求，而不是只看 echo 有沒有變小。
13. false interruption 必須有 recovery 機制。
14. 所有 latency 必須拆成 local audio、network、STT、LLM、TTS、playback 等部分量測。
15. 正式上線前必須在實際麥克風、喇叭、音量、房間環境下做 double-talk 測試。
```

---

## 45. 重要說明

本文件的目的不是保證任何單一 AEC library 在所有電腦與房間都「絕對不會」誤消使用者語音。AEC 是高度依賴：

- 麥克風與 speaker 位置
- speaker 音量
- room acoustics
- device driver
- capture/render buffer
- hardware clock
- audio routing
- OS audio stack

的 DSP 問題。

因此最安全的工程策略不是「找一個號稱完美 AEC 的套件」，而是：

```text
成熟 WebRTC AEC3
       +
正確 far-end reference
       +
正確 delay
       +
10 ms processing
       +
pre-roll
       +
local barge-in
       +
false-interruption recovery
       +
raw/AEC 雙路記錄
       +
真實設備測試
```

這才是可以逐步驗證、定位問題並進入 production 的方案。


---

# 第二次實作前審查：AEC + Barge-in 尚缺的關鍵事項

> **本節是 2026-10-07 重新依「現在就要開始寫 Python 實作」的標準補強。前面的架構仍成立，但下列事項若不補上，實際上線後最容易遇到的問題會集中在：AEC reference 錯位、音訊 thread 抖動、speaker buffer 拖尾、取消競態、Bluetooth route、以及 AEC 過度消除 user speech。**

## 46. P0：Capture/Render/APM 必須共用一個「可驗證的時間軸」

### 46.1 不只要有 `frame`，每個 frame 都要有 timestamp

建議每個 10 ms frame 都保存：

```python
@dataclass(slots=True)
class AudioFrame:
    seq: int
    timestamp_ns: int          # monotonic/perf_counter_ns domain
    pcm: np.ndarray
    sample_rate: int
    channels: int
    kind: Literal["capture", "render"]
```

不要用 `datetime.now()` 當 audio clock；應使用 monotonic clock，例如：

```python
from time import perf_counter_ns

now_ns = perf_counter_ns()
```

### 46.2 Render frame 必須具有 sequence number

例如：

```text
render #100 ──────► speaker callback
render #101 ──────► speaker callback
render #102 ──────► speaker callback
```

capture frame 也有：

```text
capture #900
capture #901
capture #902
```

AEC pairing 不應用「目前 queue 第 N 個」這種脆弱方法，而要依時間戳、裝置 timing 與 `stream_delay_ms` 來定義對應關係。

### 46.3 WebRTC 官方 delay 定義應直接寫入實作規格

WebRTC 對 client-side delay 的定義是：

```text
delay = (t_render - t_analyze)
      + (t_process - t_capture)
```

其中：

- `t_analyze`：far/render frame 交給 APM 的時間
- `t_render`：同一 frame 第一個 sample 真正由 audio hardware render 的時間
- `t_capture`：對應 near/capture frame 第一個 sample 被硬體捕捉的時間
- `t_process`：同一 capture frame 被交給 APM 的時間

這個定義比「硬編碼 40 ms」可靠得多。

來源：WebRTC `set_stream_delay_ms()` API。

---

## 47. P0：不要把 `stream_delay_ms=40` 當永久設定

原文件中的 `40 ms` 只能視為 prototype hint，正式版不應永久硬編碼。

### 正確優先順序

```text
1. 裝置 / PortAudio timing 可取得
        ↓
2. 每個 frame 計算 capture + render buffer delay
        ↓
3. 對 delay 做平滑 / 限幅
        ↓
4. 更新 APM stream delay
```

如果沒有可靠的 device timestamp，再退而求其次：

```text
播放已知測試訊號
      ↓
錄製 microphone
      ↓
cross-correlation
      ↓
估計「speaker → mic」主峰延遲
```

### 不應該做

```python
stream_delay_ms = 40
# 永久固定所有電腦、所有 speaker、所有 mic
```

因為不同：

- USB DAC
- USB microphone
- HDMI audio
- Bluetooth
- OS mixer
- driver buffer
- speaker 距離

都會改變時間關係。

---

## 48. P0：播放裝置「持續開啟」，不要每句 TTS 反覆 open/close

推薦：

```text
Application startup
    ↓
open mic stream once
open speaker stream once
    ↓
整個 Companion session 持續維持
```

沒有 TTS 時：

```text
speaker output = zeros
far/reference   = zeros
```

有 TTS 時：

```text
speaker output = actual rendered PCM
far/reference   = 同一個 actual rendered PCM
```

如果每個 turn 都 close/open，會同時改變 device buffer、device clock、PortAudio timing、AEC convergence、Bluetooth profile、OS route。

### Barge-in 時也不要關閉 output device

應該：

```text
BARGE-IN
   ↓
cancel TTS producer
   ↓
clear application playback queue
   ↓
next render callback output zeros
   ↓
far reference = zeros
```

這樣 AEC 的時間軸仍然連續。

---

## 49. P0：`stop_immediately()` 其實不能保證「硬體立即無聲」

```text
Application queue
      ↓
OS audio buffer
      ↓
DAC / hardware buffer
      ↓
Speaker
```

當使用者插話時，已經進入 OS/hardware buffer 的資料不一定能跨平台瞬間清除。

因此真正可以控制的是：

```text
t_interrupt
   ↓
不再產生新的 TTS frame
   ↓
next callback 全部輸出 zero
   ↓
剩餘 hardware tail <= 已量測 output latency
```

要量測：

```text
speaker_tail_ms = interrupt command → physical silence
```

而不是只量 Python queue clear time。

### 工程上的處理

先測：

```text
10 ms
20 ms
40 ms
```

找出在目標硬體上「不爆音、不 underrun」的最小穩定 output buffer。

不要因 framework 預設 100 ms I/O blocksize，就把 100 ms 當成 barge-in 延遲；LiveKit 目前的 `MediaDevices` 內部仍以 10 ms frame 做 APM，但其 sounddevice I/O blocksize 預設可為 100 ms。

---

## 50. P0：一定要防止「舊 TTS chunk 在取消後又跑出來」

純 `asyncio.cancel()` 常漏掉競態：

```text
Turn 15 TTS
   ↓
chunk A
chunk B
chunk C

User barge-in
   ↓
cancel Turn 15
   ↓
Turn 16 starts
```

如果 chunk C 已經在另一個 queue / worker 裡，仍可能被播放。

### 建議加入 `turn_id`

```python
@dataclass(slots=True)
class PlaybackChunk:
    turn_id: int
    pcm: bytes
    timestamp_ns: int

class PlaybackManager:
    def __init__(self):
        self.current_turn_id = 0

    def accept(self, chunk: PlaybackChunk) -> bool:
        return chunk.turn_id == self.current_turn_id

    def interrupt(self) -> None:
        self.current_turn_id += 1
        self.clear_queue()
```

LLM / TTS 也使用相同的 generation token：

```text
turn_id = 17
    ↓
LLM 17
    ↓
TTS 17

barge-in
    ↓
current_turn_id = 18

任何 late chunk(turn_id=17)
    ↓
DISCARD
```

這個機制應視為 P0。

---

## 51. P0：Barge-in 不要只有「第一個 VAD frame 就 hard-stop」

如果只做：

```text
VAD start
 ↓
立即 stop speaker
```

很容易把 AEC residual echo、咳嗽、短 backchannel、背景電視等都變成硬中斷。

### 推薦的兩階段策略

```text
VAD speech-start
       ↓
INTERRUPT_CANDIDATE
       ↓
speaker duck / mute in next 10–20 ms frame
       ↓
收集額外 80–150 ms 音訊
       ↓
確認
       ├─ genuine → HARD INTERRUPT
       └─ false   → restore playback
```

推薦先做 `duck = -12 dB ~ -18 dB`，而不是 candidate 一出現就完全 mute。

確認後才：

```text
cancel TTS
clear queue
output zero
```

---

## 52. P0：建議「VAD + Echo Guard」雙路判斷，不要只相信 APM 的 speech probability

`pywebrtc-audio` 的 `speech_probability` 主要來自其 pipeline 中的 speech analysis；它不是專門為「AI 正在播放時的 barge-in」訓練的 classifier。

正式版建議：

```text
                     ┌─ raw mic metrics ──────┐
                     │                         │
Mic ──► AEC/NS ──► clean speech VAD ─────────┤
                     │                         ├─► Barge-in decision
Speaker far ref ──► far energy / correlation ─┤
                     │                         │
                     └─► optional dedicated VAD┘
```

最低成本 echo guard 可監控：

```text
far_rms
raw_rms
clean_rms
vad_clean
```

若 `far_rms` 很高、`clean_rms` 很低且 clean-VAD=false，很像純 speaker echo，不要因 raw audio 很大就 interrupt。

第一版可研究：

- WebRTC VAD：低成本、10/20/30 ms frame、8/16/32/48 kHz。
- Silero VAD：neural VAD，現行 repository 仍提供 streaming 路徑。

原則：

> **AEC 負責去 echo，dedicated VAD 負責 speech decision。兩者不要互相取代。**

---

## 53. P0：第一版建議先「關掉 AGC」，等 AEC 穩定後再開

原文件示範：

```python
auto_gain_control=True
```

可以作為 feature demo；但驗證 AEC + barge-in 的第一個 prototype 建議先固定 gain：

```python
AudioProcessor(
    sample_rate=16000,
    num_channels=1,
    echo_cancellation=True,
    noise_suppression=False,
    auto_gain_control=False,
    stream_delay_ms=measured_delay_ms,
)
```

先固定：

```text
mic gain
speaker volume
AEC
VAD
```

AEC / VAD 穩定後，再逐項加入：

```text
NS
AGC2
```

並比較 STT / WER / residual echo。

---

## 54. P0：AEC warm-up 不應直接寫死 200–500 ms

LiveKit Agents 現行 `aec_warmup_duration` 預設為 3 秒，其用途就是 agent 開始說話後暫時不接受 interruption，讓 AEC 有時間建立穩定狀態。

因此本專案應定義：

```text
AEC_WARMUP = 可設定參數
```

而不是永久固定 200 ms。

推薦量測：

```text
TTS playback starts
        ↓
record far + raw mic + AEC output
        ↓
觀察 residual echo / clean VAD
        ↓
決定本機最短穩定 warm-up
```

而不是直接引用 LiveKit 的 3 秒作為本專案固定值。

更理想的是：

```text
仍收音
仍做 AEC
但短暫提高 barge-in decision threshold
```

這樣 user audio 仍會留在 ring buffer。

---

## 55. P0：AEC reset 的時機要明確

至少在下列情況考慮 reset / reinitialize：

```text
input device change
output device change
sample-rate change
channel-count change
Bluetooth profile change
long audio stream restart
APM error / repeated frame mismatch
```

同時避免「每句 TTS 都 reset」，否則每個 turn 都重新收斂。

原則：

```text
same hardware route → keep AEC state
route / format changed → reset AEC
```

---

## 56. P0：Bluetooth 必須列為獨立硬體模式

Windows 官方資料目前明確指出：

- A2DP 是 stereo output-only。
- 使用 Bluetooth microphone 時要使用 HFP。
- HFP 是 simultaneous mono capture + mono playback。
- Windows 會因 microphone usage 在 A2DP/HFP 間切換，且可能改變 sample rate / route。

因此 Bluetooth headset 不能只視為「另一個 speaker」。

至少測：

```text
1. 內建 mic + 內建 speaker
2. USB mic + 內建 speaker
3. USB mic + USB speaker
4. wired headset
5. Bluetooth HFP
6. Bluetooth A2DP + separate mic
```

並記錄：

```text
audio route
sample rate
buffer size
input/output device id
profile
```

若某 route 在 OS/driver 上無法穩定同時 input/output，應標記 unsupported，而不是要求 AEC 解決 OS routing 問題。

---

## 57. P0：Windows 使用「實際 render reference」時，可考慮 WASAPI loopback

如果 Companion 不只播放自己的 TTS，系統同時還可能有 music / browser / notification 等聲音，單純餵「自己的 TTS PCM」並不等於 speaker 實際播放的全部內容。

Windows WASAPI loopback 可以 capture 某個 render endpoint 正在播放的 audio stream；Microsoft 官方也明確指出 loopback mode 可用於 acoustic echo cancellation。

因此：

```text
只有自己的 TTS
    → 最終 playback mixer PCM = AEC reference

系統整體混音也會漏進 mic
    → WASAPI loopback = 更接近實際 render reference
```

但 loopback 包含整個 system mix，不等於所有聲音都是 user / AI conversation。

---

## 58. P1：Audio buffer 必須 bounded，capture 丟 frame 要視為嚴重錯誤

network queue 可以設計成 bounded + drop policy；AEC capture queue 不宜默默 drop frame。

如果：

```text
capture queue > capacity
```

通常表示：

```text
DSP processing < real time
```

這時要：

```text
log + metric
→ audio pipeline degraded
→ 必要時 reset/reopen
```

而不是把 overflow 吞掉。

---

## 59. P1：加入「AEC calibration mode」

建議做：

```bash
python tools/calibrate_audio.py
```

流程：

```text
1. enumerate input/output device
2. 顯示 sample rate / channels / buffer
3. 播放已知 calibration sequence
4. 同時 capture mic
5. 保存 far_reference.wav / raw_mic.wav
6. cross-correlate
7. 顯示 estimated delay
8. 顯示 residual echo curve
9. 建議 stream_delay_ms
```

這會比在主程式猜 `30? 40? 50?` 有效得多。

---

## 60. P1：增加 AEC offline regression test

保留固定 fixture：

```text
fixtures/
├── far_only.wav
├── near_only.wav
├── double_talk.wav
├── noisy_double_talk.wav
├── speech_with_echo.wav
└── speaker_change.wav
```

每次修改：

- AEC config
- NS level
- AGC
- sample rate
- buffering

都重新跑。

至少驗證：

```text
speech preservation
residual echo
VAD detection
STT transcript
```

---

## 61. P1：增加三個 diagnostic mode

### Mode A — AEC only

```text
Mic + Speaker
  ↓
AEC
  ↓
WAV
```

### Mode B — VAD only

```text
AEC output
  ↓
VAD
  ↓
visual timeline
```

### Mode C — Barge-in only

```text
fake TTS
  ↓
Speaker
  ↓
Mic
  ↓
AEC + VAD
  ↓
stop speaker
```

只有這三個都穩定後，再接 STT/LLM/TTS。

---

## 62. P1：加入 playback gain change 測試

至少測：

```text
TTS volume = 100%
TTS volume = 50%
TTS volume = 20%
volume changed while speaking
```

AEC reference 必須對應**實際 render frame**，不能繼續拿未經 volume scaling 的 logical TTS PCM 當 reference。

---

## 63. P1：加入 route-change / hot-plug handling

例如 AI speaking 中拔掉 USB headset：

```text
USB headset disconnected
        ↓
OS reroutes speaker
        ↓
AEC old acoustic path invalid
```

系統應：

```text
pause / reinitialize audio route
reset AEC
recompute device timing
resume playback
```

---

## 64. 修正後的完整 real-time pipeline

```text
                 ┌─────────────────────────────┐
                 │        APPLICATION          │
                 │   STT ←→ LLM ←→ TTS        │
                 │       async / network      │
                 └─────────────┬───────────────┘
                               │ TTS PCM
                               ▼
                   ┌────────────────────────┐
                   │ Playback Mixer / Queue │
                   │ turn_id + bounded buf  │
                   └───────────┬────────────┘
                               │
                         final rendered PCM
                               │
                  ┌────────────┴─────────────┐
                  │                          │
                  ▼                          ▼
               Speaker               AEC far reference
                  │                          │
                  │ acoustic                 │
                  ▼                          │
Mic ──► capture frame ──► AEC3 ◄─────────────┘
                              │
                              ▼
                         NS / optional AGC
                              │
                 ┌────────────┴─────────────┐
                 │                          │
                 ▼                          ▼
           pre-roll ring                local VAD
                                            │
                              ┌─────────────┴─────────────┐
                              │                           │
                         AI speaking                 AI idle
                              │                           │
                              ▼                           ▼
                       Echo guard /                  normal
                       candidate                     STT turn
                              │
                     80–150 ms confirmation
                              │
                     ┌────────┴────────┐
                     │                 │
                   false             true
                     │                 │
                     ▼                 ▼
                  resume        increment turn_id
                                   cancel TTS
                                   clear queue
                                   output zeros
                                      │
                                      ▼
                                     STT
```

---

## 65. 修正後的第一版正式 prototype 推薦設定

### Audio

```python
SAMPLE_RATE = 48000       # 若裝置與 AEC pipeline 能穩定使用
CHANNELS = 1
FRAME_MS = 10
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
```

若 STT 偏好 16 kHz：

```text
48 kHz capture
    ↓
AEC at stable device rate
    ↓
AEC output
    ↓
16 kHz resample
    ↓
STT
```

不要在 AEC 前後任意改 sample rate，讓 near/far 的格式與時間軸保持可驗證。

### AEC

第一版：

```python
AudioProcessor(
    sample_rate=SAMPLE_RATE,
    num_channels=1,
    echo_cancellation=True,
    noise_suppression=False,
    auto_gain_control=False,
    stream_delay_ms=measured_delay_ms,
)
```

### VAD

第一版可先用：

```text
WebRTC VAD 或 Silero VAD
```

不要直接把：

```python
ap.speech_probability
```

當唯一 barge-in gate。

### Buffer

```text
pre-roll           300 ms
render queue       20–100 ms（需實測）
hardware buffer    儘量 10–40 ms
candidate window   80–150 ms
```

這些都是工程起始值，不是標準答案。

---

## 66. 最終不可省略 Checklist

### P0 — 開始寫 code 前

- [ ] 明確選定一套 AEC：native WebRTC / LiveKit APM / pywebrtc-audio 三選一
- [ ] 明確定義 far-end reference 來源
- [ ] 明確定義 capture/render timestamp domain
- [ ] 明確定義 `stream_delay_ms` 的量測方式
- [ ] mic/speaker stream 持續開啟
- [ ] output buffer 尺寸已量測
- [ ] `turn_id` / generation token 已設計
- [ ] pre-roll ring buffer 已設計
- [ ] raw / AEC / far reference logging 已設計
- [ ] route-change / reset 已設計

### P0 — 第一個 Prototype

- [ ] AI 不說話 + user speech
- [ ] AI 說話 + user silence
- [ ] AI 說話 + user barge-in
- [ ] AI / user double-talk
- [ ] AEC warm-up
- [ ] output tail measurement
- [ ] AEC delay calibration

### P1 — 接 API 前

- [ ] AEC regression WAV set
- [ ] VAD regression set
- [ ] false interruption test
- [ ] old TTS chunk race test
- [ ] Bluetooth route test
- [ ] USB unplug / replug test
- [ ] system volume change test
- [ ] speaker / mic sample-rate change test

---

## 67. 這次審查後對原文件的核心修正

原文件的核心方向正確，但要真正開工，以下 8 點必須視為新增工程硬規則：

```text
1. AEC 不能只是「放進 asyncio worker」；它必須留在可預測的 real-time audio path。
2. `stream_delay_ms` 不可永久寫死 40 ms，應使用裝置 timing / calibration。
3. Mic 與 speaker stream 儘量整個 session 持續開啟，不要每句重建。
4. `stop_immediately()` 的真正限制是 hardware output tail，而不是 Python queue。
5. LLM/TTS cancellation 必須用 turn_id/generation token 防 stale audio。
6. Barge-in 應採 candidate → confirm，而不是 VAD 第一個 frame 就 hard-stop。
7. APM speech_probability 不應成為唯一 barge-in classifier；增加 dedicated VAD / echo guard。
8. Bluetooth / route change / AGC / output volume 都是獨立的 AEC 變因，必須單獨測試。
```

---

## 68. 本次補強所依據的新增公開來源

### WebRTC APM

- Audio Processing API：
  https://webrtc.googlesource.com/src/+/refs/heads/main/api/audio/audio_processing.h
- APM header（10 ms、render/capture threading、delay 說明）：
  https://webrtc.googlesource.com/src/+/0695df1a5990ffd02cff4f7b49a865d7085f9d0b/modules/audio_processing/include/audio_processing.h

### LiveKit Python MediaDevices

- https://github.com/livekit/python-sdks/blob/main/livekit-rtc/livekit/rtc/media_devices.py

目前原始碼明確採：

- 同一 APM instance 接 capture + reverse path
- output callback 將實際 render frame 餵回 APM
- 以 PortAudio timing 計算 stream delay
- APM 以 10 ms frame 處理

### LiveKit Agents

- AgentSession / AEC warm-up：
  https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py
- Basic voice agent：
  https://github.com/livekit/agents/blob/main/examples/voice_agents/basic_agent.py
- Turn handling：
  https://docs.livekit.io/reference/agents/turn-handling-options/
- Adaptive interruption：
  https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- Turn-taking tuning：
  https://docs.livekit.io/agents/logic/turns/tuning/

### pywebrtc-audio

- https://github.com/strands-labs/pywebrtc-audio
- Real-time callback example：
  https://github.com/strands-labs/pywebrtc-audio/blob/main/examples/pyaudio_realtime.py
- Unit tests：
  https://github.com/strands-labs/pywebrtc-audio/tree/main/tests

### VAD

- WebRTC VAD Python binding：
  https://github.com/wiseman/py-webrtcvad
- Silero VAD：
  https://github.com/snakers4/silero-vad

### Windows audio routing / loopback

- WASAPI Loopback Recording：
  https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
- Windows Bluetooth Classic Audio：
  https://learn.microsoft.com/en-us/windows-hardware/drivers/bluetooth/bluetooth-classic-audio

### AIRI

- pre-roll issue #2092：
  https://github.com/moeru-ai/airi/issues/2092

---

## 69. 審查結論

**原文件的核心方向正確，但第一次版本還不足以直接進 production-like 實作。**

重新檢查後，真正需要優先補的是：

```text
時間軸
  ↓
AEC reference
  ↓
real-time threading
  ↓
output hardware tail
  ↓
turn cancellation race
  ↓
VAD / echo guard
  ↓
device route
```

而不是再增加更多 LLM / STT / TTS 功能。

若依本 v2 執行，建議先完成：

```text
Phase 1
  Audio device enumeration
      ↓
Phase 2
  Continuous mic + speaker
      ↓
Phase 3
  WebRTC AEC3 + far reference
      ↓
Phase 4
  Delay calibration
      ↓
Phase 5
  Dedicated VAD + barge-in candidate
      ↓
Phase 6
  Playback cancel / turn_id
      ↓
Phase 7
  Offline + live regression
      ↓
Phase 8
  STT / LLM / TTS integration
```

這個順序可以最大程度避免「API 都接好了，最後才發現 AEC / 音效裝置時間軸有問題」的返工。
