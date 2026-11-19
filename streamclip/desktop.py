"""Stream Clipper desktop app: starts the engine + local dashboard and shows it in its own window
(pywebview / Edge WebView2 on Windows). Falls back to the default browser if pywebview is missing."""
import socket, sys, threading, time, urllib.request, webbrowser
from .util import cfg, log, setup_logging

TITLE = "Stream Clipper"


def _running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def engine(post=True):
    from . import app, sysinfo
    if cfg().get("keep_awake", True):     # 24/7 clipping: no sleep while the engine thread lives (reverts on exit)
        sysinfo.keep_awake(True)
    while not app.STOP.is_set():
        try:
            app.run_forever(post=post)
        except Exception as e:      # never die: log, show in the app, restart the watcher
            log.exception("eroare neasteptata: %s", e)
            app.error(f"eroare neasteptata, repornesc in 60s: {str(e)[:150]}")
            app.sleep_until(app.STOP, 60)


SPLASH = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#0d0f14;color:#e9edf3;font:14px "Segoe UI",system-ui,sans-serif;overflow:hidden}
.w{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px}
img{width:96px;height:96px;border-radius:22px;box-shadow:0 12px 40px rgba(255,45,85,.35)}
h1{margin:0;font-size:26px;letter-spacing:.3px}h1 b{color:#ff2d55}
.bar{width:320px;height:8px;background:#252b36;border-radius:6px;overflow:hidden}
.bar i{display:block;height:100%;width:3%;background:linear-gradient(90deg,#25f4ee,#ff2d55);transition:width .4s}
#m{color:#8b95a7;min-height:20px}small{color:#5d6678}
</style></head><body><div class="w"><img src="data:image/png;base64,__ICON__" alt="">
<h1>Stream <b>Clipper</b></h1><div class="bar"><i id="b"></i></div><div id="m">Starting…</div><small>v__VER__</small></div>
<script>function set(m,p){document.getElementById('m').textContent=m;if(p!=null)document.getElementById('b').style.width=Math.max(3,p)+'%'}</script>
</body></html>"""


def splash_html():
    import base64
    from pathlib import Path
    from . import updater
    try:
        icon = base64.b64encode((Path(__file__).parent / "web" / "icon.png").read_bytes()).decode()
    except OSError:
        icon = ""
    return SPLASH.replace("__ICON__", icon).replace("__VER__", updater.local_version())


def _start_engine(port):
    from . import web, updater
    web.serve(port)

    if cfg().get("check_updates", True):
        updater.check_async()
    threading.Thread(target=engine, daemon=True, name="engine").start()


def main(no_window=False):
    setup_logging()
    from .util import _install_signal_handlers
    _install_signal_handlers()
    from . import updater
    from .util import migrate_settings
    updater.wait_for_parent()        # restarted after an update: let the old process free the port
    migrate_settings()
    port = cfg().get("dashboard_port", 8777)
    url = f"http://127.0.0.1:{port}/"
    if _running(port):                      # already open -> just show it again (single instance)
        log.info("Stream Clipper ruleaza deja, deschid fereastra.")
        return _window(url, owner=False)
    from . import app
    try:
        import webview
    except ImportError:
        webview = None
    try:
        if no_window or webview is None:
            if updater.startup_update(lambda m, p: print(f"[update] {m}")) == "updated":
                return updater.restart()
            _start_engine(port)
            if no_window:
                while True:
                    time.sleep(3600)
            return _window(url, owner=True)
        from . import sysinfo
        tray = bool(cfg().get("minimize_to_tray", False)) and sysinfo.tray_available()
        w = webview.create_window(TITLE, html=splash_html(), width=1440, height=920, min_size=(900, 600),
                                  confirm_close=not tray, text_select=True, background_color="#0d0f14")
        sysinfo.WINDOW = w
        quitting = {"v": False}

        def really_quit():
            quitting["v"] = True
            w.destroy()

        def on_closing():
            # "Minimize to tray": the X hides the window, the engine keeps clipping; Quit from the tray menu
            if tray and not quitting["v"] and cfg().get("minimize_to_tray", False):
                if sysinfo.to_tray(w, really_quit):
                    return False
            return True
        sysinfo.QUIT = really_quit
        try:
            w.events.closing += on_closing
        except Exception:
            pass

        def boot():
            import json as _j

            def show(msg, pct):
                try:
                    w.evaluate_js(f"set({_j.dumps(msg)},{int(pct)})")
                except Exception:
                    pass
            time.sleep(0.3)
            if updater.startup_update(show) == "updated":
                time.sleep(0.8)
                return updater.restart()
            show("Starting the engine…", 100)
            _start_engine(port)
            for _ in range(50):                     # wait until the dashboard answers
                if _running(port):
                    break
                time.sleep(0.1)
            w.load_url(url)
        webview.start(boot, private_mode=False)
    except KeyboardInterrupt:
        pass
    finally:
        app.STOP.set()
        app.stop_all_lives()
        log.info("Stream Clipper oprit.")


def _window(url, owner):
    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        if owner:
            print(f"Stream Clipper is open in your browser: {url}\nKeep this window open. Ctrl+C = stop.")
            while True:
                time.sleep(3600)
        return
    webview.create_window(TITLE, url, width=1440, height=920, min_size=(900, 600),
                          confirm_close=owner, text_select=True, background_color="#0d0f14")
    webview.start(private_mode=False)
