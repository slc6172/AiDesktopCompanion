"""Starts the local server and opens the desktop-pet window for it.

The window is Electron's: frameless and genuinely transparent, with a full-body character, a small
toolbar and a slide-out chat panel (see electron/main.js). It needs Node.js and one `npm install`
in the electron/ folder. There is no other way to show the program.
"""
import argparse
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn

from .paths import user_dir

def find_free_port(preferred=8000):
    for port in (preferred, 0):  # 0 = let the OS pick
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("找不到可用的連接埠")


def wait_for_port(port, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.15)
    return False


def show_error(message):
    """Started by run.bat the program has no console (pythonw.exe), so errors must appear in a dialog."""
    logging.getLogger(__name__).error(message)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "AI 動畫朋友", 0x10)
    else:
        print(message, file=sys.stderr)


def start_server(port):
    from .server import create_app

    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_config=None)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    if not wait_for_port(port):
        raise RuntimeError("伺服器沒有在時限內啟動")
    return server


def electron_dir():
    return Path(__file__).resolve().parent.parent / "electron"


def find_electron_binary():
    """The electron/ folder's own local install (one `npm install` run there) — never a
    system-wide electron, so this stays independent of whatever else is on the machine.

    Starts the real program (named in the package's own path.txt, e.g. dist/electron.exe), never
    npm's `.bin/electron.cmd`: that shim is a batch file, so starting it means cmd.exe and then Node
    run first, which needs Node on the PATH at launch and puts a layer of batch-file parsing
    between us and the window. Starting the program itself is exactly what the shim ends up doing.
    """
    package = electron_dir() / "node_modules" / "electron"
    path_txt = package / "path.txt"
    if path_txt.exists():
        program = package / "dist" / path_txt.read_text(encoding="utf-8").strip()
        # path.txt is written by the package's install step; if the program itself is missing the
        # download did not finish, which running `npm install` again repairs.
        return program if program.exists() else None
    return None  # no path.txt: Electron is not installed (npm install in electron/ has not run)


def open_electron_window(url):
    root = electron_dir()
    binary = find_electron_binary()
    if binary is None:
        raise RuntimeError(
            f"找不到 Electron。請先安裝 Node.js(https://nodejs.org),\n"
            f"然後在 {root} 資料夾執行一次:\n  npm install\n之後就可以直接啟動。"
        )
    from .config import resolve_ui_config

    env = dict(
        os.environ,
        COMPANION_URL=url,
        COMPANION_DATA_DIR=str(user_dir() / "data"),  # window-state.json lives here
        COMPANION_ON_TOP_LEVEL=resolve_ui_config()["on_top_level"],
    )
    subprocess.Popen([str(binary), "."], cwd=str(root), env=env).wait()


def set_key_dialog(provider="gemini", label="Gemini API 金鑰"):
    from .apikey import save_api_key

    try:
        import tkinter
        from tkinter import simpledialog

        root = tkinter.Tk()
        root.withdraw()
        key = simpledialog.askstring(label, f"貼上你的{label}(會存進 Windows 憑證管理員):", show="*")
        root.destroy()
    except Exception:
        import getpass

        key = getpass.getpass(f"貼上你的{label}:")
    if key and key.strip():
        save_api_key(key.strip(), provider=provider)
        return True
    return False


def reset_character_state():
    """`--reset-state`: put her outfit, place, body status and belongings back to the start.
    History, memory, affection and the photo quota record are NOT touched."""
    from .state import SqliteState

    path = os.environ.get("COMPANION_DB")
    path = Path(path) if path else user_dir() / "data" / "history.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    SqliteState(path).reset()
    print("已重置角色狀態(服裝、地點、身體狀態、持有物品)。對話紀錄、記憶、好感度與照片額度都沒有動。")


def build_parser():
    parser = argparse.ArgumentParser(description="AI 動畫朋友")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--set-key", action="store_true", help="儲存 Gemini API 金鑰後結束")
    parser.add_argument("--set-key-groq", action="store_true", help="儲存 Groq API 金鑰(語音辨識用)後結束")
    parser.add_argument("--set-key-fish", action="store_true", help="儲存 Fish Audio API 金鑰(語音合成用)後結束")
    parser.add_argument("--set-key-tinyfish", action="store_true", help="儲存 TinyFish API 金鑰(上網查資料用)後結束")
    parser.add_argument("--set-key-cloudflare", action="store_true", help="儲存 Cloudflare API Token(照片生成用)後結束")
    parser.add_argument("--reset-state", action="store_true",
                        help="重置角色狀態(服裝、地點、身體狀態、持有物品)後結束;不動對話、記憶、好感度、照片額度")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    log_file = user_dir() / "data" / "app.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_file, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stdout is None:  # started by pythonw.exe (run.bat): there is no console, so give libraries a file to write to
        sys.stdout = sys.stderr = open(log_file, "a", encoding="utf-8")

    try:
        if args.set_key:
            set_key_dialog()
            return
        if args.set_key_groq:
            set_key_dialog(provider="groq", label="Groq API 金鑰")
            return
        if args.set_key_fish:
            set_key_dialog(provider="fish", label="Fish Audio API 金鑰")
            return
        if args.set_key_tinyfish:
            set_key_dialog(provider="tinyfish", label="TinyFish API 金鑰")
            return
        if args.set_key_cloudflare:
            set_key_dialog(provider="cloudflare", label="Cloudflare API Token")
            return
        if args.reset_state:
            reset_character_state()
            return
        port = find_free_port(args.port)
        server = start_server(port)
        url = f"http://127.0.0.1:{port}/"
        try:
            open_electron_window(url)
        finally:
            server.should_exit = True
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logging.exception("startup failed")
        show_error(f"程式無法啟動:\n{exc}\n\n詳細記錄:{log_file}")
        sys.exit(1)
