const fs = require("fs");
const path = require("path");
const vm = require("vm");
const readline = require("readline");
const { webcrypto } = require("crypto");
const https = require("https");

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36";
const CHALLENGE_PATH = path.join(__dirname, "challenge.js");
const challengeScript = new vm.Script(fs.readFileSync(CHALLENGE_PATH, "utf8"), { filename: "challenge.js" });

function get(url) {
  return new Promise((resolve, reject) => {
    https
      .get(url, { headers: { "user-agent": UA, accept: "text/html,*/*" } }, (res) => {
        let d = "";
        res.on("data", (c) => (d += c));
        res.on("end", () => resolve({ body: d, headers: res.headers }));
      })
      .on("error", reject);
  });
}

function gokuFromHtml(html) {
  const key = html.match(/["']key["']\s*:\s*["']([^"']+)["']/);
  const iv = html.match(/["']iv["']\s*:\s*["']([^"']+)["']/);
  const ctx = html.match(/["']context["']\s*:\s*["']([^"']+)["']/);
  if (!key || !iv || !ctx) throw new Error("goku missing");
  return { key: key[1], iv: iv[1], context: ctx[1] };
}

function wafRoots(html) {
  const tok = html.match(/(https:\/\/[^"']+token\.awswaf\.com\/[^"']+)\/challenge\.js/);
  if (!tok) throw new Error("token root missing");
  return tok[1];
}

function makeWindow(goku, tokenRoot, pageUrl) {
  const storage = {};
  const capture = { meta: null, fetches: [] };
  const glExt = {
    UNMASKED_VENDOR_WEBGL: 37445,
    UNMASKED_RENDERER_WEBGL: 37446,
  };
  const gl = {
    getParameter(p) {
      if (p === glExt.UNMASKED_VENDOR_WEBGL) return "Google Inc. (NVIDIA)";
      if (p === glExt.UNMASKED_RENDERER_WEBGL) return "ANGLE (NVIDIA, NVIDIA GeForce GTX 1050 Ti Direct3D11 vs_5_0 ps_5_0)";
      return null;
    },
    getSupportedExtensions: () => ["WEBGL_debug_renderer_info"],
    getExtension(name) {
      if (name === "WEBGL_debug_renderer_info") return glExt;
      return {};
    },
  };
  const ctx2d = {
    fillStyle: "#000",
    strokeStyle: "#000",
    font: "10px Arial",
    textBaseline: "alphabetic",
    globalCompositeOperation: "source-over",
    fillRect() {},
    fillText() {},
    strokeText() {},
    measureText() {
      return { width: 10 };
    },
    getImageData(_x, _y, w, h) {
      return { data: new Uint8ClampedArray(Math.max(400, (w || 1) * (h || 1) * 4)) };
    },
    putImageData() {},
    drawImage() {},
    arc() {},
    beginPath() {},
    closePath() {},
    fill() {},
    stroke() {},
    moveTo() {},
    lineTo() {},
    rect() {},
    clip() {},
    save() {},
    restore() {},
    translate() {},
    rotate() {},
    scale() {},
    setTransform() {},
    transform() {},
    createLinearGradient() {
      return { addColorStop() {} };
    },
    createRadialGradient() {
      return { addColorStop() {} };
    },
    createPattern() {
      return {};
    },
  };
  const canvas = {
    style: {},
    width: 300,
    height: 150,
    getContext(type) {
      if (type === "webgl" || type === "experimental-webgl") return gl;
      return ctx2d;
    },
    toDataURL: () => "data:image/png;base64,iVBORw0KGgo=",
  };
  ctx2d.canvas = canvas;
  const host = (() => {
    try {
      return new URL(pageUrl).hostname;
    } catch (_) {
      return "minisoshop.co.uk";
    }
  })();
  const origin = `https://${host}`;
  const doc = {
    createElement(tag) {
      if (tag === "canvas") return { ...canvas };
      return {
        style: {},
        appendChild() {},
        removeChild() {},
        setAttribute() {},
        getAttribute: () => null,
        getElementsByTagName: () => [],
        getContext: () => null,
      };
    },
    getElementsByTagName(tag) {
      if (tag === "script") return doc.scripts;
      return [];
    },
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    body: { appendChild() {}, removeChild() {}, clientWidth: 1920, clientHeight: 1080, innerHTML: "" },
    documentElement: { clientWidth: 1920, clientHeight: 1080, style: {}, getAttribute: () => null },
    scripts: [{ src: tokenRoot + "/challenge.js" }],
    addEventListener() {},
    removeEventListener() {},
    cookie: "",
    referrer: "",
    visibilityState: "visible",
    hidden: false,
  };
  const nav = {
    userAgent: UA,
    language: "en-GB",
    languages: ["en-GB", "en"],
    platform: "Win32",
    hardwareConcurrency: 8,
    deviceMemory: 8,
    plugins: [{ name: "PDF Viewer", filename: "internal-pdf-viewer", description: "PDF Viewer", length: 1 }],
    mimeTypes: [],
    webdriver: false,
    maxTouchPoints: 0,
    cookieEnabled: true,
    vendor: "Google Inc.",
    productSub: "20030107",
    connection: { effectiveType: "4g" },
  };
  const win = {
    gokuProps: goku,
    document: doc,
    navigator: nav,
    location: { href: pageUrl, protocol: "https:", hostname: host, origin },
    screen: { width: 1920, height: 1080, colorDepth: 24, availWidth: 1920, availHeight: 1040, pixelDepth: 24 },
    innerWidth: 1920,
    innerHeight: 1080,
    outerWidth: 1920,
    outerHeight: 1080,
    devicePixelRatio: 1,
    performance: { now: () => Date.now() % 100000, timing: { navigationStart: Date.now() - 500 } },
    crypto: webcrypto,
    TextEncoder,
    TextDecoder,
    URL,
    Uint8Array,
    ArrayBuffer,
    atob: (s) => Buffer.from(s, "base64").toString("binary"),
    btoa: (s) => Buffer.from(s, "binary").toString("base64"),
    Blob: class {
      constructor(parts = [], opts = {}) {
        this.parts = parts;
        this.type = (opts && opts.type) || "";
      }
    },
    FormData: class {
      constructor() {
        this.parts = [];
      }
      append(name, value) {
        if (name === "solution_metadata" && typeof value === "string") {
          try {
            capture.meta = JSON.parse(value);
          } catch (_) {}
        }
        this.parts.push([name, value]);
      }
    },
    fetch: async (input, init = {}) => {
      const url = String(typeof input === "string" ? input : input.url);
      capture.fetches.push(url);
      if (url.includes("/inputs")) {
        const r = await get(url);
        return { ok: true, status: 200, json: async () => JSON.parse(r.body) };
      }
      if (url.includes("/mp_verify") && init.body && init.body.parts) {
        for (const [name, value] of init.body.parts) {
          if (name === "solution_metadata" && typeof value === "string") capture.meta = JSON.parse(value);
        }
        return { ok: true, status: 200, json: async () => ({ token: "vm-interim-token" }) };
      }
      if (url.includes("/mp_verify")) {
        return { ok: true, status: 200, json: async () => ({ token: "vm-interim-token" }) };
      }
      if (url.includes("/report") || url.includes("/telemetry")) {
        return { ok: true, status: 200, json: async () => ({}), text: async () => "" };
      }
      const r = await get(url);
      return { ok: r.status === 200, status: r.status || 200, json: async () => JSON.parse(r.body), text: async () => r.body };
    },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    addEventListener() {},
    removeEventListener() {},
    localStorage: {
      getItem: (k) => storage[k] || null,
      setItem: (k, v) => {
        storage[k] = String(v);
      },
      removeItem: (k) => {
        delete storage[k];
      },
    },
    sessionStorage: {
      getItem: (k) => storage[k] || null,
      setItem: (k, v) => {
        storage[k] = String(v);
      },
      removeItem: (k) => {
        delete storage[k];
      },
    },
    FileReader: class {
      blobBuf(blob) {
        const parts = (blob && blob.parts) || [];
        const bufs = parts.map((p) => {
          if (p instanceof ArrayBuffer) return Buffer.from(p);
          if (ArrayBuffer.isView(p)) return Buffer.from(p.buffer, p.byteOffset, p.byteLength);
          if (typeof p === "string") return Buffer.from(p);
          return Buffer.alloc(0);
        });
        return Buffer.concat(bufs.length ? bufs : [Buffer.alloc(1024)]);
      }
      readAsArrayBuffer(blob) {
        setTimeout(() => {
          const buf = this.blobBuf(blob);
          this.result = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
          if (this.onload) this.onload({ target: this });
        }, 0);
      }
      readAsText(blob) {
        setTimeout(() => {
          this.result = this.blobBuf(blob).toString("utf8");
          if (this.onload) this.onload({ target: this });
        }, 0);
      }
      readAsDataURL(blob) {
        setTimeout(() => {
          const mime = (blob && blob.type) || "application/octet-stream";
          const b64 = this.blobBuf(blob).toString("base64");
          this.result = `data:${mime};base64,${b64}`;
          if (this.onload) this.onload({ target: this });
        }, 0);
      }
    },
    Image: class {
      set src(_v) {
        setTimeout(() => this.onload && this.onload(), 0);
      }
    },
    capture,
  };
  win.window = win;
  win.self = win;
  win.globalThis = win;
  win.top = win;
  win.parent = win;
  return win;
}

async function runZoey(opts = {}) {
  const pageUrl = opts.page_url || opts.pageUrl || "https://minisoshop.co.uk/";
  let goku = opts.goku || null;
  let tokenRoot = opts.token_root || opts.tokenRoot || null;
  if (!goku || !tokenRoot) {
    const page = await get(pageUrl);
    goku = goku || gokuFromHtml(page.body);
    tokenRoot = tokenRoot || wafRoots(page.body);
  }
  const sandbox = makeWindow(goku, tokenRoot, pageUrl);
  sandbox.console = { log() {}, warn() {}, error() {} };
  vm.createContext(sandbox);
  challengeScript.runInContext(sandbox, { timeout: 20000 });
  const aws = sandbox.AwsWafIntegration;
  if (!aws) throw new Error("no AwsWafIntegration");
  let token = null;
  if (typeof aws.forceRefreshToken === "function") token = await aws.forceRefreshToken();
  else if (typeof aws.getToken === "function") token = await aws.getToken();
  const meta = sandbox.capture.meta;
  const zoey = meta && (meta.signals || []).find((s) => s.name === "Zoey");
  const present = zoey && zoey.value && zoey.value.Present;
  return {
    ok: !!present,
    token,
    checksum: meta && meta.checksum,
    presentLen: present ? present.length : 0,
    parts: present ? present.split("::").length : 0,
    p0: present ? present.split("::")[0] : "",
    fetches: sandbox.capture.fetches,
    meta,
  };
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

async function daemon() {
  emit({ ready: true });
  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of rl) {
    const raw = (line || "").trim();
    if (!raw) continue;
    try {
      const req = JSON.parse(raw);
      emit(await runZoey(req));
    } catch (e) {
      emit({ ok: false, error: String(e.message || e) });
    }
  }
}

async function main() {
  const arg = process.argv[2] || "";
  if (arg === "--daemon") {
    await daemon();
    return;
  }
  let opts = {};
  if (arg.startsWith("{")) {
    opts = JSON.parse(arg);
  } else if (arg) {
    opts = { page_url: arg };
  }
  try {
    emit(await runZoey(opts));
  } catch (e) {
    emit({ ok: false, error: String(e.message || e), stack: e.stack ? String(e.stack).split("\n").slice(0, 8) : [] });
    process.exitCode = 1;
  }
}

main().catch((e) => {
  emit({ ok: false, error: String(e.message || e) });
  process.exit(1);
});
