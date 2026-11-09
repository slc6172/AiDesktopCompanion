const test = require("node:test");
const assert = require("node:assert");
const { VoiceActivityDetector } = require("../static/vad.js");

test("starts idle and never fires anything while it only hears quiet samples", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, onChange: (e) => events.push(e) });
  assert.strictEqual(vad.state, "idle");
  for (let at = 0; at <= 2000; at += 100) vad.handle({ type: "sample", volume: 0.01, at });
  assert.strictEqual(vad.state, "idle");
  assert.deepStrictEqual(events, []);
});

test("a loud sample starts speaking and fires a 'started' event", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 0 });
  assert.strictEqual(vad.state, "speaking");
  assert.deepStrictEqual(events, [{ type: "started" }]);
});

test("repeated loud samples while already speaking do not re-fire 'started'", () => {
  // Characterization: passed as soon as it was written.
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 0 });
  vad.handle({ type: "sample", volume: 0.6, at: 100 });
  vad.handle({ type: "sample", volume: 0.4, at: 200 });
  assert.deepStrictEqual(events, [{ type: "started" }]);
});

test("going quiet for the full silence timeout ends a long-enough turn as 'finished'", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, silenceMs: 700, minMs: 500, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 0 });      // starts speaking
  vad.handle({ type: "sample", volume: 0.5, at: 600 });    // still loud: 600ms of speech so far, last loud at 600
  vad.handle({ type: "sample", volume: 0.02, at: 1299 });  // 699ms since last loud: not quite 700ms yet
  assert.strictEqual(vad.state, "speaking");
  vad.handle({ type: "sample", volume: 0.02, at: 1300 });  // now 700ms since last loud
  assert.strictEqual(vad.state, "idle");
  assert.deepStrictEqual(events, [{ type: "started" }, { type: "finished", durationMs: 600 }]);
});

test("too little speech before the silence timeout is 'too_short', not 'finished'", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, silenceMs: 700, minMs: 500, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 1000 });   // starts speaking
  vad.handle({ type: "sample", volume: 0.5, at: 1200 });   // still loud: only 200ms of speech
  vad.handle({ type: "sample", volume: 0.02, at: 1900 });  // 700ms of silence: turn over
  assert.strictEqual(vad.state, "idle");
  assert.deepStrictEqual(events, [{ type: "started" }, { type: "too_short", durationMs: 200 }]);
});

test("volume exactly equal to the threshold counts as loud", () => {
  // Characterization: passed as soon as it was written.
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.1, at: 0 });
  assert.strictEqual(vad.state, "speaking");
  assert.deepStrictEqual(events, [{ type: "started" }]);
});

test("starting to speak and immediately stopping is 'too_short' with a duration of 0", () => {
  // Characterization: passed as soon as it was written.
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, silenceMs: 700, minMs: 500, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 0 });     // a single loud blip
  vad.handle({ type: "sample", volume: 0.02, at: 700 });  // silent from the very next sample onward
  assert.deepStrictEqual(events, [{ type: "started" }, { type: "too_short", durationMs: 0 }]);
});

test("a brief dip below the threshold mid-sentence does not end the turn", () => {
  // Characterization: passed as soon as it was written.
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, silenceMs: 700, minMs: 500, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 0 });     // "hello..."
  vad.handle({ type: "sample", volume: 0.02, at: 300 });  // a natural short pause
  vad.handle({ type: "sample", volume: 0.5, at: 500 });   // "...world" - still the same sentence
  vad.handle({ type: "sample", volume: 0.02, at: 1300 }); // now go quiet for real (800ms since last loud)
  assert.deepStrictEqual(events, [{ type: "started" }, { type: "finished", durationMs: 500 }]);
});

test("thresholds are configurable, not hard-coded", () => {
  // Characterization: passed once the test's own numbers were fixed (see commit notes); no code changed.
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.3, silenceMs: 50, minMs: 10, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.2, at: 0 });   // below this instance's threshold: not loud
  assert.strictEqual(vad.state, "idle");
  vad.handle({ type: "sample", volume: 0.35, at: 100 }); // above it: loud
  vad.handle({ type: "sample", volume: 0.35, at: 120 }); // still loud: 20ms of speech, above this instance's 10ms minimum
  vad.handle({ type: "sample", volume: 0.02, at: 171 }); // past this instance's 50ms silence timeout
  assert.deepStrictEqual(events, [{ type: "started" }, { type: "finished", durationMs: 20 }]);
});

test("after a turn ends, the detector can pick up the next one", () => {
  // Characterization: passed as soon as it was written.
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, silenceMs: 700, minMs: 500, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 0 });
  vad.handle({ type: "sample", volume: 0.02, at: 700 });   // first turn: too_short
  vad.handle({ type: "sample", volume: 0.5, at: 5000 });   // a new turn begins later
  vad.handle({ type: "sample", volume: 0.5, at: 5600 });
  vad.handle({ type: "sample", volume: 0.02, at: 6300 });  // ends: 600ms of speech, long enough
  assert.deepStrictEqual(events, [
    { type: "started" }, { type: "too_short", durationMs: 0 },
    { type: "started" }, { type: "finished", durationMs: 600 },
  ]);
});

test("maximum utterance duration bounds capture during continuous noise", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, silenceMs: 700, minMs: 100, maxMs: 1000, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 0 });
  vad.handle({ type: "sample", volume: 0.5, at: 500 });
  vad.handle({ type: "sample", volume: 0.5, at: 1000 });
  assert.equal(vad.state, "idle");
  assert.deepEqual(events, [{ type: "started" }, { type: "max_duration", durationMs: 1000 }]);
});

test("maximum utterance duration also closes a segment that became quiet", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, silenceMs: 700, minMs: 100, maxMs: 1000, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 0 });
  vad.handle({ type: "sample", volume: 0.5, at: 500 });
  vad.handle({ type: "sample", volume: 0.01, at: 1000 });
  assert.equal(vad.state, "idle");
  assert.deepEqual(events, [{ type: "started" }, { type: "max_duration", durationMs: 500 }]);
});


test("attack confirmation rejects a one-frame click before starting a turn", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, attackMs: 30, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.5, at: 0 });
  vad.handle({ type: "sample", volume: 0.01, at: 16 });
  assert.equal(vad.state, "idle");
  assert.deepEqual(events, []);
});

test("attack confirmation starts after sustained speech and preserves its start timestamp", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, attackMs: 30, releaseThreshold: 0.07, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: 0.2, at: 100 });
  vad.handle({ type: "sample", volume: 0.2, at: 116 });
  assert.equal(vad.state, "idle");
  vad.handle({ type: "sample", volume: 0.2, at: 132 });
  assert.equal(vad.state, "speaking");
  assert.deepEqual(events, [{ type: "started" }]);
  vad.handle({ type: "sample", volume: 0.08, at: 148 }); // release threshold holds speech state
  assert.equal(vad.state, "speaking");
});


test("adaptive VAD raises its gate above a gradually rising low-level noise floor", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.02, adaptive: true, noiseFloor: 0.01, noiseMultiplier: 3, noiseAlpha: 0.1, maxThresholdMultiplier: 2.5, attackMs: 30, onChange: (e) => events.push(e) });
  for (let at = 0; at <= 1000; at += 10) vad.handle({ type: "sample", volume: 0.018, at });
  assert.ok(vad.getThreshold() > 0.02);
  assert.deepEqual(events, []);
});

test("adaptive VAD still detects sustained speech above its noise-adapted threshold", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.02, adaptive: true, noiseFloor: 0.004, noiseMultiplier: 3, noiseAlpha: 0.01, attackMs: 30, silenceMs: 100, minMs: 50, onChange: (e) => events.push(e) });
  for (let at = 0; at <= 100; at += 10) vad.handle({ type: "sample", volume: 0.06, at });
  vad.handle({ type: "sample", volume: 0, at: 220 });
  vad.handle({ type: "sample", volume: 0, at: 310 });
  assert.deepEqual(events, [{ type: "started" }, { type: "finished", durationMs: 100 }]);
});

test("adaptive VAD rejects non-finite sample values instead of entering an invalid state", () => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.02, adaptive: true, onChange: (e) => events.push(e) });
  vad.handle({ type: "sample", volume: Number.NaN, at: 0 });
  vad.handle({ type: "sample", volume: Number.POSITIVE_INFINITY, at: 10 });
  assert.equal(vad.state, "idle");
  assert.deepEqual(events, []);
});

// ---- while the character is talking, the bar is higher (her own voice leaks back into the mic) ----

const makeVad = (opts = {}) => {
  const events = [];
  const vad = new VoiceActivityDetector({ threshold: 0.1, speakingBoost: 2.5, onChange: (e) => events.push(e), ...opts });
  return { vad, events };
};
const sample = (vad, volume, at, speaking) => vad.handle({ type: "sample", volume, at, ...(speaking === undefined ? {} : { speaking }) });

test("while she is speaking, a volume that would normally start an utterance is ignored", () => {
  const { vad, events } = makeVad();
  sample(vad, 0.2, 0, true);                 // 0.2 clears 0.1, but the bar is 0.1 x 2.5 = 0.25 while she talks
  assert.strictEqual(vad.state, "idle");
  assert.deepStrictEqual(events, []);
});

test("while she is speaking, a clearly louder voice (the user cutting in) still starts an utterance", () => {
  const { vad, events } = makeVad();
  sample(vad, 0.4, 0, true);
  assert.strictEqual(vad.state, "speaking");
  assert.deepStrictEqual(events, [{ type: "started" }]);
});

test("the raised bar is inclusive, like the normal one: exactly threshold x boost counts as loud", () => {
  const { vad } = makeVad({ threshold: 0.1, speakingBoost: 2 });
  sample(vad, 0.2, 0, true);
  assert.strictEqual(vad.state, "speaking");
});

test("when she is not speaking the bar is the ordinary one", () => {
  const a = makeVad();
  sample(a.vad, 0.2, 0, false);
  assert.strictEqual(a.vad.state, "speaking");
  const b = makeVad();
  sample(b.vad, 0.2, 0);                      // the flag left out entirely means "not speaking"
  assert.strictEqual(b.vad.state, "speaking");
});

test("her voice leaves an echo tail: the raised bar stays for a moment after she stops", () => {
  const { vad } = makeVad({ tailMs: 400 });
  sample(vad, 0.0, 0, true);                  // she is talking
  sample(vad, 0.2, 100, false);               // she just stopped: room echo still rings, bar still 0.25
  assert.strictEqual(vad.state, "idle");
  sample(vad, 0.2, 399, false);               // one millisecond short of the tail
  assert.strictEqual(vad.state, "idle");
  sample(vad, 0.2, 500, false);               // 500 - 0 >= 400: back to the ordinary bar
  assert.strictEqual(vad.state, "speaking");
});

test("the tail counts from the LAST moment she was heard talking, not the first", () => {
  const { vad } = makeVad({ tailMs: 400 });
  sample(vad, 0.0, 0, true);
  sample(vad, 0.0, 1000, true);               // still talking a second later
  sample(vad, 0.2, 1300, false);              // 300 ms after the last sample of her talking
  assert.strictEqual(vad.state, "idle");
  sample(vad, 0.2, 1400, false);              // 400 ms after: tail over
  assert.strictEqual(vad.state, "speaking");
});

test("with no tail time configured the bar drops the instant she stops", () => {
  const { vad } = makeVad({ tailMs: 0 });
  sample(vad, 0.0, 0, true);
  sample(vad, 0.2, 1, false);
  assert.strictEqual(vad.state, "speaking");
});

test("an utterance that began while she was talking keeps being judged by the raised bar while she still talks", () => {
  const { vad, events } = makeVad({ silenceMs: 300, minMs: 100 });
  for (let at = 0; at <= 200; at += 50) sample(vad, 0.5, at, true);     // the user cuts in, loudly, for 200 ms
  assert.strictEqual(vad.state, "speaking");
  for (let at = 250; at <= 600; at += 50) sample(vad, 0.15, at, true);  // then only 0.15: above 0.1, below the raised 0.25
  assert.strictEqual(vad.state, "idle");      // her echo level does not hold the utterance open
  assert.deepStrictEqual(events.map((e) => e.type), ["started", "finished"]);
  assert.strictEqual(events[1].durationMs, 200);   // it ended where the user's own voice ended
});

test("the same dips do NOT end an utterance when she is not talking", () => {
  const { vad } = makeVad({ silenceMs: 300, minMs: 100 });
  for (let at = 0; at <= 200; at += 50) sample(vad, 0.5, at, false);
  for (let at = 250; at <= 600; at += 50) sample(vad, 0.15, at, false);
  assert.strictEqual(vad.state, "speaking");
});

test("a boost that is missing, below 1, or not a number means no boost at all", () => {
  for (const speakingBoost of [undefined, 1, 0.5, 0, -2, NaN, "2.5", null, Infinity]) {
    const { vad } = makeVad({ speakingBoost });
    sample(vad, 0.11, 0, true);               // just above the ordinary 0.1 bar
    assert.strictEqual(vad.state, "speaking", `boost ${String(speakingBoost)} must not raise the bar`);
  }
});

test("a boost below 1 must never LOWER the bar while she talks (that would make echo easier to trigger)", () => {
  for (const speakingBoost of [0.5, 0, -2, 0.99]) {
    const { vad } = makeVad({ speakingBoost });
    sample(vad, 0.07, 0, true);               // under the ordinary 0.1 bar: must stay quiet
    assert.strictEqual(vad.state, "idle", `boost ${speakingBoost} lowered the bar`);
  }
});

// ---- the adaptive noise floor must not learn her own echo as "steady room noise" ----

const makeAdaptive = (opts = {}) => makeVad({ threshold: 0.03, speakingBoost: 2.5, adaptive: true, ...opts });
const feed = (vad, volume, fromMs, toMs, speaking) => { for (let at = fromMs; at < toMs; at += 10) sample(vad, volume, at, speaking); };

test("echo-level samples while she talks do NOT move the noise floor or the threshold", () => {
  const { vad, events } = makeAdaptive();
  const floor0 = vad.getNoiseFloor();
  const thr0 = vad.getThreshold();
  feed(vad, 0.025, 0, 4000, true);            // four seconds of her echo: below the base 0.03 gate, but it is HER voice
  assert.strictEqual(vad.getNoiseFloor(), floor0);
  assert.strictEqual(vad.getThreshold(), thr0);
  sample(vad, 0.03, 4500, false);             // tail is over; a 0.03 voice must still be heard
  assert.deepStrictEqual(events, [{ type: "started" }]);
});

test("the same samples when she is NOT talking do teach the noise floor (proves it is really adaptive)", () => {
  const { vad } = makeAdaptive();
  const floor0 = vad.getNoiseFloor();
  const thr0 = vad.getThreshold();
  feed(vad, 0.025, 0, 4000, false);
  assert.ok(vad.getNoiseFloor() > floor0, "floor should rise toward steady room noise");
  assert.ok(vad.getThreshold() > thr0, "threshold should rise with it");
});
