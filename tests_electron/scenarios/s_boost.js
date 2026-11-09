// Page -> header -> server log chain for ui.speaking_boost and the [audio] measurement line.
// run: echo '{"stt":{"debug_log":true}}' > <project>/config.json ; COMPANION_SPEAKING_BOOST=3 CTXISO=0 PROJ=<p> ../run.sh s_boost.js ../stub-osc.js ; grep '^\[audio\]' /tmp/server.log
// expect with boost 3: A (silent, 0.05) triggers; B (talking, 0.05 = echo level) records NOTHING; C (talking, 0.12) triggers with during_speech=1
const wait = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = async (win, shot, ev) => {
  await ev(`startContinuous(); void 0`); await wait(1200);
  console.log("page:", await ev(`JSON.stringify({boost: speakingBoost(), on: document.getElementById('continuous').classList.contains('on')})`));
  const say = async (rms, ms = 1300) => { await ev(`window.__setLevel(${rms}); void 0`); await wait(ms); await ev(`window.__setLevel(0); void 0`); await wait(2600); };
  const shesTalking = () => ev(`(player.handle({type:"sent", at: performance.now()}), player.handle({type:"audio_started", index: 0}), player.state)`);
  console.log("A she is silent, mic at RMS 0.05      ->", "player:", await ev(`player.state`)); await say(0.05);
  console.log("B she talks:", await shesTalking(), ", mic at 0.05 (echo-level)");              await say(0.05);
  console.log("C she talks:", await shesTalking(), ", mic at 0.12 (a real cut-in)");           await say(0.12);
};
