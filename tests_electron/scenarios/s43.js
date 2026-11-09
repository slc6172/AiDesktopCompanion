// click-through decisions (the MESSAGES the page sends; Linux cannot do real click-through), tray menu, hide => microphone off.
// run: COMPANION_DATA_DIR=/tmp/x PROJ=<p> ../run-main.sh s43.js   (needs openbox + xdotool)
const { execSync } = require("child_process");
const xdo = (c) => execSync(`xdotool ${c}`, { env: process.env });
module.exports = async ({ win, ev, wait, b }) => {
  const menu = () => global.__menus[global.__menus.length - 1].items.filter(i => i.type !== "separator").map(i => `${i.label}${i.enabled ? "" : "(disabled)"}`).join(" | ");
  const item = (label) => global.__menus[global.__menus.length - 1].items.find(i => i.label === label);
  win.setBounds({ x: 600, y: 300, width: 748, height: 640 }); await wait(500);
  const at = async (label, x, y) => { global.__ignoreMsgs.length = 0; xdo(`mousemove ${600 + x} ${300 + y}`); await wait(120); xdo(`mousemove_relative 1 1`); await wait(200);
    const last = global.__ignoreMsgs.length ? global.__ignoreMsgs[global.__ignoreMsgs.length - 1] : "(unchanged)"; console.log(label.padEnd(46), "->", last === true ? "click-through" : last === false ? "TAKES THE MOUSE" : last); };
  const center = async (id) => (await ev(`(()=>{const r=document.getElementById('${id}').getBoundingClientRect();return [r.x+r.width/2, r.y+r.height/2]})()`)).map(Math.round);
  console.log("initial tray menu:", menu());
  await at("middle of the character", 180, 320); await at("transparent side of the character (x=30)", 30, 320);
  const gear = await center("gear"); await at("the gear", gear[0], gear[1]);
  await ev(`document.getElementById('gear').click(); void 0`); await wait(400);
  const handle = await center("handle"); await at("handle (toolbar expanded)", handle[0], handle[1]);
  global.__ignoreMsgs.length = 0; await ev(`setPanelOpen(true); void 0`); await wait(700);
  console.log("panel opened under a still pointer ->", JSON.stringify(global.__ignoreMsgs), "(expect [false])");
  await ev(`setPanelOpen(false); void 0`); await wait(400);
  const pt = await center("passthrough"); xdo(`mousemove ${600 + pt[0]} ${300 + pt[1]}`); await wait(150);
  await ev(`document.getElementById('passthrough').click(); void 0`); await wait(300);
  console.log("click-through ON: button active =", await ev(`document.getElementById('passthrough').classList.contains('active')`), "| tray:", menu());
  await at("middle of the character, click-through ON", 180, 320);
  item("關閉穿透").click(); await wait(400);
  console.log("tray '關閉穿透' -> page mode off:", !(await ev(`passthroughMode`)), "| tray:", menu());
  await ev(`navigator.mediaDevices.getUserMedia = async () => new AudioContext().createMediaStreamDestination().stream; void 0`);
  await ev(`startContinuous(); void 0`); await wait(600);
  item("隱藏角色").click(); await wait(500);
  console.log("hidden: visible =", win.isVisible(), "| listening after hide:", await ev(`document.getElementById('continuous').classList.contains('on')`));
  item("顯示角色").click(); await wait(500);
  console.log("shown again: visible =", win.isVisible(), "| listening back on by itself:", await ev(`document.getElementById('continuous').classList.contains('on')`));
};
