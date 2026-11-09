// Voice-activity detector: a pure state machine, independent of browser APIs.
// Optional adaptive noise tracking helps raise the speech gate above steady low-level room noise;
// it is deliberately only a first-stage gate, not a speech-recognition model or an AEC replacement.
class VoiceActivityDetector {
  constructor({ threshold = 0.02, releaseThreshold = null, attackMs = 0, silenceMs = 700, minMs = 500, maxMs = 20000, onChange = null, adaptive = false, noiseMultiplier = 3, noiseFloor = null, noiseAlpha = 0.025, maxThresholdMultiplier = 2.5, speakingBoost = 1, tailMs = 400 } = {}) {
    this._baseThreshold = Math.max(0, threshold);
    this._threshold = this._baseThreshold;
    this._releaseRatio = Number.isFinite(releaseThreshold) && threshold > 0
      ? Math.min(1, Math.max(0, releaseThreshold / threshold)) : 1;
    this._releaseThreshold = Number.isFinite(releaseThreshold) ? Math.min(threshold, Math.max(0, releaseThreshold)) : threshold;
    this._attackMs = Math.max(0, attackMs);
    this._candidateAt = null;
    this._silenceMs = silenceMs;
    this._minMs = minMs;
    this._maxMs = Math.max(minMs, maxMs);
    this._onChange = onChange;
    this._adaptive = Boolean(adaptive);
    this._noiseMultiplier = Math.max(1, noiseMultiplier);
    this._noiseAlpha = Math.min(0.25, Math.max(0.001, noiseAlpha));
    this._maxThreshold = this._baseThreshold * Math.max(1, maxThresholdMultiplier);
    this._noiseFloor = Number.isFinite(noiseFloor) ? Math.max(0, noiseFloor) : this._baseThreshold * 0.2;
    this._activeReleaseThreshold = this._releaseThreshold;
    // Only a real number above 1 raises the bar; anything else (missing, 0.5, NaN, "2.5") means "no boost".
    this._speakingBoost = typeof speakingBoost === "number" && Number.isFinite(speakingBoost) && speakingBoost > 1 ? speakingBoost : 1;
    this._tailMs = tailMs;
    this._lastSpeakingAt = -Infinity;
    this.state = "idle"; // idle | speaking
  }

  getThreshold() { return this._threshold; }
  getNoiseFloor() { return this._noiseFloor; }

  handle(event) {
    if (event.type === "sample") this._sample(Number.isFinite(event.volume) ? Math.max(0, event.volume) : 0, event.at, event.speaking === true);
  }

  _updateThreshold() {
    const adaptiveThreshold = this._adaptive ? this._noiseFloor * this._noiseMultiplier : this._baseThreshold;
    this._threshold = Math.min(this._maxThreshold, Math.max(this._baseThreshold, adaptiveThreshold));
    this._releaseThreshold = this._threshold * this._releaseRatio;
  }

  // While the character talks her own voice leaks back into the mic (speakers, not headphones), so the
  // bar is higher then. Her voice keeps ringing in the room for `tailMs` after she stops.
  _echoFactor(at, speaking) {
    if (speaking) this._lastSpeakingAt = at;
    return speaking || at - this._lastSpeakingAt < this._tailMs ? this._speakingBoost : 1;
  }

  _sample(volume, at, speaking) {
    const factor = this._echoFactor(at, speaking);
    if (this.state === "idle") {
      this._updateThreshold();
      // Learn only from sub-gate samples while idle. Freeze the estimate during a candidate/speech
      // event so a real utterance does not teach the detector to ignore the user's voice. Also not while she
      // talks (or her echo tail rings): her echo is not steady room noise.
      if (this._adaptive && factor === 1 && this._candidateAt === null && volume < this._threshold) {
        this._noiseFloor += (Math.min(volume, this._baseThreshold * 1.5) - this._noiseFloor) * this._noiseAlpha;
        this._noiseFloor = Math.max(0.0001, Math.min(this._baseThreshold * 1.5, this._noiseFloor));
        this._updateThreshold();
      }
      if (volume < this._threshold * factor) {
        this._candidateAt = null;
        return;
      }
      if (this._candidateAt === null) this._candidateAt = at;
      if (at - this._candidateAt >= this._attackMs) {
        this.state = "speaking";
        this._startedAt = this._candidateAt;
        this._lastLoudAt = at;
        this._activeReleaseThreshold = this._releaseThreshold;
        this._candidateAt = null;
        this._fire({ type: "started" });
      }
      return;
    }

    // Freeze the gate for this utterance and use hysteresis to avoid splitting syllables.
    if (volume >= this._activeReleaseThreshold * factor) this._lastLoudAt = at;

    if (at - this._startedAt >= this._maxMs) {
      const durationMs = Math.min(this._maxMs, Math.max(0, this._lastLoudAt - this._startedAt));
      this.state = "idle";
      this._candidateAt = null;
      this._fire({ type: durationMs < this._minMs ? "too_short" : "max_duration", durationMs });
      return;
    }
    if (at - this._lastLoudAt >= this._silenceMs) {
      const durationMs = this._lastLoudAt - this._startedAt;
      this.state = "idle";
      this._candidateAt = null;
      this._fire({ type: durationMs < this._minMs ? "too_short" : "finished", durationMs });
    }
  }

  _fire(event) { if (this._onChange) this._onChange(event); }
}

if (typeof module !== "undefined") module.exports = { VoiceActivityDetector };
else globalThis.VoiceActivityDetector = VoiceActivityDetector;
