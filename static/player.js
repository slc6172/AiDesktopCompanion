const DEFAULT_EMOTIONS = ["neutral", "happy", "angry", "sad", "surprised"];

const LISTENING_ACCEPTS = ["listen_started", "listen_failed", "sent", "tick"];

class CharacterPlayer {
  constructor({ emotions = DEFAULT_EMOTIONS, fallback = "neutral", onChange = null,
                fillerAfterMs = 2000, onFiller = null } = {}) {
    this._fillerAfterMs = fillerAfterMs;
    this._onFiller = onFiller;
    this._onChange = onChange;
    this._emotions = emotions;
    this._fallback = fallback;
    this.state = "idle";
    this._reset();
  }

  _reset() {
    this._emotion = this._fallback;
    this._clipEmotions = new Map(); // emotion of each audio clip, by its index
    this._pending = 0; // audio clips received but not finished
    this._talking = false; // has any sound started this turn
    this._done = false;
    this._sentAt = null;
    this._fillerFired = false;
  }

  handle(event) {
    // While the user is speaking, leftovers of the interrupted reply are ignored.
    if (this.state === "listening" && !LISTENING_ACCEPTS.includes(event.type)) return;
    switch (event.type) {
      case "tick":
        if (this.state === "thinking" && !this._fillerFired && this._onFiller &&
            event.at - this._sentAt >= this._fillerAfterMs) {
          this._fillerFired = true;
          this._onFiller();
        }
        return;
      case "listen_started":
        this._reset(); // cut off whatever was being said
        this._set("listening");
        return;
      case "listen_failed":
        this._reset();
        this._set("idle");
        return;
      case "sent":
        this._reset();
        this._sentAt = event.at;
        this._set("thinking");
        return;
      case "audio":
        this._pending += 1;
        this._clipEmotions.set(event.index, this._emotions.includes(event.emotion) ? event.emotion : this._fallback);
        break;
      case "audio_started":
        this._talking = true;
        if (this._clipEmotions.has(event.index)) this._emotion = this._clipEmotions.get(event.index);
        break;
      case "audio_ended":
        this._pending = Math.max(0, this._pending - 1);
        break;
      case "done":
      case "error":
        this._done = true;
        break;
    }
    this._update();
  }

  _set(state) {
    if (state === this.state) return;
    this.state = state;
    if (this._onChange) this._onChange(state);
  }

  _update() {
    if (this._done && this._pending === 0) this._set("idle");
    else if (this._talking) this._set("talking:" + this._emotion);
  }
}

if (typeof module !== "undefined") module.exports = { CharacterPlayer };
else globalThis.CharacterPlayer = CharacterPlayer;
