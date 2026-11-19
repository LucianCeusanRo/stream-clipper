"""PC detection and OS integration for the Settings page: GPU / CUDA / NVENC, start with Windows, open folder,
system tray. Everything degrades gracefully: no NVIDIA GPU -> CPU, not Windows -> the option says so."""
import os, shutil, subprocess, sys, threading
from pathlib import Path
from .util import log

WINDOW = None            # the pywebview window (set by desktop.py) - used by File -> Exit and the tray
_gpu = None
_lk = threading.Lock()
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_KEY = "StreamClipper"


def _nvidia_smi():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=8,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = (r.stdout or "").strip().splitlines()[0]
        name, mem = [x.strip() for x in line.split(",")[:2]]
        return {"name": name, "vram_gb": round(float(mem) / 1024, 1)}
    except Exception:
        return None


def _cuda_count():
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def detect(refresh=False):
    """-> {gpu, vram_gb, cuda, nvenc, cpu_threads, recommended: {...}} (cached; NVENC test encode is ~1 s)."""
    global _gpu
    with _lk:
        if _gpu is not None and not refresh:
            return _gpu
        smi = _nvidia_smi()
        cuda = _cuda_count() > 0
        try:
            from . import render
            if refresh:
                render._enc = None
            nvenc = render.encoder() == "h264_nvenc"
        except Exception:
            nvenc = False
        vram = (smi or {}).get("vram_gb") or 0
        if cuda and vram >= 6:
            rec = {"whisper_device": "cuda", "whisper_model": "large-v3", "whisper_compute_type": "float16"}
        elif cuda:
            rec = {"whisper_device": "cuda", "whisper_model": "medium", "whisper_compute_type": "int8_float16"}
        else:
            rec = {"whisper_device": "cpu", "whisper_model": "small", "whisper_compute_type": "int8"}
        rec["encoder"] = "h264_nvenc" if nvenc else "libx264"
        _gpu = {"gpu": (smi or {}).get("name") or ("NVIDIA GPU" if cuda else None), "vram_gb": vram or None,
                "cuda": cuda, "nvenc": nvenc, "cpu_threads": os.cpu_count() or 1, "recommended": rec,
                "summary": (f"{smi['name']} ({vram} GB) · CUDA {'✔' if cuda else '✘'} · NVENC {'✔' if nvenc else '✘'}"
                            if smi else ("CUDA GPU" if cuda else "No NVIDIA GPU found → CPU mode"))}
        return _gpu


# ---------- start with Windows (current user only, no admin) ----------
def _launch_cmd():
    exe = Path(sys.executable)
    root = Path(__file__).resolve().parent.parent
    launcher = root / "Stream Clipper.exe"
    if launcher.exists():
        return f'"{launcher}"'
    pyw = exe.with_name("pythonw.exe")
    return f'"{pyw if pyw.exists() else exe}" -m streamclip app'


def autostart_supported():
    return sys.platform == "win32"


def autostart_get():
    if not autostart_supported():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_KEY)
            return True
    except OSError:
        return False


def autostart_set(on):
    """-> (ok, message). Writes/removes HKCU\\...\\Run\\StreamClipper."""
    if not autostart_supported():
        return False, "start with Windows works only on Windows"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_KEY, 0, winreg.REG_SZ, _launch_cmd())
            else:
                try:
                    winreg.DeleteValue(k, APP_KEY)
                except FileNotFoundError:
                    pass
        return True, ""
    except OSError as e:
        return False, str(e)[:150]


def open_folder(path):
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(p))                      # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True
    except Exception as e:
        log.warning("nu pot deschide folderul %s: %s", p, e)
        return False


# ---------- system tray (optional: needs pystray + Pillow, installed on Windows) ----------
def tray_available():
    try:
        import pystray  # noqa
        from PIL import Image  # noqa
        return True
    except Exception:
        return False


_tray = None


def to_tray(window, on_quit):
    """Hide the window and show a tray icon (Open / Quit). Returns False if the tray is not available."""
    global _tray
    if not tray_available():
        return False
    import pystray
    from PIL import Image
    window.hide()
    if _tray:
        return True
    icon_path = Path(__file__).parent / "web" / "icon.png"

    def show(icon=None, item=None):
        global _tray
        window.show()
        if _tray:
            _tray.stop(); _tray = None

    def quit_(icon=None, item=None):
        global _tray
        if _tray:
            _tray.stop(); _tray = None
        on_quit()

    _tray = pystray.Icon("StreamClipper", Image.open(icon_path), "Stream Clipper",
                         menu=pystray.Menu(pystray.MenuItem("Open Stream Clipper", show, default=True),
                                           pystray.MenuItem("Quit", quit_)))
    threading.Thread(target=_tray.run, daemon=True, name="tray").start()
    return True


def keep_awake(on=True):
    """While the app runs, ask Windows not to sleep (ES_CONTINUOUS|ES_SYSTEM_REQUIRED). Unlike changing the power
    plan this is undone automatically when the app exits. No-op elsewhere."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        flags = 0x80000000 | (0x00000001 if on else 0)
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
    except Exception:
        return False


def notify(title, msg):
    """Desktop notification through the tray icon when it exists; the page also shows in-app notifications."""
    try:
        if _tray:
            _tray.notify(msg, title)
    except Exception:
        pass
