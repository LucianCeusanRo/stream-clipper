"""Shared helpers: config, paths, logging, subprocess, yt-dlp args, CUDA dll setup."""
import json, logging, os, shutil, subprocess, sys, time
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
from pathlib import Path

ROOT = Path(os.environ.get("CLIPPER_HOME", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
FONTS = Path(os.environ.get("CLIPPER_FONTS", ROOT / "fonts"))
log = logging.getLogger("streamclip")


def setup_logging():
    DATA.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(threadName)-9s %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt)
    try:
        sh.stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(DATA / "streamclip.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"); fh.setFormatter(fmt)
    quiet = logging.Filter(); quiet.filter = lambda r: "HTTP Request:" not in r.getMessage() and "HF_TOKEN" not in r.getMessage()
    sh.addFilter(quiet); fh.addFilter(quiet)
    root.addHandler(sh); root.addHandler(fh)
    for noisy in ("faster_whisper", "httpx", "urllib3", "huggingface_hub", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_cfg = None
_cfg_stamp = None
SETTINGS = DATA / "settings.json"     # changes made from the app (override config.yaml)


def _cfg_paths():
    if os.environ.get("CLIPPER_CONFIG"):
        return Path(os.environ["CLIPPER_CONFIG"]), SETTINGS
    p = ROOT / "config.yaml"
    if not p.exists():
        p = Path(__file__).resolve().parent.parent / "config.example.yaml"   # first run: defaults
    return p, SETTINGS


def cfg():
    """config.yaml + data/settings.json overrides; re-read automatically when either file changes."""
    global _cfg, _cfg_stamp
    p, sp = _cfg_paths()
    stamp = tuple((f.stat().st_mtime_ns, f.stat().st_size) if f.exists() else 0 for f in (p, sp))
    if _cfg is None or stamp != _cfg_stamp:
        import yaml
        c = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        over = load_json(sp, {}) if sp.exists() else {}
        c.update(over or {})
        def _tags(lst):
            out = []
            for t in lst or []:
                t = "#" + str(t).strip().lstrip("#")
                if len(t) > 1 and t.lower() not in [o.lower() for o in out]:
                    out.append(t)
            return out
        # optional campaign hashtag (required_hashtag), always FIRST when set
        req = _tags([c["required_hashtag"]]) if c.get("required_hashtag") else []
        c["required_hashtag"] = req[0] if req else ""
        low = {t.lower() for t in req}
        c["hashtags"] = req + [t for t in _tags(c.get("hashtags")) if t.lower() not in low]
        c["extra_hashtags"] = [t for t in _tags(c.get("extra_hashtags")) if t.lower() not in low]
        _cfg, _cfg_stamp = c, stamp
    return _cfg


def save_settings(changes):
    cur = load_json(SETTINGS, {}) if SETTINGS.exists() else {}
    cur.update(changes)
    DATA.mkdir(parents=True, exist_ok=True)
    save_json(SETTINGS, cur)
    global _cfg
    _cfg = None          # never trust the mtime alone (coarse timestamps on some disks)
    return cfg()


BIN = ROOT / "bin"            # setup.bat drops ffmpeg/ffprobe/deno here (no winget, no PATH changes needed)
if BIN.is_dir() and str(BIN) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(BIN) + os.pathsep + os.environ.get("PATH", "")   # yt-dlp finds deno.exe this way


def tool(name):
    local = BIN / (name + (".exe" if sys.platform == "win32" else ""))
    if local.exists():
        return str(local)               # our own copy first (known to have NVENC)
    p = shutil.which(name)
    if not p:
        raise SystemExit(f"{name} nu a fost gasit. Ruleaza setup.bat (instaleaza ffmpeg).")
    return p


def run(cmd, check=True, capture=True, timeout=None):
    r = subprocess.run([str(c) for c in cmd], text=True, encoding="utf-8", errors="replace",
                       stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None,
                       timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))[:300]}\n{(r.stderr or '')[-1500:]}")
    return r


def ytdlp_opts():
    """Options dict for the yt_dlp Python API (shared by every YouTube call)."""
    c = cfg()
    o = {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 30, "retries": 10,
         "fragment_retries": 20, "extractor_retries": 3}
    if c.get("youtube_cookies_from_browser"):
        o["cookiesfrombrowser"] = (c["youtube_cookies_from_browser"],)
    if c.get("youtube_cookies_file"):
        o["cookiefile"] = c["youtube_cookies_file"]
    o["js_runtimes"] = {"deno": {}, "node": {}, "bun": {}}   # YouTube needs a JS runtime (setup.bat installs deno)
    if os.environ.get("CLIPPER_YT_CLIENT"):
        o["extractor_args"] = {"youtube": {"player_client": os.environ["CLIPPER_YT_CLIENT"].split(",")}}
    return o


def setup_cuda_dlls():
    """On Windows, pip's nvidia-cublas/cudnn wheels put DLLs in site-packages/nvidia/*/bin. Add them."""
    if sys.platform != "win32":
        return
    try:
        import nvidia
        base = Path(list(nvidia.__path__)[0])
    except Exception:
        return
    for b in base.glob("*/bin"):
        try:
            os.add_dll_directory(str(b))
        except Exception:
            pass
        os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


# ---- child processes (ffmpeg recorder, chat downloader): never leave orphans behind ----
_children = {}
_children_lock = __import__("threading").Lock()
PIDS = DATA / "children.json"


def spawn(cmd, **kw):
    import atexit
    p = subprocess.Popen([str(c) for c in cmd], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kw)
    with _children_lock:
        if not _children:
            atexit.register(kill_children)
            _install_signal_handlers()
        _children[p.pid] = p
        _write_pids()
    return p


def _install_signal_handlers():
    import signal, threading
    if threading.current_thread() is not threading.main_thread():
        return _pending_signals.append(1)

    def h(sig, frame):
        kill_children()
        raise SystemExit(0)
    for name in ("SIGTERM", "SIGBREAK", "SIGHUP"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), h)
            except Exception:
                pass


_pending_signals = []


def forget(p):
    with _children_lock:
        _children.pop(p.pid, None); _write_pids()


def _write_pids():
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        PIDS.write_text(json.dumps(list(_children)), encoding="utf-8")
    except OSError:
        pass


def kill_children():
    for p in list(_children.values()):
        try:
            p.kill()
        except Exception:
            pass
    _children.clear(); _write_pids()


def kill_stale_children():
    """After a crash/hard kill: stop ffmpeg/yt-dlp processes left running by the previous run."""
    try:
        pids = json.loads(PIDS.read_text(encoding="utf-8"))
    except Exception:
        return
    for pid in pids:
        try:
            pid = int(pid)
            if sys.platform == "win32":     # only if that PID is still an ffmpeg/python of ours (PIDs get reused)
                r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                                   text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if not any(n in r.stdout.lower() for n in ("ffmpeg", "python")):
                    continue
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="ignore") if Path(f"/proc/{pid}").exists() else ""
                if not any(n in cmdline for n in ("ffmpeg", "yt_dlp")):
                    continue
                os.kill(pid, 9)
            log.info("am oprit un proces ramas de la rularea anterioara (pid %s)", pid)
        except Exception:
            pass
    _write_pids()


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def ffprobe_duration(path):
    try:
        r = run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "json", path])
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def sleep_until(stop_event, secs):
    """Sleep that wakes up early on shutdown."""
    end = time.time() + secs
    while not stop_event.is_set() and time.time() < end:
        stop_event.wait(min(1.0, end - time.time()))
