// Ticket 65: the real main.js must create its window with backgroundThrottling:false (a covered / background window must not
// slow its timers and AudioWorklet down). Also: the startup clearCache is still there (s_cache4 covers its effect).
// run: COMPANION_DATA_DIR=/tmp/x PROJ=<p> ../run-main.sh s65_throttling.js
const fs = require("fs");
module.exports = async ({ win }) => {
  const value = win.webContents.backgroundThrottling;   // (getLastWebPreferences() does not report this key)
  console.log(`${value === false ? "PASS" : "FAIL"}  webContents.backgroundThrottling = ${JSON.stringify(value)} (expect false)`);
  const src = fs.readFileSync(process.env.PROJ + "/electron/main.js", "utf-8");
  const kept = src.includes("session.defaultSession.clearCache()");
  console.log(`${kept ? "PASS" : "FAIL"}  startup clearCache() still present`);
};
