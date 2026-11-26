"""Multistream YOUR OWN live: OBS -> local RTMP relay (127.0.0.1) -> YouTube / Twitch / Kick at the same time.
Free and local: ffmpeg receives OBS and copies the stream (no re-encode) to each destination (`tee`, one failing
destination doesn't stop the others). Stream keys are stored encrypted by the OS (Windows Credential Manager /
DPAPI via `keyring`, or DPAPI directly), never in config files or logs.
The relay's input is always the local listener: there is no way to feed it someone else's live or a URL."""
import json
import os
import re
import secrets as _rnd
import subprocess
import threading
import time
from urllib.parse import urlparse

from . import secretstore
from .util import DATA, log, tool

FILE = DATA / "multistream.json"
SERVICE = "StreamClipper-multistream"
DESTS = {   # id -> (label, default ingest server, allowed host suffixes)
    "youtube": ("YouTube", "rtmp://a.rtmp.youtube.com/live2", ("youtube.com",)),
    "twitch": ("Twitch", "rtmp://live.twitch.tv/app", ("twitch.tv", "live-video.net")),
    "kick": ("Kick", "", ("live-video.net", "kick.com")),
}
LOCK = threading.Lock()
STATE = {"state": "off", "msg": "", "since": None, "dests": {}}
_proc = {"p": None, "stop": None, "thread": None}


class MsError(Exception):
    pass


# ---------- settings (no keys in here) ----------
def load():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("port", 1935)
    fresh = "token" not in d
    ds = d.get("dests") if isinstance(d.get("dests"), dict) else {}
    d["dests"] = {k: {"server": str((ds.get(k) or {}).get("server") or DESTS[k][1]),
                      "enabled": bool((ds.get(k) or {}).get("enabled", False))} for k in DESTS}
    if fresh:                                    # the OBS key must stay the same from the first time it's shown
        d["token"] = "sc-" + _rnd.token_hex(6)
        try:
            save(d)
        except OSError:
            pass
    return d


def save(d):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"port": d["port"], "token": d["token"], "dests": d["dests"]}, indent=1), encoding="utf-8")


def check_server(dest, url):
    """Only rtmp(s):// ingest servers of that platform are accepted."""
    u = urlparse(str(url or "").strip())
    host = (u.hostname or "").lower()
    if u.scheme not in ("rtmp", "rtmps") or not host:
        raise MsError(f"{DESTS[dest][0]}: the server must start with rtmp:// or rtmps:// (copy it from the {DESTS[dest][0]} dashboard)")
    if not any(host == s or host.endswith("." + s) for s in DESTS[dest][2]):
        raise MsError(f"{DESTS[dest][0]}: {host} is not a {DESTS[dest][0]} ingest server")
    return str(url).strip().rstrip("/")


def update(port=None, dests=None):
    d = load()
    if port is not None:
        p = int(port)
        if not 1024 <= p <= 65535:
            raise MsError("port must be between 1024 and 65535")
        d["port"] = p
    for k, v in (dests or {}).items():
        if k not in DESTS or not isinstance(v, dict):
            raise MsError(f"unknown destination: {k}")
        srv = str(v.get("server", d["dests"][k]["server"]) or "").strip()
        en = bool(v.get("enabled", d["dests"][k]["enabled"]))
        if srv or en:
            srv = check_server(k, srv)
        d["dests"][k] = {"server": srv, "enabled": en}
    save(d)
    return d


# ---------- encrypted key store ----------
def _keyring():
    return secretstore.keyring_mod()


def _dpapi(data, protect):
    return secretstore.dpapi(data, protect)


_DP = DATA / "multistream.keys"


def _dp_load():
    try:
        return json.loads(_DP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def store_name():
    if _keyring():
        return "Windows Credential Manager" if os.name == "nt" else "system keyring"
    return secretstore.describe()


def set_key(dest, key):
    if dest not in DESTS:
        raise MsError(f"unknown destination: {dest}")
    key = str(key or "").strip()
    if key and (len(key) > 300 or re.search(r"[\s|\[\]]", key)):
        raise MsError("that doesn't look like a stream key (no spaces; copy it again from the dashboard)")
    kr = _keyring()
    if kr:
        if key:
            kr.set_password(SERVICE, dest, key)
        else:
            try:
                kr.delete_password(SERVICE, dest)
            except Exception:
                pass
        return True
    if os.name == "nt":
        import base64
        d = _dp_load()
        if key:
            d[dest] = base64.b64encode(_dpapi(key.encode(), True)).decode()
        else:
            d.pop(dest, None)
        _DP.write_text(json.dumps(d), encoding="utf-8")
        return True
    raise MsError("no secure key store on this system (install a keyring backend); keys are never saved in plain text")


def get_key(dest):
    kr = _keyring()
    if kr:
        try:
            return kr.get_password(SERVICE, dest) or ""
        except Exception:
            return ""
    if os.name == "nt":
        import base64
        v = _dp_load().get(dest)
        return _dpapi(base64.b64decode(v), False).decode() if v else ""
    return ""


def mask(text, keys):
    for k in keys:
        if k:
            text = str(text).replace(k, "••••")
    return text


# ---------- relay ----------
def local_input(d):
    """The ONLY input the relay ever reads: OBS on this PC."""
    return f"rtmp://127.0.0.1:{int(d['port'])}/live/{d['token']}"


def targets(d):
    out = []
    for k, v in d["dests"].items():
        if v["enabled"]:
            key = get_key(k)
            if not key:
                raise MsError(f"{DESTS[k][0]}: add your stream key first")
            out.append((k, check_server(k, v["server"]) + "/" + key, key))
    if not out:
        raise MsError("turn on at least one destination (YouTube, Twitch or Kick)")
    return out


def command(d, tg):
    tee = "|".join(f"[f=flv:onfail=ignore:flvflags=no_duration_filesize]{url}" for _, url, _ in tg)
    return [tool("ffmpeg"), "-hide_banner", "-loglevel", "info", "-nostats", "-listen", "1", "-timeout", "-1",
            "-i", local_input(d), "-map", "0", "-c", "copy", "-f", "tee", tee]


def _loop(d, tg, stop):
    keys = [k for _, _, k in tg]
    while not stop.is_set():
        STATE.update(state="waiting", msg=f"waiting for OBS on rtmp://127.0.0.1:{d['port']}/live", since=None)
        try:
            p = subprocess.Popen(command(d, tg), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            STATE.update(state="error", msg=f"ffmpeg did not start: {e}"); return
        _proc["p"] = p
        last = ""
        for raw in p.stderr:
            line = mask(raw.decode("utf-8", "replace").strip(), keys)
            if not line:
                continue
            last = line
            if STATE["state"] != "live" and ("Input #0" in line or "Stream mapping" in line or "frame=" in line):
                STATE.update(state="live", msg="live: sending to " + ", ".join(DESTS[k][0] for k, _, _ in tg), since=time.time())
            if re.search(r"(?i)error|failed|refused|denied", line) and not re.search(r"Error during demuxing|Immediate exit", line):
                log.warning("multistream: %s", line[:200])
        p.wait()
        _proc["p"] = None
        if stop.is_set():
            break
        if STATE["state"] == "live":
            log.info("multistream: OBS stopped streaming, listening again")
        elif p.returncode:
            STATE.update(state="error", msg=f"relay stopped: {last[:160] or p.returncode}")
            stop.wait(5)
    STATE.update(state="off", msg="", since=None)


def start():
    with LOCK:
        if _proc["thread"] and _proc["thread"].is_alive():
            return status()
        d = load()
        tg = targets(d)
        stop = threading.Event()
        _proc["stop"] = stop
        _proc["thread"] = threading.Thread(target=_loop, args=(d, tg, stop), daemon=True, name="multistream")
        _proc["thread"].start()
        log.info("multistream on: OBS -> %s", ", ".join(DESTS[k][0] for k, _, _ in tg))
        return status()


def stop():
    with LOCK:
        if _proc["stop"]:
            _proc["stop"].set()
        p = _proc["p"]
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        t = _proc["thread"]
    if t:
        t.join(6)
    STATE.update(state="off", msg="", since=None)
    return status()


def status():
    d = load()
    return {"state": STATE["state"], "msg": STATE["msg"], "since": STATE["since"], "port": d["port"],
            "obs_server": f"rtmp://127.0.0.1:{d['port']}/live", "obs_key": d["token"], "store": store_name(),
            "dests": [{"id": k, "label": DESTS[k][0], "server": d["dests"][k]["server"], "enabled": d["dests"][k]["enabled"],
                       "has_key": bool(get_key(k))} for k in DESTS]}
