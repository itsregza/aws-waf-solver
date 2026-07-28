import atexit
import json
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VM = ROOT / "js" / "zoey_vm.js"
ZERO = __import__("base64").b64encode(b"\x00" * 1024).decode("ascii")

proc = None
lock = threading.Lock()


def stop():
    global proc
    p = proc
    proc = None
    if not p:
        return
    try:
        p.stdin.close()
    except Exception:
        pass
    try:
        p.terminate()
        p.wait(timeout=2)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def daemon():
    global proc
    if proc is not None and proc.poll() is None:
        return proc
    stop()
    p = subprocess.Popen(
        ["node", str(VM), "--daemon"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        cwd=str(ROOT),
    )
    line = p.stdout.readline()
    if not line:
        stop()
        raise RuntimeError("node vm died on start")
    if not json.loads(line.strip()).get("ready"):
        stop()
        raise RuntimeError("node vm not ready")
    proc = p
    return p


def request(req):
    with lock:
        p = daemon()
        p.stdin.write(json.dumps(req, separators=(",", ":")) + "\n")
        p.stdin.flush()
        line = p.stdout.readline()
        if not line:
            stop()
            raise RuntimeError("node vm died")
        return json.loads(line.strip())


def mp_files(meta):
    raw = json.dumps(meta, separators=(",", ":"))
    return {
        "solution_metadata": (None, raw, "application/json"),
        "solution_data": (None, ZERO, "application/octet-stream"),
    }


def zoey(page_url="https://minisoshop.co.uk/", goku=None, token_root=None, tries=2):
    req = {"page_url": page_url}
    if goku:
        req["goku"] = goku
    if token_root:
        req["token_root"] = token_root
    err = None
    for _ in range(tries):
        try:
            data = request(req)
            if data.get("ok") and data.get("meta"):
                return data
            err = data.get("error") or "zoey failed"
        except Exception as e:
            err = str(e)
            stop()
    raise RuntimeError(err or "zoey failed")


def warm():
    def run():
        try:
            daemon()
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


atexit.register(stop)
warm()
