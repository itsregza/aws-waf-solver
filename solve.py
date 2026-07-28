import json
import os
import sys
import time

import requests

from solver.vlm import configure
from solver.waf import Waf, proxy_map

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(ROOT, "config.json")


def load_cfg():
    with open(CFG, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    if not os.path.isfile(CFG):
        print("copy config.example.json to config.json", file=sys.stderr)
        sys.exit(1)

    try:
        cfg = load_cfg()
    except json.JSONDecodeError as e:
        print(f"bad config.json: {e}", file=sys.stderr)
        sys.exit(1)

    api_key = (cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print("set gemini_api_key in config.json or GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    configure(api_key=api_key, model=(cfg.get("gemini_model") or "").strip() or None)

    url = (cfg.get("url") or "https://minisoshop.co.uk/").strip()
    proxy = (cfg.get("proxy") or "").strip()
    retries = int(cfg.get("retries") or 5)

    s = requests.Session()
    px = proxy_map(proxy)
    if px:
        s.proxies.update(px)

    try:
        t0 = time.perf_counter()
        token = Waf(s, url=url, retries=max(1, retries)).solve()
        ms = int((time.perf_counter() - t0) * 1000)
        print(f"ok {ms}ms")
        print(f"aws-waf-token={token}")
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
