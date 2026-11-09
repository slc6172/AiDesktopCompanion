#!/usr/bin/env bash
# Mutation check for the PAGE (static/index.html) using the real-Electron scenarios in tests_electron/.
#   tools/pmut.sh "<name>" "<CASES, e.g. 1,7>" "<exact old text>" "<new text>"
# Run from the project root (needs electron/node_modules, xvfb, openbox: see tests_electron/README.md).
# Environment variables you set (e.g. COMPANION_DUCK_LEVEL=0.25) reach the scenario. The page is restored afterwards.
set -u
PY="${PY:-python}"
root="$(pwd)"; page="$root/static/index.html"
name="$1"; cases="$2"; old="$3"; new="$4"
backup="$(mktemp)"; cp "$page" "$backup"
if ! "$PY" - "$page" "$old" "$new" <<'PY'
import sys
path, old, new = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
if text.count(old) != 1:
    sys.exit(f"pattern occurs {text.count(old)} times, need exactly 1: {old[:60]!r}")
open(path, "w", encoding="utf-8").write(text.replace(old, new))
PY
then echo "PATCH ERROR  $name"; cp "$backup" "$page"; rm -f "$backup"; exit 1; fi
out="$(cd tests_electron/scenarios && CASES="$cases" PROJ="$root" CTXISO=0 PY="$PY" timeout -k 5 150 ../run.sh s57_probation.js ../stub-osc.js 2>&1 | grep -E '^FAIL|ALL PASS|SCENARIO ERROR' | head -3 | tr '\n' ' ')"
case "$out" in *"ALL PASS"*) echo "SURVIVED  $name";; *) echo "KILLED    $name  ->  $(echo "$out" | cut -c1-140)";; esac
cp "$backup" "$page"; rm -f "$backup"
