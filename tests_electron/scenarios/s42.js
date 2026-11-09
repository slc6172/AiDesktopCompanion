// zoom: anchor bottom-left, limits, panel height at 50%. run: COMPANION_DATA_DIR=/tmp/x PROJ=<p> ../run-main.sh s42.js   (SCREEN=1366x768 for the small-screen cap)
module.exports = async ({ win, ev, wait, stateFile, b }) => {
  const stage = () => ev(`(()=>{const r=document.getElementById('stage').getBoundingClientRect();return [Math.round(r.width),Math.round(r.height),Math.round(r.bottom)]})()`);
  const btn = (id) => ev(`document.getElementById('${id}').disabled`);
  const click = async (id, n = 1) => { for (let i = 0; i < n; i++) { await ev(`document.getElementById('${id}').click(); void 0`); await wait(350); } };
  win.setBounds({ x: 600, y: 300, width: 748, height: 640 }); await wait(400);
  console.log("100%:", JSON.stringify(b()), "stage", JSON.stringify(await stage()));
  await click("zoomOut"); console.log("90% :", JSON.stringify(b()), "stage", JSON.stringify(await stage()), "(expect 712x576 at y=364: bottom 940 fixed)");
  await click("zoomOut", 4); console.log("50% :", JSON.stringify(b()), "stage", JSON.stringify(await stage()), "| zoomOut disabled:", await btn("zoomOut"), "(expect 568x560, y=380)");
  await ev(`setPanelOpen(true); void 0`); await wait(500);
  console.log("50% panel:", JSON.stringify(await ev(`(()=>{const r=document.getElementById('panel').getBoundingClientRect();return [Math.round(r.width),Math.round(r.height),Math.round(r.bottom)]})()`)), "(expect 340x560, bottom 560)");
  await click("chatBtn"); await click("zoomIn", 10);
  console.log("max :", JSON.stringify(b()), "| zoomIn disabled:", await btn("zoomIn"), "| saved scale:", (await stateFile()).scale);
};
