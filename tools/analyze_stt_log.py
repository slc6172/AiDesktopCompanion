#!/usr/bin/env python3
"""Pair the "[audio]" and "[stt]" lines of an app.log (stt.debug_log on) and summarise them.

    python analyze_stt_log.py app.log --main-language Chinese [--unsure "範例文字甲"] [--csv out.csv]

Labelling. By default an INFERENCE (there is no audio): the user speaks only --main-language, so a
recognised clip in any other language is a "phantom"; one in the main language is "real".
Better, when the user tells you what they really said: pass --real TEXT (repeatable) for each thing they
said, plus --strict-candidates, and then EVERY other clip that started while she was talking
(started_speaking=1, or during_speech=1) is a phantom, whatever language it came out in (this is how the
invented garbled-Chinese phantom such as 亂碼範例乙 gets counted). Use --unsure TEXT for clips you cannot classify. It reports: peak-volume ranges per group, how a higher volume bar would
have blocked phantoms / real speech, and how a confidence rule for non-main-language results would do.

NOTHING HERE IS A UNIVERSAL CONSTANT: every number describes ONE person / microphone / speaker / room.
"""
import argparse, re, statistics as st, sys

AUDIO = re.compile(r"\[audio\] (\d+) bytes \| peak=([0-9.]+);during_speech=(\d);started_speaking=(\d);boost=([0-9.]+)(?:;duck=([0-9.]+))?")
STT = re.compile(r"\[stt\] (kept|dropped)(?: \(([^)]*)\))?(?: \(filter off\))? \| (\d+) bytes \| language=(.*?) \| no_speech_prob=(\S+) \| avg_logprob=(\S+) \| (.*)$")


def parse(path):
    rows, pending = [], None
    for line in open(path, encoding="utf-8", errors="replace"):
        m = AUDIO.search(line)
        if m:
            pending = dict(bytes=int(m[1]), peak=float(m[2]), during=int(m[3]), started=int(m[4]), boost=float(m[5]), duck=float(m[6]) if m[6] else None)
            continue
        m = STT.search(line)
        if m:
            r = dict(outcome=m[1], reason=m[2] or "", bytes=int(m[3]), language=m[4].strip(), nsp=m[5], logprob=m[6], text=m[7].strip().strip("'\""))
            r["logprob"] = float(r["logprob"]) if r["logprob"] != "?" else None
            if pending and pending["bytes"] == r["bytes"]:
                r.update(pending)
            else:   # no matching [audio] line (debug_log was off for it, or an older log)
                r.update(peak=None, during=None, started=None, boost=None, duck=None)
            pending = None
            rows.append(r)
    return rows


def label(r, main, unsure, real_texts=(), strict=False):
    norm = lambda t: t.strip().rstrip(".。!!?? ").casefold()
    if r["text"] in unsure:
        return "unsure"
    if norm(r["text"]) in {norm(t) for t in real_texts}:
        return "real"
    if strict and (r["started"] == 1 or r["during"] == 1) and r["started"] is not None:
        return "phantom"        # a candidate the user did not say
    return "real" if r["language"].lower().startswith(main.lower()) else "phantom"


def rng(values):
    v = sorted(values)
    return "n=0" if not v else f"n={len(v)}  min {v[0]:.3f}  median {st.median(v):.3f}  max {v[-1]:.3f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log"); ap.add_argument("--main-language", default="Chinese"); ap.add_argument("--unsure", action="append", default=[]); ap.add_argument("--csv")
    ap.add_argument("--real", action="append", default=[], help="text the user confirms they really said (repeatable)")
    ap.add_argument("--strict-candidates", action="store_true", help="every candidate clip not listed with --real is a phantom")
    a = ap.parse_args()
    rows = parse(a.log)
    if not rows:
        sys.exit("no [stt] lines found (is stt.debug_log on?)")
    for r in rows:
        r["label"] = label(r, a.main_language, set(a.unsure), a.real, a.strict_candidates)
    measured = [r for r in rows if r["peak"] is not None]
    print(f"{len(rows)} clips ({len(measured)} with [audio] measurements)")
    by = {k: [r for r in rows if r["label"] == k] for k in ("real", "phantom", "unsure")}
    print({k: len(v) for k, v in by.items()})
    real = [r for r in by["real"] if r["peak"] is not None]; ph = [r for r in by["phantom"] if r["peak"] is not None]
    print("\nPEAK VOLUME")
    print("  real     :", rng([r["peak"] for r in real]))
    print("  phantom  :", rng([r["peak"] for r in ph]))
    print("  phantom, character was silent  (started_speaking=0):", rng([r["peak"] for r in ph if r["started"] == 0]))
    print("  phantom, character was talking (started_speaking=1):", rng([r["peak"] for r in ph if r["started"] == 1]))
    print("  real, started while the character talked (= genuine cut-ins):", rng([r["peak"] for r in real if r["started"] == 1]))
    talk = [r for r in ph if r["started"] == 1]
    print("\nIF the bar WHILE THE CHARACTER TALKS were B (a clip with peak < B never starts):")
    for bar in (0.04, 0.06, 0.08, 0.10, 0.14, 0.20):
        blocked = sum(r["peak"] < bar for r in talk); lost = [r["text"] for r in real if r["started"] == 1 and r["peak"] < bar]
        print(f"  B={bar:.2f}: blocks {blocked}/{len(talk)} echo phantoms; genuine cut-ins lost: {len(lost)} {lost[:3]}")
    kept_ph = [r for r in by["phantom"] if r["outcome"] == "kept" and r["logprob"] is not None]
    print(f"\nPHANTOMS THAT STILL REACHED THE CHARACTER (kept): {len(kept_ph)} of {len(by['phantom'])}")
    from collections import Counter
    print("  most common:", Counter(r["text"].rstrip(".") for r in kept_ph).most_common(8))
    print("  their avg_logprob   :", sorted(round(r["logprob"], 2) for r in kept_ph))
    print("  real avg_logprob min:", min((r["logprob"] for r in by["real"] if r["logprob"] is not None), default=None))
    print("\nA rule 'non-main-language result needs avg_logprob >= X' would remove this many of them:")
    for x in (-0.3, -0.4, -0.5, -0.6):
        print(f"  X={x:+.2f}: {sum(r['logprob'] < x for r in kept_ph)}/{len(kept_ph)}   (it never touches main-language results)")
    print("  CAUTION: this says nothing about how the user's REAL speech in other languages would score; measure that first.")
    cand_real = [r for r in by["real"] if r["started"] == 1 and r["logprob"] is not None]
    cand_ph = [r for r in by["phantom"] if r["started"] == 1 and r["outcome"] == "kept" and r["logprob"] is not None]
    print(f"\nCANDIDATE-ONLY CONFIDENCE RULE (a clip that started while the character talked is rejected when avg_logprob < X), any language:")
    print("  real candidates' avg_logprob   :", sorted(round(r["logprob"], 2) for r in cand_real))
    print("  kept phantom candidates'       :", sorted(round(r["logprob"], 2) for r in cand_ph))
    for x in (-0.5, -0.6, -0.7, -0.8, -0.9, -1.0):
        lost = [r["text"] for r in cand_real if r["logprob"] < x]
        print(f"  X={x:+.1f}: rejects {sum(r['logprob'] < x for r in cand_ph)}/{len(cand_ph)} kept phantoms; real interruptions lost: {len(lost)} {lost[:3]}")
    print("  CAUTION: tiny samples, one person/device. A real interruption below X is simply ignored: the user must repeat it.")
    ducks = sorted({r["duck"] for r in rows if r["duck"] is not None})
    if ducks:
        print("\nBY ui.duck_level (from the log):", {d: sum(1 for r in rows if r["duck"] == d) for d in ducks})
    if a.csv:
        import csv
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["label", "outcome", "reason", "language", "peak", "during", "started", "boost", "duck", "nsp", "logprob", "text", "bytes"], extrasaction="ignore")
            w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
