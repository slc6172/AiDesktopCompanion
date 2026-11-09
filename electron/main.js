// Electron 主行程(規格書 Part 9)。由 companion/launcher.py 的 open_electron_window() 啟動,
// 透過環境變數接收設定:
//   COMPANION_URL           要載入的網址(embedded 的 uvicorn 伺服器,連接埠是動態挑選的)
//   COMPANION_DATA_DIR      window-state.json 存放的資料夾
//   COMPANION_ON_TOP_LEVEL  "normal"(預設)或 "screen-saver"(Windows 上會蓋過工作列與部分全螢幕程式)
// 所有版面運算(視窗大小、位置驗證)都在 static/shell.js,與網頁共用同一份。
"use strict";
const { app, BrowserWindow, Menu, Tray, ipcMain, screen, session } = require("electron");
const path = require("path");
const shell = require(path.join(__dirname, "..", "static", "shell.js"));
const windowState = require("./windowstate.js");
const navguard = require("./navguard.js");

const DEFAULT_URL = "http://127.0.0.1:8000/";
const isAppUrl = navguard.makeIsAppUrl(process.env.COMPANION_URL || DEFAULT_URL);
const DATA_DIR = process.env.COMPANION_DATA_DIR || "";
const TOP_LEVEL = process.env.COMPANION_ON_TOP_LEVEL === "screen-saver" ? "screen-saver" : "normal";

let win = null;
let tray = null;
let state = windowState.defaults();
let saveTimer = null;
let drag = null; // 拖曳進行中:{ dx, dy, timer, pendingIgnore }
let passthroughOn = false; // 頁面的「穿透」開關目前是否開啟(只用來決定系統匣選單的內容)

// setIgnoreMouseEvents 的 {forward:true}(穿透時仍把滑鼠移動轉發給頁面)只有 Windows 和 macOS 支援。
// Linux 上一旦進入穿透,頁面就再也收不到事件、切不回來,所以 Linux 乾脆不穿透(整個視窗都收滑鼠)。
const CAN_FORWARD_MOUSE = process.platform !== "linux";
function setIgnore(ignore) {
  if (win && CAN_FORWARD_MOUSE) win.setIgnoreMouseEvents(ignore, { forward: true });
}

// 主螢幕排第一個:validateBounds 以第一個工作區當作「預設位置」所在的螢幕。
function workAreas() {
  const primary = screen.getPrimaryDisplay();
  const others = screen.getAllDisplays().filter((d) => d.id !== primary.id);
  return [primary, ...others].map((d) => d.workArea);
}

function applyAlwaysOnTop(flag) {
  state.alwaysOnTop = flag;
  if (!win) return;
  if (flag) win.setAlwaysOnTop(true, TOP_LEVEL === "screen-saver" ? "screen-saver" : "normal");
  else win.setAlwaysOnTop(false);
}

function persistSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(persistNow, 400);
}

function persistNow() {
  clearTimeout(saveTimer);
  if (win) {
    const [x, y] = win.getPosition();
    state.x = x;
    state.y = y;
  }
  windowState.save(DATA_DIR, state);
}

const currentLayout = () => shell.computeLayout(state.scale);

// 一律用 setBounds 並明確帶入寬高,而不是 setPosition:Windows 上有顯示縮放比例時,
// 對透明視窗呼叫 setPosition 偶爾會讓視窗大小慢慢漂移。
function moveTo(x, y) {
  if (!win) return;
  const l = currentLayout();
  win.setBounds({ x: Math.round(x), y: Math.round(y), width: l.winW, height: l.winH });
}

function dragTick() {
  if (!win || !drag) return stopDrag();
  const cursor = screen.getCursorScreenPoint();
  const target = shell.clampPosition(
    { x: cursor.x - drag.dx, y: cursor.y - drag.dy },
    workAreas(),
    currentLayout(),
    cursor
  );
  const [x, y] = win.getPosition();
  if (target.x !== x || target.y !== y) moveTo(target.x, target.y);
}

function startDrag() {
  if (!win || drag) return;
  const cursor = screen.getCursorScreenPoint();
  const [x, y] = win.getPosition();
  // 拖曳期間必須接收滑鼠(否則視窗一動、游標短暫落在透明處就會失去事件),結束後再還原穿透狀態。
  if (CAN_FORWARD_MOUSE) win.setIgnoreMouseEvents(false);
  drag = { dx: cursor.x - x, dy: cursor.y - y, timer: setInterval(dragTick, 8), pendingIgnore: null };
}

function stopDrag() {
  if (!drag) return;
  clearInterval(drag.timer);
  const pending = drag.pendingIgnore;
  drag = null;
  if (pending !== null) setIgnore(pending);
  persistNow();
}

function createWindow() {
  const url = process.env.COMPANION_URL || DEFAULT_URL;
  state = windowState.load(DATA_DIR, shell.clampScale);
  // 存檔的比例若比主螢幕放得下的還大(例如換到較小的螢幕),縮到放得下為止。
  state.scale = Math.min(state.scale, shell.maxScaleForWorkArea(screen.getPrimaryDisplay().workArea.height));
  const layout = shell.computeLayout(state.scale);
  const pos = shell.validateBounds(
    state.x === null ? null : { x: state.x, y: state.y },
    workAreas(),
    layout
  );
  state.x = pos.x;
  state.y = pos.y;

  win = new BrowserWindow({
    x: pos.x,
    y: pos.y,
    width: layout.winW,
    height: layout.winH,
    useContentSize: true,
    frame: false, // 無邊框
    transparent: true, // 透明背景:Electron 在 Windows 上真的支援(早期用的視窗函式庫做不到這點)
    hasShadow: false, // 透明視窗如果保留陰影,會在角色周圍看到一圈方形陰影
    resizable: false, // 大小由縮放比例決定,不讓使用者拖邊框
    skipTaskbar: false,
    show: false,
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      preload: path.join(__dirname, "preload.js"),
      // 視窗被別的程式蓋住或縮到背景時,不要把頁面的計時器和 AudioWorklet 降速:
      // 持續聆聽的錄音(10 ms 一幀)與 VAD 都靠它們,降速會讓聆聽斷斷續續。
      backgroundThrottling: false,
    },
  });
  win.setMenuBarVisibility(false);
  // 視窗只顯示本機伺服器的頁面:導向別的網址(包括轉址)一律擋下,也不開新視窗。
  // 否則頁面一旦被導去外站,該站就坐在一個有麥克風權限的視窗裡。
  const blockForeign = (event, target) => { if (!isAppUrl(target)) event.preventDefault(); };
  win.webContents.on("will-navigate", blockForeign);
  win.webContents.on("will-redirect", blockForeign);
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  applyAlwaysOnTop(state.alwaysOnTop);
  setIgnore(true); // 啟動時整個視窗穿透;滑鼠進入互動區(頁面的 hitTest 判斷)才接收
  win.once("ready-to-show", () => win.show());
  // 系統匣選單的「隱藏角色/顯示角色」要跟著視窗真正的狀態走(包括啟動時視窗還沒 show 的那一刻)。
  win.on("show", refreshTray);
  win.on("hide", refreshTray);
  win.on("move", persistSoon);
  win.on("close", persistNow);
  win.on("closed", () => {
    if (drag) clearInterval(drag.timer);
    drag = null;
    win = null;
    app.quit(); // 沒有系統匣圖示可以重新叫出視窗時,關掉視窗就等同結束程式
  });
  win.loadURL(url);
  return win;
}

// 結束程式的唯一入口:系統匣的「結束程式」與頁面的退出鈕都走這裡,兩條路徑不會分歧。
// 立即結束:不等記憶摘要、照片生成等背景工作(它們在 Python 那邊,伺服器隨後被啟動器關掉;
// 資料庫寫入本來就是交易式)。視窗位置在 win 的 "close" 事件裡存檔。
function quitApp() {
  app.quit();
}

function toggleVisible() {
  if (!win) return;
  if (win.isVisible()) {
    win.hide();
    win.webContents.send("tray-command", "hidden"); // 頁面會順便關掉持續聆聽
  } else {
    win.show();
  }
  refreshTray();
}

function refreshTray() {
  if (!tray) return;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: win && win.isVisible() ? "隱藏角色" : "顯示角色", click: toggleVisible },
    // 逃生門:穿透開啟時,連角色本體都點不到;這個選項不依賴視窗,永遠點得到。
    {
      label: "關閉穿透",
      enabled: passthroughOn,
      click: () => win && win.webContents.send("tray-command", "passthrough-off"),
    },
    { type: "separator" },
    { label: "結束程式", click: quitApp },
  ]));
}

function createTray() {
  // 沒有標題列/選單,所以用系統匣圖示的右鍵選單操作。
  // icon.png 只是一個佔位的實心圓;真的要換成品牌圖示,直接換掉這個檔案即可。
  tray = new Tray(path.join(__dirname, "icon.png"));
  tray.setToolTip("AI 動畫朋友");
  refreshTray();
}

app.whenReady().then(async () => {
  // 啟動時清掉 HTTP 快取。伺服器現在對所有檔案都送 Cache-Control: no-cache(每次先確認再用),
  // 但「升級之前」被快取住的舊檔不會再來問伺服器——瀏覽器認為它還新鮮(依 Last-Modified 推算,
  // 可以新鮮好幾天到好幾週),所以重新編碼過的影片或新版的 JS 會一直被舊的蓋住。
  // 內容都來自本機伺服器,清掉的代價只是這一次重新讀一遍。
  await session.defaultSession.clearCache();
  // Electron 預設會擋掉麥克風權限請求(沒有像瀏覽器那樣的允許/拒絕對話框可以點),
  // 所以主行程要明確允許;但只允許本程式自己的頁面(navguard.permissionAllowed)。
  // 「請求」與「檢查」是兩條路:getUserMedia 之前的權限檢查也要答對,所以兩個都設。
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    callback(navguard.permissionAllowed(permission, (details && details.requestingUrl) || webContents.getURL(), isAppUrl));
  });
  session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin) =>
    navguard.permissionAllowed(permission, requestingOrigin, isAppUrl));
  createWindow();
  createTray();
});

app.on("window-all-closed", () => app.quit());

// 滑鼠穿透:網頁告知目前滑鼠是否在互動區域上;不在區域內時整個視窗轉發滑鼠事件到桌面上
// 被蓋住的其他視窗。(判斷邏輯在票券 43 改成 static/shell.js 的 hitTest。)
ipcMain.on("set-ignore-mouse-events", (event, ignore) => {
  if (drag) { drag.pendingIgnore = !!ignore; return; } // 拖曳中先記著,放開後再套用
  setIgnore(!!ignore);
});

// 縮放:視窗左下角固定不動(角色腳底的位置不變),大小依 computeLayout 重設。
// resizable:false 的視窗在部分平台上會忽略程式呼叫的大小變更,所以暫時打開再關回去。
ipcMain.handle("set-scale", (event, requested) => {
  if (!win) return state.scale;
  const bounds = win.getBounds();
  const workArea = screen.getDisplayMatching(bounds).workArea;
  const next = shell.clampScale(Math.min(Number(requested), shell.maxScaleForWorkArea(workArea.height)));
  if (next === state.scale) return state.scale;
  const layout = shell.computeLayout(next);
  const bottom = bounds.y + bounds.height;
  const pos = shell.clampPosition({ x: bounds.x, y: bottom - layout.winH }, workAreas(), layout);
  state.scale = next;
  win.setResizable(true);
  win.setBounds({ x: Math.round(pos.x), y: Math.round(pos.y), width: layout.winW, height: layout.winH });
  win.setResizable(false);
  persistNow();
  return next;
});

// 頁面的退出鈕(已經過兩段式確認)。
ipcMain.on("quit-app", quitApp);

ipcMain.on("passthrough-changed", (event, on) => {
  passthroughOn = !!on;
  refreshTray();
});

ipcMain.on("start-drag", startDrag);
ipcMain.on("stop-drag", stopDrag);

// 面板展開後若視窗超出所在螢幕工作區的右緣,整個視窗往左移到放得下;收合後不移回,並記住新位置。
ipcMain.on("ensure-panel-visible", () => {
  if (!win) return;
  const bounds = win.getBounds();
  const workArea = screen.getDisplayMatching(bounds).workArea;
  const next = shell.placePanelOpen(bounds, workArea);
  if (next.x !== bounds.x || next.y !== bounds.y) {
    moveTo(next.x, next.y);
    persistNow();
  }
});

ipcMain.on("set-always-on-top", (event, flag) => {
  applyAlwaysOnTop(!!flag);
  persistNow();
});

ipcMain.handle("get-initial-state", () => ({ alwaysOnTop: state.alwaysOnTop, scale: state.scale }));
