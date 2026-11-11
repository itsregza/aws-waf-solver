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
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)


class WafError(RuntimeError):
    pass


def parse_goku(html):
    key = re.search(r'["\']key["\']\s*:\s*["\']([^"\']+)["\']', html)
    iv = re.search(r'["\']iv["\']\s*:\s*["\']([^"\']+)["\']', html)
    ctx = re.search(r'["\']context["\']\s*:\s*["\']([^"\']+)["\']', html)
    if not (key and iv and ctx):
        raise WafError("gokuProps not found in page")
    return {"key": key.group(1), "iv": iv.group(1), "context": ctx.group(1)}


def parse_roots(html):
    tok = re.search(r'(?:https:)?//([^"\'\s<>]+token\.awswaf\.com/[^"\'\s<>]+)/challenge\.js', html, re.I)
    if not tok:
        raise WafError("challenge.js url not found in page")
    token_root = "https://" + tok.group(1)
    cap = re.search(r'(?:https:)?//([^"\'\s<>]+captcha\.awswaf\.com/[^"\'\s<>]+)/captcha\.js', html, re.I)
    if cap:
        return token_root, "https://" + cap.group(1), True
    captcha_root = re.sub(r"token\.awswaf\.com", "captcha.awswaf.com", token_root, count=1, flags=re.I)
    return token_root, captcha_root, False


def is_challenge(html):
    return "gokuProps" in html and "challenge.js" in html


def tiles(problem):
    assets = problem.get("assets") or {}
    loc = problem.get("localized_assets") or {}
    target = json.loads(assets.get("target") or "[]")
    raw_imgs = json.loads(assets.get("images") or "[]")
    label = (loc.get("target0") or (target[0] if target else "object")).strip()
    out = []
    for raw in raw_imgs:
        out.append(base64.b64decode(raw.split(",", 1)[-1]))
    return label, out


def proxy_map(raw):
    px = (raw or "").strip()
    if not px:
        return None
    if "://" in px:
        return {"http": px, "https": px}
    parts = px.split(":")
    if len(parts) == 4:
        url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    else:
        url = f"http://{px}"
    return {"http": url, "https": url}


class Waf:
    def __init__(self, url, session=None, ua=None, retries=5, locale="en-gb", log=None):
        if "://" not in url:
            url = "https://" + url
        self.page_url = url if url.endswith("/") else url + "/"
        self.domain = urlparse(self.page_url).netloc
        self.origin = f"https://{self.domain}"
        self.session = session or requests.Session()
        self.ua = ua or UA
        self.retries = max(1, retries)
        self.locale = locale
        self.log = log or (lambda msg: None)
        self.hdrs = {
            "accept": "*/*",
            "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
            "origin": self.origin,
            "referer": self.page_url,
            "user-agent": self.ua,
        }

    def step(self, name, t0):
        self.log(f"{name} ({int((time.perf_counter() - t0) * 1000)}ms)")

    def fetch_page(self):
        t0 = time.perf_counter()
        r = self.session.get(
            self.page_url,
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "user-agent": self.ua,
            },
            timeout=30,
        )
        html = r.text or ""
        if not is_challenge(html):
            raise WafError(f"{self.page_url} did not return an aws waf challenge (http {r.status_code})")
        self.step(f"challenge page {r.status_code}", t0)
        return html

    def token(self, goku, token_root):
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_in = pool.submit(
                self.session.get, token_root + "/inputs?client=browser", headers=self.hdrs, timeout=30
            )
            fut_z = pool.submit(zoey, self.page_url, goku=goku, token_root=token_root)
            r = fut_in.result()
            r.raise_for_status()
            inputs = r.json()
            vm = fut_z.result()
        self.step("inputs + zoey", t0)

        meta = json.loads(json.dumps(vm["meta"]))
        meta["challenge"] = inputs.get("challenge") or meta.get("challenge") or {}
        meta["goku_props"] = goku

        t0 = time.perf_counter()
        r = self.session.post(token_root + "/mp_verify", headers=self.hdrs, files=mp_files(meta), timeout=60)
        r.raise_for_status()
        token = (r.json().get("token") or "").strip()
        if not token:
            raise WafError("mp_verify returned no token")
        self.step("mp_verify", t0)
        return token

    def captcha(self, goku, token_root, captcha_root, interim, cells=None):
        problem_url = f"{captcha_root}/problem?kind=visual&domain={self.domain}&locale={self.locale}"
        post_hdrs = {**self.hdrs, "content-type": "text/plain;charset=UTF-8"}
        err = None
        for attempt in range(1, self.retries + 1):
            if attempt > 1:
                self.log(f"retry {attempt}/{self.retries}")
            try:
                t0 = time.perf_counter()
                r = self.session.get(problem_url, headers=self.hdrs, timeout=30)
                r.raise_for_status()
                problem = r.json()
                label, tile_bytes = tiles(problem)
                self.step(f"captcha problem: {label}", t0)

                t0 = time.perf_counter()
                pick = cells if cells is not None else pick_tiles(f"select all images containing {label}", tile_bytes)
                self.step(f"picked {pick}", t0)

                t0 = time.perf_counter()
                body = {
                    "state": problem.get("state"),
                    "key": problem.get("key"),
                    "hmac_tag": problem.get("hmac_tag"),
                    "client_solution": pick,
                    "metrics": {"solve_time_millis": 12000},
                    "goku_props": goku,
                    "locale": self.locale,
                }
                r = self.session.post(captcha_root + "/verify", headers=post_hdrs, data=json.dumps(body), timeout=30)
                r.raise_for_status()
                data = r.json()
                if not data.get("success"):
                    raise WafError("captcha answer rejected")
                voucher = (data.get("captcha_voucher") or "").strip()
                if not voucher:
                    raise WafError("verify returned no captcha_voucher")
                self.step("captcha verify", t0)

                t0 = time.perf_counter()
                r = self.session.post(
                    token_root + "/voucher",
                    headers=post_hdrs,
                    data=json.dumps({"captcha_voucher": voucher, "existing_token": interim}),
                    timeout=30,
                )
                r.raise_for_status()
                token = (r.json().get("token") or "").strip()
                if not token:
                    raise WafError("voucher returned no token")
                self.step("voucher", t0)
                return token
            except Exception as e:
                err = e
                self.log(f"failed: {e}")
                if cells is not None:
                    break
        raise WafError(f"captcha failed after {self.retries} attempts: {err}")

    def solve(self, html=None, cells=None):
        html = html or self.fetch_page()
        goku = parse_goku(html)
        token_root, captcha_root, has_captcha = parse_roots(html)
        token = self.token(goku, token_root)
        if not has_captcha:
            return token
        return self.captcha(goku, token_root, captcha_root, token, cells=cells)


def solve(url, html=None, session=None, proxy="", retries=5, log=None):
    s = session or requests.Session()
    px = proxy_map(proxy)
    if px:
        s.proxies.update(px)
    return Waf(url, session=s, retries=retries, log=log).solve(html=html)
