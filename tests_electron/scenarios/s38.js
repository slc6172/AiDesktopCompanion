// Unread/listening dots, retry after collapsed error, history not unread. run: CTXISO=0 PROJ=<p> ../run.sh s38.js ../stub-mic.js
const wait = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = async (win, shot, ev) => {
  const dots = () => ev(`({red: !document.getElementById('dotUnread').hidden, green: !document.getElementById('dotListen').hidden})`);
  console.log("start:", JSON.stringify(await dots()));
  await ev(`send("你好")`); await wait(2500); console.log("reply while collapsed:", JSON.stringify(await dots()), "| panel still closed:", !(await ev(`panelOpen`)));
  await ev(`setPanelOpen(true)`); await wait(250); console.log("opened:", JSON.stringify(await dots()));
  await ev(`addNote("面板開著時的提示")`); console.log("note while open -> red stays off:", !(await dots()).red);
  await ev(`setPanelOpen(false)`); await ev(`addNote("收合時的提示")`); console.log("note while collapsed -> red:", (await dots()).red);
  await ev(`setPanelOpen(true)`); await ev(`setPanelOpen(false)`);
  await ev(`window.__realFetch = window.fetch; window.fetch = (u, o) => String(u).includes('/chat') ? Promise.reject(new Error('down')) : window.__realFetch(u, o); send("會失敗的訊息")`); await wait(800);
  console.log("error while collapsed -> red:", (await dots()).red, "| retry button in log:", await ev(`!!document.querySelector('#log .retry')`));
  await ev(`void (window.fetch = window.__realFetch)`); await ev(`setPanelOpen(true)`); await wait(250);
  await ev(`document.querySelector('#log .retry').click()`); await wait(2500); await ev(`setPanelOpen(false)`);
  await win.webContents.reloadIgnoringCache(); await wait(1500);
  console.log("after reload (history loaded) -> dots:", JSON.stringify(await dots()));
  await ev(`startContinuous()`); await wait(500); console.log("listening -> green:", (await dots()).green);
  await ev(`stopContinuous()`); console.log("stopped -> green:", (await dots()).green);
};
