// Testable policy for selecting and validating browser-native echo cancellation.
// We intentionally use ONE AEC implementation: Chromium/WebRTC's capture path.
(function (root) {
  const RETRYABLE_CONSTRAINT_ERRORS = new Set(["OverconstrainedError", "ConstraintNotSatisfiedError", "TypeError", "NotSupportedError"]);

  function constraints(sampleRate, exactAec = true) {
    return {
      audio: {
        channelCount: { ideal: 1 },
        echoCancellation: exactAec ? { exact: true } : { ideal: true },
        noiseSuppression: { ideal: true },
        autoGainControl: { ideal: true },
        sampleRate: { ideal: sampleRate }
      }
    };
  }

  function inspectSettings(settings = {}) {
    const value = settings.echoCancellation;
    if (value === true) return { mode: "active", verified: true, message: "瀏覽器回報已啟用回音消除。" };
    if (value === false) return { mode: "disabled", verified: true, message: "此音訊輸入未啟用回音消除。" };
    return { mode: "unknown", verified: false, message: "瀏覽器未回報回音消除狀態；將使用較保守的插話判斷。" };
  }

  async function acquire(mediaDevices, sampleRate) {
    let stream;
    try {
      stream = await mediaDevices.getUserMedia(constraints(sampleRate, true));
    } catch (error) {
      if (!error || !RETRYABLE_CONSTRAINT_ERRORS.has(error.name)) throw error;
      stream = await mediaDevices.getUserMedia(constraints(sampleRate, false));
    }
    const track = stream.getAudioTracks && stream.getAudioTracks()[0];
    const settings = track && typeof track.getSettings === "function" ? track.getSettings() : {};
    const status = inspectSettings(settings);
    if (status.mode === "disabled") {
      if (stream.getTracks) stream.getTracks().forEach((item) => item.stop());
      const error = new Error("The selected audio input did not enable echoCancellation");
      error.code = "AEC_UNAVAILABLE";
      throw error;
    }
    return { stream, settings, status };
  }

  const api = { constraints, inspectSettings, acquire };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AudioCapturePolicy = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
