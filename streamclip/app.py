"""24/7 orchestrator (runs inside the Stream Clipper app, or headless with `python -m streamclip run`).

threads:
  watcher  : every N s asks YouTube whether the channel is live; starts recorder + chat + DVR backfill for a
             new live; when a live ends schedules VOD gap-filling; handles extra URLs / URLs added in the app.
  record   : live-edge HLS -> N-minute chunks (recorder.py)
  fill-*   : downloads everything of a live/VOD not yet covered (from the start, after restarts, dropouts)
  worker   : chunks -> clips (GPU, one at a time)
  poster   : posts clips to TikTok: the ones you approved in the app (and, if auto-post is ON, the best pending
             ones) with a minimum interval and a daily cap.
All state lives in data/state.db, so after a crash/restart nothing is processed or posted twice.
"""
import random, re, threading, time, traceback
from collections import deque
from datetime import datetime
from pathlib import Path
from . import db, pipeline, recorder, tiktok, youtube
from .util import DATA, cfg, log, sleep_until, ffprobe_duration

STOP = threading.Event()           # program exit
WATCHING = threading.Event()       # Start/Stop button in the app
WATCHING.set()
POST_PAUSED = threading.Event()    # "Pauza postare" button
ACTIVE, VOD_JOBS, SKIPPED, MANUAL_URLS = {}, {}, set(), []
ERRORS = deque(maxlen=50)          # shown in the app
STATUS = {"worker": "astept", "poster": "astept", "next_post_at": 0, "watcher": "pornesc", "last_check": 0}
_started = False


def error(msg):
    log.warning(msg)
    ERRORS.appendleft({"t": time.time(), "msg": msg})


def chunk_ranges(a, b, size):
    t = a
    while t < b - 30:
        yield t, min(b, t + size)
        t += size


def backlog():
    return db.q("SELECT COUNT(*) n FROM chunks WHERE status='queued'", one=True)["n"]


class Backfill(threading.Thread):
    """Downloads uncovered parts of a video. mode='live' uses the DVR (from start), mode='vod' the archive."""

    def __init__(self, vid, mode, rec=None, stop=None):
        super().__init__(daemon=True, name=f"fill-{mode}")
        self.vid, self.mode, self.rec = vid, mode, rec
        self.stop = stop or STOP
        self.url = f"https://www.youtube.com/watch?v={vid}"
        self.complete = False

    def stopped(self):
        return STOP.is_set() or self.stop.is_set()

    def run(self):
        try:
            self._run()
        except Exception as e:
            error(f"completare {self.mode} {self.vid} oprita: {str(e)[:200]}")

    def _run(self):
        c = cfg()
        size = c.get("chunk_minutes", 5) * 60
        folder = DATA / self.vid / ("dvr" if self.mode == "live" else self.mode)
        folder.mkdir(parents=True, exist_ok=True)
        dash = None
        if self.mode == "live":
            if not c.get("backfill_from_start", True):
                return
            i = 0
            while not dash and not self.stopped():     # 24/7 lives may never end -> keep trying the DVR
                try:
                    dash = youtube.DashBackfill(self.url, c.get("video_max_height", 1080))
                except Exception as e:
                    i += 1
                    if i == 3:
                        error(f"nu pot lua inceputul live-ului {self.vid} din DVR ({str(e).splitlines()[0][:120]}). "
                              "Reincerc la fiecare 10 minute; ce ramane se completeaza si din VOD dupa ce se termina live-ul.")
                    if self.rec and self.rec.ended.is_set():
                        return
                    sleep_until(self.stop, min(600, 30 * i))
            if not dash:
                return
        else:
            info = youtube.extract(self.url)
            vod_dur = float(info.get("duration") or 0)
            if not vod_dur:
                raise RuntimeError("VOD-ul nu are inca durata (YouTube il proceseaza); reincerc mai tarziu")
        fails = 0
        while not self.stopped():
            v = db.video(self.vid)
            if self.mode == "live":
                if self.rec and self.rec.ended.is_set():
                    return
                now_t = time.time() - (v["start_ts"] or time.time())
                lo = max(0.0, now_t - c.get("backfill_max_hours", 12) * 3600)
                first_live = db.q("SELECT MIN(t0) t FROM chunks WHERE video_id=? AND kind='live'", (self.vid,), one=True)["t"]
                hi = first_live if first_live is not None else now_t - 60
                todo = db.gaps(self.vid, lo, max(lo, hi - 1))
                todo += [g for g in db.gaps(self.vid, hi, now_t - size - 120) if g[0] >= hi]   # recorder holes
            else:
                todo = db.gaps(self.vid, 0, min(vod_dur, c.get("vod_max_hours", 12) * 3600))
            if not todo:
                if self.mode == "vod":
                    log.info("VOD %s complet descarcat.", self.vid)
                    self.complete = True
                    return
                sleep_until(self.stop, 120); continue
            for g0, g1 in todo:
                for a, b in chunk_ranges(g0, g1, size):
                    while backlog() >= 4 and not self.stopped():   # don't fill the disk ahead of the GPU
                        sleep_until(self.stop, 20)
                    if self.stopped():
                        return
                    out = folder / f"{self.mode}_{int(a):06d}.mp4"
                    try:
                        if dash:
                            real_a = dash.download(a, b, out)
                        else:
                            out = youtube.download_section(self.url, a, b, out, c.get("video_max_height", 1080))
                            real_a = a
                        fails = 0
                    except Exception as e:
                        fails += 1
                        error(f"descarcare {self.vid} [{pipeline.hms(a)}] esuata ({fails}): {str(e)[:150]}")
                        if dash and fails % 3 == 0:
                            try:
                                dash.refresh()
                            except Exception:
                                pass
                        if fails >= 10:
                            raise RuntimeError("prea multe erori de descarcare la rand")
                        sleep_until(self.stop, min(300, 20 * fails))
                        continue
                    d = ffprobe_duration(out)
                    db.add_chunk(self.vid, real_a, real_a + d, out, self.mode)
                    log.info("bucata %s noua: [%s - %s]", "DVR" if dash else "VOD", pipeline.hms(real_a), pipeline.hms(real_a + d))
            sleep_until(self.stop, 10)


def worker():
    while not STOP.is_set():
        ch = db.next_chunk()
        if not ch:
            STATUS["worker"] = "astept bucati noi"
            sleep_until(STOP, 5); continue
        if not Path(ch["path"]).exists():
            db.finish_chunk(ch["id"], "error", "fisier lipsa"); continue
        STATUS["worker"] = f"procesez {ch['video_id']} [{pipeline.hms(ch['t0'])}]"
        try:
            n = pipeline.process_chunk(ch)
            db.finish_chunk(ch["id"], "done")
            log.info("bucata %s [%s] gata: %d clipuri noi. In coada: %d bucati", ch["video_id"],
                     pipeline.hms(ch["t0"]), n, backlog())
        except Exception as e:
            log.error("eroare la procesare: %s\n%s", e, traceback.format_exc()[-1500:])
            error(f"procesare {ch['video_id']} [{pipeline.hms(ch['t0'])}] esuata: {str(e).splitlines()[0][:160]}")
            db.retry_or_fail(ch["id"], str(e)[:500])
        try:
            pipeline.cleanup_sources(ch["video_id"])
        except Exception:
            pass


def midnight():
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def post_one(clip):
    """Upload one clip and record the result. Returns True if posted."""
    c = cfg()
    db.x("UPDATE clips SET status='posting', attempts=attempts+1 WHERE id=?", (clip["id"],))
    STATUS["poster"] = f"postez {Path(clip['file']).name}"
    log.info("POSTEZ pe TikTok: %s | %s", Path(clip["file"]).name, clip["caption"])
    try:
        ok, msg, url = tiktok.upload(Path(clip["file"]), clip["caption"])
    except Exception as e:
        ok, msg, url = False, f"eroare browser: {str(e)[:150]}", None
    if ok:
        db.x("UPDATE clips SET status='posted', posted_at=?, url=?, error=NULL WHERE id=?", (time.time(), url, clip["id"]))
        log.info("POSTAT OK %s. Azi: %d/%d", url or "", db.posts_since(midnight()), c.get("daily_post_cap", 30))
        return True
    if "confirmarea" in msg:
        # may actually be online: never re-post automatically (no duplicates)
        db.x("UPDATE clips SET status='unconfirmed', posted_at=?, error=? WHERE id=?", (time.time(), msg, clip["id"]))
        error(f"postare neconfirmata: {msg}. Verifica in TikTok Studio; daca nu apare, apasa din nou Posteaza.")
        return True
    r = db.q("SELECT attempts FROM clips WHERE id=?", (clip["id"],), one=True)
    final = (r["attempts"] or 0) >= 3 or "logat" in msg
    db.x("UPDATE clips SET status=?, error=? WHERE id=?", ("failed" if final else "queued", msg, clip["id"]))
    error(f"postare esuata ({Path(clip['file']).name}): {msg}" + (" - apasa din nou Posteaza dupa ce rezolvi." if final else " - reincerc."))
    return False


def poster():
    next_at = 0
    while not STOP.is_set():
        c = cfg()
        auto = bool(c.get("auto_post", False))
        if POST_PAUSED.is_set():
            STATUS["poster"] = "pauza"; sleep_until(STOP, 5); continue
        clip = db.next_clip_to_post(c.get("post_order", "best_first"), auto=auto)
        if not clip:
            STATUS["poster"] = "nimic de postat" + (" (auto-postare ON)" if auto else " (apasa Posteaza pe un clip)")
            sleep_until(STOP, 5); continue
        manual = clip["status"] == "queued"
        if not manual and datetime.now().hour in (c.get("quiet_hours") or []):
            STATUS["poster"] = "ore de liniste"; sleep_until(STOP, 60); continue
        if db.posts_since(midnight()) >= c.get("daily_post_cap", 30):
            STATUS["poster"] = f"limita zilnica atinsa ({c.get('daily_post_cap', 30)})"; sleep_until(STOP, 30); continue
        # spacing: approved clips wait at least post_min_gap_minutes, auto ones the random 30-45 min interval
        gap = (c.get("manual_min_gap_minutes", 3) * 60 if manual else
               random.uniform(c.get("post_interval_min_minutes", 30), c.get("post_interval_max_minutes", 45)) * 60)
        last = db.last_post_time()
        if not next_at or manual:
            next_at = last + gap
        if time.time() < next_at:
            STATUS["next_post_at"] = next_at
            STATUS["poster"] = f"urmatoarea postare la {datetime.fromtimestamp(next_at):%H:%M}"
            sleep_until(STOP, min(5, next_at - time.time())); continue
        if not Path(clip["file"]).exists():
            db.x("UPDATE clips SET status='failed', error='fisierul video lipseste' WHERE id=?", (clip["id"],)); continue
        posted = post_one(clip)
        next_at = 0
        STATUS["poster"] = "astept"
        if not posted:
            sleep_until(STOP, 120)       # don't hammer TikTok after a failure


def register(info, status):
    db.upsert_video(info["id"], info.get("title"), info.get("channel"), youtube.start_ts(info), status)


def start_live(li):
    vid = li["id"]
    log.info("LIVE detectat: %s | %s", vid, li.get("title"))
    register(li, "live")
    folder = DATA / vid; folder.mkdir(parents=True, exist_ok=True)
    ev = threading.Event()
    rec = recorder.LiveRecorder(li, folder, ev); rec.start()
    chat = youtube.ChatRecorder(f"https://www.youtube.com/watch?v={vid}", folder, youtube.start_ts(li), rec.ended)
    chat.start()
    fill = Backfill(vid, "live", rec, ev); fill.start()
    ACTIVE[vid] = {"rec": rec, "chat": chat, "fill": fill, "stop": ev, "title": li.get("title"), "since": time.time()}


def stop_all_lives():
    for vid, a in list(ACTIVE.items()):
        a["stop"].set()
    for vid, a in list(ACTIVE.items()):
        a["rec"].ended.wait(20)
        ACTIVE.pop(vid, None)


def start_vod(vid, delay=0):
    if vid not in VOD_JOBS:
        VOD_JOBS[vid] = [None, time.time() + delay, 0]


def add_url(url):
    """URL added from the app: live -> followed; VOD -> processed."""
    MANUAL_URLS.append(url)


def _seed(urls, flt):
    for u in dict.fromkeys(urls):
        try:
            info = youtube.extract(u)
        except Exception as e:
            error(f"nu pot citi {u}: {str(e)[:150]}"); continue
        if info.get("live_status") == "is_live":
            if info["id"] not in ACTIVE:
                start_live(info)
            continue
        if flt and u not in (cfg().get("extra_urls") or []) + MANUAL_URLS and not re.search(flt, info.get("title") or ""):
            continue
        if info.get("duration"):
            register(info, "vod"); start_vod(info["id"])


def run_forever(post=True):
    c = cfg()
    global _started
    log.info("STREAM CLIPPER pornit. Canal: %s | hashtag-uri: %s", c.get("channel_url") or "(nesetat)", " ".join(c["hashtags"]))
    if not _started:          # survive watcher restarts without duplicating workers
        _started = True
        from .util import kill_stale_children
        kill_stale_children()
        threading.Thread(target=worker, daemon=True, name="worker").start()
        if post:
            threading.Thread(target=poster, daemon=True, name="poster").start()
    seeds = list(c.get("extra_urls") or [])
    for e in (youtube.recent_streams(c["channel_url"], 6) if c.get("channel_url") else [])[: int(c.get("process_recent_vods", 0))]:
        if e.get("live_status") == "was_live":
            seeds.append(f"https://www.youtube.com/watch?v={e['id']}")
    _seed(seeds, c.get("live_title_filter") or "")
    fails = 0
    while not STOP.is_set():
        c = cfg()
        if not WATCHING.is_set():
            if ACTIVE:
                log.info("Oprit din aplicatie: opresc inregistrarea.")
                stop_all_lives()
            STATUS["watcher"] = "oprit (apasa Start)"
            sleep_until(STOP, 2); continue
        if MANUAL_URLS:
            urls = MANUAL_URLS[:]; _seed(urls, ""); del MANUAL_URLS[:len(urls)]
        if not c.get("channel_url"):
            STATUS["watcher"] = "niciun canal setat (Setari -> Canal urmarit); poti genera clipuri din orice link"
            sleep_until(STOP, 5); continue
        STATUS["watcher"] = "verific daca canalul e live..."
        try:
            info = youtube.current_live(c["channel_url"])
            fails = 0
        except Exception as e:
            fails += 1; info = None
            if fails % 5 == 1:
                error(f"nu pot verifica live-ul (internet/YouTube): {str(e)[:150]}")
        STATUS["last_check"] = time.time()
        if info and info["id"] not in ACTIVE:
            flt = c.get("live_title_filter") or ""
            if flt and not re.search(flt, info.get("title") or "") and info["id"] not in [youtube.video_id(u) for u in c.get("extra_urls") or []]:
                if info["id"] not in SKIPPED:
                    log.info("live %s ignorat (titlul nu contine %s): %s", info["id"], flt, info.get("title"))
                    SKIPPED.add(info["id"])
            else:
                start_live(info)
        for vid in list(ACTIVE):
            if ACTIVE[vid]["rec"].ended.is_set():
                log.info("live %s terminat: completez golurile din VOD peste 20 min", vid)
                db.upsert_video(vid, None, None, None, "ended")
                start_vod(vid, delay=20 * 60)
                del ACTIVE[vid]
        for vid, job in VOD_JOBS.items():
            th, not_before, tries = job
            if (th is None or not th.is_alive()) and time.time() >= not_before and tries < 12:
                if th is not None and th.complete:
                    continue
                job[0] = Backfill(vid, "vod"); job[0].start(); job[2] += 1
                job[1] = time.time() + 30 * 60        # retry later if the VOD isn't ready yet
        STATUS["watcher"] = ("inregistrez: " + ", ".join(ACTIVE)) if ACTIVE else "canalul nu e live acum, verific din nou in curand"
        sleep_until(STOP, c.get("check_live_every_sec", 60))


def snapshot():
    """Everything the dashboard shows."""
    lives = []
    for vid, a in ACTIVE.items():
        lives.append({"id": vid, "title": a["title"], "url": f"https://www.youtube.com/watch?v={vid}",
                      "recording": not a["rec"].ended.is_set(), "since": a["since"],
                      "chunks": db.q("SELECT COUNT(*) n FROM chunks WHERE video_id=?", (vid,), one=True)["n"]})
    counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM clips GROUP BY status")}
    ch = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM chunks GROUP BY status")}
    return {"watching": WATCHING.is_set(), "post_paused": POST_PAUSED.is_set(), "lives": lives, "status": STATUS,
            "clips": counts, "chunks": ch, "posted_today": db.posts_since(midnight()), "errors": list(ERRORS)[:15],
            "auto_post": bool(cfg().get("auto_post", False)), "daily_cap": cfg().get("daily_post_cap", 30)}
