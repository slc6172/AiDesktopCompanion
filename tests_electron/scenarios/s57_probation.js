// Tickets 57-60: candidate -> confirm -> resume, in a real Electron page. Prints PASS/FAIL per expectation.
// run: PROJ=<project> CTXISO=0 ../run.sh s57_probation.js ../stub-osc.js
// Limits: she "talks" through a fake Audio-like object + player events (no audio device in the sandbox); the STT verdict
// delay is simulated in the PAGE (fetch wrapper), not on the server; the STT is the harness' scripted fake.
const fs = require("fs");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
const check = (name, cond, detail = "") => { if (!cond) failures++; console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? "  [" + detail + "]" : ""}`); };

module.exports = async (win, shot, ev) => {
  const modeFile = process.env.COMPANION_STT_MODE_FILE;
  const setStt = (mode) => fs.writeFileSync(modeFile, mode);
  const waitFor = async (expr, ms = 12000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(expr)) return true; await wait(80); } return false; };
  const burst = async (ms, level = 0.12) => { await ev(`window.__setLevel(${level}); void 0`); await wait(ms); await ev(`window.__setLevel(0); void 0`); };
  const want = (n) => !process.env.CASES || process.env.CASES.split(",").includes(String(n));   // CASES=1,3 runs only those
  const msgs = () => ev(`document.querySelectorAll('#log .msg').length`);

  const fresh = async (delayMs = 0) => {
    await win.loadURL(process.env.URL); await wait(900);
    await ev(`window.__stops = 0; window.__aborts = 0; window.__errs = []; window.addEventListener("error", (e) => window.__errs.push(String(e.message)));
      const so = stopAudio; stopAudio = function () { window.__stops++; return so.apply(this, arguments); };
      const ao = abortCurrentSend; abortCurrentSend = function () { window.__aborts++; return ao.apply(this, arguments); };
      window.__audioReqs = 0; window.__pending = false; window.__delay = ${delayMs};
      const f = window.fetch; window.fetch = async function (u, o) {
        if (String(u).includes("/chat/audio")) { window.__audioReqs++; window.__pending = true; const r = await f.apply(this, arguments);
          if (window.__delay) await new Promise((x) => setTimeout(x, window.__delay)); window.__pending = false; return r; }
        return f.apply(this, arguments); };
      startContinuous(); void 0`);
    await wait(2500);
    console.log("   (speakingBoost =", await ev(`speakingBoost()`), "| listening on:", await ev(`contBtn.classList.contains("on")`) + ")");
  };
  const sheTalks = () => ev(`current = { volume: 1, pause() {}, paused: false, ended: false, removeAttribute() {}, load() {} };
      player.handle({ type: "sent", at: performance.now() }); player.handle({ type: "audio_started", index: 0 }); void 0`);

  if (want(1)) try {
    // ---- Case 1: false trigger, STT hears nothing -> ducked, then fully restored; nothing cut, no bubble ----
    console.log("\n== Case 1: false trigger (STT empty)");
    setStt("empty"); await fresh(1500); await sheTalks();
    const m0 = await msgs(), ab0 = await ev(`currentAbort`);
    await ev(`window.__abort0 = (currentAbort = new AbortController()); void 0`);   // a running turn
    await burst(900);
    check("1a ducked while the candidate is recorded", (await ev(`current ? current.volume : null`)) === (await ev(`duckTarget()`)), "volume " + await ev(`current ? current.volume : null`));
    await waitFor(`window.__pending`);
    check("1b still ducked and NOT cut off while the verdict is pending", (await ev(`current ? current.volume : null`)) === (await ev(`duckTarget()`)) && (await ev(`window.__stops`)) === 0 && (await ev(`window.__aborts`)) === 0,
          `volume ${await ev(`current ? current.volume : null`)}, stopAudio ${await ev(`window.__stops`)}, aborts ${await ev(`window.__aborts`)}`);
    await waitFor(`window.__audioReqs >= 1 && !window.__pending`); await wait(300);
    check("1c volume restored to 1", (await ev(`current ? current.volume : null`)) === 1 && (await ev(`duckLevel`)) === 1);
    check("1d stopAudio never called, running turn not aborted", (await ev(`window.__stops`)) === 0 && (await ev(`window.__aborts`)) === 0 && (await ev(`window.__abort0.signal.aborted`)) === false);
    check("1e player still talking", (await ev(`player.state`)).startsWith("talking:"), await ev(`player.state`));
    check("1f no new bubble", (await msgs()) === m0, `${m0} -> ${await msgs()}`);
    check("1g unclearStreak not incremented", (await ev(`gate.unclearStreak`)) === 0);
  } catch (e) { failures++; console.log("FAIL  case 1 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  if (want(2)) try {
    // ---- Case 2: real words -> only AFTER the verdict is she cut off; new turn; volume reset ----
    console.log("\n== Case 2: real words");
    setStt("say:今天天氣真好"); await fresh(1500); await sheTalks();
    const m2 = await msgs();
    await burst(900);
    await waitFor(`window.__pending`);
    check("2a before the verdict: ducked, not cut off", (await ev(`current ? current.volume : null`)) === (await ev(`duckTarget()`)) && (await ev(`window.__stops`)) === 0, `stopAudio ${await ev(`window.__stops`)}`);
    await waitFor(`window.__audioReqs >= 1 && !window.__pending`); await wait(1200);
    check("2b after the verdict: she was cut off exactly once", (await ev(`window.__stops`)) === 1, "stopAudio " + await ev(`window.__stops`));
    check("2c the old turn was aborted", (await ev(`window.__aborts`)) >= 1, "aborts " + await ev(`window.__aborts`));
    check("2d a new turn: two new bubbles (me + ai)", (await msgs()) === m2 + 2, `${m2} -> ${await msgs()}`);
    check("2e the heard words are shown", (await ev(`[...document.querySelectorAll('#log .msg.me')].pop()?.textContent`) || "").includes("今天天氣真好"));
    check("2f duck level reset to 1", (await ev(`duckLevel`)) === 1);
  } catch (e) { failures++; console.log("FAIL  case 2 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  if (want(3)) try {
    // ---- Case 3: stale candidate: another turn began while it waited -> its transcript is dropped ----
    console.log("\n== Case 3: stale candidate");
    setStt("say:這句是過期的候選"); await fresh(3500); await sheTalks();
    await burst(900);
    await waitFor(`window.__pending`);
    await ev(`send("我用打字開了新的回合"); void 0`);                           // turn B begins while A waits
    await wait(400);
    const stopsB = await ev(`window.__stops`), msgsB = await msgs();
    await waitFor(`!window.__pending`); await wait(1500);                       // A's verdict (a real transcript) arrives late
    check("3a the stale transcript did not cut anything off", (await ev(`window.__stops`)) === stopsB, `stopAudio ${stopsB} -> ${await ev(`window.__stops`)}`);
    check("3b no bubbles were added for the stale candidate", (await msgs()) === msgsB, `${msgsB} -> ${await msgs()}`);
    check("3c turn B was not aborted", (await ev(`currentAbort && currentAbort.signal.aborted`)) !== true && !(await ev(`document.body.innerText`)).includes("已中斷"));
    check("3d the stale words never appeared", !(await ev(`document.body.innerText`)).includes("這句是過期的候選"));
    check("3e no page errors", (await ev(`window.__errs.length`)) === 0);
  } catch (e) { failures++; console.log("FAIL  case 3 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  if (want(4)) try {
    // ---- Case 4: her turn ends naturally while a candidate waits -> no errors, volume sane ----
    console.log("\n== Case 4: old turn ends during the candidate");
    setStt("empty"); await fresh(1800); await sheTalks();
    await burst(900); await waitFor(`window.__pending`);
    await ev(`current = null; player.handle({ type: "audio_ended" }); player.handle({ type: "done" }); void 0`);
    await waitFor(`window.__audioReqs >= 1 && !window.__pending`); await wait(500);
    check("4a no page errors", (await ev(`window.__errs.length`)) === 0, await ev(`JSON.stringify(window.__errs)`));
    check("4b duck level back to 1", (await ev(`duckLevel`)) === 1);
  } catch (e) { failures++; console.log("FAIL  case 4 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  if (want(5)) try {
    // ---- Case 5: too_short restores; a candidate while she THINKS does not abort the pending reply ----
    console.log("\n== Case 5: too short / thinking");
    setStt("empty"); await fresh(0); await sheTalks();
    await burst(250);
    await wait(900);
    check("5a short noise: volume restored", (await ev(`current ? current.volume : null`)) === 1);
    check("5b short noise: nothing uploaded", (await ev(`window.__audioReqs`)) === 0);
    check("5c short noise: nothing cut off", (await ev(`window.__stops`)) === 0);
    await fresh(0);
    await ev(`window.__pendingReply = (currentAbort = new AbortController()); player.handle({ type: "sent", at: performance.now() }); void 0`);   // she is only THINKING: a reply is pending
    check("5d (setup) state is thinking", (await ev(`player.state`)) === "thinking", await ev(`player.state`));
    await burst(900); await waitFor(`window.__audioReqs >= 1 && !window.__pending`); await wait(1200);
    check("5e thinking + rejected candidate: the pending reply is NOT aborted", (await ev(`window.__pendingReply.signal.aborted`)) === false && (await ev(`window.__aborts`)) === 0);
    check("5f thinking + rejected candidate: still thinking", (await ev(`player.state`)) === "thinking", await ev(`player.state`));
  } catch (e) { failures++; console.log("FAIL  case 5 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  if (want(6)) try {
    // ---- Case 6: repeated rejected candidates never switch listening off; every 5th gives one hint ----
    console.log("\n== Case 6: 5 rejected candidates in a row");
    setStt("empty"); await fresh(0); await sheTalks();
    const notesNow = () => ev(`[...document.querySelectorAll('#log .note')].map((n) => n.textContent)`);
    const echoNotes = async () => (await notesNow()).filter((t) => t.includes("不是人聲"));
    for (let i = 1; i <= 5; i++) {
      await burst(900); await waitFor(`window.__audioReqs >= ${i} && !window.__pending`); await wait(1800);
      if (i === 3) check("6a after 3 rejections listening is still ON and nothing was switched off", (await ev(`contBtn.classList.contains("on")`)) === true && (await ev(`gate.unclearStreak`)) === 0);
      if (i === 4) check("6b no hint yet after 4", (await echoNotes()).length === 0);
    }
    check("6c exactly one hint after the 5th", (await echoNotes()).length === 1, JSON.stringify(await notesNow()));
    check("6d listening still on, unclearStreak 0", (await ev(`contBtn.classList.contains("on")`)) === true && (await ev(`gate.unclearStreak`)) === 0);
  } catch (e) { failures++; console.log("FAIL  case 6 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  // ---- Case 7: audio that starts while she is ducked is ducked too (new sentence, thinking filler) ----
  if (want(7)) try {
    console.log("\n== Case 7: new audio while ducked");
    setStt("empty"); await fresh(2500); await sheTalks();
    await ev(`fillerEl = new Audio(); void 0`);
    await burst(900); await waitFor(`window.__pending`);
    check("7a the thinking filler is ducked", (await ev(`fillerEl.volume`)) === (await ev(`duckTarget()`)), "volume " + await ev(`fillerEl.volume`));
    const wav = (() => { const n = 4800, b = Buffer.alloc(44 + n * 2); b.write("RIFF", 0); b.writeUInt32LE(36 + n * 2, 4); b.write("WAVEfmt ", 8); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(8000, 24); b.writeUInt32LE(16000, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write("data", 36); b.writeUInt32LE(n * 2, 40); return b.toString("base64"); })();
    await ev(`fillers = ["data:audio/wav;base64,${wav}"]; fillerEl = null; playFiller(); void 0`);   // a NEW thinking filler starts while ducked
    await wait(200);
    check("7d a new thinking filler starts ducked", (await ev(`fillerEl.volume`)) === (await ev(`duckTarget()`)), "volume " + await ev(`fillerEl.volume`));
    await ev(`current = null; fillerEl = null; enqueue({ data: "${wav}", mime: "audio/wav", index: 1 }); void 0`);   // her next sentence arrives while ducked
    await wait(300);
    check("7b her next sentence starts ducked", (await ev(`current && current.volume`)) === (await ev(`duckTarget()`)), "volume " + await ev(`current && current.volume`));
    await waitFor(`window.__audioReqs >= 1 && !window.__pending`); await wait(400);
    check("7c after the verdict (rejected) the playing sentence is back to full volume", (await ev(`current ? current.volume : 1`)) === 1);
  } catch (e) { failures++; console.log("FAIL  case 7 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  // ---- Case 8: switching listening off while ducked gives her volume back ----
  if (want(8)) try {
    console.log("\n== Case 8: stop listening while ducked");
    setStt("empty"); await fresh(4000); await sheTalks();
    await burst(900); await waitFor(`window.__pending`);
    check("8a (setup) ducked", (await ev(`current ? current.volume : null`)) === (await ev(`duckTarget()`)));
    await ev(`stopContinuous(); void 0`); await wait(200);
    check("8b stopping continuous listening restores the volume", (await ev(`current ? current.volume : null`)) === 1 && (await ev(`duckLevel`)) === 1);
  } catch (e) { failures++; console.log("FAIL  case 8 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  // ---- Case 9: network failure while the candidate waits -> restore + note, no bubble, nothing cut ----
  if (want(9)) try {
    console.log("\n== Case 9: network failure on a candidate");
    setStt("text"); await fresh(0); await sheTalks();
    await ev(`const f2 = window.fetch; window.fetch = async function (u) { if (String(u).includes("/chat/audio")) throw new TypeError("network down"); return f2.apply(this, arguments); }; void 0`);
    const m9 = await msgs();
    await burst(900); await wait(2500);
    check("9a volume restored", (await ev(`current ? current.volume : null`)) === 1);
    check("9b the user is told", (await ev(`[...document.querySelectorAll('#log .note')].map((n) => n.textContent).join("|")`)).includes("連不上伺服器"));
    check("9c no bubble, nothing cut off", (await msgs()) === m9 && (await ev(`window.__stops`)) === 0, `msgs ${m9} -> ${await msgs()}, stops ${await ev(`window.__stops`)}`);
  } catch (e) { failures++; console.log("FAIL  case 9 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  // ---- Case 10: three unclear ordinary turns in a row still switch listening off (rule moved into the gate, wired in the page) ----
  if (want(10)) try {
    console.log("\n== Case 10: three unclear turns");
    setStt("empty"); await fresh(0);                                // nothing is recognised: ordinary turns
    for (let i = 1; i <= 3; i++) {
      await burst(900); await waitFor(`window.__audioReqs >= ${i} && !window.__pending`); await wait(3500);
      if (i === 3) await waitFor(`!contBtn.classList.contains("on")`, 8000);
      if (i === 2) check("10a still listening after 2", (await ev(`contBtn.classList.contains("on")`)) === true);
    }
    check("10b after the 3rd unclear turn listening is switched off", (await ev(`contBtn.classList.contains("on")`)) === false);
    check("10c with a note", (await ev(`[...document.querySelectorAll('#log .note')].map((n) => n.textContent).join("|")`)).includes("聽不清楚"));
  } catch (e) { failures++; console.log("FAIL  case 10 crashed: " + String(e.message).split("\n")[0].slice(0, 160)); }

  console.log(`\n${failures === 0 ? "ALL PASS" : failures + " FAILED"}`);
};
