import argparse
import json
import os
import sys
import time

import requests

from solver.vlm import configure
from solver.waf import Waf, proxy_map
from solver.zoey import warm

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(ROOT, "config.json")


def load_cfg(path):
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        sys.exit(f"bad {os.path.basename(path)}: {e}")


def args():
    p = argparse.ArgumentParser(description="get an aws-waf-token for a site behind aws waf")
    p.add_argument("url", nargs="?", help="page that serves the waf challenge")
    p.add_argument("-p", "--proxy", help="host:port, host:port:user:pass or a full proxy url")
    p.add_argument("-r", "--retries", type=int, help="captcha attempts (default 5)")
    p.add_argument("--provider", choices=["gemini", "openai"], help="model used for the image captcha")
    p.add_argument("--model", help="override the default model")
    p.add_argument("--config", default=CFG, help="path to config.json")
    p.add_argument("-q", "--quiet", action="store_true", help="only print the token")
    return p.parse_args()


def main():
    a = args()
    cfg = load_cfg(a.config)

    url = (a.url or cfg.get("url") or "").strip()
    if not url:
        sys.exit("no url given, pass one or set url in config.json")

    provider = (a.provider or cfg.get("provider") or "gemini").strip().lower()
    api_key = (cfg.get("api_key") or cfg.get(f"{provider}_api_key") or "").strip()
    configure(provider=provider, model=a.model or cfg.get("model") or cfg.get(f"{provider}_model"), api_key=api_key)

    s = requests.Session()
    px = proxy_map(a.proxy or cfg.get("proxy"))
    if px:
        s.proxies.update(px)

    log = (lambda msg: None) if a.quiet else (lambda msg: print(f"  {msg}", file=sys.stderr, flush=True))
    retries = a.retries or int(cfg.get("retries") or 5)

    warm()
    t0 = time.perf_counter()
    try:
        token = Waf(url, session=s, retries=retries, log=log).solve()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        sys.exit(f"error: {e}")

    if not a.quiet:
        print(f"solved in {int((time.perf_counter() - t0) * 1000)}ms", file=sys.stderr)
    print(token)


if __name__ == "__main__":
    main()
