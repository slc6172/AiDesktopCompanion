"""Manual smoke test against the real Groq speech-to-text API. Needs GROQ_API_KEY (or a key stored via
`app.py --set-key-groq`). Usage: python smoke_stt.py path/to/any-recording.(webm|wav|mp3|m4a|ogg|flac)

No recording at hand? You do not need this script to check the microphone: open the chat panel in the
pet window, hold "按住說話" (or F2) and see your words appear (docs/install.md)."""
import os
import sys
import time

MIME_TYPES = {
    ".webm": "audio/webm", ".wav": "audio/wav", ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".flac": "audio/flac",
}  # spelled out: the standard library's guess for .webm is video/webm


def mime_type_for(path):
    extension = os.path.splitext(str(path))[1].lower()
    if extension not in MIME_TYPES:
        raise ValueError(f"不支援的副檔名「{extension}」;可用的是:{' '.join(MIME_TYPES)}")
    return MIME_TYPES[extension]


def main(argv):
    if len(argv) < 2:
        print("用法: python smoke_stt.py 錄音檔路徑(" + " ".join(MIME_TYPES) + ")")
        print("手邊沒有錄音的話,在桌寵視窗的聊天面板按住「按住說話」(或按住 F2),看到自己說的字出現就代表麥克風和辨識都正常。")
        return 1
    path = argv[1]
    try:
        mime_type = mime_type_for(path)
    except ValueError as error:
        print(error)
        return 1
    from companion.groq_stt import GroqSTT

    data = open(path, "rb").read()
    start = time.perf_counter()
    text = GroqSTT().transcribe(data, mime_type)
    elapsed = time.perf_counter() - start
    print(f"辨識耗時 {elapsed:.2f}s,{len(data)} bytes 音訊")
    print(f"逐字稿: {text!r}" if text else "逐字稿是空的(Groq 判斷沒聽到內容)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
