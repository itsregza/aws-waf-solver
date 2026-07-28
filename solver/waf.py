import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from solver.vlm import pick_tiles
from solver.zoey import mp_files, zoey

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


def parse_goku(html):
    key = re.search(r'["\']key["\']\s*:\s*["\']([^"\']+)["\']', html)
    iv = re.search(r'["\']iv["\']\s*:\s*["\']([^"\']+)["\']', html)
    ctx = re.search(r'["\']context["\']\s*:\s*["\']([^"\']+)["\']', html)
    if not (key and iv and ctx):
        raise ValueError("gokuProps missing")
    return {"key": key.group(1), "iv": iv.group(1), "context": ctx.group(1)}


def parse_roots(html):
    tok = re.search(r'(https://[^"\']+token\.awswaf\.com/[^"\']+/challenge\.js)', html)
    cap = re.search(r'(https://[^"\']+captcha\.awswaf\.com/[^"\']+/captcha\.js)', html)
    if not tok or not cap:
        raise ValueError("waf js urls missing")
    return tok.group(1).rsplit("/", 1)[0], cap.group(1).rsplit("/", 1)[0]


def tiles(problem):
    assets = problem.get("assets") or {}
    loc = problem.get("localized_assets") or {}
    target = json.loads(assets.get("target") or "[]")
    raw_imgs = json.loads(assets.get("images") or "[]")
    label = (loc.get("target0") or (target[0] if target else "object")).strip()
    out = []
    for raw in raw_imgs:
        s = raw.split(",", 1)[-1] if raw.startswith("/9j/") else raw
        out.append(base64.b64decode(s))
    return label, out


def proxy_map(raw):
    px = (raw or "").strip()
    if not px:
        return None
    parts = px.split(":")
    if len(parts) == 4:
        url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    else:
        url = f"http://{px}"
    return {"http": url, "https": url}


class Waf:
    def __init__(self, session=None, url="https://minisoshop.co.uk/", ua=None, retries=5):
        self.session = session or requests.Session()
        self.page_url = url if url.endswith("/") else url + "/"
        host = (urlparse(url).netloc or "minisoshop.co.uk").lstrip(".")
        self.domain = host
        self.origin = f"https://{host}"
        self.ua = ua or UA
        self.retries = max(1, retries)

    def solve(self, html=None, cells=None):
        if not html:
            r = self.session.get(
                self.page_url,
                headers={
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "user-agent": self.ua,
                },
                timeout=30,
            )
            html = r.text or ""
            if "gokuProps" not in html and "challenge.js" not in html:
                raise RuntimeError(f"not waf page ({r.status_code})")

        goku = parse_goku(html)
        token_root, captcha_root = parse_roots(html)
        locale = "en-gb"
        hdrs = {
            "accept": "*/*",
            "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
            "origin": self.origin,
            "referer": self.page_url,
            "user-agent": self.ua,
        }
        inputs_url = token_root + "/inputs?client=browser"
        mp_url = token_root + "/mp_verify"

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_in = pool.submit(self.session.get, inputs_url, headers=hdrs, timeout=30)
            fut_z = pool.submit(zoey, self.page_url, goku=goku, token_root=token_root)
            r = fut_in.result()
            r.raise_for_status()
            inputs = r.json()
            vm = fut_z.result()

        meta = json.loads(json.dumps(vm["meta"]))
        meta["challenge"] = inputs.get("challenge") or meta.get("challenge") or {}
        meta["goku_props"] = goku

        r = self.session.post(mp_url, headers=hdrs, files=mp_files(meta), timeout=60)
        r.raise_for_status()
        interim = (r.json().get("token") or "").strip()
        if not interim:
            raise RuntimeError("mp_verify no token")

        problem_url = captcha_root + f"/problem?kind=visual&domain={self.domain}&locale={locale}"
        verify_url = captcha_root + "/verify"
        voucher_url = token_root + "/voucher"
        post_hdrs = {**hdrs, "content-type": "text/plain;charset=UTF-8"}

        err = None
        for _ in range(self.retries):
            r = self.session.get(problem_url, headers=hdrs, timeout=30)
            r.raise_for_status()
            problem = r.json()
            label, tile_bytes = tiles(problem)
            pick = cells if cells is not None else pick_tiles(
                f"select all images containing {label}", tile_bytes
            )
            try:
                body = {
                    "state": problem.get("state"),
                    "key": problem.get("key"),
                    "hmac_tag": problem.get("hmac_tag"),
                    "client_solution": pick,
                    "metrics": {"solve_time_millis": 12000},
                    "goku_props": goku,
                    "locale": locale,
                }
                r = self.session.post(verify_url, headers=post_hdrs, data=json.dumps(body), timeout=30)
                r.raise_for_status()
                data = r.json()
                if not data.get("success"):
                    raise RuntimeError("verify failed")
                voucher = (data.get("captcha_voucher") or "").strip()
                if not voucher:
                    raise RuntimeError("no captcha_voucher")
                r = self.session.post(
                    voucher_url,
                    headers=post_hdrs,
                    data=json.dumps({"captcha_voucher": voucher, "existing_token": interim}),
                    timeout=30,
                )
                r.raise_for_status()
                token = (r.json().get("token") or "").strip()
                if not token:
                    raise RuntimeError("voucher no token")
                return token
            except Exception as e:
                err = e
                if cells is not None:
                    break
        raise RuntimeError(str(err or "solve failed"))

    def solve_timed(self, html=None):
        t0 = time.perf_counter()
        token = self.solve(html=html)
        return token, int((time.perf_counter() - t0) * 1000)


def solve(url="https://minisoshop.co.uk/", html=None, session=None, proxy="", retries=5):
    s = session or requests.Session()
    px = proxy_map(proxy)
    if px:
        s.proxies.update(px)
    return Waf(s, url=url, retries=retries).solve(html=html)
