// Preload (contextIsolation:false). A fake microphone: oscillator -> GainNode -> MediaStreamDestination.
// window.__setLevel(rms): a sine of amplitude A has RMS A/sqrt(2), so gain = rms * sqrt(2).
// The page's volume reading therefore equals the number you pass (when the page measures RMS).
(() => {
  let ctx = null, gain = null, dest = null, level = 0;
  window.__gumCalls = 0;
  if (typeof process !== "undefined" && process.env && process.env.GUM_FAIL === "1") window.__GUM_FAIL = true;  // simulate a denied permission
  window.__setLevel = (rms) => { level = rms; if (gain) gain.gain.value = rms * Math.SQRT2; };
  const build = () => {
    if (ctx) return;
    ctx = new AudioContext();
    const osc = ctx.createOscillator();
    osc.frequency.value = 440;
    gain = ctx.createGain();
    gain.gain.value = level * Math.SQRT2;
    dest = ctx.createMediaStreamDestination();
    osc.connect(gain); gain.connect(dest); osc.start();
    window.__micCtx = ctx;
  };
  const gum = async (constraints) => {
    window.__gumCalls++;
    window.__gumConstraints = JSON.parse(JSON.stringify(constraints || {}));
    if (window.__GUM_FAIL) throw new DOMException("denied", "NotAllowedError");
    build();
    if (ctx.state === "suspended") await ctx.resume();
    return dest.stream;
  };
  if (!navigator.mediaDevices) Object.defineProperty(navigator, "mediaDevices", { value: {}, configurable: true });
  navigator.mediaDevices.getUserMedia = gum;
})();
