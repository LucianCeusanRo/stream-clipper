"""Local dashboard for Stream Clipper: a tiny JSON API + one HTML page (stdlib only, no extra web framework).
Listens on 127.0.0.1 only, so nothing is reachable from outside the PC."""
import hmac, json, mimetypes, re, secrets, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from . import accounts, app, db, effects, game, i18n, jobs, progress, styles, render, pipeline, texts, updater, viral
from .util import DATA, cfg, log, reset_settings, save_settings

WEB = Path(__file__).parent / "web"
EDITABLE = {"youtube_client_secret": str, "language": str, "ui_language": str, "extra_keywords": list, "channel_url": str, "streamer_name": str,
            "game": str, "required_hashtag": str, "credit_text": str, "check_updates": bool, "auto_update": bool,
            "hashtags": list, "post_interval_min_minutes": float, "post_interval_max_minutes": float,
            "daily_post_cap": int, "auto_post": bool, "min_score": float, "clips_per_chunk_max": int,
            "quiet_hours": list, "visibility": str, "layout": str, "censor_swears": bool, "caption_template": str,
            "live_title_filter": str, "manual_min_gap_minutes": float, "caption_font": str,
            "extra_hashtags": list, "hashtags_max": int, "effects": dict,
            "auto_post_min_viral": int, "post_order": str, "dedupe_similarity": float,
            "post_jitter_minutes": float, "post_preset": str, "delete_after_post": bool, "delete_after_post_days": float,
            "keep_raw_chunks_hours": float, "skipped_retention_days": float, "disk_budget_gb": float,
            # General settings (1.2.1): performance, general, onboarding
            "whisper_device": str, "whisper_model": str, "whisper_compute_type": str, "max_parallel_renders": int,
            "encoder": str, "theme": str, "start_with_windows": bool, "minimize_to_tray": bool, "notifications": bool,
            "onboarded": bool, "rotate": bool, "rotate_accounts": list, "channel_check_every_sec": int}
from . import schema
CHOICES = {"whisper_device": ("auto", "cuda", "cpu"),
           "whisper_model": ("auto", "large-v3", "large-v3-turbo", "medium", "small", "base", "tiny"),
           "whisper_compute_type": ("auto", "float16", "int8_float16", "int8", "float32"),
           "encoder": ("auto", "h264_nvenc", "libx264"), "theme": ("dark", "light"), "visibility": ("public", "private"),
           "layout": ("split", "blur", "fill")}
SECTIONS = {
    "general": ["ui_language", "theme", "start_with_windows", "minimize_to_tray", "notifications"],
    "performance": ["whisper_device", "whisper_model", "whisper_compute_type", "max_parallel_renders", "encoder"],
    "storage": ["delete_after_post", "delete_after_post_days", "keep_raw_chunks_hours", "skipped_retention_days", "disk_budget_gb"],
    "updates": ["auto_update", "check_updates"],
    "clipping": ["language", "channel_url", "streamer_name", "game", "credit_text", "extra_keywords", "min_score",
                 "clips_per_chunk_max", "layout", "caption_font", "censor_swears", "live_title_filter", "effects"],
    "posting": ["required_hashtag", "hashtags", "extra_hashtags", "hashtags_max", "caption_template", "auto_post",
                "auto_post_min_viral", "post_order", "post_interval_min_minutes", "post_interval_max_minutes",
                "post_jitter_minutes", "manual_min_gap_minutes", "daily_post_cap", "quiet_hours", "visibility",
                "post_preset", "dedupe_similarity", "rotate", "rotate_accounts"],
}
PRESETS = {"sigur": {"daily_post_cap": 20, "post_interval_min_minutes": 40, "post_interval_max_minutes": 60},
           "normal": {"daily_post_cap": 45, "post_interval_min_minutes": 20, "post_interval_max_minutes": 30},
           "agresiv": {"daily_post_cap": 60, "post_interval_min_minutes": 15, "post_interval_max_minutes": 20}}
SORTS = {"viral": lambda d: (-d["viral"], -(d.get("created") or 0)), "new": lambda d: -(d.get("created") or 0),
         "old": lambda d: d.get("created") or 0, "dur": lambda d: (-d["dur"], -d["viral"])}


def sort_rows(rows, sort="viral", min_viral=0, style=None):
    """Gallery order/filter (all tabs). viral = highest viral % first (default)."""
    rows = [r for r in rows if r["viral"] >= min_viral and (not style or r.get("style") == style)]
    if sort == "plan":
        return rows
    return sorted(rows, key=SORTS.get(sort, SORTS["viral"]))


def ensure_tags(cap):
    """Captions edited in the app: required_hashtag (if set) is forced in as the FIRST hashtag."""
    return texts.finalize_caption(cap)


def _acc_cache():
    try:
        return {a["id"]: a for a in accounts.all_accounts()}
    except Exception:
        return {}


def accounts_payload():
    from . import youtube_upload
    stats = db.account_stats(app.midnight())
    out = []
    for a in accounts.all_accounts():
        d = accounts.public(a)
        d["today"] = stats.get(a["id"], {}).get("today", 0)
        d["queued"] = db.q("SELECT COUNT(*) n FROM clips WHERE status='queued' AND account=?", (a["id"],), one=True)["n"]
        out.append(d)
    return {"accounts": out, "youtube_configured": bool(youtube_upload.client()), "defaults": accounts.DEFAULTS}


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
    if i18n.english():
        d["factors_list"] = [[i18n.LABELS_EN.get(k, k), v] for k, v in (fac or {}).items()]
        d["viral_tip"] = ("Viral chance (estimate): " + str(d["viral"]) + "%\n"
                          + "\n".join(f"{i18n.LABELS_EN.get(k, k)}: {v}%" for k, v in (fac or {}).items()))
        d["why"] = i18n.en(d.get("why"))
    else:
        d["factors_list"] = [[viral.LABELS.get(k, k), v] for k, v in (fac or {}).items()]
        d["viral_tip"] = "Șansă de viral (estimare): " + str(d["viral"]) + "%\n" + viral.tooltip(fac)
    d["can_recut"] = bool(d.get("src")) and Path(d["src"]).exists()
    acc = _acc_cache().get(d.get("account") or "")
    d["account_name"] = acc["name"] if acc else ""
    d["account_platform"] = acc["platform"] if acc else ""
    d["style"] = d.get("style") or "moment"
    d["style_label"] = styles.label(d["style"]) if d["style"] in styles.LABEL else ("🏆 Top 5" if d["style"] == "top5" else d["style"])
    return d


TOKEN = secrets.token_urlsafe(24)      # per-session; the page gets it, other websites can't (CSRF protection)
MAX_BODY = 1 << 20


def inside(p: Path, base: Path):
    try:
        Path(p).resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False


class H(BaseHTTPRequestHandler):
    def _host_ok(self):
        """Only http://127.0.0.1:<port> / localhost (blocks DNS-rebinding pages from reading the API)."""
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost")

    def _csrf_ok(self):
        tok = self.headers.get("X-Clipper-Token") or ""
        if not hmac.compare_digest(tok, TOKEN):
            return False
        origin = self.headers.get("Origin")
        port = self.server.server_address[1]
        return origin in (None, "null", f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        if isinstance(obj, dict) and isinstance(obj.get("error"), str) and i18n.english():
            obj = dict(obj, error=i18n.en(obj["error"]))
        b = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(b)

    def _file(self, p: Path, html_token=False):
        if not p.exists() or not p.is_file():
            return self._json({"error": "nu exista"}, 404)
        if html_token:                                   # dashboard page: hand it the session token
            b = p.read_bytes().replace(b"__CLIPPER_TOKEN__", TOKEN.encode())
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY"); self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers(); self.wfile.write(b); return
        size = p.stat().st_size
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):            # video seeking in the preview player
            a, _, b = rng[6:].split(",")[0].partition("-")
            try:
                start = int(a or 0); end = min(size - 1, int(b)) if b else size - 1
            except ValueError:
                start, end = 0, size - 1
            if start > end or start >= size:
                self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
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
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path); qs = parse_qs(u.query)
        if not self._host_ok():
            return self._json({"error": "host nepermis"}, 403)
        try:
            if u.path in ("/", "/index.html"):
                ui = str(cfg().get("ui_language") or "en").lower()
                return self._file(WEB / ("index.ro.html" if ui == "ro" else "index.html"), html_token=True)
            if u.path.startswith("/static/"):
                f = WEB / Path(u.path).name                      # basename only -> no ../ traversal
                return self._file(f) if inside(f, WEB) else self._json({"error": "nu exista"}, 404)
            if u.path == "/api/state":
                return self._json(i18n.deep_en(app.snapshot()))
            if u.path == "/api/styles":
                return self._json({"categories": styles.stats(), "top5": db.q("SELECT COUNT(*) n FROM clips WHERE style='top5' AND status!='deleted'", one=True)["n"],
                                   "edit": [{"key": k, "label": styles.edit_label(k, l), "enabled": styles.enabled_edit_styles()[k]} for k, l, _ in styles.EDIT_STYLES]})
            if u.path == "/api/progress":
                return self._json(i18n.deep_en(app.progress_snapshot()))
            if u.path == "/api/version":
                return self._json(updater.status(check=qs.get("check", ["0"])[0] == "1"))
            if u.path == "/api/clips":
                st = qs.get("status", ["pending"])[0]
                sort = qs.get("sort", ["viral"])[0]
                sty = qs.get("style", [""])[0] or None
                try:
                    mv = max(0, min(100, int(float(qs.get("min_viral", ["0"])[0]))))
                except ValueError:
                    mv = 0
                if st == "queue":       # exact posting order (what the poster will do), + failed/posting ones
                    c = cfg()
                    plan, below = db.post_plan(c.get("post_order", "viral_first"), bool(c.get("auto_post")),
                                               int(c.get("auto_post_min_viral", 40)), limit=300)
                    out = []
                    for r in plan:
                        d = clip_row(r); d["pos"] = r["pos"]; d["plan"] = r["plan"]; out.append(d)
                    for r in db.q("SELECT * FROM clips WHERE status IN ('posting','failed') ORDER BY queued_at"):
                        d = clip_row(r); d["pos"] = None; d["plan"] = r["status"]; out.append(d)
                    out = sort_rows(out, sort, mv, sty)
                    return self._json(out)
                if st == "posted":
                    rows = db.q("SELECT * FROM clips WHERE status IN ('posted','unconfirmed','exported') ORDER BY posted_at DESC LIMIT 200")
                elif st == "all":
                    rows = db.q("SELECT * FROM clips WHERE status!='deleted' ORDER BY created DESC, score DESC LIMIT 500")
                else:
                    rows = db.q("SELECT * FROM clips WHERE status=? ORDER BY score DESC, created DESC LIMIT 300", (st,))
                return self._json(sort_rows([clip_row(r) for r in rows], sort, mv, sty))
            if u.path == "/api/settings":
                c = cfg()
                import shutil as _sh
                try:
                    du = _sh.disk_usage(DATA)
                    disk = {"free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1),
                            "used_gb": round(pipeline.data_used() / 1e9, 2)}
                except OSError:
                    disk = {}
                from .util import ROOT as _R
                me = (_R / "data_move_error.txt")
                return self._json(dict({k: c.get(k) for k in EDITABLE}, fonts=list(render.FONTS), effects=effects.settings(),
                                       data_dir=str(DATA), data_dir_real=str(DATA.resolve()), disk=disk, presets=PRESETS,
                                       move_error=me.read_text(encoding="utf-8") if me.exists() else None))
            if u.path == "/api/jobs":
                return self._json(i18n.deep_en(jobs.list_jobs(), keys=("stage", "error", "detail")))
            if u.path == "/api/log":
                p = DATA / "streamclip.log"
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-int(qs.get("n", ["200"])[0]):] if p.exists() else []
                return self._json(lines)
            if u.path.startswith("/media/"):
                _, _, cid, kind = u.path.split("/")[:4]
                if not cid.isdigit():
                    return self._json({"error": "id invalid"}, 400)
                r = db.q("SELECT file, thumb FROM clips WHERE id=?", (int(cid),), one=True)
                if not r:
                    return self._json({"error": "clip inexistent"}, 404)
                f = Path((r["thumb"] if kind == "thumb" else r["file"]) or "")
                if not str(f) or not (inside(f, DATA) or inside(f, util_ROOT())):
                    return self._json({"error": "fisier in afara folderului de date"}, 403)
                return self._file(f)
            if u.path == "/api/tiktok":
                from . import tiktok
                return self._json({"login": tiktok.LOGIN_STATE["state"]})
            if u.path == "/api/accounts":
                return self._json(accounts_payload())
            if u.path == "/api/schedule":
                return self._json(app.plan_schedule(int(qs.get("n", ["12"])[0] or 12)))
            if u.path == "/api/channels":
                from . import channels
                return self._json({"channels": channels.listing(), "every": int(cfg().get("channel_check_every_sec", 90)),
                                   "watching": app.WATCHING.is_set()})
            if u.path == "/api/system":
                from . import sysinfo
                d = dict(sysinfo.detect(refresh=qs.get("refresh", ["0"])[0] == "1"))
                d.update(autostart_supported=sysinfo.autostart_supported(), autostart=sysinfo.autostart_get(),
                         tray_available=sysinfo.tray_available(), sections=SECTIONS)
                return self._json(d)
            if u.path == "/oauth/youtube":                     # Google sends the browser back here after consent
                from . import youtube_upload
                ok, msg = True, "YouTube connected. You can close this tab and go back to Stream Clipper."
                try:
                    youtube_upload.finish_auth(qs.get("state", [""])[0], qs.get("code", [""])[0])
                except Exception as e:
                    ok, msg = False, "Could not connect YouTube: " + i18n.en(str(e))
                b = (f"<!doctype html><meta charset=utf-8><title>Stream Clipper</title><body style='font:16px system-ui;"
                     f"background:#0d1117;color:#e6edf3;display:grid;place-items:center;height:90vh'><p>{'✅' if ok else '⚠️'} "
                     f"{msg.replace('<', '&lt;')}</p>").encode()
                self.send_response(200 if ok else 400); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        except Exception as e:
            log.exception("web GET %s", u.path)
            return self._json({"error": str(e)}, 500)
        self._json({"error": "nu exista"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if not self._host_ok() or not self._csrf_ok():
            return self._json({"error": "cerere respinsa (token lipsa/gresit) - reincarca pagina"}, 403)
        b = self._body()
        try:
            if u.path == "/api/control":
                a = b.get("action")
                if a == "start": app.WATCHING.set()
                elif a == "stop": app.WATCHING.clear()
                elif a == "pause_post": app.POST_PAUSED.set()
                elif a == "resume_post": app.POST_PAUSED.clear()
                elif a in ("auto_on", "auto_off"):
                    save_settings({"auto_post": a == "auto_on"})
                    app.note_auto(a == "auto_on", "butonul din aplicație")
                elif a == "clear_errors": app.ERRORS.clear()
                elif a == "clear_backoff":
                    app.clear_backoff(); log.info("pauza automata de postare anulata din aplicatie")
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
                    if cap is not None:                          # required_hashtag (if set) can never be removed
                        db.x("UPDATE clips SET caption=? WHERE id=?", (ensure_tags(cap), cid))
                    targets = [t for t in (b.get("accounts") or []) if accounts.get(t)]
                    db.x("UPDATE clips SET status='queued', queued_at=?, attempts=0, error=NULL, account=? WHERE id=?",
                         (time.time(), targets[0] if targets else (r["account"] if r["status"] != "posted" else None), cid))
                    for t in targets[1:]:                        # same clip to more accounts -> one queued copy each
                        db.clone_clip(cid, t)
                elif a == "set_account":
                    acc = b.get("account") or None
                    if acc and not accounts.get(acc):
                        return self._json({"error": "cont inexistent"}, 400)
                    db.x("UPDATE clips SET account=? WHERE id=?", (acc, cid))
                elif a == "clone":
                    if not accounts.get(b.get("account") or ""):
                        return self._json({"error": "cont inexistent"}, 400)
                    return self._json({"ok": True, "id": db.clone_clip(cid, b["account"])})
                elif a == "caption":
                    db.x("UPDATE clips SET caption=? WHERE id=?", (ensure_tags(b.get("caption") or ""), cid))
                elif a == "skip":
                    db.x("UPDATE clips SET status='skipped' WHERE id=?", (cid,))
                    progress.count("skipped")
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
                    progress.count("deleted")
                elif a == "set_game":
                    # your game for this clip (empty = detect automatically); title/description/hashtags follow it
                    g = game.normalize(str(b.get("game") or "")[:80].strip())
                    db.x("UPDATE clips SET game=? WHERE id=?", (g or None, cid))
                    if r["status"] in ("posted", "posting"):
                        return self._json({"ok": True, "game": g})
                    try:
                        return self._json(dict(pipeline.retext(cid), ok=True, game=g))
                    except pipeline.ClipError as e:
                        return self._json({"error": str(e)}, 400)
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
                        try:
                            v = schema.check(k, v if k in schema.NUM else t(v))
                        except (TypeError, ValueError) as e:
                            return self._json({"error": str(e) if str(e).startswith(k) else f"{k}: invalid value"}, 400)
                    ch[k] = v
                for k, opts in CHOICES.items():
                    if k in ch and ch[k] not in opts:
                        return self._json({"error": f"{k}: {' / '.join(opts)}"}, 400)
                if "max_parallel_renders" in ch:
                    ch["max_parallel_renders"] = max(1, min(4, ch["max_parallel_renders"]))
                if "start_with_windows" in ch:
                    from . import sysinfo
                    if ch["start_with_windows"] != sysinfo.autostart_get():
                        ok, msg = sysinfo.autostart_set(ch["start_with_windows"])
                        if not ok:
                            ch.pop("start_with_windows")
                            if b.get("start_with_windows"):
                                return self._json({"error": msg}, 400)
                old = cfg()
                if any(k in ch and ch[k] != old.get(k) for k in ("whisper_device", "whisper_model", "whisper_compute_type")):
                    from . import transcribe
                    transcribe._model = None                     # loads with the new settings on the next chunk
                if "encoder" in ch and ch["encoder"] != old.get("encoder"):
                    render._enc = None
                if "ui_language" in ch and ch["ui_language"] not in ("en", "ro"):
                    return self._json({"error": "ui_language: en / ro"}, 400)
                if "language" in ch:
                    ch["language"] = ch["language"].strip().lower() or "auto"
                    if not re.fullmatch(r"auto|[a-z]{2,3}", ch["language"]):
                        return self._json({"error": "language: auto or a code like en, ro, es"}, 400)
                if "channel_url" in ch and ch["channel_url"].strip():
                    from .util import check_url
                    try:
                        ch["channel_url"] = check_url(ch["channel_url"], youtube_only=True)
                    except ValueError as e:
                        return self._json({"error": str(e)}, 400)
                if "hashtags_max" in ch and not 1 <= ch["hashtags_max"] <= 10:
                    return self._json({"error": "numarul de hashtag-uri trebuie sa fie intre 1 si 10"}, 400)
                if "auto_post_min_viral" in ch and not 0 <= ch["auto_post_min_viral"] <= 100:
                    return self._json({"error": "pragul viral trebuie sa fie intre 0 si 100"}, 400)
                if "post_order" in ch and ch["post_order"] not in ("viral_first", "newest_first"):
                    return self._json({"error": "ordine necunoscuta"}, 400)
                if "dedupe_similarity" in ch and not 0.5 <= ch["dedupe_similarity"] <= 1.0:
                    return self._json({"error": "similaritatea trebuie sa fie intre 0.5 si 1.0"}, 400)
                if "auto_post" in ch:
                    app.note_auto(ch["auto_post"], "Setări")
                if ch.get("post_preset"):
                    if ch["post_preset"] not in PRESETS and ch["post_preset"] != "personalizat":
                        return self._json({"error": "ritm necunoscut"}, 400)
                    for k, v in PRESETS.get(ch["post_preset"], {}).items():
                        ch.setdefault(k, v)
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
                from .util import check_url
                try:
                    url = check_url(b.get("url"), youtube_only=True)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                app.add_url(url)
                return self._json({"ok": True})
            if u.path == "/api/pick_folder":
                try:
                    import webview
                    wins = webview.windows
                    if not wins:
                        raise RuntimeError("fereastra nu e deschisă")
                    r = wins[0].create_file_dialog(webview.FOLDER_DIALOG, directory=str(DATA.parent))
                    return self._json({"path": (r[0] if isinstance(r, (list, tuple)) and r else r) or None})
                except Exception as e:
                    return self._json({"path": None, "error_hint": f"scrie calea de mână ({str(e)[:80]})"})
            if u.path == "/api/data_folder":
                from .util import request_data_move
                try:
                    res = request_data_move(b.get("path") or "", bool(b.get("move", True)))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                log.info("folder de date nou: %s (mutare: %s) -> repornesc aplicatia", res["path"], res["move"])
                app.WATCHING.clear(); app.POST_PAUSED.set()          # pause pipeline + posting right away
                threading.Thread(target=lambda: (time.sleep(1.5), updater.restart()), daemon=True).start()
                return self._json(dict(res, ok=True, restarting=True))
            if u.path == "/api/styles":
                ch = {}
                valid_c = {k for k, *_ in styles.CATEGORIES}; valid_e = {k for k, *_ in styles.EDIT_STYLES}
                if isinstance(b.get("styles"), dict):
                    cur = dict(cfg().get("styles") or {})
                    cur.update({k: bool(v) for k, v in b["styles"].items() if k in valid_c}); ch["styles"] = cur
                if isinstance(b.get("edit_styles"), dict):
                    cur = dict(cfg().get("edit_styles") or {})
                    cur.update({k: bool(v) for k, v in b["edit_styles"].items() if k in valid_e}); ch["edit_styles"] = cur
                if "split" in (b.get("edit_styles") or {}):
                    ch["layout"] = "split" if b["edit_styles"]["split"] else "blur"
                save_settings(ch)
                return self._json({"ok": True})
            if u.path == "/api/compile":
                n = max(2, min(10, int(b.get("n") or 5))); hours = max(1, min(168, float(b.get("hours") or 24)))
                def go():
                    try:
                        cid = pipeline.compile_top(n, hours, b.get("style") or None)
                        progress.event(f"compilație TOP {n} gata (clip #{cid})")
                    except Exception as e:
                        app.error(f"compilația a eșuat: {str(e)[:150]}")
                threading.Thread(target=go, daemon=True, name="compile").start()
                return self._json({"ok": True})
            if u.path == "/api/update":
                return self._json(updater.start_update())
            if u.path == "/api/settings/reset":
                sec = b.get("section") or ""
                keys = sum(SECTIONS.values(), []) if sec == "all" else SECTIONS.get(sec)
                if keys is None:
                    return self._json({"error": "actiune necunoscuta"}, 400)
                if "start_with_windows" in keys:
                    from . import sysinfo
                    sysinfo.autostart_set(False)
                if "auto_post" in keys and cfg().get("auto_post"):
                    app.note_auto(False, "Resetare setări")
                reset_settings(keys + (["onboarded"] if sec == "all" else []))
                render._enc = None
                from . import transcribe
                transcribe._model = None
                done = {"section": sec}
                if sec == "all" and b.get("delete_clips"):       # only when ticked in the confirmation dialog
                    n = 0
                    for r in db.q("SELECT * FROM clips WHERE status NOT IN ('deleted','posting')"):
                        for f in (r["file"], r["thumb"], r["src"]):
                            if f and inside(Path(f), DATA):
                                for ext in (".mp4", ".jpg", ".json", ".ass"):
                                    Path(f).with_suffix(ext).unlink(missing_ok=True)
                        n += 1
                    db.x("UPDATE clips SET status='deleted' WHERE status NOT IN ('deleted','posting')")
                    done["clips_deleted"] = n
                if sec == "all" and b.get("delete_accounts"):
                    import shutil as _sh
                    for a in accounts.all_accounts():
                        for d in (accounts.profile_dir(a), accounts.token_file(a).parent):
                            if d.exists() and inside(d, DATA) and d.resolve() != DATA.resolve():
                                _sh.rmtree(d, ignore_errors=True)
                    accounts.FILE.unlink(missing_ok=True)
                    Path(str(accounts.FILE) + ".bak").unlink(missing_ok=True)
                    done["accounts_deleted"] = True
                log.info("setari resetate: %s", done)
                return self._json(dict(done, ok=True))
            if u.path == "/api/open_folder":
                from . import sysinfo
                _clips = pipeline.CLIPS
                which = b.get("which") or "clips"
                path = {"clips": _clips, "data": DATA, "exports": DATA / "exports"}.get(which)
                if not path:
                    return self._json({"error": "actiune necunoscuta"}, 400)
                return self._json({"ok": sysinfo.open_folder(path), "path": str(path)})
            if u.path == "/api/exit":
                from . import sysinfo
                def bye():
                    time.sleep(0.3)
                    q = getattr(sysinfo, "QUIT", None)
                    if q:
                        q()
                    else:
                        app.STOP.set(); import os as _os; _os._exit(0)
                threading.Thread(target=bye, daemon=True).start()
                return self._json({"ok": True})
            if u.path == "/api/channels":
                from . import channels, platforms
                a = b.get("action")
                try:
                    if a == "add":
                        return self._json({"ok": True, "channel": channels.add(b.get("channel") or "")})
                    if a == "remove":
                        channels.remove(str(b.get("key") or "")); return self._json({"ok": True})
                    if a == "enable":
                        channels.set_enabled(str(b.get("key") or ""), bool(b.get("on"))); return self._json({"ok": True})
                except (ValueError, platforms.PlatformError) as e:
                    return self._json({"error": str(e)}, 400)
                return self._json({"error": "actiune necunoscuta"}, 400)
            if u.path == "/api/tiktok_login":
                from . import tiktok
                acc = accounts.get(b.get("account") or "") if b.get("account") else None
                threading.Thread(target=tiktok.login, kwargs={"acc": acc}, daemon=True, name="login").start()
                return self._json({"ok": True})
            if u.path == "/api/accounts":
                a = b.get("action")
                if a == "save":
                    return self._json({"ok": True, "account": accounts.upsert(b.get("account") or {})})
                if a == "remove":
                    acc = accounts.get(b.get("id") or "")
                    if not acc:
                        return self._json({"error": "cont inexistent"}, 404)
                    accounts.remove(acc["id"])
                    if b.get("delete_login"):                    # only when you tick it in the confirmation
                        import shutil as _sh
                        for d in (accounts.profile_dir(acc), accounts.token_file(acc).parent):
                            if d.exists() and inside(d, DATA) and d != DATA:
                                (_sh.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True))
                    db.x("UPDATE clips SET account=NULL WHERE account=? AND status IN ('pending','queued','failed')", (acc["id"],))
                    return self._json({"ok": True})
                if a == "youtube_connect":
                    from . import youtube_upload
                    acc = accounts.get(b.get("id") or "")
                    if not acc or acc["platform"] != "youtube":
                        return self._json({"error": "cont YouTube inexistent"}, 404)
                    url = youtube_upload.auth_url(acc["id"], self.server.server_address[1])
                    import webbrowser
                    webbrowser.open(url)
                    return self._json({"ok": True, "url": url})
                if a == "youtube_disconnect":
                    acc = accounts.get(b.get("id") or "")
                    if acc:
                        accounts.clear_token(acc)
                    return self._json({"ok": True})
                return self._json({"error": "actiune necunoscuta"}, 400)
        except Exception as e:
            log.exception("web POST %s", u.path)
            return self._json({"error": str(e)}, 500)
        self._json({"error": "nu exista"}, 404)


def util_ROOT():
    from .util import ROOT
    return ROOT


def serve(port=None):
    port = port or cfg().get("dashboard_port", 8777)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="web").start()
    log.info("aplicatia ruleaza la http://127.0.0.1:%d", port)
    return srv
