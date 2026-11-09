// The pet window must stay on the local server's page: navigation, redirects and window.open to another site are refused,
// and only the app's own page gets the microphone permission. run: see run-main.sh
const { BrowserWindow } = require("electron");
module.exports = async ({ win, ev, wait }) => {
  const home = process.env.COMPANION_URL;
  const ok = (name, cond) => { console.log(`${cond ? "PASS" : "FAIL"} ${name}`); if (!cond) process.exitCode = 1; };
  await ev(`location.href = "http://example.com/"`); await wait(1500);
  ok("navigation to another site is blocked", win.webContents.getURL().startsWith(home));
  const before = BrowserWindow.getAllWindows().length;
  await ev(`window.open("http://example.com/")`); await wait(800);
  ok("window.open does not create a window", BrowserWindow.getAllWindows().length === before);
  ok("microphone permission is granted for the app's page", (await ev(`navigator.permissions.query({name: "microphone"}).then(r => r.state)`)) === "granted");
  ok("another permission (notifications) is not granted", (await ev(`navigator.permissions.query({name: "notifications"}).then(r => r.state)`)) !== "granted");
};
