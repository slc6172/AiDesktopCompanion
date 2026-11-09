// window-state.json:視窗位置、置頂、縮放跨重啟記住(規格書 F 節)。
// 由 Electron 主行程讀寫,放在 COMPANION_DATA_DIR(launcher.py 傳入,即專案的 data/ 資料夾),
// 刻意不寫進使用者手動編輯的 config.json。穿透、持續聆聽、面板展開狀態每次啟動都重置,所以不存。
"use strict";
const fs = require("fs");
const path = require("path");

const FILE_NAME = "window-state.json";

function defaults() {
  return { x: null, y: null, alwaysOnTop: true, scale: 1 };
}

// 檔案不存在、損毀、或內容型別不對時都不能讓程式崩潰——一律當作「沒存過」。
function sanitize(raw, clampScale) {
  const state = defaults();
  if (!raw || typeof raw !== "object") return state;
  if (Number.isFinite(raw.x) && Number.isFinite(raw.y)) {
    state.x = raw.x;
    state.y = raw.y;
  }
  if (typeof raw.alwaysOnTop === "boolean") state.alwaysOnTop = raw.alwaysOnTop;
  // 超出 50%~150% 的存檔值視為壞資料,退回 100%(而不是夾到邊界,否則手改成 9 會變成 150%)。
  if (typeof raw.scale === "number" && raw.scale >= 0.5 && raw.scale <= 1.5) state.scale = clampScale(raw.scale);
  return state;
}

function load(dir, clampScale) {
  if (!dir) return defaults();
  try {
    return sanitize(JSON.parse(fs.readFileSync(path.join(dir, FILE_NAME), "utf-8")), clampScale);
  } catch {
    return defaults();
  }
}

// 先寫暫存檔再改名,避免寫到一半被關機而留下半個檔案。
function save(dir, state) {
  if (!dir) return;
  try {
    fs.mkdirSync(dir, { recursive: true });
    const target = path.join(dir, FILE_NAME);
    const tmp = target + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2), "utf-8");
    fs.renameSync(tmp, target);
  } catch (err) {
    console.error("無法儲存視窗狀態:", err.message);
  }
}

module.exports = { load, save, sanitize, defaults, FILE_NAME };
