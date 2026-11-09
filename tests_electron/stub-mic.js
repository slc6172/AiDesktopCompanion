// Preload: simpler fake microphone (a constant silent stream) that counts getUserMedia calls in
// window.__gumCalls. GUM_FAIL=1 (set by run.sh) makes it reject, like a denied permission.
(() => {
  window.__gumCalls = 0;
  if (typeof process !== "undefined" && process.env && process.env.GUM_FAIL === "1") window.__GUM_FAIL = true;  // simulate a denied permission
  const gum = async () => {
    window.__gumCalls++;
    if (window.__GUM_FAIL) throw new DOMException("denied", "NotAllowedError");
    const ctx = new AudioContext();
    const dest = ctx.createMediaStreamDestination();
    return dest.stream;
  };
  if (!navigator.mediaDevices) Object.defineProperty(navigator, "mediaDevices", { value: {}, configurable: true });
  navigator.mediaDevices.getUserMedia = gum;
})();
