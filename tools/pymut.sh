#!/usr/bin/env bash
# Mutation check for PYTHON code: break ONE thing, run the tests, expect them to go red.
#   tools/pymut.sh <file> "<name of the mutant>" "<exact old text>" "<new text>" [pytest paths ...]
# Run from the project root. The old text must occur exactly once (else "PATCH ERROR"). The file is restored afterwards.
#   KILLED   = at least one test went red (good).   SURVIVED = all green (the tests would not notice this bug: add one).
# A "KILLED" can be a lie: check that it failed for the REASON you meant (a test-client encoding error once "killed"
# a mutant that was never really exercised).
set -u
PY="${PY:-python}"
file="$1"; name="$2"; old="$3"; new="$4"; shift 4
tests="${*:-tests}"
backup="$(mktemp)"; cp "$file" "$backup"
if ! "$PY" - "$file" "$old" "$new" <<'PY'
import sys
path, old, new = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
if text.count(old) != 1:
    sys.exit(f"pattern occurs {text.count(old)} times, need exactly 1: {old[:60]!r}")
open(path, "w", encoding="utf-8").write(text.replace(old, new))
PY
then echo "PATCH ERROR  $name"; cp "$backup" "$file"; rm -f "$backup"; exit 1; fi
result="$(timeout 180 "$PY" -m pytest -q -p no:cacheprovider -x $tests 2>&1 | tail -1)"
case "$result" in *failed*|*error*) echo "KILLED    $name  ($result)";; *) echo "SURVIVED  $name  ($result)";; esac
cp "$backup" "$file"; rm -f "$backup"
