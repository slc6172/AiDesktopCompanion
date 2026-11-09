// Decides whether a body/clip change should actually take effect right now, or be suppressed
// because the current clip hasn't been showing long enough yet — the same spirit as the mouth-
// flicker guard originally planned for word-level lip sync (ticket 16, superseded), just applied
// to whole-clip switches instead. A pure function of (requested state, timestamp): no timers, no
// setTimeout, no browser APIs, so it is testable the same way static/vad.js is.
//
// This intentionally *drops* a request that arrives too soon rather than queuing it to fire
// later: if the state keeps changing quickly, only whichever request finally lands at least
// minDwellMs after the last accepted switch gets through, and anything in between is treated as
// a transient the viewer was never meant to see.

const DEFAULT_MIN_DWELL_MS = 220;

class ClipSwitchDebouncer {
  constructor({ minDwellMs = DEFAULT_MIN_DWELL_MS } = {}) {
    this._minDwellMs = minDwellMs;
    this._current = null;
    this._changedAt = null;
  }

  /** Request a switch to `state` at time `atMs` (same clock as every other caller; the browser
   * glue code uses performance.now(), tests use plain numbers). Returns true if this is a real,
   * new, accepted switch — the caller should apply it — or false if it should be ignored
   * (either already showing `state`, or a different state was requested too soon after the
   * last accepted switch). */
  request(state, atMs) {
    if (state === this._current) return false;
    if (this._changedAt !== null && atMs - this._changedAt < this._minDwellMs) return false;
    this._current = state;
    this._changedAt = atMs;
    return true;
  }
}

// Which clip a state shows, inside ONE outfit's clips ({state: url}): its own, else the plain
// talking clip, else idle. Never looks at another outfit.
function clipFor(clips, state) {
  const chain = state.startsWith("talking:") ? [state, "talking:neutral", "idle"] : [state, "idle"];
  return chain.map((k) => clips[k]).find(Boolean);
}

// Putting on a new outfit without ever showing half of it. Pure decisions, no timers and no
// browser APIs: the page does the actual preloading and drawing and asks this when to switch.
//
//   begin(name, clips, playerState)  -> the urls to preload, or null when there is nothing to do
//   loaded(name, playerState)        -> a decision once those urls are ready
//   failed(name)                     -> a decision when they could not be loaded
//   stateChanged(playerState)        -> a decision at every change of her state
//
// A decision is null (nothing to do yet) or {type: "apply", name, clips} (switch now, hard cut)
// or {type: "failed", message} (stay as she is and tell the person). She is switched when she is
// standing idle, or otherwise at her next change of state — the end of a sentence's clip is the
// natural cut. A newer request replaces an older one, whose late results are then ignored.
class OutfitSwap {
  constructor(current = null) {
    this._current = current;
    this._pending = null;
  }

  begin(name, clips, playerState) {
    if (name === this._current) {
      this._pending = null;  // going back to what she already wears cancels a switch still waiting
      return null;
    }
    this._pending = { name, clips, ready: false };
    const urls = [clips.idle, clipFor(clips, playerState)].filter(Boolean);
    return urls.filter((url, i) => urls.indexOf(url) === i);
  }

  loaded(name, playerState) {
    if (!this._pending || this._pending.name !== name) return null;
    this._pending.ready = true;
    return playerState === "idle" ? this._apply() : null;
  }

  failed(name) {
    if (!this._pending || this._pending.name !== name) return null;
    this._pending = null;
    return { type: "failed", message: `換成「${name}」的影片載入失敗,先維持目前的服裝。` };
  }

  stateChanged(_playerState) {
    return this._pending && this._pending.ready ? this._apply() : null;
  }

  _apply() {
    const { name, clips } = this._pending;
    this._current = name;
    this._pending = null;
    return { type: "apply", name, clips };
  }
}

if (typeof module !== "undefined") module.exports = { ClipSwitchDebouncer, DEFAULT_MIN_DWELL_MS, OutfitSwap, clipFor };
else Object.assign(globalThis, { ClipSwitchDebouncer, OutfitSwap, clipFor });
