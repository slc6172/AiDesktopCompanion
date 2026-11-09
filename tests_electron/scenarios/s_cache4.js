// Is a file replaced on disk picked up on the next load? (run with the REAL main.js: needs the startup clearCache)
// run: COMPANION_DATA_DIR=/tmp/x PROJ=<p> ../run-main.sh s_cache4.js   (uses <project>/clips/_cachetest.txt; deletes it)
const fs = require("fs");
module.exports = async ({ win, ev }) => {
  const FILE = process.env.PROJ + "/clips/_cachetest.txt";
  fs.writeFileSync(FILE, "OLD"); const old = Date.now() / 1000 - 30 * 86400; fs.utimesSync(FILE, old, old);   // a file last modified 30 days ago
  const get = () => ev(`fetch('/clips/_cachetest.txt').then(r => r.text())`);
  const first = await get();
  fs.writeFileSync(FILE, "NEW-CONTENT");
  const second = await get();
  console.log(`first: ${first} | after replacing: ${second} | picked up: ${second === "NEW-CONTENT"}`);
  fs.unlinkSync(FILE);
};
