// Electron main process for page-level scenarios (does NOT use the project's electron/main.js).
//   electron runner.js  with env: URL, SCENARIO, STUB (optional preload), CTXISO (0 => contextIsolation:false), OUT (screenshots dir)
// Scenario contract: module.exports = async (win, shot, ev) => { ... }
const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const os = require("os");
const path = require("path");

// Fresh user-data dir EVERY run (the Electron disk cache survives between runs and has served the
// wrong project's page before). Must happen before app is ready.
const userData = fs.mkdtempSync(path.join(os.tmpdir(), "companion-ud-"));
app.setPath("userData", userData);
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
app.commandLine.appendSwitch("disable-http-cache");

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

app.whenReady().then(async () => {
  let code = 0;
  try {
    const win = new BrowserWindow({
      width: 748, height: 640, show: true,
      webPreferences: {
        preload: process.env.STUB ? path.resolve(process.env.STUB) : undefined,
        contextIsolation: process.env.CTXISO !== "0",
        sandbox: false,
        backgroundThrottling: false,
      },
    });
    // 新版 Electron 把參數合併成事件物件(event.message);舊版是 (event, level, message)。Electron 靠監聽函式宣告了
  // 幾個參數來判斷是不是舊寫法,所以這裡只宣告一個參數,舊版的 message 從 arguments 取。
  win.webContents.on("console-message", function (event) {
    const text = event && event.message !== undefined ? event.message : arguments[2];
    if (process.env.PAGE_LOG) console.log("[page]", text);
  });
    win.webContents.on("render-process-gone", (_e, d) => console.error("render-process-gone", d.reason));
    if (process.env.GUM_FAIL === "1") win.webContents.once("dom-ready", () => win.webContents.executeJavaScript("window.__GUM_FAIL = true; void 0"));
    await win.loadURL(process.env.URL);
    await wait(500);
    const ev = (c) => win.webContents.executeJavaScript(c);
    let n = 0;
    const shot = async (name) => {
      const dir = process.env.OUT || os.tmpdir();
      fs.mkdirSync(dir, { recursive: true });
      const img = await win.webContents.capturePage();
      const f = path.join(dir, `${String(++n).padStart(2, "0")}-${name || "shot"}.png`);
      fs.writeFileSync(f, img.toPNG());
      return f;
    };
    await require(path.resolve(process.env.SCENARIO))(win, shot, ev);
  } catch (e) {
    console.error("SCENARIO ERROR:", e && e.stack || e);
    code = 1;
  } finally {
    app.exit(code);
  }
});
