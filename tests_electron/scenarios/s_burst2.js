// Page-level: how does the page react to a short loud NOISE BURST while she is "talking"?
// (used to show that a 350 ms burst permanently cut her off in the Part-15 build but not in ours)
// run: PROJ=<project> CTXISO=0 ../run.sh s_burst2.js ../stub-osc.js
const wait = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = async (win, shot, ev) => {
  const which = await ev(`document.documentElement.innerHTML.includes('BARGE_IN_CONFIRM_MS') ? 'THEIR page (has BARGE_IN_CONFIRM_MS)' : (document.documentElement.innerHTML.includes('speakingBoost') ? 'MY page (has speakingBoost)' : 'unknown page')`);
  console.log("page actually loaded:", which);   // ALWAYS verify which page was served (cache!)
  await ev(`window.__stops = 0; const orig = stopAudio; stopAudio = function () { window.__stops++; return orig.apply(this, arguments); }; window.__aborts = 0; const oa = abortCurrentSend; abortCurrentSend = function () { window.__aborts++; return oa.apply(this, arguments); }; void 0`);
  await ev(`startContinuous(); void 0`); await wait(2500);
  for (const [label, rms, ms] of [["noise burst  150 ms @0.12", 0.12, 150], ["noise burst  350 ms @0.12", 0.12, 350], ["noise burst  900 ms @0.12", 0.12, 900]]) {
    await ev(`window.__stops = 0; window.__aborts = 0; (player.handle({type:"sent", at: performance.now()}), player.handle({type:"audio_started", index: 0}), void 0)`);  // = "she is talking"
    await wait(300);
    await ev(`window.__setLevel(${rms}); void 0`); await wait(ms); await ev(`window.__setLevel(0); void 0`);
    await wait(3800);
    console.log(label.padEnd(30), "-> cut off (stopAudio calls):", await ev(`window.__stops`), "| state now:", await ev(`player.state`));
  }
};
