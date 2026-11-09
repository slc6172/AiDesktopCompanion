// Layout/panel behaviours (page-level). run: PROJ=<p> ../run.sh s36b.js
const wait = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = async (win, shot, ev) => {
  const q = (code) => ev(code);
  await q(`send("你好")`); await wait(2500);
  console.log("log while collapsed:", await q(`document.querySelectorAll('#log .msg').length`), "msgs; panel visible =", await q(`getComputedStyle(document.getElementById('panel')).visibility`));
  await q(`document.getElementById('gear').dispatchEvent(new MouseEvent('mouseenter'))`);
  console.log("expanded after hover:", await q(`document.getElementById('toolbarCol').classList.contains('expanded')`));
  await q(`document.getElementById('toolbarCol').dispatchEvent(new MouseEvent('mouseleave'))`); await wait(1500);
  console.log("still expanded at 1.5s:", await q(`document.getElementById('toolbarCol').classList.contains('expanded')`)); await wait(900);
  console.log("collapsed after 2.4s:", !(await q(`document.getElementById('toolbarCol').classList.contains('expanded')`)));
  await q(`document.getElementById('chatBtn').click()`);
  await q(`document.getElementById('toolbarCol').dispatchEvent(new MouseEvent('mouseleave'))`); await wait(2600);
  console.log("expanded with panel open after 2.6s:", await q(`document.getElementById('toolbarCol').classList.contains('expanded')`));
  await q(`document.getElementById('stage').dispatchEvent(new MouseEvent('click', {bubbles:true}))`);
  console.log("panel still open after outside click:", await q(`document.getElementById('panel').classList.contains('open')`));
  await q(`document.getElementById('panelClose').click()`); await wait(2500);
  console.log("closed:", !(await q(`document.getElementById('panel').classList.contains('open')`)), "| toolbar collapsed:", !(await q(`document.getElementById('toolbarCol').classList.contains('expanded')`)));
};
