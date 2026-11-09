// Ticket 55 acceptance: one ~1.3 s utterance (she is NOT talking) through the new capture pipeline.
// Expect: a WAV upload of about 2.3 s (400 ms pre-roll + 1300 ms voice + ~700 ms VAD tail), both header groups
// (X-Voice-*, X-Clip-Meta), and with COMPANION_DEBUG_LOG=1 one "[audio]" line in the server log.
// run: COMPANION_DEBUG_LOG=1 PROJ=<project> CTXISO=0 ../run.sh s55_capture.js ../stub-osc.js
const wait = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = async (win, shot, ev) => {
  console.log("page:", await ev(`document.documentElement.innerHTML.includes('X-Clip-Meta') ? 'has X-Clip-Meta' : 'NO X-Clip-Meta'`));
  await ev(`window.__uploads = []; const f = window.fetch; window.fetch = async function (url, opts) {
    if (String(url).includes('/chat/audio')) { const b = opts.body; const buf = await b.arrayBuffer(); const v = new DataView(buf);
      window.__uploads.push({ headers: opts.headers, bytes: buf.byteLength, type: b.type, rate: v.getUint32(24, true), seconds: (buf.byteLength - 44) / 2 / v.getUint32(24, true) }); }
    return f.apply(this, arguments); }; void 0`);
  await ev(`startContinuous(); void 0`); await wait(2500);
  console.log("mode:", await ev(`nativeAecMode`), "| threshold:", await ev(`vad.getThreshold().toFixed(4)`));
  await ev(`window.__setLevel(0.12); void 0`); await wait(1300); await ev(`window.__setLevel(0); void 0`);
  await wait(3500);
  console.log("uploads:", await ev(`JSON.stringify(window.__uploads, null, 1)`));
};
