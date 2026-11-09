const test = require("node:test");
const assert = require("node:assert/strict");
const { OutfitSwap, clipFor } = require("../static/clipswitch.js");

const PAJAMAS = { idle: "/clips/pj/idle.webm", "talking:neutral": "/clips/pj/talk.webm", "talking:happy": "/clips/pj/happy.webm" };
const CASUAL = { idle: "/clips/day/idle.webm" };

// ---- which clip a state shows (the fall-back chain, inside ONE outfit) ----

test("a state uses its own clip, else talking:neutral, else idle", () => {
  assert.equal(clipFor(PAJAMAS, "talking:happy"), "/clips/pj/happy.webm");
  assert.equal(clipFor(PAJAMAS, "talking:sad"), "/clips/pj/talk.webm");
  assert.equal(clipFor(CASUAL, "talking:sad"), "/clips/day/idle.webm");
  assert.equal(clipFor(CASUAL, "thinking"), "/clips/day/idle.webm");
});

test("a state with no clip anywhere in the outfit has none (the page then shows the emoji)", () => {
  assert.equal(clipFor({}, "idle"), undefined);
});

// ---- preloading ----

test("a request says which clips to load first: the idle clip and the one for the current state", () => {
  const swap = new OutfitSwap("日常");
  assert.deepEqual(swap.begin("睡衣", PAJAMAS, "talking:happy"), ["/clips/pj/idle.webm", "/clips/pj/happy.webm"]);
});

test("the same clip is not asked for twice", () => {
  const swap = new OutfitSwap("日常");
  assert.deepEqual(swap.begin("睡衣", PAJAMAS, "idle"), ["/clips/pj/idle.webm"]);
});

test("asking for the outfit already worn does nothing", () => {
  const swap = new OutfitSwap("睡衣");
  assert.equal(swap.begin("睡衣", PAJAMAS, "idle"), null);
});

// ---- when the switch happens ----

test("when she is standing idle the new outfit is put on as soon as it has loaded", () => {
  const swap = new OutfitSwap("日常");
  swap.begin("睡衣", PAJAMAS, "idle");
  assert.deepEqual(swap.loaded("睡衣", "idle"), { type: "apply", name: "睡衣", clips: PAJAMAS });
});

test("while she is talking or thinking, a loaded outfit waits for her next change of state", () => {
  for (const busy of ["talking:happy", "thinking", "listening"]) {
    const swap = new OutfitSwap("日常");
    swap.begin("睡衣", PAJAMAS, busy);
    assert.equal(swap.loaded("睡衣", busy), null, busy);
    assert.deepEqual(swap.stateChanged("idle"), { type: "apply", name: "睡衣", clips: PAJAMAS }, busy);
  }
});

test("a change of state before the outfit has loaded does not switch to clips that are not there yet", () => {
  const swap = new OutfitSwap("日常");
  swap.begin("睡衣", PAJAMAS, "talking:happy");
  assert.equal(swap.stateChanged("idle"), null);
  assert.deepEqual(swap.loaded("睡衣", "idle"), { type: "apply", name: "睡衣", clips: PAJAMAS });
});

test("the switch happens once", () => {
  const swap = new OutfitSwap("日常");
  swap.begin("睡衣", PAJAMAS, "talking:happy");
  swap.loaded("睡衣", "talking:happy");
  assert.notEqual(swap.stateChanged("idle"), null);
  assert.equal(swap.stateChanged("thinking"), null);
});

test("after the switch the outfit counts as worn, so asking for it again does nothing", () => {
  const swap = new OutfitSwap("日常");
  swap.begin("睡衣", PAJAMAS, "idle");
  swap.loaded("睡衣", "idle");
  assert.equal(swap.begin("睡衣", PAJAMAS, "idle"), null);
});

// ---- trouble ----

test("if loading fails she stays in what she is wearing and the person is told", () => {
  const swap = new OutfitSwap("日常");
  swap.begin("睡衣", PAJAMAS, "idle");
  const decision = swap.failed("睡衣");
  assert.equal(decision.type, "failed");
  assert.match(decision.message, /睡衣/);
  assert.equal(swap.stateChanged("thinking"), null);   // nothing is left pending
});

test("a second request while the first is still loading replaces it, and the first one's late result is ignored", () => {
  const swap = new OutfitSwap("日常");
  swap.begin("睡衣", PAJAMAS, "idle");
  swap.begin("正式", { idle: "/clips/formal/idle.webm" }, "idle");
  assert.equal(swap.loaded("睡衣", "idle"), null);
  assert.equal(swap.failed("睡衣"), null);
  assert.deepEqual(swap.loaded("正式", "idle"), { type: "apply", name: "正式", clips: { idle: "/clips/formal/idle.webm" } });
});

test("asking to go back to the outfit she is wearing cancels a switch that was still pending", () => {
  const swap = new OutfitSwap("日常");
  swap.begin("睡衣", PAJAMAS, "talking:happy");
  swap.loaded("睡衣", "talking:happy");
  assert.equal(swap.begin("日常", CASUAL, "talking:happy"), null);
  assert.equal(swap.stateChanged("idle"), null);
});

test("after a failure, a late 'loaded' for the same outfit does not put it on", () => {
  const swap = new OutfitSwap("日常");
  swap.begin("睡衣", PAJAMAS, "idle");
  swap.failed("睡衣");
  assert.equal(swap.loaded("睡衣", "idle"), null);
});

// ---- first start with no animation at all: every state is a face, nothing is loaded ----

test("with no clips at all, no state has a clip (the page shows its emoji faces instead)", () => {
  for (const state of ["idle", "listening", "thinking", "talking:neutral", "talking:happy"]) {
    assert.equal(clipFor({}, state), undefined);
  }
});

test("with no clips at all, asking for an outfit change has nothing to load and does not throw", () => {
  assert.deepEqual(new OutfitSwap(null).begin("日常", {}, "idle"), []);
});
