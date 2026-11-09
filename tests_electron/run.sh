#!/usr/bin/env bash
# Page-level Electron scenario runner.
#   PROJ=<project dir (has companion/ and static/)> [CTXISO=0] ./run.sh scenarios/<name>.js [stub.js]
# Env passed through: COMPANION_SPEAKING_BOOST, COMPANION_AUTO_LISTEN, GUM_FAIL, COMPANION_STT_MODE_FILE, PAGE_LOG, OUT
# The server and Electron start AND stop inside this one command (background processes do not survive
# between separate sandbox tool calls).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCEN="$(realpath "$1")"; STUB=""; [ -n "${2:-}" ] && STUB="$(realpath "$2")"
: "${PROJ:?set PROJ to the project directory}"
PY="${PY:-python}"
ELECTRON="${ELECTRON:-$HERE/../electron/node_modules/electron/dist/electron}"
PORT="$("$PY" -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')"
# STT mode file: scenarios write `text` | `empty` | `say:<words>` here to control what the fake STT hears
export COMPANION_STT_MODE_FILE="${COMPANION_STT_MODE_FILE:-/tmp/stt-mode-$PORT}"
echo text > "$COMPANION_STT_MODE_FILE"
export PROJ PORT
"$PY" "$HERE/serve.py" >"/tmp/serve-$PORT.log" 2>&1 &
SPID=$!
trap 'kill -9 $SPID 2>/dev/null' EXIT   # SIGTERM can hang on the long-lived /chat/proactive SSE
for i in $(seq 1 50); do curl -sf "http://127.0.0.1:$PORT/config" >/dev/null && break; sleep 0.2; done
curl -sf "http://127.0.0.1:$PORT/config" >/dev/null || { echo "server did not start:"; cat "/tmp/serve-$PORT.log"; exit 2; }
URL="http://127.0.0.1:$PORT/" SCENARIO="$SCEN" STUB="$STUB" CTXISO="${CTXISO:-1}" \
xvfb-run -a -s "-screen 0 1920x1080x24" bash -c "(openbox >/dev/null 2>&1 &); sleep 1; exec '$ELECTRON' --no-sandbox --disable-gpu '$HERE/runner.js' 2>&1 | grep -v -E 'dbus|ERROR:|Fontconfig|libva|gpu_|ALSA'"
STATUS=$?
# server-side lines the scenarios care about (set COMPANION_DEBUG_LOG=1 to get [audio]/[stt])
grep -E '^\[(audio|stt)\]' "/tmp/serve-$PORT.log" | sed 's/^/[server] /'
exit $STATUS
