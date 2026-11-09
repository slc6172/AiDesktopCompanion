#!/usr/bin/env bash
# Scenarios against the REAL electron/main.js (window state, pin, drag, zoom, tray, click-through MESSAGES).
#   COMPANION_DATA_DIR=<dir> PROJ=<project dir with electron/ companion/ static/> [SCREEN=1366x768] ./run-main.sh scenarios/<name>.js
# Needs openbox + xdotool (installed in the sandbox). Linux cannot do real click-through: see main-launch.js.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCEN="$(realpath "$1")"
: "${PROJ:?set PROJ}"; : "${COMPANION_DATA_DIR:?set COMPANION_DATA_DIR (window-state.json lives there)}"
PY="${PY:-python}"
ELECTRON="${ELECTRON:-$HERE/../electron/node_modules/electron/dist/electron}"
mkdir -p "$COMPANION_DATA_DIR"
PORT="$("$PY" -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')"
export PROJ PORT
"$PY" "$HERE/serve.py" >"/tmp/serve-$PORT.log" 2>&1 &
SPID=$!
trap 'kill -9 $SPID 2>/dev/null' EXIT
for i in $(seq 1 50); do curl -sf "http://127.0.0.1:$PORT/config" >/dev/null && break; sleep 0.2; done
curl -sf "http://127.0.0.1:$PORT/config" >/dev/null || { echo "server did not start:"; cat "/tmp/serve-$PORT.log"; exit 2; }
# main.js and its preload come from $PROJ/electron (the project under test), not from this tests dir
LAUNCH="$(mktemp /tmp/main-launch-XXXX.js)"
sed "s#path.resolve(__dirname, \"../electron/main.js\")#\"$PROJ/electron/main.js\"#" "$HERE/main-launch.js" > "$LAUNCH"
COMPANION_URL="http://127.0.0.1:$PORT/" SCENARIO="$SCEN" \
xvfb-run -a -s "-screen 0 ${SCREEN:-1920x1080}x24" bash -c "(openbox >/dev/null 2>&1 &); sleep 1; exec '$ELECTRON' --no-sandbox --disable-gpu '$LAUNCH' 2>&1 | grep -v -E 'dbus|ERROR:|Fontconfig|libva|gpu_|ALSA'"
STATUS=$?
rm -f "$LAUNCH"
exit $STATUS
