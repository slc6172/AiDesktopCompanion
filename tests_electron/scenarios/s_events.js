// Intercept the VAD's own events (started / too_short / finished) for one noise burst.
const wait = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = async (win, shot, ev) => {
  await ev(`startContinuous(); void 0`); await wait(2500);
  await ev(`window.__ev = []; const o = vad._onChange; vad._onChange = (e) => { window.__ev.push(e.type + (e.durationMs !== undefined ? '(' + Math.round(e.durationMs) + 'ms)' : '')); return o(e); }; void 0`);
  await ev(`window.__setLevel(0.12); void 0`); await wait(350); await ev(`window.__setLevel(0); void 0`); await wait(3000);
  console.log("VAD events for a 350 ms burst:", await ev(`JSON.stringify(window.__ev)`));
};
