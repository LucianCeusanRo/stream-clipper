"""Updates from Stream Clipper's official GitHub releases (no git, no token needed on the PC).

check : https://api.github.com/repos/<REPO>/releases/latest  -> tag (vX.Y.Z) + release assets
update: download the release asset StreamClipper-update-vX.Y.Z.zip and SHA256SUMS.txt (both from
        https://github.com/<REPO>/releases/download/<tag>/ only) -> the zip's SHA-256 must match SHA256SUMS.txt
        -> the zip's version.txt must match the tag -> backup of the current code (data/backups/)
        -> overwrite CODE files only -> pip install if requirements.txt changed -> import smoke test.
        Any failure -> the backup is restored (rollback) and the current version keeps running.
Runs on every start (desktop app splash screen) unless Settings -> "Update automatically at start" is off.
Offline / GitHub down / anything odd -> the app simply starts the version it has.
Never touched: data/ (db, clips, settings.json, TikTok browser profile), .venv/, bin/, .env, config.yaml,
config.local.yaml, cookies, the Whisper model cache.

What the checksum protects against: a corrupted or swapped download. It is published in the same release,
so it does not protect against someone taking over the GitHub account; releases are not code-signed (yet).
"""
import hashlib, io, json, os, re, shutil, subprocess, sys, threading, time, urllib.error, urllib.request, zipfile
from pathlib import Path
from urllib.parse import urlparse
from . import __version__
from .util import DATA, ROOT, cfg, log

REPO = "LucianCeusanRo/stream-clipper"
ASSET_RX = re.compile(r"^StreamClipper-update-v(\d+\.\d+\.\d+)\.zip$")
SUMS_NAME = "SHA256SUMS.txt"
DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
PROTECTED_DIRS = {"data", ".venv", "venv", "bin", "cookies", ".git", "samples", "__pycache__", "tiktok_profile", "browser_profile", "models_cache"}
PROTECTED_FILES = {".env", "config.yaml", "config.local.yaml", "data_location.txt", "data_move_pending.json", "data_move_error.txt",
                   "cookies.txt", "youtube_cookies.txt"}
STATE = {"state": "idle", "msg": "", "pct": 0, "latest": None, "checked": 0, "error": None, "release": None}
_lock = threading.Lock()


def repo():
    return REPO          # fixed on purpose: updates can only ever come from this GitHub repo (HTTPS)


def vtuple(v):
    out = []
    for p in str(v or "0").strip().lstrip("v").split("."):
        n = "".join(ch for ch in p if ch.isdigit())
        out.append(int(n) if n else 0)
    return tuple(out + [0] * (3 - len(out)))


def local_version():
    try:
        return (ROOT / "version.txt").read_text(encoding="utf-8").strip() or __version__
    except OSError:
        return __version__


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to GitHub's own download hosts, over HTTPS."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _host_ok(newurl):
            raise urllib.error.URLError(f"redirect refuzat catre {urlparse(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _host_ok(url):
    u = urlparse(url)
    return u.scheme == "https" and (u.hostname or "").lower() in DOWNLOAD_HOSTS + ("api.github.com",)


def _get(url, timeout=20, limit=None):
    if not _host_ok(url):
        raise RuntimeError(f"adresa nepermisa: {url[:80]}")
    opener = urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "StreamClipper-updater", "Accept": "application/octet-stream, application/json"})
    with opener.open(req, timeout=timeout) as r:
        data = r.read((limit or MAX_ZIP) + 1)
    if len(data) > (limit or MAX_ZIP):
        raise RuntimeError("raspuns prea mare")
    return data


def _asset_url_ok(url, tag):
    return url.startswith(f"https://github.com/{repo()}/releases/download/{tag}/")


def latest_release(timeout=8):
    """-> {"version", "tag", "zip_url", "sums_url", "notes", "url"} of the newest release that has an update zip."""
    j = json.loads(_get(f"https://api.github.com/repos/{repo()}/releases/latest", timeout=timeout, limit=2_000_000))
    tag = str(j.get("tag_name") or "")
    zip_url = sums_url = None
    ver = None
    for a in j.get("assets") or []:
        name, url = a.get("name") or "", a.get("browser_download_url") or ""
        m = ASSET_RX.match(name)
        if m and _asset_url_ok(url, tag):
            zip_url, ver = url, m.group(1)
        elif name == SUMS_NAME and _asset_url_ok(url, tag):
            sums_url = url
    if not zip_url or not sums_url or vtuple(ver) != vtuple(tag):
        raise RuntimeError("ultima versiune de pe GitHub nu are fisierele de update (zip + SHA256SUMS.txt)")
    return {"version": ver, "tag": tag, "zip_url": zip_url, "sums_url": sums_url,
            "notes": (j.get("body") or "")[:2000], "url": j.get("html_url")}


def check(force=False, timeout=8):
    """-> latest version string on GitHub (cached 30 min)."""
    if not force and STATE["latest"] and time.time() - STATE["checked"] < 1800:
        return STATE["latest"]
    try:
        rel = latest_release(timeout)
        STATE.update(latest=rel["version"], release=rel, checked=time.time(), error=None)
    except Exception as e:
        STATE.update(error=f"nu pot verifica GitHub: {str(e)[:120]}", checked=time.time())
    return STATE["latest"]


def status(check_now=False, check=None):
    if check is not None:
        check_now = check
    if check_now:
        globals()["check"](force=True)
    cur = local_version()
    lat = STATE["latest"]
    rel = STATE.get("release") or {}
    return {"version": cur, "latest": lat, "available": bool(lat) and vtuple(lat) > vtuple(cur),
            "state": STATE["state"], "msg": STATE["msg"], "pct": STATE["pct"], "error": STATE["error"],
            "notes": rel.get("notes"), "url": rel.get("url"), "repo": repo(), "dev_checkout": is_dev_checkout()}


def check_async():
    threading.Thread(target=lambda: check(force=True), daemon=True, name="update-check").start()


def is_dev_checkout(root: Path = ROOT):
    """A git clone is updated with git, not by overwriting files."""
    return (root / ".git").exists()


def parse_sums(text):
    """SHA256SUMS.txt lines: '<64 hex>  <file name>' -> {name: hex}."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(\S+)\s*$", line.strip())
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


def verify(zbytes, sums_text, name):
    want = parse_sums(sums_text).get(name)
    if not want:
        raise RuntimeError(f"{name} lipseste din {SUMS_NAME}")
    got = hashlib.sha256(zbytes).hexdigest()
    if got != want:
        raise RuntimeError("SHA-256 nu se potriveste: descarcarea e stricata sau modificata, NU o instalez")
    return got


def protected(rel: Path):
    parts = rel.parts
    return (not parts or parts[0] in PROTECTED_DIRS or rel.name in PROTECTED_FILES or "__pycache__" in parts
            or rel.suffix in (".pyc",))


def _sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


MAX_ZIP = 120 * 1024 * 1024
TOP_ALLOWED = {"streamclip", "assets", "fonts", "models", "launcher", "tools", "installer", "README.md", "README.ro.md",
               "THIRD_PARTY.md", "CHANGELOG.md", "LICENSE", "requirements.txt", "version.txt", "config.example.yaml",
               "setup.bat", "run.bat", "run_console.bat", "status.bat", "test.bat", "update.bat", "Stream Clipper.exe",
               ".env.example"}


def _extract(zbytes, dest: Path = None):
    """The update zip has one top folder (stream-clipper/). -> {rel path: bytes}. Rejects anything odd."""
    if len(zbytes) > MAX_ZIP:
        raise RuntimeError("arhiva de update e prea mare")
    files = {}
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > 4 * MAX_ZIP:
            raise RuntimeError("arhiva de update se dezarhiveaza prea mare")
        tops = {i.filename.split("/", 1)[0] for i in infos}
        if len(tops) != 1:
            raise RuntimeError("structura arhivei de update e neasteptata")
        top = tops.pop() + "/"
        for i in infos:
            n = i.filename
            if n.startswith("/") or "\\" in n or ":" in n or (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError(f"cale nepermisa in arhiva: {n}")
            rel = Path(n[len(top):])
            if not rel.parts or ".." in rel.parts:
                raise RuntimeError(f"cale nepermisa in arhiva: {n}")
            if rel.parts[0] not in TOP_ALLOWED:
                continue                                  # unknown top-level things are ignored, never written
            files[rel] = z.read(i)
    return files


def apply(files: dict, root: Path = ROOT, log_fn=print, pip=True, smoke=True):
    """Install new code over root. Returns (old_version, new_version). Rolls back on any failure."""
    if Path("streamclip/__main__.py") not in files or Path("version.txt") not in files:
        raise RuntimeError("arhiva de update nu arata ca Stream Clipper (lipseste streamclip/__main__.py / version.txt)")
    new_ver = files[Path("version.txt")].decode().strip()
    old_ver = (root / "version.txt").read_text(encoding="utf-8").strip() if (root / "version.txt").exists() else "0"
    targets = [rel for rel in files if not protected(rel)]
    old_req = _sha(root / "requirements.txt")
    # 1) backup every file we are going to overwrite (+ note the ones we are going to create)
    bdir = (DATA if root == ROOT else root / "data") / "backups"; bdir.mkdir(parents=True, exist_ok=True)
    backup = bdir / f"code_{old_ver}_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    created = []
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in targets:
            p = root / rel
            if p.exists():
                z.write(p, rel.as_posix())
            else:
                created.append(rel.as_posix())
        z.writestr("_created.json", json.dumps(created))
    log_fn(f"backup: {backup}")
    try:
        # 2) write the new files (skip a locked exe instead of failing the whole update)
        for rel in targets:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            data = files[rel]
            if p.exists() and p.read_bytes() == data:
                continue
            tmp = p.with_name(p.name + ".new")
            tmp.write_bytes(data)
            try:
                os.replace(tmp, p)
            except PermissionError:
                tmp.unlink(missing_ok=True)
                if p.suffix.lower() == ".exe":
                    log_fn(f"[!] {rel} e in folosire, il las pe cel vechi")
                    continue
                raise
        log_fn(f"am copiat {len(targets)} fisiere de cod")
        # 3) dependencies, only if requirements.txt changed
        if pip and _sha(root / "requirements.txt") != old_req:
            py = _venv_python(root)
            log_fn("requirements.txt s-a schimbat -> pip install ...")
            r = subprocess.run([py, "-m", "pip", "install", "-r", str(root / "requirements.txt")], cwd=root,
                               capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                raise RuntimeError("pip install a esuat: " + (r.stderr or r.stdout)[-400:])
        # 4) the new code must at least import
        if smoke:
            py = _venv_python(root)
            env = dict(os.environ, PYTHONPATH=str(root), CLIPPER_HOME=str(root))
            env.pop("CLIPPER_CONFIG", None)
            r = subprocess.run([py, "-c", "import streamclip.app, streamclip.web, streamclip.pipeline; print('ok')"], cwd=root, env=env,
                               capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                raise RuntimeError("noul cod nu porneste: " + (r.stderr or "")[-400:])
    except Exception:
        log_fn("EROARE -> revin la versiunea veche (rollback)")
        rollback(backup, root)
        raise
    return old_ver, new_ver


def rollback(backup: Path, root: Path = ROOT):
    with zipfile.ZipFile(backup) as z:
        for n in z.namelist():
            if n == "_created.json":
                for rel in json.loads(z.read(n)):
                    (root / rel).unlink(missing_ok=True)
                continue
            p = root / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(z.read(n))


def _venv_python(root: Path):
    for c in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
        if c.exists():
            return str(c)
    return sys.executable.replace("pythonw.exe", "python.exe")


def download(rel=None, on_pct=None):
    """Download the release zip + checksums from the official release and verify. -> verified zip bytes."""
    rel = rel or latest_release()
    sums = _get(rel["sums_url"], timeout=30, limit=100_000).decode("utf-8", "replace")
    name = rel["zip_url"].rsplit("/", 1)[1]
    zb = _get(rel["zip_url"], timeout=300)
    if on_pct:
        on_pct(60)
    verify(zb, sums, name)
    return zb


def run_update(log_fn=print, pip=True, rel=None):
    if is_dev_checkout():
        raise RuntimeError("folderul e un clone git: actualizeaza cu 'git pull'")
    rel = rel or latest_release()
    zb = download(rel)
    log_fn(f"descarcat {len(zb) / 1e6:.1f} MB, SHA-256 verificat")
    files = _extract(zb, ROOT)
    v = files.get(Path("version.txt"), b"").decode("utf-8", "replace").strip()
    if vtuple(v) != vtuple(rel["version"]):
        raise RuntimeError(f"versiunea din arhiva ({v}) nu e cea din release ({rel['version']})")
    return apply(files, ROOT, log_fn, pip=pip)


def startup_update(on_status=lambda msg, pct: None, timeout=6):
    """Called by the desktop app before the engine starts (splash screen).
    -> "updated" (caller restarts), "current", "skipped" or "failed". Never raises."""
    try:
        c = cfg()
        if not c.get("auto_update", True) or os.environ.get("CLIPPER_NO_UPDATE") or is_dev_checkout():
            return "skipped"
        on_status("Checking for updates…", 5)
        try:
            rel = latest_release(timeout)
        except Exception as e:
            log.info("update: verificare sarita (%s)", str(e)[:120])
            on_status("Offline or GitHub not reachable, starting this version", 100)
            return "skipped"
        STATE.update(latest=rel["version"], release=rel, checked=time.time(), error=None)
        if vtuple(rel["version"]) <= vtuple(local_version()):
            on_status(f"Up to date (v{local_version()})", 100)
            return "current"
        on_status(f"Downloading v{rel['version']}…", 20)
        n = [20]

        def lf(m):
            log.info("update: %s", m); n[0] = min(95, n[0] + 15); on_status(m, n[0])
        old, new = run_update(lf, rel=rel)
        log.info("UPDATE la pornire reusit %s -> %s", old, new)
        on_status(f"Updated to v{new}, restarting…", 100)
        return "updated"
    except Exception as e:
        log.warning("update la pornire esuat, pornesc versiunea curenta: %s", str(e)[:200])
        STATE.update(error=str(e)[:300])
        on_status("Update failed, starting the current version", 100)
        return "failed"


def start_update():
    """From the app button: runs in background, then restarts the app."""
    with _lock:
        if STATE["state"] == "running":
            return {"ok": True, "state": "running"}
        STATE.update(state="running", msg="downloading the new version…", pct=10, error=None)

    def go():
        def lf(m):
            log.info("update: %s", m); STATE["msg"] = m; STATE["pct"] = min(95, STATE["pct"] + 15)
        try:
            old, new = run_update(lf)
            STATE.update(state="restarting", msg=f"updated {old} -> {new}. Restarting…", pct=100)
            log.info("UPDATE reusit %s -> %s, repornesc", old, new)
            time.sleep(1.5)
            restart()
        except Exception as e:
            log.exception("update esuat")
            STATE.update(state="failed", msg="update failed, kept the current version", error=str(e)[:300], pct=0)
    threading.Thread(target=go, daemon=True, name="update").start()
    return {"ok": True, "state": "running"}


def restart():
    """Start a fresh copy of the app (it waits for this process to exit), then exit."""
    from . import app
    from .util import kill_children
    exe = sys.executable
    env = dict(os.environ, CLIPPER_WAIT_PID=str(os.getpid()))
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([exe, "-m", "streamclip", "app"], cwd=str(ROOT), env=env, close_fds=True, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app.STOP.set()
    try:
        threading.Thread(target=app.stop_all_lives, daemon=True).start()
        time.sleep(3)
        kill_children()
    finally:
        os._exit(0)


def wait_for_parent():
    """New process after an update: wait until the old one is gone (it holds the port)."""
    pid = os.environ.pop("CLIPPER_WAIT_PID", None)
    if not pid:
        return
    t = time.time()
    while time.time() - t < 40:
        if not _alive(int(pid)):
            return
        time.sleep(0.5)


def _alive(pid):
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x100000, False, pid)   # QUERY_LIMITED | SYNCHRONIZE
        if not h:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(h, 0) == 0x102     # WAIT_TIMEOUT = still running
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main_cli():
    """update.bat"""
    print(f"Stream Clipper {local_version()} - checking GitHub releases ({repo()})...")
    lat = check(force=True)
    if STATE["error"]:
        print("[!]", STATE["error"]); return 1
    if lat and vtuple(lat) <= vtuple(local_version()) and "--force" not in sys.argv:
        print(f"You already have the latest version ({local_version()})."); return 0
    try:
        old, new = run_update(lambda m: print("  " + m))
    except Exception as e:
        print("[!] update failed, kept the current version:", e); return 1
    print(f"DONE: {old} -> {new}. Start Stream Clipper again.")
    return 0
