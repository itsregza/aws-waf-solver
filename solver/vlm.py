import base64
import io
import json
import os
import re
import urllib.error
import urllib.request

CELL = 168
DEFAULT_MODEL = "gemini-flash-lite-latest"
FALLBACK_MODELS = (
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-flash-latest",
)

OPENAI_MODEL = "gpt-4.1-mini"

cfg = {"provider": "gemini", "model": "", "api_key": ""}


def configure(provider=None, model=None, api_key=None):
    if provider:
        cfg["provider"] = provider.strip().lower()
    if model is not None:
        cfg["model"] = (model or "").strip()
    if api_key is not None:
        cfg["api_key"] = (api_key or "").strip()


class HttpErr(RuntimeError):
    def __init__(self, code, body):
        self.code = int(code)
        self.body = body or ""
        super().__init__(f"HTTP {self.code}: {self.body[:500]}")


def key_and_model():
    provider = (cfg.get("provider") or "gemini").strip().lower()
    if provider in ("google", "gemini-flash"):
        provider = "gemini"
    if provider not in ("gemini", "openai"):
        raise RuntimeError(f"unknown provider {provider!r}, use gemini or openai")
    env = ("OPENAI_API_KEY",) if provider == "openai" else ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    key = (cfg.get("api_key") or next((os.environ[k] for k in env if os.environ.get(k)), "")).strip()
    default = OPENAI_MODEL if provider == "openai" else DEFAULT_MODEL
    model = (cfg.get("model") or default).strip()
    if model.lower() in ("gemini-2.0-flash", "gemini-2.0-flash-001"):
        model = DEFAULT_MODEL
    return provider, key, model


def rgb(data):
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


def fit(im, size=CELL):
    from PIL import Image

    resample = getattr(getattr(Image, "Resampling", Image), "BILINEAR", Image.BILINEAR)
    w, h = im.size
    scale = float(size) / float(max(w, h) or 1)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    im = im.resize((nw, nh), resample)
    canvas = Image.new("RGB", (size, size), (18, 18, 22))
    canvas.paste(im, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def tag(im, idx):
    from PIL import ImageDraw, ImageFont

    out = im.copy()
    draw = ImageDraw.Draw(out)
    text = str(idx)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    pad = 4
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = 14, 14
    draw.rectangle((0, 0, tw + pad * 2, th + pad * 2), fill=(0, 0, 0))
    draw.text((pad, pad), text, fill=(255, 220, 0), font=font)
    return out


def jpeg(im, quality=82):
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def montage(tile_bytes):
    from PIL import Image

    cells = [tag(fit(rgb(b)), i) for i, b in enumerate(tile_bytes)]
    grid = Image.new("RGB", (CELL * 3, CELL * 3), (10, 10, 12))
    for i, cell in enumerate(cells):
        grid.paste(cell, ((i % 3) * CELL, (i // 3) * CELL))
    return jpeg(grid)


def prompt(challenge):
    return "\n".join(
        [
            f"Challenge: {challenge}",
            "3x3 grid, yellow numbers are tile ids:",
            "0 1 2 / 3 4 5 / 6 7 8",
            'JSON only: {"click":[...],"reason":"short"}',
            "Click every tile that matches.",
        ]
    )


def norm(click):
    if not isinstance(click, list):
        return []
    out = []
    seen = set()
    for x in click:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= i <= 8 and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def salvage(raw):
    m = re.search(r'"click"\s*:\s*\[([^\]]*)\]', raw or "", flags=re.I)
    if not m:
        return []
    vals = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            vals.append(int(part))
        except ValueError:
            continue
    return norm(vals)


def parse_json(text):
    raw = (text or "").strip()
    if not raw:
        return []
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                data = None
    if isinstance(data, dict):
        got = norm(data.get("click"))
        if got:
            return got
    return salvage(raw)


def post_json(url, payload, headers, timeout=60.0):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise HttpErr(e.code, err) from e


def models(preferred):
    out = []
    for m in (preferred, *FALLBACK_MODELS):
        s = (m or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def gemini_once(text_prompt, image_jpeg, api_key, model):
    b64 = base64.b64encode(image_jpeg).decode("ascii")
    parts = [{"text": text_prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    gen = {"temperature": 0.0, "responseMimeType": "application/json", "maxOutputTokens": 256}
    if "2.5" in (model or "").lower() and "lite" not in (model or "").lower():
        gen["thinkingConfig"] = {"thinkingBudget": 0}
    payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
    data = post_json(url, payload, headers={"Content-Type": "application/json"})
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"gemini empty: {json.dumps(data)[:400]}")
    parts_out = (((cands[0] or {}).get("content") or {}).get("parts")) or []
    text = ""
    for p in parts_out:
        if isinstance(p, dict) and p.get("text"):
            text += str(p["text"])
    return parse_json(text)


def gemini(text_prompt, image_jpeg, api_key, model):
    errors = []
    for mid in models(model):
        try:
            return gemini_once(text_prompt, image_jpeg, api_key, mid)
        except HttpErr as e:
            errors.append(f"{mid}: HTTP {e.code}")
            if e.code == 429:
                raise RuntimeError(f"gemini rate limited on {mid}, free tier keys run out fast") from e
            if e.code in (400, 404):
                continue
            raise
        except Exception as e:
            errors.append(f"{mid}: {e}")
            continue
    raise RuntimeError("gemini failed: " + "; ".join(errors[:6]))


def openai(text_prompt, image_jpeg, api_key, model):
    b64 = base64.b64encode(image_jpeg).decode("ascii")
    payload = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 120,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
    }
    try:
        data = post_json(
            "https://api.openai.com/v1/chat/completions",
            payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
    except HttpErr as e:
        raise RuntimeError(f"openai http {e.code}: {e.body[:200]}") from e
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"openai bad response: {json.dumps(data)[:300]}") from e
    return parse_json(str(text or ""))


def pick_tiles(challenge, tile_bytes):
    if len(tile_bytes) != 9:
        raise ValueError(f"expected 9 tiles, got {len(tile_bytes)}")
    provider, key, model = key_and_model()
    if not key:
        raise RuntimeError(f"no {provider} api key set")
    try:
        sheet = montage(tile_bytes)
    except ImportError as e:
        raise RuntimeError("pillow is missing, run pip install -r requirements.txt") from e
    if provider == "openai":
        return openai(prompt(challenge), sheet, key, model)
    return gemini(prompt(challenge), sheet, key, model)
