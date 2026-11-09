const test = require("node:test");
const assert = require("node:assert");
const { CharacterPlayer } = require("../static/player.js");

test("starts idle", () => {
  assert.strictEqual(new CharacterPlayer().state, "idle");
});

test("goes to thinking as soon as the user sends a message", () => {
  const p = new CharacterPlayer();
  p.handle({ type: "sent" });
  assert.strictEqual(p.state, "thinking");
});

test("stays thinking until the first audio starts, then talks with that clip's emotion", () => {
  const p = new CharacterPlayer();
  p.handle({ type: "sent" });
  p.handle({ type: "sentence", text: "你好呀!", emotion: "happy" });
  p.handle({ type: "audio", index: 0, emotion: "happy" });
  assert.strictEqual(p.state, "thinking"); // words arrived, but no sound yet
  p.handle({ type: "audio_started", index: 0 });
  assert.strictEqual(p.state, "talking:happy");
});

test("returns to idle once the reply is done and its audio has finished", () => {
  const p = new CharacterPlayer();
  p.handle({ type: "sent" });
  p.handle({ type: "audio", index: 0, emotion: "happy" });
  p.handle({ type: "audio_started", index: 0 });
  p.handle({ type: "done" });
  assert.strictEqual(p.state, "talking:happy"); // still speaking
  p.handle({ type: "audio_ended" });
  assert.strictEqual(p.state, "idle");
});

test("keeps talking through the gap between sentences until the reply is done", () => {
  const p = new CharacterPlayer();
  p.handle({ type: "sent" });
  p.handle({ type: "audio", index: 0, emotion: "happy" });
  p.handle({ type: "audio_started", index: 0 });
  p.handle({ type: "audio_ended" }); // first clip over; next sentence not here yet
  assert.strictEqual(p.state, "talking:happy");
  p.handle({ type: "audio", index: 1, emotion: "happy" });
  p.handle({ type: "audio_started", index: 1 });
  p.handle({ type: "done" });
  assert.strictEqual(p.state, "talking:happy"); // second clip still playing
  p.handle({ type: "audio_ended" });
  assert.strictEqual(p.state, "idle");
});

for (const [label, events] of [
  ["an unknown emotion", { type: "audio", index: 0, emotion: "furious" }],
  ["a missing emotion", { type: "audio", index: 0 }],
]) {
  test(`falls back to the neutral animation for ${label}`, () => {
    const p = new CharacterPlayer();
    p.handle({ type: "sent" });
    p.handle(events);
    p.handle({ type: "audio_started", index: 0 });
    assert.strictEqual(p.state, "talking:neutral");
  });
}

test("the set of emotions (and the fallback) is configurable", () => {
  const p = new CharacterPlayer({ emotions: ["calm", "cheer"], fallback: "calm" });
  const talkWith = (name) => {
    p.handle({ type: "sent" });
    p.handle({ type: "audio", index: 0, emotion: name });
    p.handle({ type: "audio_started", index: 0 });
    return p.state;
  };
  assert.strictEqual(talkWith("cheer"), "talking:cheer");
  assert.strictEqual(talkWith("happy"), "talking:calm"); // not in this set
});

test("sending a new message mid-speech interrupts: back to thinking, old emotion forgotten", () => {
  const p = new CharacterPlayer();
  p.handle({ type: "sent" });
  p.handle({ type: "audio", index: 0, emotion: "happy" });
  p.handle({ type: "audio_started", index: 0 });
  assert.strictEqual(p.state, "talking:happy");
  p.handle({ type: "sent" });
  assert.strictEqual(p.state, "thinking");
  p.handle({ type: "audio", index: 0, emotion: "angry" });
  p.handle({ type: "audio_started", index: 0 });
  assert.strictEqual(p.state, "talking:angry");
});

test("an error or a text-only reply (no audio) ends in idle, never stuck thinking", () => {
  const withError = new CharacterPlayer();
  withError.handle({ type: "sent" });
  withError.handle({ type: "error", message: "boom" });
  assert.strictEqual(withError.state, "idle");

  const textOnly = new CharacterPlayer();
  textOnly.handle({ type: "sent" });
  textOnly.handle({ type: "sentence", text: "嗨", emotion: "happy" });
  textOnly.handle({ type: "done" });
  assert.strictEqual(textOnly.state, "idle");
});

test("notifies the listener only when the animation state actually changes", () => {
  const seen = [];
  const p = new CharacterPlayer({ onChange: (state) => seen.push(state) });
  p.handle({ type: "sent" });
  p.handle({ type: "audio", index: 0, emotion: "happy" });
  p.handle({ type: "audio_started", index: 0 });
  p.handle({ type: "audio_started", index: 0 }); // no change: already talking
  p.handle({ type: "audio_ended" }); // no change: reply not done yet
  p.handle({ type: "done" });
  assert.deepStrictEqual(seen, ["thinking", "talking:happy", "idle"]);
});

test("asks for a filler sound once when thinking runs past the threshold", () => {
  let fired = 0;
  const p = new CharacterPlayer({ fillerAfterMs: 2000, onFiller: () => fired++ });
  p.handle({ type: "sent", at: 0 });
  p.handle({ type: "tick", at: 1999 });
  assert.strictEqual(fired, 0);
  p.handle({ type: "tick", at: 2000 });
  assert.strictEqual(fired, 1);
  p.handle({ type: "tick", at: 4000 });
  assert.strictEqual(fired, 1); // only once per turn
});

test("no filler once the reply is audible or while idle; each new turn gets its own", () => {
  let fired = 0;
  const p = new CharacterPlayer({ fillerAfterMs: 2000, onFiller: () => fired++ });
  p.handle({ type: "tick", at: 9000 }); // idle: nothing pending
  p.handle({ type: "sent", at: 0 });
  p.handle({ type: "audio", index: 0, emotion: "happy" });
  p.handle({ type: "audio_started", index: 0 });
  p.handle({ type: "tick", at: 5000 }); // already talking
  assert.strictEqual(fired, 0);

  p.handle({ type: "done" });
  p.handle({ type: "audio_ended" });
  p.handle({ type: "sent", at: 10000 });
  p.handle({ type: "tick", at: 12500 });
  assert.strictEqual(fired, 1);
  p.handle({ type: "done" });
  p.handle({ type: "sent", at: 20000 });
  p.handle({ type: "tick", at: 22500 });
  assert.strictEqual(fired, 2);
});

test("starts listening when the user begins speaking", () => {
  const p = new CharacterPlayer();
  p.handle({ type: "listen_started" });
  assert.strictEqual(p.state, "listening");
});

test("speaking over the character interrupts it, and leftovers of the old reply cannot revive it", () => {
  const p = new CharacterPlayer();
  p.handle({ type: "sent", at: 0 });
  p.handle({ type: "audio", index: 0, emotion: "happy" });
  p.handle({ type: "audio_started", index: 0 });
  assert.strictEqual(p.state, "talking:happy");
  p.handle({ type: "listen_started" });
  assert.strictEqual(p.state, "listening");
  p.handle({ type: "audio_ended" }); // stray event from the clip that was cut off
  p.handle({ type: "done" });
  assert.strictEqual(p.state, "listening");
});

test("if nothing usable was heard, the character goes back to idle", () => {
  const p = new CharacterPlayer();
  p.handle({ type: "listen_started" });
  p.handle({ type: "listen_failed" });
  assert.strictEqual(p.state, "idle");
});

test("a spoken message flows on to thinking, and no filler is requested while listening", () => {
  let fired = 0;
  const p = new CharacterPlayer({ fillerAfterMs: 1000, onFiller: () => fired++ });
  p.handle({ type: "listen_started" });
  p.handle({ type: "tick", at: 5000 });
  assert.strictEqual(fired, 0);
  p.handle({ type: "sent", at: 5000 });
  assert.strictEqual(p.state, "thinking");
  p.handle({ type: "tick", at: 6000 });
  assert.strictEqual(fired, 1);
});

test("switches to each clip's own emotion at the moment that clip starts playing", () => {
  const p = new CharacterPlayer();
  p.handle({ type: "sent" });
  p.handle({ type: "audio", index: 0, emotion: "surprised" });
  p.handle({ type: "audio", index: 1, emotion: "happy" });
  p.handle({ type: "audio_started", index: 0 });
  assert.strictEqual(p.state, "talking:surprised");
  p.handle({ type: "audio_ended", index: 0 });
  p.handle({ type: "audio_started", index: 1 });
  assert.strictEqual(p.state, "talking:happy");
});

test("during the gap between two clips the previous emotion stays until the next clip starts", () => {
  // Characterization: passed as soon as it was written.
  const p = new CharacterPlayer();
  p.handle({ type: "sent" });
  p.handle({ type: "audio", index: 0, emotion: "surprised" });
  p.handle({ type: "audio_started", index: 0 });
  p.handle({ type: "audio_ended" });
  p.handle({ type: "audio", index: 1, emotion: "happy" }); // its text and sound have arrived, but it is not playing yet
  assert.strictEqual(p.state, "talking:surprised");
  p.handle({ type: "audio_started", index: 1 });
  assert.strictEqual(p.state, "talking:happy");
});
