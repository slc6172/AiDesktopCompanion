// Ticket 56: audio queue hygiene. Run on the ORIGINAL (p11e) page and on the merged page and compare.
//  A) stopAudio() with 1 playing + 2 queued items: how many object URLs are released? (merged: all 3)
//  B) a late "ended" event from an OLD audio element (after stopAudio + a new turn's audio started)
//     must not clear/advance the NEW turn's audio.
// run: PROJ=<project> CTXISO=0 ../run.sh s56_audio_queue.js ../stub-osc.js
const wait = (ms) => new Promise(r => setTimeout(r, ms));
function silentWavB64(seconds = 0.6, rate = 8000) {
  const n = Math.round(seconds * rate), b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n * 2, 4); b.write("WAVEfmt ", 8); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20);
  b.writeUInt16LE(1, 22); b.writeUInt32LE(rate, 24); b.writeUInt32LE(rate * 2, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34);
  b.write("data", 36); b.writeUInt32LE(n * 2, 40); return b.toString("base64");
}
module.exports = async (win, shot, ev) => {
  const which = await ev(`document.documentElement.innerHTML.includes('currentItemUrl') ? 'MERGED/P15-style queue (currentItemUrl)' : 'ORIGINAL queue (no currentItemUrl)'`);
  console.log("page:", which);
  const wav = silentWavB64();
  await ev(`window.__made = 0; window.__revoked = 0; const c = URL.createObjectURL.bind(URL), r = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = (x) => { window.__made++; return c(x); }; URL.revokeObjectURL = (u) => { window.__revoked++; return r(u); }; void 0`);

  // A) one playing + two queued, then stopAudio()
  await ev(`for (let i = 0; i < 3; i++) enqueue({ data: "${wav}", mime: "audio/wav", index: i }); void 0`);
  await wait(300);
  console.log("A) before stopAudio: made", await ev(`window.__made`), "| queue length", await ev(`queue.length`), "| current is set:", await ev(`!!current`));
  await ev(`stopAudio(); void 0`); await wait(100);
  console.log("A) after  stopAudio: revoked", await ev(`window.__revoked`), "of", await ev(`window.__made`), "(merged: 3 of 3; original leaks the queued ones)");

  // B) late 'ended' from an old element must not touch the new turn
  await ev(`window.__made = 0; window.__revoked = 0; window.__ended = 0; const h = player.handle.bind(player); player.handle = (e) => { if (e.type === "audio_ended") window.__ended++; return h(e); };
            enqueue({ data: "${wav}", mime: "audio/wav", index: 0 }); void 0`);
  await wait(300);
  await ev(`window.__old = current; stopAudio(); enqueue({ data: "${wav}", mime: "audio/wav", index: 0 }); void 0`);   // a new turn starts
  await wait(300);
  const newOne = await ev(`current && current !== window.__old`);
  await ev(`window.__old.dispatchEvent(new Event("ended")); void 0`);                                               // the OLD element reports "ended" late
  await wait(100);
  console.log("B) new turn's audio is current:", newOne, "| still current after the late 'ended':", await ev(`!!current && current !== window.__old`),
              "| audio_ended events sent:", await ev(`window.__ended`), "(expect 0 so far)");
};
