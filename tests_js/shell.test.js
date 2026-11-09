const test = require("node:test");
const assert = require("node:assert/strict");
const shell = require("../static/shell.js");

// ---- scale ----

test("scale steps by exactly 10% each way and never drifts into floating-point noise", () => {
  let s = 1;
  for (let i = 0; i < 5; i++) s = shell.stepScale(s, +1);
  assert.equal(s, 1.5);
  for (let i = 0; i < 10; i++) s = shell.stepScale(s, -1);
  assert.equal(s, 0.5);
  assert.equal(shell.stepScale(0.7, +1), 0.8); // 0.7 + 0.1 is 0.7999999999999999 in raw floats
});

test("scale is held between 50% and 150%", () => {
  assert.equal(shell.stepScale(1.5, +1), 1.5);
  assert.equal(shell.stepScale(0.5, -1), 0.5);
  assert.equal(shell.clampScale(9), 1.5);
  assert.equal(shell.clampScale(0.01), 0.5);
  assert.equal(shell.clampScale("garbage"), 1); // a corrupt saved value falls back to 100%
});

test("scale-up stops where the character would become taller than the screen's work area", () => {
  // 800px of height fits a 640px-tall character at most 1.2x (768px); 1.3x would be 832px.
  assert.equal(shell.stepScale(1.2, +1, 800), 1.2);
  assert.equal(shell.stepScale(1.1, +1, 800), 1.2);
  assert.equal(shell.stepScale(1.0, +1, 1080), 1.1); // a tall screen does not hold it back
});

test("a work area too small for even the smallest scale still allows the minimum, not less", () => {
  assert.equal(shell.stepScale(0.5, +1, 300), 0.5);
});

test("moving to a smaller screen shrinks an over-large scale on the next step-up instead of growing it", () => {
  assert.equal(shell.stepScale(1.5, +1, 800), 1.2);
});

// ---- layout ----

test("at 100% the window is the character, the toolbar column and the panel side by side", () => {
  assert.deepEqual(shell.computeLayout(1), {
    scale: 1, charW: 360, charH: 640, toolbarW: 48, panelW: 340,
    winW: 748, winH: 640, panelH: 640, charTop: 0,
  });
});

test("at 50% the window keeps a 560px floor so the panel stays usable, and the character sits at the bottom", () => {
  assert.deepEqual(shell.computeLayout(0.5), {
    scale: 0.5, charW: 180, charH: 320, toolbarW: 48, panelW: 340,
    winW: 568, winH: 560, panelH: 560, charTop: 240,
  });
});

test("at 150% the window grows with the character but the panel never gets taller than 640px", () => {
  const l = shell.computeLayout(1.5);
  assert.equal(l.charW, 540);
  assert.equal(l.charH, 960);
  assert.equal(l.winW, 928);
  assert.equal(l.winH, 960);
  assert.equal(l.panelH, 640);
  assert.equal(l.toolbarW, 48); // toolbar and panel do not scale
  assert.equal(l.panelW, 340);
});

test("an out-of-range or garbage scale is clamped before layout", () => {
  assert.equal(shell.computeLayout(9).charW, 540);
  assert.equal(shell.computeLayout(undefined).charW, 360);
});

// ---- saved position ----

const WA = { x: 0, y: 0, width: 1920, height: 1040 }; // primary work area (taskbar excluded)
const L100 = shell.computeLayout(1);

test("with nothing saved, the window starts at the bottom-right of the primary work area", () => {
  assert.deepEqual(shell.validateBounds(null, [WA], L100), { x: 1496, y: 384 });
});

test("a saved position that keeps the character and toolbar on screen is kept as-is", () => {
  assert.deepEqual(shell.validateBounds({ x: 100, y: 200 }, [WA], L100), { x: 100, y: 200 });
});

test("the panel column may hang off the screen edge, the character and toolbar may not", () => {
  // char(360)+toolbar(48)=408 wide: x=1512 ends exactly at 1920, x=1513 pokes out by 1px.
  assert.deepEqual(shell.validateBounds({ x: 1512, y: 100 }, [WA], L100), { x: 1512, y: 100 });
  assert.deepEqual(shell.validateBounds({ x: 1513, y: 100 }, [WA], L100), { x: 1496, y: 384 });
});

test("a position left over from a monitor that is no longer connected falls back to the default", () => {
  assert.deepEqual(shell.validateBounds({ x: 3000, y: 100 }, [WA], L100), { x: 1496, y: 384 });
  assert.deepEqual(shell.validateBounds({ x: -2000, y: 100 }, [WA], L100), { x: 1496, y: 384 });
});

test("with two monitors, a position on the second one is valid", () => {
  const second = { x: 1920, y: 0, width: 1920, height: 1080 };
  assert.deepEqual(shell.validateBounds({ x: 2500, y: 300 }, [WA, second], L100), { x: 2500, y: 300 });
});

test("a character straddling two monitors does not count as on screen", () => {
  const second = { x: 1920, y: 0, width: 1920, height: 1080 };
  assert.deepEqual(shell.validateBounds({ x: 1700, y: 300 }, [WA, second], L100), { x: 1496, y: 384 });
});

test("a saved value that is not a pair of numbers is ignored", () => {
  assert.deepEqual(shell.validateBounds({ x: "left", y: 100 }, [WA], L100), { x: 1496, y: 384 });
  assert.deepEqual(shell.validateBounds({ x: NaN, y: 100 }, [WA], L100), { x: 1496, y: 384 });
});

test("on a screen shorter than the window, the default sticks to the top instead of going off the top", () => {
  const short = { x: 0, y: 0, width: 1366, height: 600 };
  assert.deepEqual(shell.validateBounds(null, [short], shell.computeLayout(1.5)), { x: 1366 - 588 - 16, y: 0 });
});

// ---- panel opens near the right edge ----

test("a window whose panel column would run off the right edge is moved left just enough", () => {
  // window is 748 wide; at x=1400 it ends at 2148, 228px past 1920
  assert.deepEqual(shell.placePanelOpen({ x: 1400, y: 300, width: 748, height: 640 }, WA), { x: 1172, y: 300 });
});

test("a window that already fits is not moved", () => {
  assert.deepEqual(shell.placePanelOpen({ x: 100, y: 300, width: 748, height: 640 }, WA), { x: 100, y: 300 });
  assert.deepEqual(shell.placePanelOpen({ x: 1172, y: 300, width: 748, height: 640 }, WA), { x: 1172, y: 300 });
});

test("on a screen narrower than the window, the character and toolbar stay on screen even though the panel cannot fit", () => {
  const narrow = { x: 0, y: 0, width: 600, height: 800 };
  assert.deepEqual(shell.placePanelOpen({ x: 100, y: 0, width: 748, height: 640 }, narrow), { x: 0, y: 0 });
});

test("a second monitor's own right edge is the limit, not the first monitor's", () => {
  const second = { x: 1920, y: 0, width: 1920, height: 1080 };
  assert.deepEqual(shell.placePanelOpen({ x: 3300, y: 0, width: 748, height: 640 }, second), { x: 3092, y: 0 });
});

// ---- click-through hit testing ----

// Window coordinates at 100%: character 0..360, toolbar column 360..408, panel 408..748.
const REGIONS = {
  character: { x: 0, y: 0, w: 360, h: 640 },
  toolbar: [{ x: 360, y: 580, w: 48, h: 48 }], // just the visible buttons, not the whole column
  panel: { x: 408, y: 0, w: 340, h: 640 },
};
const hit = (x, y, opts = {}) =>
  shell.hitTest({ x, y }, REGIONS, { passthrough: false, panelOpen: false, ratio: 0.6, ...opts });

test("only the middle of the character takes the mouse; the transparent sides let clicks fall through", () => {
  assert.equal(hit(180, 300), true);  // dead centre
  assert.equal(hit(72, 300), true);   // left edge of the middle 60% (x=72)
  assert.equal(hit(71, 300), false);  // one pixel further out
  assert.equal(hit(287, 300), true);  // last pixel of the middle 60% (x=72..288)
  assert.equal(hit(288, 300), false);
  assert.equal(hit(10, 300), false);
});

test("a visible toolbar button takes the mouse; the empty rest of its column does not", () => {
  assert.equal(hit(380, 600), true);
  assert.equal(hit(380, 200), false);
});

test("the panel only takes the mouse while it is open", () => {
  assert.equal(hit(500, 300), false);
  assert.equal(hit(500, 300, { panelOpen: true }), true);
});

test("with click-through on, the character stops taking the mouse but the toolbar and an open panel still do", () => {
  assert.equal(hit(180, 300, { passthrough: true }), false);
  assert.equal(hit(380, 600, { passthrough: true }), true);
  assert.equal(hit(500, 300, { passthrough: true, panelOpen: true }), true);
});

test("the hit-width ratio is held to 20%..100%", () => {
  assert.equal(hit(10, 300, { ratio: 1 }), true);     // 100%: whole rectangle
  assert.equal(hit(10, 300, { ratio: 5 }), true);     // out of range -> 100%
  assert.equal(hit(160, 300, { ratio: 0.2 }), true);  // 20%: x=144..216
  assert.equal(hit(143, 300, { ratio: 0.2 }), false);
  assert.equal(hit(143, 300, { ratio: 0.01 }), false); // out of range -> 20%, not 1%
  assert.equal(hit(150, 300, { ratio: 0.01 }), true);
});

test("a point outside every region is never a hit", () => {
  assert.equal(hit(900, 900, { panelOpen: true }), false);
});

// ---- unread counter ----

const feed = (...events) => events.reduce((state, e) => shell.nextUnread(state, e), shell.initialUnread());

test("messages arriving while the panel is collapsed are counted", () => {
  assert.equal(feed({ type: "message" }, { type: "message" }).count, 2);
});

test("opening the panel clears the count, and messages while it stays open are not counted", () => {
  const s = feed({ type: "message" }, { type: "panel_opened" }, { type: "message" });
  assert.equal(s.count, 0);
});

test("collapsing again starts counting from zero", () => {
  const s = feed({ type: "panel_opened" }, { type: "panel_closed" }, { type: "message" });
  assert.equal(s.count, 1);
});

test("the saved conversation loaded at start-up is never unread", () => {
  assert.equal(feed({ type: "message", history: true }, { type: "message", history: true }).count, 0);
});

test("an unknown event leaves the state alone", () => {
  assert.deepEqual(feed({ type: "whatever" }), shell.initialUnread());
});

// ---- keeping the character and toolbar on screen while dragging ----

// 100% layout: kept-visible part is 408 wide (character + toolbar) and 640 tall, bottom of window.
test("a drag target that keeps the character and toolbar on screen is left alone", () => {
  assert.deepEqual(shell.clampPosition({ x: 200, y: 100 }, [WA], L100), { x: 200, y: 100 });
});

test("a drag past any edge is pushed back so the character and toolbar stay fully visible", () => {
  assert.deepEqual(shell.clampPosition({ x: -50, y: 100 }, [WA], L100), { x: 0, y: 100 });       // left
  assert.deepEqual(shell.clampPosition({ x: 1700, y: 100 }, [WA], L100), { x: 1512, y: 100 });   // right: 1920 - 408
  assert.deepEqual(shell.clampPosition({ x: 200, y: -80 }, [WA], L100), { x: 200, y: 0 });       // top
  assert.deepEqual(shell.clampPosition({ x: 200, y: 900 }, [WA], L100), { x: 200, y: 400 });      // bottom: 1040 - 640
});

test("only the panel column may hang off the right edge; at 50% the empty space above the character may go off the top", () => {
  assert.deepEqual(shell.clampPosition({ x: 1512, y: 100 }, [WA], L100), { x: 1512, y: 100 }); // panel off-screen: allowed
  const L50 = shell.computeLayout(0.5); // window 560 tall, character only 320 tall at the bottom
  assert.deepEqual(shell.clampPosition({ x: 200, y: -200 }, [WA], L50), { x: 200, y: -200 }); // still legal: character top is at y=40
  assert.deepEqual(shell.clampPosition({ x: 200, y: -240 }, [WA], L50), { x: 200, y: -240 }); // character top exactly at the screen top
  assert.deepEqual(shell.clampPosition({ x: 200, y: -300 }, [WA], L50), { x: 200, y: -240 }); // would push the character off the top
});

test("with two monitors the pointer decides which screen the character is kept inside", () => {
  const second = { x: 1920, y: 0, width: 1920, height: 1080 };
  // pointer on the second monitor, window dragged so it straddles the seam -> pulled fully onto the second screen
  assert.deepEqual(shell.clampPosition({ x: 1800, y: 100 }, [WA, second], L100, { x: 2000, y: 300 }), { x: 1920, y: 100 });
  // pointer still on the first monitor -> pulled fully onto the first
  assert.deepEqual(shell.clampPosition({ x: 1800, y: 100 }, [WA, second], L100, { x: 1850, y: 300 }), { x: 1512, y: 100 });
});

test("without a pointer, the screen the character overlaps most is used", () => {
  const second = { x: 1920, y: 0, width: 1920, height: 1080 };
  assert.deepEqual(shell.clampPosition({ x: 1700, y: 100 }, [WA, second], L100), { x: 1512, y: 100 }); // 220px on #1, 188px on #2
  assert.deepEqual(shell.clampPosition({ x: 1800, y: 100 }, [WA, second], L100), { x: 1920, y: 100 }); // 120px on #1, 288px on #2
});

test("a work area smaller than the character keeps its top and left edge in view", () => {
  const tiny = { x: 0, y: 0, width: 300, height: 500 };
  assert.deepEqual(shell.clampPosition({ x: 100, y: 100 }, [tiny], L100), { x: 0, y: 0 });
});

// ---- exit button: two-step confirmation (time is passed in; nothing here reads a clock) ----

const exitAfter = (...events) =>
  events.reduce((r, e) => { const out = shell.nextExitState(r.state, e); return { state: out.state, effects: [...r.effects, out.effect] }; },
    { state: shell.initialExit(), effects: [] });

test("exit: the first press only arms the button, it does not quit", () => {
  const r = exitAfter({ type: "press", now: 1000 });
  assert.deepEqual(r.effects, ["arm"]);
  assert.equal(r.state.phase, "armed");
});

test("exit: a second press within the time limit quits, and the button is idle again afterwards", () => {
  const r = exitAfter({ type: "press", now: 1000 }, { type: "press", now: 3999 });
  assert.deepEqual(r.effects, ["arm", "quit"]);
  assert.equal(r.state.phase, "idle");
});

test("exit: waiting out the limit puts the button back to normal", () => {
  const r = exitAfter({ type: "press", now: 1000 }, { type: "tick", now: 3999 }, { type: "tick", now: 4000 });
  assert.deepEqual(r.effects, ["arm", "none", "disarm"]);
  assert.equal(r.state.phase, "idle");
});

test("exit: folding the toolbar away puts the button back to normal", () => {
  const r = exitAfter({ type: "press", now: 1000 }, { type: "fold", now: 1500 });
  assert.deepEqual(r.effects, ["arm", "disarm"]);
  assert.equal(r.state.phase, "idle");
});

test("exit: a press after the limit (even if no tick was delivered) starts over instead of quitting", () => {
  const r = exitAfter({ type: "press", now: 1000 }, { type: "press", now: 4000 });
  assert.deepEqual(r.effects, ["arm", "arm"]);
  assert.equal(r.state.phase, "armed");
  assert.equal(r.state.armedAt, 4000);
});

test("exit: tick and fold do nothing while the button is idle", () => {
  const r = exitAfter({ type: "tick", now: 10 }, { type: "fold", now: 20 });
  assert.deepEqual(r.effects, ["none", "none"]);
  assert.equal(r.state.phase, "idle");
});

test("exit: a press that arrives after a fold is a first press again", () => {
  const r = exitAfter({ type: "press", now: 1000 }, { type: "fold", now: 1200 }, { type: "press", now: 1300 });
  assert.deepEqual(r.effects, ["arm", "disarm", "arm"]);
});
