// 讓網頁(context isolation 開啟,無法直接碰 Node/Electron API)呼叫視窗層級功能。
// 刻意只暴露規格書 H 節列出的最小介面,不暴露 ipcRenderer 本身。
"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("companionShell", {
  setIgnoreMouseEvents: (ignore) => ipcRenderer.send("set-ignore-mouse-events", ignore),
  setAlwaysOnTop: (flag) => ipcRenderer.send("set-always-on-top", !!flag),
  // JS 驅動的視窗拖曳:按下並移動超過門檻後 startDrag,放開時 stopDrag。
  startDrag: () => ipcRenderer.send("start-drag"),
  stopDrag: () => ipcRenderer.send("stop-drag"),
  // 頁面的「穿透」開關狀態變了,讓系統匣選單決定要不要提供「關閉穿透」。
  passthroughChanged: (on) => ipcRenderer.send("passthrough-changed", !!on),
  // 系統匣選單的指令:"passthrough-off"(關閉穿透)、"hidden"(角色被隱藏了)。
  onTrayCommand: (callback) => ipcRenderer.on("tray-command", (event, command) => callback(command)),
  // 縮放:傳入想要的比例,主行程依所在螢幕工作區高度再夾一次、重設視窗大小(左下角固定),
  // 回傳實際套用的比例。
  setScale: (scale) => ipcRenderer.invoke("set-scale", scale),
  // 面板展開後呼叫:若視窗超出螢幕右緣,主行程把整個視窗往左移到放得下。
  ensurePanelVisible: () => ipcRenderer.send("ensure-panel-visible"),
  // 啟動時取回記住的狀態:{ alwaysOnTop, scale }
  getInitialState: () => ipcRenderer.invoke("get-initial-state"),
  // 退出鈕(兩段式確認在頁面裡做完才呼叫):結束整個程式。只有這一個動作,沒有參數。
  quit: () => ipcRenderer.send("quit-app"),
});
