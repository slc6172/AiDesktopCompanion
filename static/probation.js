// Decides what to do with a "candidate" interruption: someone (or her own echo) made sound while the
// character was talking or thinking. Pure state machine: events in, actions out, no browser API.
// The page performs the actions (duck / restore the volume, cut her off, show a note, ...).
const UNCLEAR_OFF_NOTE = "持續聆聽好像一直聽不清楚,可能環境比較吵,已經先關閉了。可以改用按住說話,或再按一次「持續聆聽」重新試試。";
const INTERRUPT_MISS_NOTE = "角色說話時仍偵測到回音。已持續啟用麥克風並使用瀏覽器 AEC;若仍發生,請降低喇叭音量或使用耳機。";
const UNCLEAR_LIMIT = 3, INTERRUPT_MISS_LIMIT = 3;
const ECHO_HINT = "偵測到好幾次聲音,但不是人聲,很可能是角色自己的回音,所以已經繼續說完。若常發生,可以降低喇叭音量或使用耳機。";
const HINT_EVERY = 5;
const NETWORK_NOTE = "連不上伺服器,確認程式還在執行後再試一次。";

class ProbationGate {
  constructor() {
    this._recording = false;   // a candidate clip is being recorded right now
    this._turnSeq = 0;         // counts turns that have really begun (see "turn_started")
    this._unclearStreak = 0;   // consecutive turns the user was not understood (never fed by candidates)
    this._rejectedCandidates = 0;
    this._interruptMisses = 0; // unclear turns that were interruptions
  }

  get turnSeq() { return this._turnSeq; }
  get unclearStreak() { return this._unclearStreak; }

  handle(event) {
    switch (event.type) {
      case "voice_started":
        this._recording = event.assistantActive === true;
        return this._recording ? [{ type: "duck" }] : [];
      case "voice_too_short": {
        const wasCandidate = this._recording;
        this._recording = false;
        return wasCandidate ? [{ type: "restore" }] : [];
      }
      case "turn_started":
        this._turnSeq += 1;
        return [];
      case "voice_finished": {
        const probation = this._recording;
        this._recording = false;
        return [{ type: "send", probation, wasInterrupt: probation, token: probation ? this._turnSeq : null }];
      }
      case "stt_result":
        // Another turn began while this candidate waited for its verdict: whatever the verdict, it no
        // longer has anything to say. Never cut off the newer turn, never touch its volume.
        if (event.token !== this._turnSeq) return [{ type: "discard" }];
        if (event.kind === "transcript") return [{ type: "begin_turn" }];
        if (event.kind === "network_error") return [{ type: "restore" }, { type: "note", text: NETWORK_NOTE }];
        // "rejected" | "ended_undecided": not a person after all. This says nothing about whether the user
        // can be understood, so it is counted on its own and never reaches the unclear-streak safety net.
        this._rejectedCandidates += 1;
        return this._rejectedCandidates % HINT_EVERY === 0
          ? [{ type: "restore" }, { type: "note", text: ECHO_HINT }]
          : [{ type: "restore" }];
      case "audio_outcome": {
        const actions = [];
        if (!event.unclear) {
          this._unclearStreak = 0;
          if (event.wasInterrupt) this._interruptMisses = 0;
          return actions;
        }
        this._unclearStreak += 1;
        if (this._unclearStreak >= UNCLEAR_LIMIT) {
          this._unclearStreak = 0;
          actions.push({ type: "stop_continuous" }, { type: "note", text: UNCLEAR_OFF_NOTE });
        }
        if (event.wasInterrupt) {
          this._interruptMisses += 1;
          if (this._interruptMisses >= INTERRUPT_MISS_LIMIT) {
            this._interruptMisses = 0;
            actions.push({ type: "note", text: INTERRUPT_MISS_NOTE });
          }
        }
        return actions;
      }
      case "listening_started":
        this._recording = false;
        this._unclearStreak = 0;
        this._interruptMisses = 0;
        this._rejectedCandidates = 0;
        return [];
      case "listening_stopped":
        this._recording = false;
        return [{ type: "restore" }];
      default:
        return [];
    }
  }
}

if (typeof module !== "undefined") module.exports = { ProbationGate };
else globalThis.ProbationGate = ProbationGate;
