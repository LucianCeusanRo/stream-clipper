"""Local dashboard for Stream Clipper: a tiny JSON API + one HTML page (stdlib only, no extra web framework).
Listens on 127.0.0.1 only, so nothing is reachable from outside the PC."""
import json, mimetypes, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from . import app, db, effects, jobs, render, pipeline, texts, viral
from .util import DATA, cfg, log, save_settings

WEB = Path(__file__).parent / "web"
EDITABLE = {"channel_url": str, "streamer_name": str, "game": str, "required_hashtag": str, "credit_text": str,
            "hashtags": list, "post_interval_min_minutes": float, "post_interval_max_minutes": float,
            "daily_post_cap": int, "auto_post": bool, "min_score": float, "clips_per_chunk_max": int,
            "quiet_hours": list, "visibility": str, "layout": str, "censor_swears": bool, "caption_template": str,
            "live_title_filter": str, "manual_min_gap_minutes": float, "caption_font": str,
            "extra_hashtags": list, "hashtags_max": int, "effects": dict}


def ensure_tags(cap):
    """Captions edited in the app: required_hashtag (if set) is forced in as the FIRST hashtag."""
    return texts.finalize_caption(cap)


def clip_row(r):
    d = dict(r)
    d["name"] = Path(d["file"]).name if d.get("file") else ""
    d["dur"] = round((d["end"] or 0) - (d["start"] or 0))
    try:
        fac = json.loads(d.get("factors") or "null")
    except ValueError:
        fac = None
    if d.get("viral") is None:
        d["viral"] = viral.fallback(d.get("score"))
    d["factors_list"] = [[viral.LABELS.get(k, k), v] for k, v in (fac or {}).items()]
    d["viral_tip"] = "Șansă de viral (estimare): " + str(d["viral"]) + "%\n" + viral.tooltip(fac)
    d["can_recut"] = bool(d.get("src")) and Path(d["src"]).exists()
    return d


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(b)

    def _file(self, p: Path):
        if not p.exists():
            return self._json({"error": "nu exista"}, 404)
        size = p.stat().st_size
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):            # video seeking in the preview player
            a, _, b = rng[6:].partition("-")
            start = int(a or 0); end = int(b) if b else size - 1
            self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1)); self.end_headers()
        with open(p, "rb") as f:
            f.seek(start); left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path); qs = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._file(WEB / "index.html")
            if u.path.startswith("/static/"):
                return self._file(WEB / Path(u.path).name)
            if u.path == "/api/state":
                return self._json(app.snapshot())
            if u.path == "/api/clips":
                st = qs.get("status", ["pending"])[0]
                if st == "posted":
                    rows = db.q("SELECT * FROM clips WHERE status IN ('posted','unconfirmed') ORDER BY posted_at DESC LIMIT 200")
                elif st == "all":
                    rows = db.q("SELECT * FROM clips WHERE status!='deleted' ORDER BY created DESC, score DESC LIMIT 500")
                elif st == "queue":
                    rows = db.q("SELECT * FROM clips WHERE status IN ('queued','posting','failed') ORDER BY queued_at, created LIMIT 200")
                else:
                    rows = db.q("SELECT * FROM clips WHERE status=? ORDER BY score DESC, created DESC LIMIT 300", (st,))
                return self._json([clip_row(r) for r in rows])
            if u.path == "/api/settings":
                c = cfg()
                return self._json(dict({k: c.get(k) for k in EDITABLE}, fonts=list(render.FONTS), effects=effects.settings()))
            if u.path == "/api/jobs":
                return self._json(jobs.list_jobs())
            if u.path == "/api/log":
                p = DATA / "streamclip.log"
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-int(qs.get("n", ["200"])[0]):] if p.exists() else []
                return self._json(lines)
            if u.path.startswith("/media/"):
                _, _, cid, kind = u.path.split("/")[:4]
                r = db.q("SELECT file, thumb FROM clips WHERE id=?", (int(cid),), one=True)
                if not r:
                    return self._json({"error": "clip inexistent"}, 404)
                return self._file(Path(r["thumb"] if kind == "thumb" else r["file"]))
            if u.path == "/api/tiktok":
                from . import tiktok
                return self._json({"login": tiktok.LOGIN_STATE["state"]})
        except Exception as e:
            log.exception("web GET %s", u.path)
            return self._json({"error": str(e)}, 500)
        self._json({"error": "nu exista"}, 404)

    def do_POST(self):
        u = urlparse(self.path); b = self._body()
        try:
            if u.path == "/api/control":
                a = b.get("action")
                if a == "start": app.WATCHING.set()
                elif a == "stop": app.WATCHING.clear()
                elif a == "pause_post": app.POST_PAUSED.set()
                elif a == "resume_post": app.POST_PAUSED.clear()
                elif a == "auto_on": save_settings({"auto_post": True})
                elif a == "auto_off": save_settings({"auto_post": False})
                elif a == "clear_errors": app.ERRORS.clear()
                else: return self._json({"error": "actiune necunoscuta"}, 400)
                return self._json({"ok": True})
            if u.path == "/api/clip":
                cid, a = int(b.get("id")), b.get("action")
                r = db.q("SELECT * FROM clips WHERE id=?", (cid,), one=True)
                if not r:
                    return self._json({"error": "clip inexistent"}, 404)
                if a == "post":
                    if r["status"] in ("posted",):
                        return self._json({"error": "clipul e deja postat"}, 400)
                    if r["status"] in ("posting", "deleted"):
                        return self._json({"error": "clipul se posteaza acum" if r["status"] == "posting" else "clipul e sters"}, 400)
                    cap = b.get("caption")
                    if cap is not None:                          # required_hashtag can never be removed
                        db.x("UPDATE clips SET caption=? WHERE id=?", (ensure_tags(cap), cid))
                    db.x("UPDATE clips SET status='queued', queued_at=?, attempts=0, error=NULL WHERE id=?", (time.time(), cid))
                elif a == "caption":
                    db.x("UPDATE clips SET caption=? WHERE id=?", (ensure_tags(b.get("caption") or ""), cid))
                elif a == "skip":
                    db.x("UPDATE clips SET status='skipped' WHERE id=?", (cid,))
                elif a == "restore":
                    db.x("UPDATE clips SET status='pending' WHERE id=? AND status IN ('skipped','failed','queued')", (cid,))
                elif a == "delete":
                    for f in (r["file"], r["thumb"]):
                        if f:
                            for ext in (".mp4", ".jpg", ".json", ".ass"):
                                Path(f).with_suffix(ext).unlink(missing_ok=True)
                    if r["src"]:
                        Path(r["src"]).unlink(missing_ok=True)
                    db.x("UPDATE clips SET status='deleted' WHERE id=?", (cid,))   # row kept -> never re-clipped
                elif a == "retext":
                    try:
                        return self._json(dict(pipeline.retext(cid), ok=True))
                    except pipeline.ClipError as e:
                        return self._json({"error": str(e)}, 400)
                elif a == "recut":
                    try:
                        res = pipeline.recut(cid, float(b.get("dstart") or 0), float(b.get("dend") or 0), bool(b.get("snap", True)))
                        return self._json(dict(res, ok=True))
                    except pipeline.ClipError as e:
                        return self._json({"error": str(e)}, 400)
                    except Exception as e:
                        log.exception("re-taiere esuata")
                        return self._json({"error": "re-tăierea a eșuat: " + str(e)[:200]}, 500)
                else:
                    return self._json({"error": "actiune necunoscuta"}, 400)
                return self._json({"ok": True})
            if u.path == "/api/settings":
                ch = {}
                for k, v in b.items():
                    if k not in EDITABLE:
                        continue
                    t = EDITABLE[k]
                    if t is list:
                        v = v if isinstance(v, list) else [x for x in str(v).replace(",", " ").split() if x]
                        if k == "quiet_hours":
                            v = [int(x) for x in v if str(x).isdigit() and 0 <= int(x) <= 23]
                    elif t is bool:
                        v = bool(v)
                    elif t is dict:              # effects: only known keys, right types
                        cur = effects.settings()
                        v = {kk: (bool(vv) if isinstance(effects.DEFAULTS[kk], bool) else
                                  max(0.0, min(12.0 if kk == "boost_db" else 1.0, float(vv))))
                             for kk, vv in (v or {}).items() if kk in effects.DEFAULTS}
                        v = dict(cur, **v)
                    else:
                        v = t(v)
                    ch[k] = v
                if "hashtags_max" in ch and not 1 <= ch["hashtags_max"] <= 10:
                    return self._json({"error": "numarul de hashtag-uri trebuie sa fie intre 1 si 10"}, 400)
                if "caption_font" in ch and ch["caption_font"] not in render.FONTS:
                    return self._json({"error": "font necunoscut"}, 400)
                if "post_interval_min_minutes" in ch and ch["post_interval_min_minutes"] < 1:
                    return self._json({"error": "intervalul minim trebuie sa fie cel putin 1 minut"}, 400)
                c = save_settings(ch)
                return self._json({"ok": True, "hashtags": c["hashtags"]})
            if u.path == "/api/job":
                try:
                    return self._json(dict(jobs.submit(b.get("source"), b.get("start"), b.get("end"), b.get("clips") or 5), ok=True))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            if u.path == "/api/url":
                url = (b.get("url") or "").strip()
                if not url.startswith("http"):
                    return self._json({"error": "link invalid"}, 400)
                app.add_url(url)
                return self._json({"ok": True})
            if u.path == "/api/tiktok_login":
                from . import tiktok
                threading.Thread(target=tiktok.login, daemon=True, name="login").start()
                return self._json({"ok": True})
        except Exception as e:
            log.exception("web POST %s", u.path)
            return self._json({"error": str(e)}, 500)
        self._json({"error": "nu exista"}, 404)


def serve(port=None):
    port = port or cfg().get("dashboard_port", 8777)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="web").start()
    log.info("aplicatia ruleaza la http://127.0.0.1:%d", port)
    return srv
