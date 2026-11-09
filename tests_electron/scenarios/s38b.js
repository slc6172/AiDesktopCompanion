// ui.auto_listen: COMPANION_AUTO_LISTEN=1 [GUM_FAIL=1] CTXISO=0 PROJ=<p> ../run.sh s38b.js ../stub-mic.js
const wait = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = async (win, shot, ev) => {
  await wait(2500);
  console.log(JSON.stringify({
    autoListenSetting: await ev(`(async () => (await (await fetch('/config')).json()).ui.autoListen)()`),
    gumCalls: await ev(`window.__gumCalls`), green: await ev(`!document.getElementById('dotListen').hidden`),
    continuousOn: await ev(`document.getElementById('continuous').classList.contains('on')`),
    notes: await ev(`[...document.querySelectorAll('#log .note')].map(n=>n.textContent)`) }));
};
