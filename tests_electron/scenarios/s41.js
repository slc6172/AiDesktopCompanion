// REAL main.js + xdotool (real pointer): JS-driven drag, click vs drag, clamping, blur ends a drag, panel shifts left near the right edge.
// needs: openbox + xdotool, and NO_PASSTHROUGH not required (main.js makes click-through a no-op on Linux). run: COMPANION_DATA_DIR=/tmp/x PROJ=<p> ../run-main.sh s41.js
const { execSync } = require("child_process");
const xdo = (cmd) => {
  cmd = cmd.replace(/^mousemove (-?\d+) (-?\d+)$/, (m, x, y) => `mousemove ${Math.min(1919, Math.max(0, +x))} ${Math.min(1079, Math.max(0, +y))}`);  // the pointer cannot leave the screen
  return execSync(`xdotool ${cmd}`, { env: process.env });
};
module.exports = async ({ win, ev, wait, stateFile, b }) => {
  const center = async (id) => { const r = await ev(`(()=>{const r=document.getElementById('${id}').getBoundingClientRect();return [r.x+r.width/2, r.y+r.height/2]})()`); const bb = b(); return [Math.round(bb.x + r[0]), Math.round(bb.y + r[1])]; };
  const drag = async ([x, y], dx, dy, steps = 12) => { xdo(`mousemove ${x} ${y}`); await wait(120); xdo("mousedown 1"); await wait(80);
    for (let i = 1; i <= steps; i++) { xdo(`mousemove ${x + Math.round(dx * i / steps)} ${y + Math.round(dy * i / steps)}`); await wait(25); }
    await wait(120); xdo("mouseup 1"); await wait(200); };
  await ev(`document.getElementById('gear').click(); void 0`); await wait(300);
  win.setBounds({ x: 600, y: 300, width: 748, height: 640 }); await wait(300);
  let start = b(); await drag(await center("handle"), 120, -80);
  console.log("A handle drag +120,-80 ->", JSON.stringify([b().x - start.x, b().y - start.y]), "(about 110,-73: the window lags the cursor by the 4px start threshold)", "| size kept:", b().width + "x" + b().height);
  start = b(); await drag(await center("stage"), -150, 60); console.log("B body drag -150,+60 ->", JSON.stringify([b().x - start.x, b().y - start.y]));
  await ev(`window.__stageClicks = 0; document.getElementById('stage').addEventListener('click', () => window.__stageClicks++); void 0`);
  start = b(); const c = await center("stage"); xdo(`mousemove ${c[0]} ${c[1]}`); await wait(100); xdo("click 1"); await wait(200);
  console.log("C plain click: window moved:", b().x !== start.x || b().y !== start.y, "| click reached the character:", await ev(`window.__stageClicks`));
  start = b(); await drag(await center("stage"), 2, 1, 2); console.log("C2 2px wobble: window moved:", b().x !== start.x || b().y !== start.y);
  win.setBounds({ x: 600, y: 300, width: 748, height: 640 }); await wait(200);
  await drag(await center("stage"), 1500, -900, 20); console.log("D1 far right/up -> x,y:", b().x, b().y, "(expect x=1512, y=0)");
  await drag(await center("stage"), -2500, 1200, 24); console.log("D2 far left/down -> x,y:", b().x, b().y, "(expect x=0, y=440)");
  win.setBounds({ x: 600, y: 300, width: 748, height: 640 }); await wait(200);
  const p = await center("stage"); xdo(`mousemove ${p[0]} ${p[1]}`); await wait(100); xdo("mousedown 1"); await wait(60); xdo(`mousemove ${p[0] + 60} ${p[1]}`); await wait(150);
  await ev(`window.dispatchEvent(new Event('blur')); void 0`); await wait(100);
  const afterBlur = b().x; xdo(`mousemove ${p[0] + 200} ${p[1] + 50}`); await wait(200); xdo("mouseup 1"); await wait(100);
  console.log("E drag ended by blur:", b().x === afterBlur, "| body.dragging cleared:", !(await ev(`document.body.classList.contains('dragging')`)));
  win.setBounds({ x: 1500, y: 300, width: 748, height: 640 }); await wait(300);
  await ev(`setPanelOpen(true); void 0`); await wait(500); console.log("F panel open at x=1500 -> window x:", b().x, "(expect 1172)");
  await ev(`setPanelOpen(false); void 0`); await wait(400); console.log("F panel closed -> x:", b().x, "(expect still 1172)");
};
