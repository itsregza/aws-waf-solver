import atexit
import base64
import json
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VM = ROOT / "js" / "zoey_vm.js"
ZERO = base64.b64encode(b"\x00" * 1024).decode("ascii")
TIMEOUT = 60

proc = None
lock = threading.Lock()
reader = ThreadPoolExecutor(max_workers=1)


def node_path():
    path = shutil.which("node")
    if not path:
        raise RuntimeError("node not found on PATH, install Node.js 18+")
    return path


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


def readline(p, timeout):
    try:
        return reader.submit(p.stdout.readline).result(timeout=timeout)
    except FutureTimeout:
        stop()
        raise RuntimeError(f"node vm timed out after {timeout}s")


def daemon():
    global proc
    if proc is not None and proc.poll() is None:
        return proc
    stop()
    p = subprocess.Popen(
        [node_path(), str(VM), "--daemon"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        cwd=str(ROOT),
    )
    proc = p
    line = readline(p, 15)
    if not line or not json.loads(line.strip()).get("ready"):
        stop()
        raise RuntimeError("node vm failed to start")
    return p


def request(req, timeout=TIMEOUT):
    with lock:
        p = daemon()
        p.stdin.write(json.dumps(req, separators=(",", ":")) + "\n")
        p.stdin.flush()
        line = readline(p, timeout)
        if not line:
            stop()
            raise RuntimeError("node vm exited unexpectedly")
        return json.loads(line.strip())


def mp_files(meta):
    raw = json.dumps(meta, separators=(",", ":"))
    return {
        "solution_metadata": (None, raw, "application/json"),
        "solution_data": (None, ZERO, "application/octet-stream"),
    }


def zoey(page_url, goku=None, token_root=None, tries=2):
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
            err = data.get("error") or "zoey payload was empty"
        except Exception as e:
            err = str(e)
            stop()
    raise RuntimeError(f"zoey failed: {err}")


def warm():
    def run():
        try:
            with lock:
                daemon()
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


atexit.register(stop)
