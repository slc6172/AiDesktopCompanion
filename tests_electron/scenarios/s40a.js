// REAL main.js: first start, exposed API, pin, move-save. run: COMPANION_DATA_DIR=/tmp/x PROJ=<p> ../run-main.sh s40a.js
module.exports = async ({ win, ev, wait, stateFile, b }) => {
  console.log("first start, bounds:", JSON.stringify(b()), "(on a plain 1920x1080 Xvfb: x=1496 y=424; WITH openbox the whole 748px window is pulled on screen: x=1172)");
  console.log("resizable:", win.isResizable(), "| alwaysOnTop:", win.isAlwaysOnTop());
  console.log("exposed API:", await ev(`Object.keys(window.companionShell).sort().join(',')`), "| ipcRenderer/require leaked:", await ev(`typeof window.ipcRenderer + '/' + typeof window.require`));
  await ev(`document.getElementById('pin').click(); void 0`); await wait(300);
  console.log("after pin click -> alwaysOnTop:", win.isAlwaysOnTop(), "| saved:", JSON.stringify(await stateFile()));
  win.setPosition(300, 200); await wait(900);
  console.log("after move -> saved:", JSON.stringify(await stateFile()));
};
