const test = require("node:test");
const assert = require("node:assert");
const { ProbationGate } = require("../static/probation.js");

const types = (actions) => actions.map((a) => a.type);

// ---- a candidate: sound while she is talking/thinking. Duck her, do not cut her off yet. ----

test("sound starting while she is talking or thinking ducks her volume (nothing is cut off)", () => {
  const gate = new ProbationGate();
  assert.deepStrictEqual(gate.handle({ type: "voice_started", assistantActive: true }), [{ type: "duck" }]);
});

test("sound starting while she is silent is an ordinary turn: no duck", () => {
  const gate = new ProbationGate();
  assert.deepStrictEqual(gate.handle({ type: "voice_started", assistantActive: false }), []);
});

test("a candidate that turns out too short (a click, a cough) gives her volume back", () => {
  const gate = new ProbationGate();
  gate.handle({ type: "voice_started", assistantActive: true });
  assert.deepStrictEqual(gate.handle({ type: "voice_too_short" }), [{ type: "restore" }]);
});

test("a too-short clip that was NOT a candidate changes nothing", () => {
  const gate = new ProbationGate();
  gate.handle({ type: "voice_started", assistantActive: false });
  assert.deepStrictEqual(gate.handle({ type: "voice_too_short" }), []);
});

test("a too-short event with nothing recording is ignored, and only the first one restores", () => {
  const gate = new ProbationGate();
  assert.deepStrictEqual(gate.handle({ type: "voice_too_short" }), []);
  gate.handle({ type: "voice_started", assistantActive: true });
  gate.handle({ type: "voice_too_short" });
  assert.deepStrictEqual(gate.handle({ type: "voice_too_short" }), []);
});

// ---- the clip is finished: a candidate is sent "on probation" (she keeps talking, ducked) ----

test("a finished candidate is sent on probation, tagged with the turn it was heard during", () => {
  const gate = new ProbationGate();
  gate.handle({ type: "turn_started" });          // turn 1 is running
  gate.handle({ type: "voice_started", assistantActive: true });
  assert.deepStrictEqual(gate.handle({ type: "voice_finished" }), [{ type: "send", probation: true, wasInterrupt: true, token: 1 }]);
});

test("a finished ordinary clip is sent normally (the page cuts in and starts a new turn at once)", () => {
  const gate = new ProbationGate();
  gate.handle({ type: "voice_started", assistantActive: false });
  assert.deepStrictEqual(gate.handle({ type: "voice_finished" }), [{ type: "send", probation: false, wasInterrupt: false, token: null }]);
});

test("one clip is judged once: after it finishes, the next clip starts from scratch", () => {
  const gate = new ProbationGate();
  gate.handle({ type: "voice_started", assistantActive: true });
  gate.handle({ type: "voice_finished" });
  gate.handle({ type: "voice_started", assistantActive: false });
  assert.strictEqual(gate.handle({ type: "voice_finished" })[0].probation, false);
});

// ---- the verdict on a candidate: not a person after all -> she carries on, the volume comes back ----

const candidateSent = (gate) => {
  gate.handle({ type: "turn_started" });
  gate.handle({ type: "voice_started", assistantActive: true });
  return gate.handle({ type: "voice_finished" })[0].token;
};

test("a rejected candidate (STT heard nothing / unavailable / filtered it out) restores the volume and nothing else", () => {
  const gate = new ProbationGate();
  const token = candidateSent(gate);
  assert.deepStrictEqual(gate.handle({ type: "stt_result", token, kind: "rejected" }), [{ type: "restore" }]);
});

test("a stream that ends without ever deciding is treated as a rejection", () => {
  const gate = new ProbationGate();
  const token = candidateSent(gate);
  assert.deepStrictEqual(gate.handle({ type: "stt_result", token, kind: "ended_undecided" }), [{ type: "restore" }]);
});

test("a network failure before the verdict restores the volume and tells the user, without building a bubble", () => {
  const gate = new ProbationGate();
  const token = candidateSent(gate);
  const actions = gate.handle({ type: "stt_result", token, kind: "network_error" });
  assert.deepStrictEqual(types(actions), ["restore", "note"]);
  assert.match(actions[1].text, /連不上伺服器/);
});

// ---- the verdict on a candidate: real words -> only NOW does the old turn get cut off ----

test("a transcript for a still-current candidate confirms it: the page begins the new turn (which cuts her off)", () => {
  const gate = new ProbationGate();
  const token = candidateSent(gate);
  assert.deepStrictEqual(gate.handle({ type: "stt_result", token, kind: "transcript" }), [{ type: "begin_turn" }]);
});

test("once the new turn has begun, later candidates are tagged with the new turn", () => {
  const gate = new ProbationGate();
  const first = candidateSent(gate);
  gate.handle({ type: "stt_result", token: first, kind: "transcript" });
  gate.handle({ type: "turn_started" });          // the page reports the turn it just began
  gate.handle({ type: "voice_started", assistantActive: true });
  const second = gate.handle({ type: "voice_finished" })[0].token;
  assert.strictEqual(second, first + 1);
});

// ---- a stale candidate: another turn began while it waited for the verdict ----

test("a transcript for a STALE candidate is dropped: it must not cut off the turn that began meanwhile", () => {
  const gate = new ProbationGate();
  const token = candidateSent(gate);               // candidate A is waiting for STT
  gate.handle({ type: "turn_started" });           // the user typed a message: turn B begins
  assert.deepStrictEqual(gate.handle({ type: "stt_result", token, kind: "transcript" }), [{ type: "discard" }]);
});

test("a stale candidate's rejection or network failure touches nothing either (turn B owns the volume and the screen)", () => {
  for (const kind of ["rejected", "ended_undecided", "network_error"]) {
    const gate = new ProbationGate();
    const token = candidateSent(gate);
    gate.handle({ type: "turn_started" });
    assert.deepStrictEqual(gate.handle({ type: "stt_result", token, kind }), [{ type: "discard" }], kind);
  }
});

test("two candidates waiting at once: the first real transcript wins, the second is stale", () => {
  const gate = new ProbationGate();
  const a = candidateSent(gate);
  gate.handle({ type: "voice_started", assistantActive: true });
  const b = gate.handle({ type: "voice_finished" })[0].token;
  assert.strictEqual(a, b);                        // both heard during the same turn
  assert.deepStrictEqual(gate.handle({ type: "stt_result", token: a, kind: "transcript" }), [{ type: "begin_turn" }]);
  gate.handle({ type: "turn_started" });           // the page began the new turn
  assert.deepStrictEqual(gate.handle({ type: "stt_result", token: b, kind: "transcript" }), [{ type: "discard" }]);
});

// ---- rejected candidates are counted separately from "could not understand you" ----

const rejectOne = (gate, kind = "rejected") => gate.handle({ type: "stt_result", token: candidateSent(gate), kind });
const notes = (actions) => actions.filter((a) => a.type === "note");

test("every 5th rejected candidate shows one hint (that it was probably her own echo); the others stay quiet", () => {
  const gate = new ProbationGate();
  const seen = [];
  let hint = null;
  for (let i = 1; i <= 10; i++) {
    const n = notes(rejectOne(gate));
    seen.push(n.length);
    if (n.length) hint = n[0].text;
  }
  assert.deepStrictEqual(seen, [0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  assert.match(hint, /不是人聲/);
  assert.match(hint, /回音/);
});

test("rejected candidates never count toward 'could not understand you' and never ask the page to switch listening off", () => {
  const gate = new ProbationGate();
  for (let i = 0; i < 12; i++) {
    const actions = rejectOne(gate);
    assert.ok(!types(actions).includes("stop_continuous"));
  }
  assert.strictEqual(gate.unclearStreak, 0);
});

test("a stream that ends undecided counts like a rejection; a network failure or a stale candidate does not", () => {
  const gate = new ProbationGate();
  for (let i = 0; i < 4; i++) rejectOne(gate, "ended_undecided");
  rejectOne(gate, "network_error");                                   // not evidence of an echo
  const stale = candidateSent(gate); gate.handle({ type: "turn_started" });
  gate.handle({ type: "stt_result", token: stale, kind: "rejected" }); // belongs to a turn that is gone
  assert.strictEqual(notes(rejectOne(gate)).length, 1);               // this is only the 5th that really counted
});

// ---- the existing "could not understand you" safety net now lives here (moved from the page, same rules) ----

const outcome = (gate, unclear, wasInterrupt = false) => gate.handle({ type: "audio_outcome", unclear, wasInterrupt });

test("three unclear turns in a row switch continuous listening off, with a note", () => {
  const gate = new ProbationGate();
  assert.deepStrictEqual(outcome(gate, true), []);
  assert.deepStrictEqual(outcome(gate, true), []);
  const actions = outcome(gate, true);
  assert.deepStrictEqual(types(actions), ["stop_continuous", "note"]);
  assert.match(actions[1].text, /聽不清楚/);
  assert.strictEqual(gate.unclearStreak, 0);       // starts over after switching off
});

test("a turn that WAS understood resets the unclear streak", () => {
  const gate = new ProbationGate();
  outcome(gate, true); outcome(gate, true);
  outcome(gate, false);
  assert.deepStrictEqual(outcome(gate, true), []);
  assert.deepStrictEqual(outcome(gate, true), []);
  assert.deepStrictEqual(types(outcome(gate, true)), ["stop_continuous", "note"]);
});

test("three unclear turns that were interruptions also mention the echo (once), then start counting again", () => {
  const gate = new ProbationGate();
  outcome(gate, true, true); outcome(gate, true, true);
  const actions = outcome(gate, true, true);
  assert.deepStrictEqual(types(actions), ["stop_continuous", "note", "note"]);
  assert.match(actions[2].text, /回音/);
});

test("an understood interruption forgives the unclear ones before it", () => {
  const gate = new ProbationGate();
  outcome(gate, true, true); outcome(gate, true, true);
  outcome(gate, false, true);
  assert.deepStrictEqual(outcome(gate, true, true), []);
  assert.deepStrictEqual(outcome(gate, true, true), []);
  assert.deepStrictEqual(types(outcome(gate, true, true)), ["stop_continuous", "note", "note"]);   // needs a fresh run of three
});

test("starting to listen again clears the counters and any half-recorded candidate; stopping gives her volume back", () => {
  const gate = new ProbationGate();
  outcome(gate, true); outcome(gate, true);
  for (let i = 0; i < 4; i++) rejectOne(gate);
  gate.handle({ type: "voice_started", assistantActive: true });
  gate.handle({ type: "listening_started" });
  assert.strictEqual(gate.unclearStreak, 0);
  assert.deepStrictEqual(gate.handle({ type: "voice_too_short" }), []);   // the half-recorded candidate is gone
  assert.strictEqual(notes(rejectOne(gate)).length, 0);                   // 4 earlier rejections no longer count
  assert.deepStrictEqual(gate.handle({ type: "listening_stopped" }), [{ type: "restore" }]);
});

test("once a candidate has been sent, a stray too-short event does not give her volume back before the verdict", () => {
  const gate = new ProbationGate();
  gate.handle({ type: "voice_started", assistantActive: true });
  gate.handle({ type: "voice_finished" });             // sent; waiting for the verdict, she stays ducked
  assert.deepStrictEqual(gate.handle({ type: "voice_too_short" }), []);
});
