// restart scenarios: put a window-state.json in COMPANION_DATA_DIR first (saved position / bad file / wrong types / scale)
module.exports = async ({ win, ev, b }) => {
  console.log("bounds:", JSON.stringify(b()), "| alwaysOnTop:", win.isAlwaysOnTop(), "| pin active:", await ev(`document.getElementById('pin').classList.contains('active')`));
};
