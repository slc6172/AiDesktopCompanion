"""Manual check against the real Cloudflare Workers AI image model (spec Part 12, section 5; ticket 89).

    set CF_API_TOKEN=...   (or: python app.py --set-key-cloudflare)
    set CF_ACCOUNT_ID=...  (or "account_id" in the image section of config.json)
    python smoke_image.py                 # 3 situations x 2 runs
    python smoke_image.py --runs 3 --outfit 日常

It makes real pictures (saved to data/photos/smoke-*.png), so it uses up some of the free daily allowance.
It shows whether the request shape is accepted (multipart, Bearer, result.image), how long each picture
takes, and which response headers come back (in case one of them reports the cost).

NEURONS: each answer carries a `cf-ai-neurons` header (found on the first real run, 2026-10-29) with what that
picture cost; this script prints it for every picture and the average per situation. Paste the output back:
the numbers decide the default of image.max_per_day (ticket 92). (The free allowance is counted in neurons per
day; the dashboard under Workers AI -> Usage shows the same total, if you want to cross-check.)
"""
import argparse
import sys
import time
from pathlib import Path

import httpx

from companion.apikey import get_api_key
from companion.cloudflare_adapter import CloudflareImage, ImageError
from companion.config import resolve_image_config
from companion.imageprep import shrink_reference
from companion.outfits import Wardrobe
from companion.paths import user_dir
from companion.state import InMemoryState

parser = argparse.ArgumentParser()
parser.add_argument("--runs", type=int, default=2, help="pictures per situation")
parser.add_argument("--outfit", help="which outfit's base photo to use (default: the first one that has one)")
parser.add_argument("--only", choices=["A", "B", "C"], help="run just one situation")
args = parser.parse_args()

settings = resolve_image_config()
token, account = get_api_key("cloudflare"), settings["account_id"]
if not token or not account:
    sys.exit("缺少 CF_API_TOKEN 或 CF_ACCOUNT_ID(或 config.json image.account_id)。")

seen_headers = {}
neurons_of_last = []


def note_headers(response):
    if "cf-ai-neurons" in response.headers:
        neurons_of_last.append(response.headers["cf-ai-neurons"])
    for name, value in response.headers.items():
        if name.lower().startswith(("cf-", "x-", "ratelimit", "retry-after")) and name.lower() not in ("cf-ray", "cf-cache-status"):
            seen_headers[name] = value


adapter = CloudflareImage(token, account, model=settings["model"], timeout=settings["timeout_s"],
                          client=httpx.Client(timeout=settings["timeout_s"], event_hooks={"response": [note_headers]}))
out = user_dir() / "data" / "photos"
out.mkdir(parents=True, exist_ok=True)

wardrobe = Wardrobe(user_dir() / "clips", InMemoryState(), settings=lambda: {"default": None, "aliases": {}})
scan = wardrobe.scan()
name = args.outfit or next(iter(scan.bases), None)
base = scan.bases.get(name) if name else None
reference = shrink_reference(base.read_bytes()) if base else None

PROMPT = "sitting by the window in soft afternoon light, looking at the camera, smiling"
SAME = "Keep the same person, face, hairstyle, body shape and outfit as in the reference image. "
situations = {
    "A": ("A 純文字 %dx%d" % (settings["width"], settings["height"]), SAME.strip() and settings["appearance"] + ". " + PROMPT,
          None, settings["width"], settings["height"]),
    "B": ("B 基底照 + 提示 %dx%d(基底照:%s)" % (settings["width"], settings["height"], name), SAME + PROMPT,
          reference, settings["width"], settings["height"]),
    "C": ("C 純文字 1024x1024(對照組)", settings["appearance"] + ". " + PROMPT, None, 1024, 1024),
}
total = 0
for key, (label, prompt, ref, width, height) in situations.items():
    if args.only and key != args.only:
        continue
    if key == "B" and reference is None:
        print(f"\n[{key}] 略過:找不到任何服裝的基底照(clips/<服裝>/base.png)。")
        continue
    print(f"\n[{label}]")
    costs = []
    for i in range(args.runs):
        del neurons_of_last[:]
        start = time.perf_counter()
        try:
            picture = adapter.generate(prompt, ref, width, height)
        except ImageError as error:
            print(f"  第 {i + 1} 張失敗:{error}(HTTP {error.status}, code {error.code}, timeout={error.timed_out})")
            continue
        total += 1
        cost = neurons_of_last[-1] if neurons_of_last else "?"
        try:
            costs.append(float(cost))
        except ValueError:
            pass
        path = out / f"smoke-{key}-{i + 1}-{int(time.time())}.png"
        path.write_bytes(picture)
        print(f"  第 {i + 1} 張:{time.perf_counter() - start:.1f}s,{len(picture) // 1024} KB -> {path}  neurons={cost}")
    if costs:
        print(f"  平均每張 {sum(costs) / len(costs):.0f} neurons(免費額度每天 10,000 neurons 的話,約 {10000 // (sum(costs) / len(costs)):.0f} 張)")
print(f"\n成功 {total} 張。回應標頭裡可能與額度有關的:", seen_headers or "(沒有)")
print("請依檔案開頭的說明,到儀表板讀 neurons 前後差距,除以張數,貼回來。")
