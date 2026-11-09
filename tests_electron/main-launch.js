// Launches the REAL electron/main.js with test hooks (used by run-main.sh):
//   global.__menus      every Menu built with Menu.buildFromTemplate (the tray menu is rebuilt on state changes)
//   global.__ignoreMsgs every "set-ignore-mouse-events" message the PAGE sends (main.js itself makes click-through a
//                       no-op on Linux, so this verifies the page's decisions, NOT real click-through)
// Scenario contract: module.exports = async ({ win, ev, wait, stateFile, b }) => { ... }
const { app, Menu, ipcMain } = require("electron");
const fs = require("fs");
const os = require("os");
const path = require("path");

app.setPath("userData", fs.mkdtempSync(path.join(os.tmpdir(), "companion-main-ud-")));   // fresh cache every run
global.__menus = [];
global.__ignoreMsgs = [];
const build = Menu.buildFromTemplate.bind(Menu);
Menu.buildFromTemplate = (template) => { const m = build(template); global.__menus.push(m); return m; };
const on = ipcMain.on.bind(ipcMain);
ipcMain.on = (channel, fn) => on(channel, (event, ...args) => {
  if (channel === "set-ignore-mouse-events") global.__ignoreMsgs.push(args[0]);
  return fn(event, ...args);
});

let win = null;
app.on("browser-window-created", (_e, w) => { win = w; });

require(path.resolve(__dirname, "../electron/main.js"));

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
app.whenReady().then(async () => {
  let code = 0;
  try {
    for (let i = 0; i < 100 && !win; i++) await wait(100);
    if (!win) throw new Error("main.js never created a window");
    await new Promise((resolve) => { if (!win.webContents.isLoading()) resolve(); else win.webContents.once("did-finish-load", resolve); });
    await wait(1200);
    const ev = (c) => win.webContents.executeJavaScript(c);
    const b = () => win.getBounds();
    const stateFile = async () => {   // main.js saves with a 400 ms debounce
      await wait(700);
      return JSON.parse(fs.readFileSync(path.join(process.env.COMPANION_DATA_DIR, "window-state.json"), "utf-8"));
    };
    await require(path.resolve(process.env.SCENARIO))({ win, ev, wait, stateFile, b });
  } catch (e) {
    console.error("SCENARIO ERROR:", e && e.stack || e);
    code = 1;
  } finally {
    app.exit(code);
  }
});
