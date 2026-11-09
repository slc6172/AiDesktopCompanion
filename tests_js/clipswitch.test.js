const test = require("node:test");
const assert = require("node:assert/strict");
const { ClipSwitchDebouncer } = require("../static/clipswitch.js");

test("the very first request is always accepted, whatever the dwell time", () => {
  const d = new ClipSwitchDebouncer({ minDwellMs: 1000 });
  assert.equal(d.request("idle", 0), true);
});

test("requesting the state already showing is a no-op, immediately or later", () => {
  const d = new ClipSwitchDebouncer({ minDwellMs: 1000 });
  d.request("idle", 0);
  assert.equal(d.request("idle", 1), false);
  assert.equal(d.request("idle", 5000), false);
});

test("a different state requested within the dwell window is suppressed", () => {
  const d = new ClipSwitchDebouncer({ minDwellMs: 300 });
  d.request("talking:happy", 0);
  assert.equal(d.request("talking:sad", 100), false);
  assert.equal(d.request("talking:sad", 299), false);
});

test("a different state requested once the dwell window has passed goes through", () => {
  const d = new ClipSwitchDebouncer({ minDwellMs: 300 });
  d.request("talking:happy", 0);
  assert.equal(d.request("talking:sad", 300), true);
});

test("a suppressed request never becomes the new baseline for the next comparison", () => {
  // If it did, "talking:sad" here would wrongly look like "already showing" on the next call.
  const d = new ClipSwitchDebouncer({ minDwellMs: 300 });
  d.request("talking:happy", 0);
  d.request("talking:sad", 100); // suppressed
  assert.equal(d.request("talking:sad", 150), false); // still suppressed: dwell measured from t=0
  assert.equal(d.request("talking:happy", 150), false); // "happy" is still what is actually showing
});

test("the dwell window is measured from the last ACCEPTED switch, not the last request", () => {
  const d = new ClipSwitchDebouncer({ minDwellMs: 300 });
  d.request("a", 0); // accepted, baseline t=0
  d.request("b", 100); // suppressed (only 100ms since t=0)
  d.request("c", 250); // suppressed (only 250ms since t=0, NOT 150ms since the b attempt)
  assert.equal(d.request("d", 320), true); // 320ms since t=0: now it goes through
});

test("a dwell time of zero disables debouncing entirely", () => {
  const d = new ClipSwitchDebouncer({ minDwellMs: 0 });
  d.request("a", 0);
  assert.equal(d.request("b", 0), true);
  assert.equal(d.request("c", 0), true);
});

test("minDwellMs defaults to something sane when not specified", () => {
  const d = new ClipSwitchDebouncer();
  assert.equal(typeof d.request("a", 0), "boolean");
  assert.equal(d.request("b", 1), false); // any reasonable default is well over 1ms
});

test("many rapid requests within one turn settle on whatever is asked for once dwell allows it", () => {
  // Characterization of the motivating scenario: several emotion changes packed into one
  // fast-streaming reply should not flip the clip on every single one of them.
  const d = new ClipSwitchDebouncer({ minDwellMs: 200 });
  const accepted = [];
  const requests = [
    ["talking:happy", 0], ["talking:sad", 40], ["talking:angry", 90],
    ["talking:happy", 210], ["talking:neutral", 500],
  ];
  for (const [state, at] of requests) {
    if (d.request(state, at)) accepted.push(state);
  }
  assert.deepEqual(accepted, ["talking:happy", "talking:neutral"]);
  // ^ t=0 accepted; t=40/90 suppressed (still showing "happy" and within 200ms of t=0);
  // t=210's request is for "happy" too, which is already showing, so it is correctly a
  // no-op rather than a new acceptance; t=500 is 500ms after the t=0 baseline (the dwell
  // clock was never reset by any of the suppressed/no-op requests), well past 200ms, so the
  // switch to neutral finally goes through.
});

test("without any clip, two states shown as the same fallback face do not restart the dwell timer", () => {
  // the page asks for `emoji:<state>` when a state has no video; only a visible change may count
  const d = new ClipSwitchDebouncer({ minDwellMs: 220 });
  assert.equal(d.request("emoji:idle", 0), true);
  assert.equal(d.request("emoji:idle", 300), false);
  assert.equal(d.request("emoji:thinking", 600), true);
});
